"""Write-back connector endpoints (growth round W4, flag ``write_integrations``).

GET    /api/v2/orgs/{org}/integrations/write                       providers, actions, connections
POST   /api/v2/orgs/{org}/integrations/write/{provider}/connect    start OAuth (or save Odoo key)
POST   /api/v2/orgs/{org}/integrations/write/confirm               finish OAuth with the one-time code
DELETE /api/v2/orgs/{org}/integrations/write/connections/{id}      disconnect (tokens wiped)
PATCH  /api/v2/orgs/{org}/integrations/write/actions/{tool}        admin turns an action on or off
GET    /api/v2/orgs/{org}/integrations/write/log                   recent write actions and their approval state
GET    /api/v2/integrations/write/oauth/callback/{provider}        provider redirect (public, state only)

Checks: org member (403) → flag (501, like the other integration endpoints) → ``integrations.act``
or ``integrations.manage`` (403). Org-wide connections, disconnecting them and action switches need
``integrations.manage``; a personal Google or Microsoft account needs ``integrations.act``.
Tokens are never returned.
"""

import json
import secrets
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import Throttled
from rest_framework.response import Response

from brain.throttles import AISendThrottle
from core_v2.views import V2APIView, V2PublicAPIView
from integrations import crypto
from integrations.write import registry
from integrations.write.connections import (
    ACT,
    FLAG,
    MANAGE,
    catalog_payload,
    connection_payload,
    demo_allowed,
)
from integrations.write.models import WriteActionToggle, WriteConnection, WriteOAuthState
from integrations.write.transport import WriteError
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import IsActiveOrgMember
from organizations.permissions.engine import can
from organizations.services.core import audit


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _err(status, code, details):
    return Response({"error": code, "details": details}, status=status)


def _gate(request, org_id):
    """(org, manager, error response)."""
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, FLAG, default=False):
        return org, False, _err(501, "not_implemented", "Write-back connectors are not enabled")
    manager = can(request.user, MANAGE, org)
    if not manager and not can(request.user, ACT, org):
        return org, False, _err(403, "permission_denied", f"Missing permission: {ACT}")
    return org, manager, None


def _throttle(request, view):
    throttle = AISendThrottle()
    if not throttle.allow_request(request, view):
        raise Throttled(wait=throttle.wait())


class WriteCatalogView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Write-back providers, their actions and this org's connections (never tokens)")
    def get(self, request, org_id):
        org, manager, err = _gate(request, org_id)
        if err:
            return err
        return Response(
            {
                "providers": catalog_payload(request.user, org, manager),
                "can_manage": manager,
                "can_act": can(request.user, ACT, org),
                "demo": demo_allowed(org),
                "encryption_configured": crypto.is_configured(),
            }
        )


class WriteConnectView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Connect a provider: returns the authorize URL (OAuth + PKCE), or saves an Odoo API key")
    def post(self, request, org_id, provider):
        org, manager, err = _gate(request, org_id)
        if err:
            return err
        prov = registry.get(provider)
        if prov is None:
            return _err(404, "not_found", "Unknown provider")
        data = _body(request)
        personal = str(data.get("scope") or "org") == "personal"
        if personal and not prov.per_user:
            return _err(400, "invalid", f"{prov.name} connects for the whole organization only")
        if not personal and not manager:
            return _err(403, "permission_denied", f"Missing permission: {MANAGE}")
        _throttle(request, self)
        if demo_allowed(org):
            return self._demo(request, org, prov, personal)
        if not crypto.is_configured():
            return _err(501, "not_configured", "Encryption is not configured on this server")
        if prov.auth == "api_key":
            return self._api_key(request, org, prov, data)
        if not prov.configured():
            return _err(501, "not_configured", f"{prov.name} is not set up on this server yet")
        from integrations.write.oauth import start

        return Response({"authorize_url": start(prov, org, request.user, personal)})

    def _demo(self, request, org, prov, personal):
        """Demo workspace: a simulated connection, no OAuth, no token, no network."""
        owner = request.user if personal else None
        conn, _ = WriteConnection.objects.update_or_create(
            org=org,
            provider=prov.key,
            owner=owner,
            defaults={
                "account_label": prov.demo_label or f"{prov.name} (demo, simulated)",
                "scopes": prov.scopes(),
                "config": dict(prov.demo_config),
                "status": WriteConnection.STATUS_CONNECTED,
                "demo": True,
                "last_error": "",
                "connected_by": request.user,
            },
        )
        audit(request.user, "integration.write.connect", target=conn, payload={"provider": prov.key, "scope": conn.scope, "demo": True}, request=request, org=org)
        return Response(connection_payload(conn), status=201)

    def _api_key(self, request, org, prov, data):
        from integrations.write.catalog import odoo

        url = odoo.normalize_url(str(data.get("url") or ""))
        if url is None:
            return _err(400, "invalid", "Use the https address of your Odoo, on odoo.com or a host your operator allowed")
        database = str(data.get("database") or "").strip()
        login = str(data.get("login") or "").strip()
        api_key = data.get("api_key") or ""
        if not odoo.DB_RE.match(database):
            return _err(400, "invalid", "database is the Odoo database name")
        if not login or len(login) > 120:
            return _err(400, "invalid", "login is the Odoo user's login or email")
        if not isinstance(api_key, str) or not odoo.KEY_RE.match(api_key):
            return _err(400, "invalid", "api_key must be 8 to 256 printable characters without spaces")
        probe = SimpleNamespace(config={"url": url, "database": database})
        try:
            uid = odoo.authenticate(probe, login, api_key)
        except WriteError as exc:
            return _err(400, exc.code, exc.details)
        conn = WriteConnection.objects.filter(org=org, provider=prov.key, owner__isnull=True).first() or WriteConnection(org=org, provider=prov.key)
        conn.account_label = f"{login} on {url.removeprefix('https://')}"[:160]
        conn.config = {"url": url, "database": database, "login": login, "uid": uid}
        conn.scopes = []
        conn.set_secrets(api_key)
        conn.secret_hint = api_key[-4:]
        conn.expires_at = None
        conn.status = WriteConnection.STATUS_CONNECTED
        conn.last_error = ""
        conn.demo = False
        conn.connected_by = request.user
        conn.save()
        audit(request.user, "integration.write.connect", target=conn, payload={"provider": prov.key, "scope": "org"}, request=request, org=org)
        return Response(connection_payload(conn), status=201)


def _frontend(path: str) -> str:
    return f"{(getattr(settings, 'FRONTEND_BASE_URL', '') or '').rstrip('/')}{path}"


class WriteOAuthCallbackView(V2PublicAPIView):
    """Authenticated by ``state`` only (single use, 10 minutes). It does not connect anything: it
    parks the encrypted tokens and sends this browser back with a one-time code. The connection is
    created only when the person who started the flow confirms that code while signed in."""

    @extend_schema(summary="OAuth callback for write-back connectors (fixed redirect URI)")
    def get(self, request, provider):
        from integrations.write.oauth import consume, digest, exchange, verifier_of

        state = str(request.query_params.get("state") or "")[:200]
        code = str(request.query_params.get("code") or "")[:2000]
        prov = registry.get(provider)
        known = WriteOAuthState.objects.filter(state_hash=digest(state), provider=provider).select_related("org").first() if state else None

        def done(result, confirm=""):
            page = f"/w/{quote(known.org.slug)}/integrations?" if known is not None else "/?"
            suffix = f"&write_confirm={quote(confirm)}&provider={quote(provider)}" if confirm else ""
            return HttpResponseRedirect(_frontend(f"{page}write_result={quote(result)}{suffix}"))

        row = consume(provider, state) if prov is not None else None
        if row is None or not code:
            return done("invalid_state")
        if not prov.configured() or not crypto.is_configured():
            return done("not_configured")
        try:
            result = exchange(prov, code, verifier_of(row))
        except (WriteError, crypto.CredentialCryptoError):
            return done("exchange_failed")
        confirm = secrets.token_urlsafe(24)
        row.result_ciphertext = crypto.encrypt(json.dumps(result), f"write-oauth-result:{row.id}", row.org_id)
        row.key_version = crypto.current_key_version()
        row.confirm_hash = digest(confirm)
        row.save(update_fields=["result_ciphertext", "key_version", "confirm_hash"])
        return done("confirm", confirm)


class WriteConfirmView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Finish connecting: the person who started OAuth confirms with the one-time code")
    def post(self, request, org_id):
        from integrations.write.oauth import digest

        org, manager, err = _gate(request, org_id)
        if err:
            return err
        code = str(_body(request).get("code") or "")
        row = (
            WriteOAuthState.objects.filter(
                org=org, user=request.user, confirm_hash=digest(code), confirmed_at__isnull=True, used_at__isnull=False
            ).first()
            if code
            else None
        )
        if row is None or row.expires_at + timedelta(minutes=10) <= timezone.now():
            return _err(404, "not_found", "Nothing to confirm. Start connecting again.")
        if not row.personal and not manager:
            return _err(403, "permission_denied", f"Missing permission: {MANAGE}")
        if not WriteOAuthState.objects.filter(pk=row.pk, confirmed_at__isnull=True).update(confirmed_at=timezone.now()):
            return _err(404, "not_found", "Nothing to confirm. Start connecting again.")
        prov = registry.get(row.provider)
        try:
            result = json.loads(crypto.decrypt(row.result_ciphertext, f"write-oauth-result:{row.id}", org.id, row.key_version))
        except (crypto.CredentialCryptoError, TypeError, ValueError):
            return _err(409, "expired", "Start connecting again")
        finally:
            WriteOAuthState.objects.filter(pk=row.pk).update(result_ciphertext=None)
        owner = request.user if row.personal else None
        conn = WriteConnection.objects.filter(org=org, provider=row.provider, owner=owner).first() or WriteConnection(
            org=org, provider=row.provider, owner=owner
        )
        conn.account_label = str(result.get("label") or (prov.name if prov else row.provider))[:160]
        conn.scopes = [str(s)[:200] for s in result.get("scopes") or []][:40]
        conn.config = result.get("config") if isinstance(result.get("config"), dict) else {}
        conn.set_secrets(result["access_token"], result.get("refresh_token") or None)
        conn.secret_hint = ""
        try:
            conn.expires_at = timezone.now() + timedelta(seconds=int(result.get("expires_in")))
        except (TypeError, ValueError):
            conn.expires_at = None
        conn.status = WriteConnection.STATUS_CONNECTED
        conn.last_error = ""
        conn.demo = False
        conn.connected_by = request.user
        conn.save()
        audit(request.user, "integration.write.connect", target=conn, payload={"provider": row.provider, "scope": conn.scope}, request=request, org=org)
        return Response(connection_payload(conn), status=201)


class WriteConnectionDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Disconnect: delete the connection and its tokens")
    def delete(self, request, org_id, connection_id):
        org, manager, err = _gate(request, org_id)
        if err:
            return err
        conn = WriteConnection.objects.filter(org=org, pk=connection_id).first()
        if conn is None or (conn.owner_id is not None and conn.owner_id != request.user.id):
            return _err(404, "not_found", "Connection not found")
        if conn.owner_id is None and not manager:
            return _err(403, "permission_denied", f"Missing permission: {MANAGE}")
        audit(request.user, "integration.write.disconnect", target=conn, payload={"provider": conn.provider, "scope": conn.scope}, request=request, org=org)
        conn.wipe()
        conn.delete()
        return Response(status=204)


class WriteActionToggleView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Turn one write action on or off for this org (integrations.manage)")
    def patch(self, request, org_id, tool):
        org, manager, err = _gate(request, org_id)
        if err:
            return err
        if not manager:
            return _err(403, "permission_denied", f"Missing permission: {MANAGE}")
        provider, action = registry.action_for(tool)
        if action is None:
            return _err(404, "not_found", "Unknown action")
        enabled = _body(request).get("enabled")
        if not isinstance(enabled, bool):
            return _err(400, "invalid", "enabled must be true or false")
        WriteActionToggle.objects.update_or_create(org=org, tool_key=tool, defaults={"enabled": enabled, "updated_by": request.user})
        audit(request.user, "integration.write.toggle", payload={"tool": tool, "enabled": enabled}, request=request, org=org)
        return Response({"tool": tool, "enabled": enabled})


STATE = {"proposed": "waiting", "executed": "done", "failed": "failed", "rejected": "rejected", "expired": "expired", "approved": "waiting"}


def log_payload(proposal) -> dict:
    provider, action = registry.action_for(proposal.tool_key)
    result = proposal.result if isinstance(proposal.result, dict) else {}
    url = result.get("url")
    return {
        "id": str(proposal.id),
        "tool": proposal.tool_key,
        "provider": provider.key if provider else "",
        "provider_name": provider.name if provider else "",
        "label": action.label if action else proposal.tool_key,
        "risk": action.risk if action else "",
        "summary": proposal.summary,
        "status": proposal.status,
        "state": STATE.get(proposal.status, proposal.status),
        "url": url if isinstance(url, str) and url.startswith("https://") else "",
        "simulated": bool(result.get("simulated")),
        "error": proposal.error,
        "by": (proposal.user.username or "") if proposal.user_id else "",
        "created_at": proposal.created_at.isoformat(),
        "decided_at": proposal.decided_at.isoformat() if proposal.decided_at else None,
    }


class WriteLogView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Recent write actions: waiting for approval, done or failed (admins see the org's)")
    def get(self, request, org_id):
        from actions.models import ActionProposal

        org, manager, err = _gate(request, org_id)
        if err:
            return err
        qs = ActionProposal.objects.filter(org=org, tool_key__in=registry.tool_keys()).select_related("user")
        if not manager:
            qs = qs.filter(user=request.user)
        state = request.query_params.get("state") or ""
        wanted = [k for k, v in STATE.items() if v == state]
        if wanted:
            qs = qs.filter(status__in=wanted)
        return Response([log_payload(p) for p in qs.order_by("-created_at")[:50]])
