"""MCP hub (growth round M1): governance for outside MCP servers and the MCP call log.

- ``policy_error(server, tool, buddy)``: the org's rules for an outside server (tool allow/deny,
  read-only mode, end date, which buddies). ``external_agents`` asks it before a tool is offered,
  proposed, tested or sent. No policy row means no extra rule (the owner's tool approval still
  applies). A policy keeps applying even if the ``mcp_hub`` flag is later turned off: a deny
  never silently lapses.
- ``log_call(...)``: one row per MCP tool call, in or out, with a redacted shape of the arguments
  (never values), only while ``mcp_hub`` is on for the org. Rows older than 90 days are removed by
  ``purge_old_logs`` (``manage.py purge_mcp_logs``, and opportunistically at most hourly).
"""

import re
import time
from datetime import timedelta

from django.utils import timezone

FLAG = "mcp_hub"
PERM = "mcp.manage"
LOG_RETENTION_DAYS = 90
SECRET_KEY_RE = re.compile(r"(pass(word)?|secret|token|api[_-]?key|auth|cookie|session|dsn|credential|private|otp|pin)", re.I)
MAX_SUMMARY_KEYS = 20


# --- flags -------------------------------------------------------------------------------


def flag_on(org, user=None) -> bool:
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership

    membership = OrgMembership.objects.filter(org=org, user=user).first() if user is not None else None
    return effective_flag(org, membership, FLAG, default=False)


# --- governance --------------------------------------------------------------------------


def policy_for(server):
    from platform_api.models import MCPServerPolicy

    return MCPServerPolicy.objects.filter(server=server).first()


def tool_read_only(server, tool_name) -> bool:
    for tool in server.tools_cache or []:
        if tool.get("name") == tool_name:
            return tool.get("readOnly") is True
    return False


def policy_error(server, tool_name, buddy=None, policy=None, now=None) -> str | None:
    """None when allowed, else a short code: ``server_expired``, ``tool_denied``, ``read_only``,
    ``buddy_not_allowed``. ``buddy`` None means "no buddy involved" (a person testing it)."""
    policy = policy if policy is not None else policy_for(server)
    if policy is None:
        return None
    now = now or timezone.now()
    if policy.expires_at and policy.expires_at <= now:
        return "server_expired"
    if (policy.tool_rules or {}).get(tool_name) == "deny":
        return "tool_denied"
    if policy.read_only and not tool_read_only(server, tool_name):
        return "read_only"
    if buddy is not None and policy.buddy_ids and str(buddy.pk) not in {str(b) for b in policy.buddy_ids}:
        return "buddy_not_allowed"
    return None


ERROR_TEXT = {
    "server_expired": "Access to this server has ended. An admin can extend it.",
    "tool_denied": "An admin turned this tool off.",
    "read_only": "This server is read-only here, and this tool can change things.",
    "buddy_not_allowed": "This buddy may not use this server.",
}


def clean_policy(server, data) -> dict:
    """Validate an admin's policy update. Raises ValueError with a readable message."""
    from django.utils.dateparse import parse_datetime

    out = {}
    names = {t.get("name") for t in server.tools_cache or []}
    if "tool_rules" in data:
        rules = data["tool_rules"]
        if not isinstance(rules, dict) or len(rules) > 100:
            raise ValueError("tool_rules must be an object of tool name to allow or deny")
        clean = {}
        for name, rule in rules.items():
            if name not in names:
                raise ValueError(f"unknown tool: {str(name)[:60]}")
            if rule not in ("allow", "deny"):
                raise ValueError("each rule is allow or deny")
            clean[name] = rule
        out["tool_rules"] = clean
    if "read_only" in data:
        if not isinstance(data["read_only"], bool):
            raise ValueError("read_only must be true or false")
        out["read_only"] = data["read_only"]
    if "expires_at" in data:
        raw = data["expires_at"]
        if raw in (None, ""):
            out["expires_at"] = None
        else:
            when = parse_datetime(str(raw)) if isinstance(raw, str) else None
            if when is None:
                raise ValueError("expires_at must be a date and time (ISO 8601) or empty")
            if timezone.is_naive(when):
                when = timezone.make_aware(when, timezone.utc)
            if when > timezone.now() + timedelta(days=3660):
                raise ValueError("expires_at is too far away")
            out["expires_at"] = when
    if "buddy_ids" in data:
        ids = data["buddy_ids"]
        if not isinstance(ids, list) or len(ids) > 200 or not all(isinstance(i, str) for i in ids):
            raise ValueError("buddy_ids must be a list of buddy ids")
        from buddies.models import Buddy

        valid = {str(pk) for pk in Buddy.objects.filter(org=server.org, pk__in=[i for i in ids if _uuid(i)]).values_list("pk", flat=True)}
        if valid != set(ids):
            raise ValueError("one of the buddies was not found")
        out["buddy_ids"] = sorted(valid)
    return out


def _uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def save_policy(server, user, changes):
    from platform_api.models import MCPServerPolicy

    policy = policy_for(server) or MCPServerPolicy(org=server.org, server=server)
    for key, value in changes.items():
        setattr(policy, key, value)
    policy.updated_by, policy.updated_at = user, timezone.now()
    policy.save()
    return policy


def policy_payload(server, policy=None) -> dict:
    policy = policy if policy is not None else policy_for(server)
    now = timezone.now()
    rules = (policy.tool_rules if policy else {}) or {}
    return {
        "tool_rules": rules,
        "read_only": bool(policy and policy.read_only),
        "expires_at": policy.expires_at.isoformat() if policy and policy.expires_at else None,
        "expired": bool(policy and policy.expires_at and policy.expires_at <= now),
        "buddy_ids": list((policy.buddy_ids if policy else []) or []),
        "updated_at": policy.updated_at.isoformat() if policy else None,
        "tools": [
            {
                "name": t.get("name"),
                "description": t.get("description", ""),
                "read_only": t.get("readOnly") is True,
                "rule": rules.get(t.get("name"), "allow"),
                "usable": policy_error(server, t.get("name"), policy=policy, now=now) is None,
            }
            for t in server.tools_cache or []
        ],
    }


# --- call log ----------------------------------------------------------------------------


def redact_summary(args) -> dict:
    """The shape of the arguments, never their values: key names (secret-looking ones hidden)
    and each value's type and size. Booleans are kept; they carry no content."""

    def shape(value, depth=0):
        if isinstance(value, bool):
            return value
        if value is None:
            return "empty"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, str):
            return f"text ({len(value)} chars)"
        if isinstance(value, list):
            return f"list ({len(value)} items)"
        if isinstance(value, dict):
            if depth >= 1:
                return f"object ({len(value)} fields)"
            return {_key(k): ("[hidden]" if SECRET_KEY_RE.search(str(k)) else shape(v, depth + 1)) for k, v in list(value.items())[:MAX_SUMMARY_KEYS]}
        return "value"

    if not isinstance(args, dict):
        return {}
    out = {}
    for key, value in list(args.items())[:MAX_SUMMARY_KEYS]:
        out[_key(key)] = "[hidden]" if SECRET_KEY_RE.search(str(key)) else shape(value)
    if len(args) > MAX_SUMMARY_KEYS:
        out["…"] = f"{len(args) - MAX_SUMMARY_KEYS} more fields"
    return out


def _key(key) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", str(key))[:40] or "_"


_last_purge = [0.0]


def log_call(org, user, tool, ok, error="", duration_ms=0, args=None, direction="inbound", client_name="", grant=None, server=None):
    """Record one call when the hub is on for this org. Never raises: logging must not break a call."""
    from platform_api.models import MCPCallLog

    try:
        if not flag_on(org):
            return None
        row = MCPCallLog.objects.create(
            org=org, user=user, direction=direction, client_name=str(client_name or "")[:80], grant=grant, server=server,
            tool=str(tool or "")[:128], ok=bool(ok), error=str(error or "")[:60], duration_ms=max(0, int(duration_ms or 0)),
            args_summary=redact_summary(args or {}),
        )
        if time.monotonic() - _last_purge[0] > 3600:
            _last_purge[0] = time.monotonic()
            purge_old_logs()
        return row
    except Exception:  # noqa: BLE001  (best effort; the call itself already happened)
        import logging

        logging.getLogger(__name__).warning("mcp call log write failed", exc_info=True)
        return None


def purge_old_logs(now=None) -> int:
    from platform_api.models import MCPCallLog

    cutoff = (now or timezone.now()) - timedelta(days=LOG_RETENTION_DAYS)
    deleted, _ = MCPCallLog.objects.filter(created_at__lt=cutoff).delete()
    return deleted


def log_payload(row) -> dict:
    return {
        "id": str(row.id),
        "direction": row.direction,
        "client": row.client_name,
        "server": {"id": str(row.server_id), "name": row.server.name} if row.server_id and row.server else None,
        "user": {"id": str(row.user_id), "name": row.user.username or row.user.email.split("@")[0]} if row.user_id and row.user else None,
        "tool": row.tool,
        "ok": row.ok,
        "error": row.error,
        "duration_ms": row.duration_ms,
        "arguments": row.args_summary,
        "created_at": row.created_at.isoformat(),
    }


class Timer:
    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.monotonic() - self.start) * 1000)
        return False

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.start) * 1000)
