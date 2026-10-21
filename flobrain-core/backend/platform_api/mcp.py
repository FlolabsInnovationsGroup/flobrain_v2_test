"""MCP server (Phase 14d, Decision 42): ``POST /api/mcp``, JSON-RPC 2.0, personal access tokens.

Read tools answer directly. Write tools only create an ``ActionProposal`` that
the token's owner approves in FloBrain (Decision 33). The token needs the
``mcp`` scope plus the tool's own scope. Tool names use ``_`` (``tasks_list``)
for client compatibility; they map to the ``ToolDefinition`` keys.

Growth round M1 (flag ``mcp_hub``): OAuth 2.1 access tokens (``platform_api.oauth_mcp``) work
here next to PATs, more tools (``platform_api.mcp_tools_extra``), MCP tool annotations, and a
call log with redacted arguments (``platform_api.mcp_hub``).
"""

import json

from django.http import HttpResponse, JsonResponse
from rest_framework.views import APIView

from platform_api.oauth_mcp import MCPAuthentication, metadata_url
from platform_api.public_views import PATThrottle, PATUserThrottle

PROTOCOL = "2025-06-18"

TOOLS = {
    "tasks_list": {
        "scope": "tasks:read",
        "description": "List tasks you can see. Optional status: to_do, in_progress, done.",
        "schema": {"type": "object", "properties": {"status": {"type": "string", "enum": ["to_do", "in_progress", "done"]}}},
        "readOnly": True,
    },
    "rooms_list": {
        "scope": "rooms:read",
        "description": "List rooms you can read.",
        "schema": {"type": "object", "properties": {}},
        "readOnly": True,
    },
    "knowledge_search": {
        "scope": "knowledge:read",
        "description": "Search documents and messages you can read. Returns excerpts with sources.",
        "schema": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 2000}}, "required": ["query"]},
        "readOnly": True,
    },
    "time_report": {
        "scope": "time:read",
        "description": "Your own logged hours in the last N days (default 7).",
        "schema": {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90}}},
        "readOnly": True,
    },
    "tasks_create": {
        "scope": "tasks:write",
        "action": "tasks.create",
        "description": "Propose a task. Nothing is created until you approve it in FloBrain.",
        "readOnly": False,
    },
    "rooms_post_message": {
        "scope": "rooms:write",
        "action": "rooms.post_message",
        "description": "Propose a room message. Nothing is posted until you approve it in FloBrain.",
        "readOnly": False,
    },
}


def _spec(name):
    """A base tool, or a hub tool (``mcp_tools_extra``); availability is checked by the caller."""
    from platform_api import mcp_tools_extra

    return TOOLS.get(name) or mcp_tools_extra.TOOLS.get(name)


def _membership(org, user):
    from organizations.models import OrgMembership

    return OrgMembership.objects.filter(org=org, user=user).first()


def _offered(user, token):
    """Tool names this token may see: its scopes, plus hub tools while their flags are on."""
    from platform_api import mcp_tools_extra

    names = [n for n, spec in TOOLS.items() if spec["scope"] in token.scopes]
    membership = _membership(token.org, user)
    for name, spec in mcp_tools_extra.TOOLS.items():
        if spec["scope"] in token.scopes and mcp_tools_extra.available(name, user, token.org, membership):
            names.append(name)
    return names


def _schema(name):
    tool = _spec(name)
    if "action" in tool:
        from actions.registry import TOOLS as ACTIONS

        return ACTIONS[tool["action"]]["schema"]
    return tool["schema"]


def _ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _tool_result(data, is_error=False):
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}], "structuredContent": data, "isError": is_error}


def _call(user, token, name, args):
    from actions.schema import SchemaError, validate

    from platform_api import mcp_tools_extra

    org = token.org
    tool = TOOLS.get(name)
    if tool is None and name in mcp_tools_extra.TOOLS:
        if not mcp_tools_extra.available(name, user, org, _membership(org, user)):
            return _tool_result({"error": "unknown_tool"}, True)
        tool = mcp_tools_extra.TOOLS[name]
    if tool is None:
        return _tool_result({"error": "unknown_tool"}, True)
    if tool["scope"] not in token.scopes:
        return _tool_result({"error": "missing_scope", "scope": tool["scope"]}, True)
    try:
        args = validate(_schema(name), args or {}) if "action" in tool else _validate_read(name, args or {})
    except (SchemaError, ValueError) as exc:
        return _tool_result({"error": "invalid_arguments", "details": str(exc)}, True)
    if name == "tasks_list":
        from tasks.models import Task
        from tasks.selectors import visible_tasks

        qs = visible_tasks(Task.objects.filter(org=org), user, org)
        if args.get("status"):
            qs = qs.filter(status=args["status"])
        return _tool_result({"tasks": [{"id": str(t.id), "title": t.title, "status": t.status} for t in qs.order_by("-created_at")[:100]]})
    if name == "rooms_list":
        from rooms.services import accessible_rooms

        return _tool_result({"rooms": [{"id": str(r.id), "name": r.name} for r in accessible_rooms(user, org).order_by("name")[:200]]})
    if name == "time_report":
        from datetime import timedelta

        from django.utils import timezone

        from timetracking.models import TimeEntry

        since = timezone.now() - timedelta(days=args.get("days", 7))
        seconds = sum(
            int((e.ended_at - e.started_at).total_seconds())
            for e in TimeEntry.objects.filter(org=org, user=user, started_at__gte=since, ended_at__isnull=False)
        )
        return _tool_result({"days": args.get("days", 7), "hours": round(seconds / 3600, 2)})
    if name == "knowledge_search":
        return _knowledge(user, org, args["query"])
    if name in mcp_tools_extra.TOOLS and "action" not in tool:
        data, is_error = mcp_tools_extra.handle(user, org, name, args)
        return _tool_result(data, is_error)
    # write tools → proposals only
    from actions.service import ActionDenied, check, payload
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership

    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if not effective_flag(org, membership, "ai_actions", default=False):
        return _tool_result({"error": "not_available", "details": "approved actions are not enabled"}, True)
    from actions.service import _flag_allows

    if not _flag_allows(user, org, tool["action"]):
        return _tool_result({"error": "not_available", "details": "this feature is not enabled"}, True)
    try:
        summary = check(tool["action"], user, org, args)
    except ActionDenied as exc:
        return _tool_result({"error": exc.code}, True)
    from actions.models import ActionProposal
    from actions.service import _audit

    proposal = ActionProposal.objects.create(org=org, user=user, tool_key=tool["action"], arguments=args, summary=summary[:300])
    _audit(user, org, "action.proposed", proposal, {"via": "mcp"})
    return _tool_result({"proposal": payload(proposal), "next": "Approve it in FloBrain; nothing has run yet."})


def _validate_read(name, args):
    from actions.schema import validate

    return validate({**_schema(name), "additionalProperties": False}, args)


def _knowledge(user, org, query):
    from knowledge.embeddings import EmbeddingError, get_embedder
    from knowledge.prompting import citations
    from knowledge.retrieve import retrieve
    from knowledge.store import get_store
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership

    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if not effective_flag(org, membership, "memory_search", default=False):
        return _tool_result({"error": "not_available"}, True)
    from brain.llm.policy import check_ai
    from telemetry.models import UsageEvent
    from telemetry.pricing import platform_budget_blocks

    if check_ai(org, "embeddings"):
        return _tool_result({"error": "private_only"}, True)
    if platform_budget_blocks(org, user, UsageEvent.CREDENTIAL_PLATFORM):
        return _tool_result({"error": "budget_exceeded"}, True)
    embedder = get_embedder()
    store = get_store(embedder.info.dimension) if embedder else None
    if embedder is None or store is None:
        return _tool_result({"error": "not_configured"}, True)
    try:
        vector = embedder.embed([query])[0]
    except EmbeddingError:
        return _tool_result({"error": "embeddings_unavailable"}, True)
    hits = retrieve(user, org, vector, embedder.info.model, store, k=8)
    results = citations(hits)
    # Cited snippets: "[n] title: excerpt", so a client can quote and cite without parsing.
    snippets = [f"[{r['n']}] {r['title']}: {r['excerpt']}" for r in results]
    return _tool_result({"results": results, "snippets": snippets})


def _client_label(token):
    from platform_api.models import OAuthAccessToken

    if isinstance(token, OAuthAccessToken):
        return token.grant.client.name, token.grant
    return f"Personal token: {token.name}"[:80], None


def _unauthorized(request, message):
    response = JsonResponse(_err(None, -32001, message), status=401)
    response["WWW-Authenticate"] = f'Bearer resource_metadata="{metadata_url(request)}"'
    return response


class MCPView(APIView):
    authentication_classes = [MCPAuthentication]
    permission_classes = []
    throttle_classes = [PATThrottle, PATUserThrottle]

    def post(self, request):
        from platform_api.models import OAuthAccessToken, PersonalAccessToken

        token = request.auth
        if not isinstance(token, (PersonalAccessToken, OAuthAccessToken)):
            return _unauthorized(request, "a personal access token is required")
        if "mcp" not in (token.scopes or []):
            return JsonResponse(_err(None, -32001, "token lacks the mcp scope"), status=403)
        msg = request.data if isinstance(request.data, dict) else None
        if msg is None or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return JsonResponse(_err(None, -32600, "invalid request"), status=400)
        rid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
        if rid is None:  # notification
            return HttpResponse(status=202)
        if method == "initialize":
            return JsonResponse(
                _ok(rid, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "flobrain", "version": "2"}})
            )
        if method == "ping":
            return JsonResponse(_ok(rid, {}))
        if method == "tools/list":
            from platform_api.mcp_tools_extra import annotations

            tools = []
            for name in _offered(request.user, token):
                spec = _spec(name)
                tools.append(
                    {
                        "name": name,
                        "title": annotations(name, spec)["title"],
                        "description": spec["description"],
                        "inputSchema": _schema(name),
                        "annotations": annotations(name, spec),
                    }
                )
            return JsonResponse(_ok(rid, {"tools": tools}))
        if method == "tools/call":
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return JsonResponse(_err(rid, -32602, "params.name is required"))
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                return JsonResponse(_err(rid, -32602, "params.arguments must be an object"))
            from platform_api import mcp_hub

            timer = mcp_hub.Timer().__enter__()
            result = _call(request.user, token, params["name"], args)
            client, grant = _client_label(token)
            structured = result.get("structuredContent") if isinstance(result.get("structuredContent"), dict) else {}
            mcp_hub.log_call(
                token.org, request.user, params["name"], not result.get("isError"), error=structured.get("error", "") if result.get("isError") else "",
                duration_ms=timer.elapsed_ms, args=args, client_name=client, grant=grant,
            )
            return JsonResponse(_ok(rid, result))
        return JsonResponse(_err(rid, -32601, "method not found"))
