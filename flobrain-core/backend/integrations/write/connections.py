"""Which connection an action uses, and what the API shows about providers and connections.

Google Workspace and Microsoft 365 can be connected per person: an approved action uses the
person's own account first and the org account otherwise. The other providers are org-wide.
Demo connections (``demo=True``) work only when ``settings.DEMO_MODE`` is on and the org is the
demo org; they never reach the network.
"""

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from integrations.write import registry
from integrations.write.models import WriteActionToggle, WriteConnection

FLAG = "write_integrations"
ACT, MANAGE = "integrations.act", "integrations.manage"


def demo_allowed(org) -> bool:
    return bool(getattr(settings, "DEMO_MODE", False)) and (org.settings or {}).get("demo") is True


def disabled_tools(org) -> set[str]:
    return set(WriteActionToggle.objects.filter(org=org, enabled=False).values_list("tool_key", flat=True))


def refresh_status(conn) -> WriteConnection:
    """An access token past its expiry with no refresh token can't be used: mark it expired."""
    if (
        conn.status == WriteConnection.STATUS_CONNECTED
        and not conn.demo
        and conn.expires_at
        and conn.expires_at <= timezone.now()
        and not conn.refresh_ciphertext
    ):
        conn.status = WriteConnection.STATUS_EXPIRED
        conn.last_error = "token_expired"
        conn.save(update_fields=["status", "last_error", "updated_at"])
    return conn


def usable(conn, org) -> bool:
    if conn is None:
        return False
    refresh_status(conn)
    if conn.status != WriteConnection.STATUS_CONNECTED:
        return False
    return demo_allowed(org) if conn.demo else bool(conn.access_ciphertext)


def connection_for(user, org, provider):
    """(connection or None, reason). Personal first for per-user providers, then the org's."""
    rows = WriteConnection.objects.filter(org=org, provider=provider.key)
    candidates = []
    if provider.per_user:
        candidates.append(rows.filter(owner=user).first())
    candidates.append(rows.filter(owner__isnull=True).first())
    for conn in candidates:
        if usable(conn, org):
            return conn, ""
    existing = next((c for c in candidates if c is not None), None)
    if existing is not None:
        if existing.demo and not demo_allowed(org):
            return None, f"{provider.name} demo connection only works in the demo workspace"
        if existing.status == WriteConnection.STATUS_EXPIRED:
            return None, f"{provider.name} needs to be connected again"
        return None, f"{provider.name} has a connection problem. An admin can reconnect it"
    if not provider.configured() and not demo_allowed(org):
        return None, f"{provider.name} is not set up on this server yet"
    return None, f"Connect {provider.name} first"


def visible_connections(user, org, manager: bool):
    qs = WriteConnection.objects.filter(org=org)
    return qs.filter(Q(owner=user) | Q(owner__isnull=True)) if manager else qs.filter(Q(owner=user) | Q(owner__isnull=True, status=WriteConnection.STATUS_CONNECTED))


def connection_payload(conn) -> dict:
    """Never a token: only a 4-character hint for API keys."""
    return {
        "id": str(conn.id),
        "provider": conn.provider,
        "scope": conn.scope,
        "account_label": conn.account_label,
        "scopes": list(conn.scopes or []),
        "status": conn.status,
        "last_error": conn.last_error,
        "secret_hint": f"…{conn.secret_hint}" if conn.secret_hint else "",
        "expires_at": conn.expires_at.isoformat() if conn.expires_at else None,
        "simulated": conn.demo,
        "site": _site(conn),
        "connected_at": conn.created_at.isoformat(),
        "last_used_at": conn.last_used_at.isoformat() if conn.last_used_at else None,
    }


def _site(conn) -> str:
    config = conn.config or {}
    return str(config.get("url") or config.get("site_url") or "")


def provider_status(provider, org_conn, org) -> str:
    """not_set_up | not_connected | connected | expired | error, for the provider card."""
    if org_conn is not None:
        refresh_status(org_conn)
        if org_conn.demo and not demo_allowed(org):
            return WriteConnection.STATUS_ERROR
        return org_conn.status
    if not provider.configured() and not demo_allowed(org):
        return WriteConnection.STATUS_NOT_SET_UP
    return "not_connected"


def provider_payload(provider, org, user, manager: bool, conns: list, disabled: set) -> dict:
    org_conn = next((c for c in conns if c.provider == provider.key and c.owner_id is None), None)
    mine = next((c for c in conns if c.provider == provider.key and c.owner_id == user.id), None)
    status = provider_status(provider, org_conn, org)
    if status == "not_connected" and mine is not None and mine.status == WriteConnection.STATUS_CONNECTED:
        status = "connected_personal"
    out = {
        "key": provider.key,
        "name": provider.name,
        "description": provider.description,
        "auth": provider.auth,
        "per_user": provider.per_user,
        "configured": provider.configured(),
        "status": status,
        "simulated": bool((org_conn and org_conn.demo) or (mine and mine.demo)),
        "scopes": provider.scopes(),
        "connection": connection_payload(org_conn) if org_conn is not None and (manager or org_conn.status == WriteConnection.STATUS_CONNECTED) else None,
        "personal": connection_payload(mine) if mine is not None else None,
        "actions": [
            {
                "tool": a.tool_key,
                "key": a.key,
                "label": a.label,
                "description": a.description,
                "risk": a.risk,
                "scopes": list(a.scopes),
                "enabled": a.tool_key not in disabled,
            }
            for a in provider.actions
        ],
    }
    if manager and not provider.configured():
        out["env"] = provider.env_names()  # the names an operator must set; never values
    return out


def catalog_payload(user, org, manager: bool) -> list[dict]:
    conns = list(visible_connections(user, org, manager))
    disabled = disabled_tools(org)
    return [provider_payload(p, org, user, manager, conns, disabled) for p in registry.providers()]
