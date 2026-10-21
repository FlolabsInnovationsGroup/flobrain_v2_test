"""MCP hub settings (growth round M1). Flag ``mcp_hub`` (off: 501); ``mcp.manage`` where noted (403).

- ``GET  /orgs/{org}/mcp/overview``: your MCP endpoint and how to connect (any member)
- ``GET  /orgs/{org}/mcp/clients``: apps connected to FloBrain (``mcp.manage``: everyone's; others: their own)
- ``DELETE /orgs/{org}/mcp/clients/{grant}``: disconnect an app (your own, or any with ``mcp.manage``)
- ``GET  /orgs/{org}/mcp/servers``: outside MCP servers with their policy (``mcp.manage``)
- ``PUT  /orgs/{org}/mcp/servers/{server}/policy``: tools allow/deny, read-only, end date, buddies (``mcp.manage``)
- ``GET  /orgs/{org}/mcp/calls``: the MCP call log, last 90 days, with filters (``mcp.manage``)
- ``GET/POST /mcp/consent``: the OAuth consent screen's data and answer (signed-in person)
"""

from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.models import Organization
from organizations.permissions import HasPerm, IsActiveOrgMember, can
from organizations.services.core import audit
from platform_api import mcp_hub, oauth_mcp
from platform_api.models import ExternalAgentServer, MCPCallLog, OAuthGrant

MAX_LOG_ROWS = 200


def _gate(request, view, org_id, perm=None):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    if perm:
        HasPerm(perm).has_permission(request, view)
    if not mcp_hub.flag_on(org, request.user):
        return org, Response({"error": "not_implemented", "details": "The MCP hub is not enabled"}, status=501)
    return org, None


def _name(user):
    return (user.username or user.email.split("@")[0]) if user else ""


def grant_payload(grant, viewer=None) -> dict:
    return {
        "id": str(grant.id),
        "client": {"name": grant.client.name, "client_uri": grant.client.client_uri, "verified": grant.client.is_demo},
        "user": {"id": str(grant.user_id), "name": _name(grant.user)},
        "mine": bool(viewer and grant.user_id == viewer.id),
        "scopes": [{"key": s, "label": oauth_mcp.SCOPE_LABELS.get(s, s)} for s in grant.scopes or []],
        "created_at": grant.created_at.isoformat(),
        "last_used_at": grant.last_used_at.isoformat() if grant.last_used_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "revoked_reason": grant.revoked_reason,
    }


class MCPOverviewView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Your MCP endpoint, its OAuth metadata and what you can manage")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        return Response(
            {
                "endpoint": oauth_mcp.resource_url(request),
                "resource_metadata": oauth_mcp.metadata_url(request),
                "authorization_server": oauth_mcp.base_url(request) + "/.well-known/oauth-authorization-server",
                "scopes": [{"key": k, "label": v} for k, v in oauth_mcp.SCOPE_LABELS.items()],
                "can_manage": can(request.user, mcp_hub.PERM, org),
                "connected_apps": OAuthGrant.objects.filter(org=org, revoked_at__isnull=True).count(),
                "log_retention_days": mcp_hub.LOG_RETENTION_DAYS,
            }
        )


class MCPClientListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Apps connected to FloBrain through OAuth")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        rows = OAuthGrant.objects.filter(org=org).select_related("client", "user")
        if not can(request.user, mcp_hub.PERM, org):
            rows = rows.filter(user=request.user)
        if request.query_params.get("all") != "1":
            rows = rows.filter(revoked_at__isnull=True)
        return Response({"results": [grant_payload(g, request.user) for g in rows.order_by("-created_at")[:200]]})


class MCPClientDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Disconnect an app: its access and refresh tokens stop working at once")
    def delete(self, request, org_id, grant_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        grant = OAuthGrant.objects.filter(org=org, pk=grant_id).select_related("client").first()
        if grant is None or (grant.user_id != request.user.id and not can(request.user, mcp_hub.PERM, org)):
            return Response({"error": "not_found", "details": "Connection not found"}, status=404)
        if grant.revoked_at is None:
            oauth_mcp.revoke_grant(grant, "revoked_by_admin" if grant.user_id != request.user.id else "revoked_by_user")
            audit(request.user, "mcp.oauth.revoke", target=grant, payload={"client": grant.client.name}, request=request, org=org)
        return Response(status=204)


def _server_row(server, buddies):
    from platform_api.views_external import server_payload

    data = server_payload(server)
    data["policy"] = mcp_hub.policy_payload(server)
    data["buddy_names"] = {b["id"]: b["name"] for b in buddies if b["id"] in data["policy"]["buddy_ids"]}
    return data


def _buddies(org):
    from buddies.models import Buddy

    return [{"id": str(b.id), "name": b.name, "slug": b.slug} for b in Buddy.objects.filter(org=org, is_enabled=True).order_by("name")[:200]]


class MCPServerListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Outside MCP servers and the org's rules for them")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id, mcp_hub.PERM)
        if error:
            return error
        buddies = _buddies(org)
        servers = ExternalAgentServer.objects.filter(org=org).order_by("name")
        return Response({"servers": [_server_row(s, buddies) for s in servers], "buddies": buddies})


class MCPServerPolicyView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Set the rules for one outside MCP server")
    def put(self, request, org_id, server_id):
        org, error = _gate(request, self, org_id, mcp_hub.PERM)
        if error:
            return error
        server = ExternalAgentServer.objects.filter(org=org, pk=server_id).first()
        if server is None:
            return Response({"error": "not_found", "details": "Server not found"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            changes = mcp_hub.clean_policy(server, data)
        except ValueError as exc:
            return Response({"error": "invalid", "details": str(exc)}, status=400)
        policy = mcp_hub.save_policy(server, request.user, changes)
        audit(
            request.user, "mcp.server_policy.update", target=server,
            payload={k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in changes.items()}, request=request, org=org,
        )
        return Response(_server_row(server, _buddies(org)) | {"policy": mcp_hub.policy_payload(server, policy)})

    patch = put


def _bool(value):
    return {"true": True, "1": True, "false": False, "0": False}.get(str(value).lower())


class MCPCallLogView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="MCP calls in and out (redacted arguments), newest first")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id, mcp_hub.PERM)
        if error:
            return error
        q = request.query_params
        try:
            days = min(max(int(q.get("days", 30)), 1), mcp_hub.LOG_RETENTION_DAYS)
        except ValueError:
            return Response({"error": "invalid", "details": "days must be a number"}, status=400)
        base = MCPCallLog.objects.filter(org=org, created_at__gte=timezone.now() - timedelta(days=days))
        rows = base.select_related("user", "server")
        if q.get("direction") in (MCPCallLog.INBOUND, MCPCallLog.OUTBOUND):
            rows = rows.filter(direction=q["direction"])
        ok = _bool(q.get("ok")) if q.get("ok") not in (None, "") else None
        if ok is not None:
            rows = rows.filter(ok=ok)
        if q.get("tool"):
            rows = rows.filter(tool=q["tool"][:128])
        if q.get("client"):
            rows = rows.filter(client_name=q["client"][:80])
        if q.get("user"):
            rows = rows.filter(user_id=oauth_mcp._uuid_or_none(q["user"]))
        total = rows.count()
        return Response(
            {
                "results": [mcp_hub.log_payload(r) for r in rows.order_by("-created_at")[:MAX_LOG_ROWS]],
                "total": total,
                "errors": rows.filter(ok=False).count(),
                "tools": sorted(set(base.values_list("tool", flat=True))),
                "clients": sorted(set(base.values_list("client_name", flat=True)) - {""}),
                "retention_days": mcp_hub.LOG_RETENTION_DAYS,
            }
        )
