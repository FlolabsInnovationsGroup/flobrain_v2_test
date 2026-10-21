"""Every write-back action as an approval-gated tool (``actions.plugins.register_tool``).

``check`` runs when a buddy proposes the call and again when a person approves it. It verifies the
``write_integrations`` flag, ``integrations.act``, the org's switch for this action, the argument
schema and a usable connection with the scopes the action needs, and returns the line shown on the
approval card. ``execute`` only ever runs from ``actions.service`` after an approval; it performs
the call (or, in the demo, a simulation that never touches the network) and returns a link to
what it created. Results are audited without the arguments' content.
"""

import logging

from django.utils import timezone

from actions.schema import SchemaError, validate
from integrations.write import registry
from integrations.write.connections import ACT, FLAG, connection_for, demo_allowed, disabled_tools
from integrations.write.transport import Client, WriteError

logger = logging.getLogger(__name__)


def _denied(code, details):
    from actions.service import ActionDenied

    return ActionDenied(code, details)


def _flag_on(user, org) -> bool:
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership

    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return effective_flag(org, membership, FLAG, default=False)


def _clean(action, args) -> dict:
    try:
        clean = validate(action.schema, args)
        if action.validate is not None:
            action.validate(clean)
    except (SchemaError, ValueError, KeyError, TypeError) as exc:
        raise _denied("invalid", str(exc)[:200]) from exc
    return clean


def _gate(user, org, provider, action, args):
    """Shared by check and execute. Returns (clean args, connection)."""
    from organizations.permissions import can

    if not _flag_on(user, org):
        raise _denied("not_available", "Write-back connectors are switched off")
    if not can(user, ACT, org):
        raise _denied("permission", f"Missing permission: {ACT}")
    if action.tool_key in disabled_tools(org):
        raise _denied("not_available", "An admin turned this action off")
    clean = _clean(action, args)
    conn, reason = connection_for(user, org, provider)
    if conn is None:
        raise _denied("not_available", reason)
    if not conn.demo:
        from integrations.write.oauth import missing_scopes

        missing = missing_scopes(action, conn.scopes)
        if missing:
            raise _denied("not_available", f"{provider.name} was connected without {', '.join(missing)}. Connect it again")
    return clean, conn


def make_check(provider, action):
    def check(user, org, args) -> str:
        clean, conn = _gate(user, org, provider, action, args)
        line = action.preview(clean, conn)
        if conn.demo:
            line += " [demo, simulated]"
        return line[:300]

    return check


def _safe_url(value) -> str:
    return value if isinstance(value, str) and value.startswith("https://") and len(value) <= 500 else ""


def make_execute(provider, action):
    def execute(user, org, args) -> dict:
        from organizations.services.core import audit

        clean, conn = _gate(user, org, provider, action, args)
        if conn.demo:
            if not demo_allowed(org):  # never reached: connection_for refuses it; kept as a second lock
                raise _denied("not_available", "Demo connections only work in the demo workspace")
            outcome = action.demo(clean)
        else:
            try:
                outcome = action.run(Client(provider, conn), clean, conn)
            except WriteError as exc:
                logger.info("write action %s failed: %s", action.tool_key, exc.code)
                raise _denied("provider_error", exc.details) from exc
            except ValueError as exc:
                raise _denied("provider_error", str(exc)[:180]) from exc
        result = {
            "provider": provider.key,
            "action": action.key,
            "id": str(outcome.get("id") or "")[:200],
            "url": _safe_url(outcome.get("url")),
            "title": str(outcome.get("title") or "")[:200],
            "simulated": conn.demo,
            "connection": str(conn.id),
            "account": conn.account_label,
        }
        conn.last_used_at = timezone.now()
        conn.save(update_fields=["last_used_at", "updated_at"])
        audit(
            user,
            "integration.write",
            target=conn,
            payload={"tool": action.tool_key, "object_id": result["id"], "url": result["url"], "simulated": conn.demo},
            org=org,
        )
        return result

    return execute


def spec_for(provider, action) -> dict:
    return {
        "perm_key": ACT,
        "risk": action.risk,
        "label": action.label,
        "description": action.description,
        "schema": action.schema,
        "provider": provider.key,
        "scopes": list(action.scopes),
        "flag": FLAG,
    }


def register_all() -> list[str]:
    from actions.plugins import register_tool

    keys = []
    for provider in registry.providers():
        for action in provider.actions:
            register_tool(action.tool_key, spec_for(provider, action), check=make_check(provider, action), execute=make_execute(provider, action))
            keys.append(action.tool_key)
    return keys
