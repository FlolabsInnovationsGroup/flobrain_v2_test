"""External agents (MCP client) endpoints (Phase 14e, Decision 48). Service rules live in
``platform_api.external_agents``.

Settings (``integrations.manage`` + flag ``external_agents``):
- ``GET/POST /orgs/{org}/external-agents``: servers, the allowlist; connect a server
- ``GET/DELETE /orgs/{org}/external-agents/{id}``; ``POST …/{id}/refresh``; ``POST …/{id}/test``
- ``POST …/{id}/approve-tools`` (owner)
- ``POST /orgs/{org}/external-agents/allowlist``, ``DELETE …/allowlist/{id}`` (owner)
Calls (any active member with ``ai.use``; only your own calls):
- ``GET/POST /orgs/{org}/external-agents/calls``; ``POST …/calls/{id}/approve|reject``
"""

import uuid

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit
from platform_api import demo_hosts
from platform_api import external_agents as ea
from platform_api.models import ExternalAgentCall, ExternalAgentHost, ExternalAgentServer


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _err(exc: ea.AgentError):
    return Response({"error": exc.code, "details": exc.details}, status=exc.status)


def _org(request, view, org_id, perm="integrations.manage"):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    if perm:
        HasPerm(perm).has_permission(request, view)
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, "external_agents", default=False):
        return org, Response({"error": "not_implemented", "details": "external_agents is not enabled"}, status=501)
    return org, None


def server_payload(s, org_hosts=None):
    host = demo_hosts.host_of(s.url)
    hosts = org_hosts if org_hosts is not None else ea.org_hosts(s.org)
    return {
        "id": str(s.id),
        "name": s.name,
        "url": s.url,
        "host": host,
        "demo": demo_hosts.is_demo_url(s.url, demo_hosts.DEMO_MCP_HOST),
        "allowed": s.allowed and host in hosts and host in ea.installation_hosts(),
        "status": s.status,
        "last_error": s.last_error,
        "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
        "server_info": s.server_info,
        "tools": s.tools_cache,
        "tools_hash": s.tools_hash,
        "tools_approved": s.tools_approved,
        "has_token": bool(s.token_ciphertext),
        "created_at": s.created_at.isoformat(),
    }


def _host_payload(h):
    return {"id": str(h.id), "host": h.host, "note": h.note, "created_at": h.created_at.isoformat()}


class ExternalAgentListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="External agents, the owner's allowlist and the installation's upper bound")
    def get(self, request, org_id):
        org, error = _org(request, self, org_id)
        if error:
            return error
        hosts = ea.org_hosts(org)
        return Response(
            {
                "servers": [server_payload(s, hosts) for s in ExternalAgentServer.objects.filter(org=org).order_by("name")],
                "allowlist": [_host_payload(h) for h in ExternalAgentHost.objects.filter(org=org).order_by("host")],
                "installation_hosts": sorted(ea.installation_hosts()),
                "can_manage_allowlist": ea.is_owner(request.user, org),
                "demo_server_url": demo_hosts.DEMO_MCP_URL if demo_hosts.enabled() else None,
            }
        )

    @extend_schema(summary="Connect an allowlisted MCP server and import its tools")
    def post(self, request, org_id):
        org, error = _org(request, self, org_id)
        if error:
            return error
        data = _body(request)
        if not all(isinstance(data.get(k, ""), str) for k in ("name", "url", "token")):
            return Response({"error": "invalid", "details": "name, url and token must be text"}, status=400)
        try:
            server = ea.connect(org, request.user, data.get("name"), data.get("url"), data.get("token") or "")
        except ea.AgentError as exc:
            return _err(exc)
        audit(request.user, "external_agent.create", target=server, payload={"host": demo_hosts.host_of(server.url), "tools": len(server.tools_cache)}, request=request, org=org)
        return Response(server_payload(server), status=201)


def _server(org, server_id):
    return ExternalAgentServer.objects.filter(org=org, pk=server_id).first()


def _missing():
    return Response({"error": "not_found", "details": "External agent not found"}, status=404)


class ExternalAgentDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="One external agent and its imported tools")
    def get(self, request, org_id, server_id):
        org, error = _org(request, self, org_id)
        if error:
            return error
        server = _server(org, server_id)
        return Response(server_payload(server)) if server else _missing()

    @extend_schema(summary="Disconnect an external agent (its call history goes with it)")
    def delete(self, request, org_id, server_id):
        org, error = _org(request, self, org_id)
        if error:
            return error
        server = _server(org, server_id)
        if server is None:
            return _missing()
        audit(request.user, "external_agent.delete", payload={"id": str(server.id), "host": demo_hosts.host_of(server.url)}, request=request, org=org)
        server.delete()
        return Response(status=204)


class ExternalAgentRefreshView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Re-import the tool list; a changed list needs the owner's approval again")
    def post(self, request, org_id, server_id):
        org, error = _org(request, self, org_id)
        if error:
            return error
        server = _server(org, server_id)
        if server is None:
            return _missing()
        before = server.tools_hash
        try:
            ea.refresh(server)
        except ea.AgentError as exc:
            return _err(exc)
        audit(request.user, "external_agent.refresh", target=server, payload={"changed": before != server.tools_hash}, request=request, org=org)
        return Response(server_payload(server))


class ExternalAgentApproveToolsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Owner: approve exactly this tool list (send its tools_hash)")
    def post(self, request, org_id, server_id):
        org, error = _org(request, self, org_id, perm=None)
        if error:
            return error
        server = _server(org, server_id)
        if server is None:
            return _missing()
        try:
            ea.approve_tools(server, request.user, str(_body(request).get("tools_hash") or ""))
        except ea.AgentError as exc:
            return _err(exc)
        audit(request.user, "external_agent.tools_approved", target=server, payload={"tools": [t["name"] for t in server.tools_cache][:50]}, request=request, org=org)
        return Response(server_payload(server))


class ExternalAgentTestView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Try one tool now (a person's own call; the answer is shown as untrusted data)")
    def post(self, request, org_id, server_id):
        org, error = _org(request, self, org_id)
        if error:
            return error
        server = _server(org, server_id)
        if server is None:
            return _missing()
        data = _body(request)
        if not isinstance(data.get("tool"), str):
            return Response({"error": "invalid", "details": "tool is required"}, status=400)
        try:
            call = ea.test_call(org, request.user, server, data["tool"], data.get("arguments") if data.get("arguments") is not None else {})
        except ea.AgentError as exc:
            return _err(exc)
        return Response(ea.call_payload(call))


class ExternalAgentAllowlistView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Owner: add a host to the org allowlist (must be within the installation's list)")
    def post(self, request, org_id):
        org, error = _org(request, self, org_id, perm=None)
        if error:
            return error
        if not ea.is_owner(request.user, org):
            return Response({"error": "permission_denied", "details": "Only the owner keeps the allowlist"}, status=403)
        data = _body(request)
        try:
            row = ea.add_host(org, request.user, data.get("host"), data.get("note") if isinstance(data.get("note"), str) else "")
        except ea.AgentError as exc:
            return _err(exc)
        audit(request.user, "external_agent.allowlist_add", payload={"host": row.host}, request=request, org=org)
        return Response(_host_payload(row), status=201)


class ExternalAgentAllowlistDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Owner: remove a host (its servers stop working at once)")
    def delete(self, request, org_id, host_id):
        org, error = _org(request, self, org_id, perm=None)
        if error:
            return error
        if not ea.is_owner(request.user, org):
            return Response({"error": "permission_denied", "details": "Only the owner keeps the allowlist"}, status=403)
        row = ea.remove_host(org, host_id)
        if row is None:
            return Response({"error": "not_found", "details": "Host not found"}, status=404)
        audit(request.user, "external_agent.allowlist_remove", payload={"host": row.host}, request=request, org=org)
        return Response(status=204)


class ExternalAgentCallListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Your external agent calls: waiting for your approval, and answered")
    def get(self, request, org_id):
        org, error = _org(request, self, org_id, perm=None)
        if error:
            return error
        rows = ExternalAgentCall.objects.filter(org=org, user=request.user).select_related("server")[:100]
        return Response([ea.call_payload(c) for c in rows])

    @extend_schema(summary="A buddy proposes a call to an external tool; nothing is sent until you approve")
    def post(self, request, org_id):
        org, error = _org(request, self, org_id, perm=None)
        if error:
            return error
        data = _body(request)
        server = _uuid_row(ExternalAgentServer, org, data.get("server"))
        if server is None:
            return _missing()
        buddy = chat = None
        if data.get("buddy"):
            from buddies.models import Buddy

            buddy = _uuid_row(Buddy, org, data.get("buddy"))
            if buddy is None:
                return Response({"error": "not_found", "details": "Buddy not found"}, status=404)
        if data.get("chat"):
            from brain.models import Chat

            try:
                chat = Chat.objects.filter(pk=int(data["chat"]), org=org, user=request.user).first()
            except (TypeError, ValueError):
                chat = None
            if chat is None:
                return Response({"error": "not_found", "details": "Chat not found"}, status=404)
        if not isinstance(data.get("tool"), str):
            return Response({"error": "invalid", "details": "tool is required"}, status=400)
        try:
            call = ea.propose(org, request.user, server, data["tool"], data.get("arguments") if data.get("arguments") is not None else {}, buddy=buddy, chat=chat)
        except ea.AgentError as exc:
            return _err(exc)
        return Response(ea.call_payload(call), status=201)


def _uuid_row(model, org, value):
    try:
        pk = uuid.UUID(str(value))
    except ValueError:
        return None
    return model.objects.filter(org=org, pk=pk).first()


class ExternalAgentCallDecisionView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    decision = "approve"

    @extend_schema(summary="Approve (send) or reject your own proposed call")
    def post(self, request, org_id, call_id):
        org, error = _org(request, self, org_id, perm=None)
        if error:
            return error
        try:
            call = (ea.approve if self.decision == "approve" else ea.reject)(org, request.user, call_id)
        except ea.AgentError as exc:
            return _err(exc)
        return Response(ea.call_payload(call))
