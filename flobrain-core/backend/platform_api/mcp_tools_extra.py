"""MCP tools added by the hub (growth round M1). Listed and callable only while ``mcp_hub`` is on
for the token's owner, and each tool's own feature flag and app are present.

Every tool runs as the person who connected the app: the same visibility, permissions and flags
as in FloBrain, checked on each call. Read tools answer directly. ``automation_run`` (like
``tasks_create``) only creates an ``ActionProposal`` the person approves in FloBrain.
"""

from django.apps import apps
from django.utils import timezone

UUID = {"type": "string", "format": "uuid"}

TOOLS = {
    "buddy_ask": {
        "scope": "buddies:read",
        "flag": "buddies",
        "title": "Ask a buddy",
        "description": "Ask one of your FloBrain buddies a question by its slug. Read-only: the buddy answers in text and runs no actions.",
        "schema": {
            "type": "object",
            "properties": {
                "buddy": {"type": "string", "minLength": 1, "maxLength": 80, "pattern": "^[a-z0-9-]+$"},
                "question": {"type": "string", "minLength": 1, "maxLength": 4000},
            },
            "required": ["buddy", "question"],
        },
        "readOnly": True,
        "openWorld": False,
    },
    "data_ask": {
        "scope": "data:read",
        "flag": "data_buddy",
        "app": "datasets",
        "title": "Ask a dataset",
        "description": "Answer a question from a dataset you can see. Runs one checked, read-only SELECT and returns the answer, the SQL and rows.",
        "schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "minLength": 1, "maxLength": 500},
                "dataset": UUID,
                "dataset_name": {"type": "string", "minLength": 1, "maxLength": 120},
            },
            "required": ["question"],
        },
        "readOnly": True,
    },
    "approvals_list": {
        "scope": "approvals:read",
        "title": "List my approvals",
        "description": "What is waiting for your approval in FloBrain: suggested actions and outside agent calls. Approve them in FloBrain.",
        "schema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}}},
        "readOnly": True,
    },
    "meetings_recent": {
        "scope": "meetings:read",
        "title": "Recent meeting summaries",
        "description": "Summaries, decisions and action items of recent meetings in rooms you can open. Never transcripts or recordings.",
        "schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
        },
        "readOnly": True,
    },
    "automation_run": {
        "scope": "automations:write",
        "flag": "automations",
        "app": "automations",
        "action": "automations.run",
        "title": "Run a workflow",
        "description": "Propose running one of your organization's workflows. Nothing runs until you approve it in FloBrain.",
        "readOnly": False,
        "destructive": True,
        "openWorld": True,
    },
}

# Titles and hints for the tools that existed before the hub (``platform_api.mcp.TOOLS``).
BASE_HINTS = {
    "tasks_list": {"title": "List tasks"},
    "rooms_list": {"title": "List rooms"},
    "knowledge_search": {"title": "Search knowledge"},
    "time_report": {"title": "My logged hours"},
    "tasks_create": {"title": "Suggest a task", "destructive": False},
    "rooms_post_message": {"title": "Suggest a room message", "destructive": False, "openWorld": False},
}


def annotations(name, spec) -> dict:
    """MCP tool annotations (spec 2025-06-18, ``ToolAnnotations``). Write tools only propose, but
    a client should still treat them as changing things, so ``readOnlyHint`` is false."""
    hints = {**BASE_HINTS.get(name, {}), **spec}
    read_only = bool(hints.get("readOnly"))
    out = {"title": hints.get("title") or name, "readOnlyHint": read_only, "openWorldHint": bool(hints.get("openWorld", False))}
    if not read_only:
        out["destructiveHint"] = bool(hints.get("destructive", False))
        out["idempotentHint"] = False
    else:
        out["idempotentHint"] = True
    return out


def available(name, user, org, membership) -> bool:
    from organizations.flags import effective_flag

    spec = TOOLS.get(name)
    if spec is None or not effective_flag(org, membership, "mcp_hub", default=False):
        return False
    if spec.get("app") and not apps.is_installed(spec["app"]):
        return False
    if spec.get("action"):
        from actions.registry import TOOLS as ACTIONS

        if spec["action"] not in ACTIONS:
            return False
    return not spec.get("flag") or effective_flag(org, membership, spec["flag"], default=False)


def handle(user, org, name, args) -> tuple[dict, bool]:
    """Run a read tool. Returns (data, is_error)."""
    return {
        "buddy_ask": _buddy_ask,
        "data_ask": _data_ask,
        "approvals_list": _approvals,
        "meetings_recent": _meetings,
    }[name](user, org, args)


def _err(code, details=""):
    out = {"error": code}
    if details:
        out["details"] = details
    return out, True


# --- buddy_ask -------------------------------------------------------------------------

MCP_NOTE = "\n\nYou are answering through MCP for an outside app the person connected. Answer in text only; no actions are available here."


def _buddy_ask(user, org, args):
    from brain.llm import direct
    from brain.llm.policy import check_ai
    from brain.llm.providers import DirectProvider
    from buddies.chat import BUDDY_BASE, _retrieve
    from buddies.services import visible_buddies
    from knowledge.prompting import citations, sources_block
    from organizations.permissions import can
    from telemetry.models import UsageEvent
    from telemetry.pricing import budget_decision, fill_missing_tokens, prompt_text
    from telemetry.writers import record_v2_provider_event

    if not can(user, "ai.use", org):
        return _err("permission_denied", "You can't use AI in this organization")
    buddy = visible_buddies(user, org).filter(slug=args["buddy"]).first()
    if buddy is None:
        return _err("not_found", "No buddy with that slug that you can use")
    if check_ai(org, "direct"):
        return _err("private_only", "This organization only allows self-hosted models")
    if not direct.is_configured():
        return _err("not_configured", "No AI provider is configured")
    decision = budget_decision(org, user, UsageEvent.CREDENTIAL_PLATFORM)
    if decision.code:
        return _err("budget_exceeded", "Platform budget cap reached")
    model = (buddy.default_model or "").strip() or None
    if model and model not in direct.allowlist():
        model = None
    if decision.downgrade_model:
        model = decision.downgrade_model
    question = args["question"].strip()
    hits, _state = _retrieve(user, org, buddy, question)
    system = BUDDY_BASE
    if (buddy.system_prompt or "").strip():
        system += "\n\nBuddy instructions:\n" + buddy.system_prompt.strip()
    system += MCP_NOTE
    content, used = question, 0
    if hits:
        block, used = sources_block(hits)
        content = f"{block}\n\nMessage: {question}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    result = DirectProvider(org).complete(messages, model=model, tools=None)
    result, estimated = fill_missing_tokens(result, prompt_text(messages), result.text or "")
    record_v2_provider_event(user, result, surface="mcp", org=org, estimated=estimated, credential_source=UsageEvent.CREDENTIAL_PLATFORM)
    if not result.ok or not result.text:
        return _err(result.error_code or "provider_error", "The AI provider did not answer")
    return {"buddy": {"slug": buddy.slug, "name": buddy.name}, "answer": result.text, "citations": citations(hits[:used])}, False


# --- data_ask --------------------------------------------------------------------------


def _data_ask(user, org, args):
    from actions.service import ActionDenied
    from datasets import tools as data_tools

    try:
        data_tools.check(user, org, args)
        return data_tools.execute(user, org, args), False
    except ActionDenied as exc:
        return _err(exc.code, str(exc))


# --- approvals_list --------------------------------------------------------------------


def _approvals(user, org, args):
    from actions.models import ActionProposal
    from actions.registry import TOOLS as ACTIONS
    from platform_api.models import ExternalAgentCall

    now, limit = timezone.now(), args.get("limit", 20)
    proposals = ActionProposal.objects.filter(org=org, user=user, status=ActionProposal.STATUS_PROPOSED, expires_at__gt=now).order_by("-created_at")[:limit]
    calls = ExternalAgentCall.objects.filter(org=org, user=user, status=ExternalAgentCall.PROPOSED, expires_at__gt=now).select_related("server").order_by("-created_at")[:limit]
    return {
        "actions": [
            {
                "id": str(p.id),
                "label": ACTIONS.get(p.tool_key, {}).get("label", p.tool_key),
                "summary": p.summary,
                "created_at": p.created_at.isoformat(),
                "expires_at": p.expires_at.isoformat(),
            }
            for p in proposals
        ],
        "outside_agent_calls": [
            {"id": str(c.id), "server": c.server.name, "tool": c.tool, "created_at": c.created_at.isoformat()} for c in calls
        ],
        "next": "Approve or reject these in FloBrain.",
    }, False


# --- meetings_recent -------------------------------------------------------------------


def _meetings(user, org, args):
    from datetime import timedelta

    from meetings.models import Meeting
    from organizations.permissions import can
    from rooms.services import accessible_rooms

    if not can(user, "meeting.view", org):
        return _err("permission_denied", "You can't see meetings in this organization")
    since = timezone.now() - timedelta(days=args.get("days", 14))
    rows = (
        Meeting.objects.filter(org=org, room__in=accessible_rooms(user, org), started_at__gte=since)
        .select_related("room", "summary")
        .order_by("-started_at")[: args.get("limit", 10)]
    )
    out = []
    for m in rows:
        summary = getattr(m, "summary", None)
        out.append(
            {
                "id": str(m.id),
                "title": m.title,
                "room": m.room.name,
                "started_at": m.started_at.isoformat(),
                "ended_at": m.ended_at.isoformat() if m.ended_at else None,
                "summary": (summary.text or "")[:3000] if summary else None,
                "decisions": [str(d.get("text") if isinstance(d, dict) else d)[:300] for d in (summary.decisions or [])[:20]] if summary else [],
                "action_items": [str(a.get("text") if isinstance(a, dict) else a)[:300] for a in (summary.action_items or [])[:20]] if summary else [],
            }
        )
    return {"meetings": out}, False


# --- automations.run (approval-gated action, registered from PlatformApiConfig.ready) --------

RUN_KEY = "automations.run"
RUN_SPEC = {
    "perm_key": "automations.use",
    "flag": "automations",
    "risk": "write",
    "label": "Run a workflow",
    "description": "Run one of the organization's workflows now. It runs only after you approve it.",
    "schema": {
        "type": "object",
        "properties": {"workflow": UUID, "workflow_name": {"type": "string", "minLength": 1, "maxLength": 120}},
        "additionalProperties": False,
    },
}


def _workflow(user, org, args):
    from actions.service import ActionDenied
    from automations.models import Workflow
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership
    from organizations.permissions import can

    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if not effective_flag(org, membership, "automations", default=False):
        raise ActionDenied("not_available", "automations are not enabled")
    qs = Workflow.objects.filter(org=org)
    if args.get("workflow"):
        wf = qs.filter(pk=args["workflow"]).first()
    elif args.get("workflow_name"):
        wf = qs.filter(name__iexact=args["workflow_name"].strip()).first()
    else:
        raise ActionDenied("invalid", "name the workflow")
    if wf is None:
        raise ActionDenied("not_found", "workflow not found")
    if not wf.enabled and not can(user, "automations.manage", org):
        raise ActionDenied("permission", "this workflow is turned off")
    if wf.run_as_id is None:
        raise ActionDenied("invalid", "nobody to run this workflow as; save it again first")
    return wf


def run_check(user, org, args) -> str:
    return f"Run workflow “{_workflow(user, org, args).name[:80]}”"


def run_execute(user, org, args) -> dict:
    from automations import engine

    wf = _workflow(user, org, args)
    run = engine.start_run(wf, "manual", {"title": wf.name, "via": "mcp"}, triggered_by=user)
    if run is None:
        return {"workflow": str(wf.id), "status": "skipped"}
    run.refresh_from_db()
    return {"workflow": str(wf.id), "run": str(run.id), "status": run.status}


def register():
    if not apps.is_installed("automations"):
        return
    from actions.plugins import handler, register_tool
    from actions.registry import TOOLS as ACTIONS

    if handler(RUN_KEY) is None and RUN_KEY not in ACTIONS:
        register_tool(RUN_KEY, RUN_SPEC, check=run_check, execute=run_execute)
