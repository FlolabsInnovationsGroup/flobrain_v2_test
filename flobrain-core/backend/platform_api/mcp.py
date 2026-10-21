"""MCP server (Phase 14d, Decision 42): ``POST /api/mcp``, JSON-RPC 2.0, personal access tokens.

Read tools answer directly. Write tools only create an ``ActionProposal`` that
the token's owner approves in FloBrain (Decision 33). The token needs the
``mcp`` scope plus the tool's own scope. Tool names use ``_`` (``tasks_list``)
for client compatibility; they map to the ``ToolDefinition`` keys.
"""

import json

from django.http import HttpResponse, JsonResponse
from rest_framework.views import APIView

from platform_api.authentication import PATAuthentication
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


def _schema(name):
    tool = TOOLS[name]
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

    org = token.org
    tool = TOOLS.get(name)
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
    # write tools → proposals only
    from actions.service import ActionDenied, check, payload
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership

    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if not effective_flag(org, membership, "ai_actions", default=False):
        return _tool_result({"error": "not_available", "details": "approved actions are not enabled"}, True)
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
    return _tool_result({"results": citations(hits)})


class MCPView(APIView):
    authentication_classes = [PATAuthentication]
    permission_classes = []
    throttle_classes = [PATThrottle, PATUserThrottle]

    def post(self, request):
        from platform_api.models import PersonalAccessToken

        token = request.auth
        if not isinstance(token, PersonalAccessToken):
            return JsonResponse(_err(None, -32001, "a personal access token is required"), status=401)
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
            tools = [
                {
                    "name": name,
                    "description": spec["description"],
                    "inputSchema": _schema(name),
                    "annotations": {"readOnlyHint": spec["readOnly"]},
                }
                for name, spec in TOOLS.items()
                if spec["scope"] in token.scopes
            ]
            return JsonResponse(_ok(rid, {"tools": tools}))
        if method == "tools/call":
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return JsonResponse(_err(rid, -32602, "params.name is required"))
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                return JsonResponse(_err(rid, -32602, "params.arguments must be an object"))
            return JsonResponse(_ok(rid, _call(request.user, token, params["name"], args)))
        return JsonResponse(_err(rid, -32601, "method not found"))
