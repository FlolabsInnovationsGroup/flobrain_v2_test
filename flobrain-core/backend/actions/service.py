"""Propose, approve and execute tools (Decision 33, spec 8.6).

1. ``offered_tools`` — what the model may see: the buddy's tools, enabled,
   that the user holds right now.
2. ``propose`` — a model tool call becomes an ``ActionProposal`` only after
   its arguments pass the schema and the target check for that user. Nothing
   runs.
3. ``approve`` — the proposer approves within 24 h. Arguments (possibly
   edited) are validated again and the target is re-checked for the approver
   **now**. FloBrain runs the executor (never the model) in a transaction that
   locks the proposal, so it runs at most once.
"""

import json
import logging
from datetime import timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from actions.models import ActionProposal, EmailDraft, ToolDefinition
from actions.registry import TOOLS, tool_key_for
from actions.schema import SchemaError, validate
from organizations.permissions import can

logger = logging.getLogger(__name__)


class ActionDenied(Exception):
    """The user may not run this tool on this target (maps to 403/404)."""

    def __init__(self, code="permission", details=""):
        super().__init__(details or code)
        self.code = code


def sync_tool_definitions():
    for key, tool in TOOLS.items():
        ToolDefinition.objects.update_or_create(
            key=key,
            defaults={
                "perm_key": tool["perm_key"],
                "json_schema": tool["schema"],
                "risk": tool["risk"],
                "requires_approval": tool["risk"] != "read",
            },
        )


def _enabled_keys():
    disabled = set(ToolDefinition.objects.filter(enabled=False).values_list("key", flat=True))
    return [key for key in TOOLS if key not in disabled]


def offered_tools(user, org, buddy) -> list[str]:
    from buddies.services import holds_tool

    wanted = list((buddy.allowed_tools if buddy else []) or [])
    enabled = set(_enabled_keys())
    return [key for key in wanted if key in enabled and holds_tool(user, org, key)]


# --- target checks and executors -------------------------------------------------


def _task(org, task_id, user):
    from tasks.models import Task

    task = Task.objects.filter(pk=task_id, org=org).first()
    if task is None or not can(user, "task.view", {"org": org, "team": task.team, "project": task.project}):
        raise ActionDenied("not_found", "task not found")
    return task


def _room(org, room_id, user):
    from rooms.models import Room
    from rooms.services import user_can_access_room

    room = Room.objects.filter(pk=room_id, org=org).first()
    if room is None or not user_can_access_room(user, room):
        raise ActionDenied("not_found", "room not found")
    return room


def _member(org, user_id):
    from organizations.models import OrgMembership

    membership = OrgMembership.objects.filter(org=org, user_id=user_id).select_related("user").first()
    if membership is None or not membership.is_active_member:
        raise ActionDenied("not_found", "member not found")
    return membership.user


def check(tool_key, user, org, args) -> str:
    """Raise ActionDenied when ``user`` cannot run this call. Returns a one-line summary."""
    from buddies.services import holds_tool

    if ToolDefinition.objects.filter(key=tool_key, enabled=False).exists():
        raise ActionDenied("not_available", "this tool is turned off")
    if not holds_tool(user, org, tool_key):
        raise ActionDenied("permission", "missing permission")
    if tool_key == "tasks.create":
        from organizations.models import Project, Team
        from tasks.services import can_use_project

        if args.get("team"):
            team = Team.objects.filter(pk=args["team"], org=org).first()
            if team is None or not can(user, "task.write", team):
                raise ActionDenied("not_found", "team not found")
        if args.get("project"):
            project = Project.objects.filter(pk=args["project"], org=org).first()
            if project is None or not can_use_project(user, project):
                raise ActionDenied("not_found", "project not found")
        return f"Create task “{args['title'][:80]}”"
    if tool_key == "tasks.assign":
        from tasks.services import assign_eligibility, can_assign

        task = _task(org, args["task"], user)
        assignee = _member(org, args["user"])
        if not can_assign(user, org, assignee, task):
            _, reason = assign_eligibility(user, org, assignee, task)
            raise ActionDenied("permission", reason or "cannot assign")
        return f"Assign “{task.title[:60]}” to {assignee.username or 'member ' + str(assignee.id)[:8]}"
    if tool_key == "tasks.update_status":
        from tasks.services import can_edit_task

        task = _task(org, args["task"], user)
        if not can_edit_task(user, task):
            raise ActionDenied("permission", "cannot edit this task")
        return f"Move “{task.title[:60]}” to {args['status']}"
    if tool_key == "rooms.post_message":
        room = _room(org, args["room"], user)
        return f"Post in {room.name[:60]}"
    if tool_key == "meetings.create":
        room = _room(org, args["room"], user)
        return f"Schedule “{args['title'][:60]}” in {room.name[:40]}"
    if tool_key == "email.draft":
        return f"Draft email “{(args.get('subject') or '')[:60]}”"
    if tool_key == "content.publish":
        _publish_targets(user, org, args)
        return f"Submit “{args['title'][:60]}” for approval"
    if tool_key == "reports.generate":
        from actions.reports import check_report_access

        team = check_report_access(user, org, args["team"])
        return f"Generate {args['kind'].replace('_', ' ')} for {team.name[:60]}"
    raise ActionDenied("permission", "unknown tool")


def _publish_targets(user, org, args):
    from content_studio.access import visible_projects
    from content_studio.models import RenderJob, SocialAccount
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership

    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if not (
        effective_flag(org, membership, "social_publishing", default=False)
        and effective_flag(org, membership, "content_studio", default=False)
    ):
        raise ActionDenied("not_available", "publishing is not enabled")
    project = visible_projects(user, org).filter(pk=args["project"]).first()
    render = (
        RenderJob.objects.filter(org=org, project=project, pk=args["render"], status=RenderJob.STATUS_SUCCEEDED).first()
        if project
        else None
    )
    account = SocialAccount.objects.filter(
        org=org, pk=args["social_account"], status=SocialAccount.STATUS_CONNECTED
    ).first()
    if project is None or render is None or account is None:
        raise ActionDenied("not_found", "project, render or account not found")
    return project, render, account


def execute(tool_key, user, org, args) -> dict:
    """Run the tool through the same services as the REST endpoints. Raises ActionDenied."""
    check(tool_key, user, org, args)
    if tool_key == "tasks.create":
        from django.utils.dateparse import parse_date

        from tasks.services import create_task

        task, error = create_task(
            user,
            org,
            args["title"],
            description=args.get("description", ""),
            team_id=args.get("team"),
            project_id=args.get("project"),
            due_on=parse_date(args["due_on"]) if args.get("due_on") else None,
        )
        if error:
            raise ActionDenied("not_found" if error == "not_found" else "permission", error)
        return {"task": str(task.id)}
    if tool_key == "tasks.assign":
        from tasks.services import assign_task

        ok, reason = assign_task(_task(org, args["task"], user), user, _member(org, args["user"]))
        if not ok:
            raise ActionDenied("permission", reason or "cannot assign")
        return {"task": args["task"], "user": args["user"]}
    if tool_key == "tasks.update_status":
        from tasks.services import move_task

        ok, reason = move_task(_task(org, args["task"], user), user, args["status"])
        if not ok:
            raise ActionDenied("permission", reason or "cannot move")
        return {"task": args["task"], "status": args["status"]}
    if tool_key == "rooms.post_message":
        from rooms.services import post_message

        message, reason = post_message(_room(org, args["room"], user), user, args["body"])
        if reason:
            raise ActionDenied("permission", reason)
        return {"message": str(message.id), "room": args["room"]}
    if tool_key == "meetings.create":
        from django.utils.dateparse import parse_datetime

        from meetings.models import Meeting

        starts = parse_datetime(args["starts_at"]) if args.get("starts_at") else timezone.now()
        if timezone.is_naive(starts):
            starts = timezone.make_aware(starts, dt_timezone.utc)
        meeting = Meeting.objects.create(
            org=org, room=_room(org, args["room"], user), title=args["title"], created_by=user, started_at=starts
        )
        return {"meeting": str(meeting.id)}
    if tool_key == "email.draft":
        draft = EmailDraft.objects.create(
            org=org, user=user, to=args.get("to", []), subject=args.get("subject", ""), body=args["body"]
        )
        return {"draft": str(draft.id)}
    if tool_key == "content.publish":
        from django.utils.dateparse import parse_datetime

        from content_studio.models import PublishJob

        project, render, account = _publish_targets(user, org, args)
        when = parse_datetime(args["scheduled_at"]) if args.get("scheduled_at") else None
        job = PublishJob.objects.create(
            org=org,
            project=project,
            render=render,
            social_account=account,
            created_by=user,
            title=args["title"],
            description=args.get("description", ""),
            hashtags=args.get("hashtags", []),
            scheduled_at=when if when is None or timezone.is_aware(when) else timezone.make_aware(when, dt_timezone.utc),
        )
        return {"publish_job": str(job.id), "status": job.status}  # awaiting_approval, never published here
    if tool_key == "reports.generate":
        from actions.reports import generate_report

        report = generate_report(user, org, args["team"], args["kind"])
        return {"report": str(report.id)}
    raise ActionDenied("permission", "unknown tool")


# --- proposals -------------------------------------------------------------------


def propose_from_calls(user, org, chat, buddy, calls, offered) -> tuple[list, list]:
    """Turn model tool calls into proposals. Returns (proposals, errors). Never executes."""
    proposals, errors = [], []
    for call in calls or []:
        key = tool_key_for(call.get("name", ""))
        if key is None or key not in offered:
            errors.append({"tool": call.get("name", "")[:64], "error": "tool_not_allowed"})
            continue
        try:
            raw = json.loads(call.get("arguments") or "{}")
            args = validate(TOOLS[key]["schema"], raw)
            summary = check(key, user, org, args)
        except (ValueError, SchemaError) as exc:
            errors.append({"tool": key, "error": "invalid_arguments", "details": str(exc)[:200]})
            continue
        except ActionDenied as exc:
            errors.append({"tool": key, "error": exc.code})
            continue
        proposal = ActionProposal.objects.create(
            org=org, user=user, thread=chat, buddy=buddy, tool_key=key, arguments=args, summary=summary[:300]
        )
        _audit(user, org, "action.proposed", proposal)
        proposals.append(proposal)
    return proposals, errors


def _audit(user, org, action, proposal, extra=None):
    from organizations.services.core import audit

    payload = {"tool": proposal.tool_key, "status": proposal.status}
    payload.update(extra or {})
    audit(user, action, target=proposal, payload=payload, org=org)


def _trace(user, org, proposal, ok):
    from telemetry.models import AITrace
    import uuid

    AITrace.objects.create(
        org=org,
        user=user,
        request_id=uuid.uuid4().hex,
        surface="buddy" if proposal.buddy_id else "room_ai",
        model=f"tool:{proposal.tool_key}",
        outcome="completed" if ok else "error",
    )


def _expire_if_due(proposal_id, user, org) -> bool:
    """Mark an overdue proposal expired (committed on its own). True when it was expired."""
    return bool(
        ActionProposal.objects.filter(
            pk=proposal_id, org=org, user=user, status=ActionProposal.STATUS_PROPOSED, expires_at__lte=timezone.now()
        ).update(status=ActionProposal.STATUS_EXPIRED)
    )


def approve(proposal_id, user, org, edited_args=None) -> ActionProposal:
    """Approve and execute once. Raises ActionDenied (not_found / expired / permission / invalid / not_available).

    A denial rolls everything back (nothing ran, the proposal stays open) and is audited afterwards.
    """
    if _expire_if_due(proposal_id, user, org):
        raise ActionDenied("expired")
    try:
        return _approve_locked(proposal_id, user, org, edited_args)
    except ActionDenied as exc:
        if exc.code in ("permission", "not_found", "not_available", "invalid"):
            proposal = ActionProposal.objects.filter(pk=proposal_id, org=org, user=user).first()
            if proposal is not None:
                _audit(user, org, "action.denied", proposal, {"reason": exc.code})
        raise


def changed_fields(before: dict, after: dict) -> list[str]:
    return sorted(k for k in set(before or {}) | set(after or {}) if (before or {}).get(k) != (after or {}).get(k))


def _apply_edit(proposal, user, org, edited_args) -> list[str]:
    """Validate edited arguments with the same schema and target check as the proposal. Returns the
    changed fields (empty when nothing changed). Keeps the model's original arguments once."""
    try:
        args = validate(TOOLS[proposal.tool_key]["schema"], edited_args)
    except (SchemaError, ValueError, KeyError) as exc:
        raise ActionDenied("invalid", str(exc)) from exc
    summary = check(proposal.tool_key, user, org, args)[:300]
    changed = changed_fields(proposal.arguments, args)
    if changed:
        if proposal.original_arguments is None:
            proposal.original_arguments = proposal.arguments
        proposal.arguments, proposal.summary = args, summary
    return changed


def _lock_open(proposal_id, user, org):
    proposal = ActionProposal.objects.select_for_update().filter(pk=proposal_id, org=org, user=user).first()
    if proposal is None:
        raise ActionDenied("not_found")
    if proposal.status != ActionProposal.STATUS_PROPOSED:
        raise ActionDenied("not_pending")
    if proposal.is_expired:  # expired between the check above and the lock
        raise ActionDenied("expired")
    return proposal


def edit(proposal_id, user, org, edited_args) -> ActionProposal:
    """Change a pending proposal's arguments without running it (the "Edit" on an approval card)."""
    if _expire_if_due(proposal_id, user, org):
        raise ActionDenied("expired")
    with transaction.atomic():
        proposal = _lock_open(proposal_id, user, org)
        changed = _apply_edit(proposal, user, org, edited_args)
        if changed:
            proposal.save(update_fields=["arguments", "original_arguments", "summary"])
            _audit(user, org, "action.edited", proposal, {"fields": changed})
    return proposal


def _approve_locked(proposal_id, user, org, edited_args):
    with transaction.atomic():
        proposal = _lock_open(proposal_id, user, org)
        changed = []
        if edited_args is not None:
            changed = _apply_edit(proposal, user, org, edited_args)
            if changed:
                _audit(user, org, "action.edited", proposal, {"fields": changed})
        args = proposal.arguments
        proposal.decided_by = user
        proposal.decided_at = timezone.now()
        try:
            with transaction.atomic():  # a failed executor rolls back its own writes only
                result = execute(proposal.tool_key, user, org, args)
        except ActionDenied as exc:
            if exc.code in ("not_found", "permission", "not_available"):
                raise  # access changed or the tool was turned off: roll back, nothing ran
            proposal.status, proposal.error = ActionProposal.STATUS_FAILED, str(exc)[:200]
            proposal.save()
            _audit(user, org, "action.failed", proposal)
            _trace(user, org, proposal, False)
            return proposal
        except Exception as exc:  # noqa: BLE001 - recorded on the proposal, never re-run
            logger.exception("action %s failed", proposal.id)
            proposal.status, proposal.error = ActionProposal.STATUS_FAILED, type(exc).__name__
            proposal.save()
            _audit(user, org, "action.failed", proposal)
            _trace(user, org, proposal, False)
            return proposal
        proposal.status, proposal.result = ActionProposal.STATUS_EXECUTED, result
        proposal.save()
        _audit(user, org, "action.executed", proposal, {"edited": proposal.original_arguments is not None, "edited_fields": changed})
        _trace(user, org, proposal, True)
        if proposal.thread_id:
            from brain.models import Message

            Message.objects.create(
                chat_id=proposal.thread_id, role=Message.ROLE_ASSISTANT, text=f"Done: {proposal.summary}"
            )
    return proposal


def reject(proposal_id, user, org) -> ActionProposal:
    with transaction.atomic():
        proposal = ActionProposal.objects.select_for_update().filter(pk=proposal_id, org=org, user=user).first()
        if proposal is None:
            raise ActionDenied("not_found")
        if proposal.status != ActionProposal.STATUS_PROPOSED:
            raise ActionDenied("not_pending")
        proposal.status = ActionProposal.STATUS_REJECTED
        proposal.decided_by, proposal.decided_at = user, timezone.now()
        proposal.save()
        _audit(user, org, "action.rejected", proposal)
    return proposal


def payload(proposal) -> dict:
    return {
        "id": str(proposal.id),
        "tool": proposal.tool_key,
        "label": TOOLS.get(proposal.tool_key, {}).get("label", proposal.tool_key),
        "summary": proposal.summary,
        "arguments": proposal.arguments,
        "original_arguments": proposal.original_arguments,
        "edited": proposal.original_arguments is not None,
        "schema": TOOLS.get(proposal.tool_key, {}).get("schema", {}),
        "status": proposal.status,
        "thread": proposal.thread_id,
        "buddy": str(proposal.buddy_id) if proposal.buddy_id else None,
        "result": proposal.result,
        "error": proposal.error,
        "expires_at": proposal.expires_at.isoformat(),
        "created_at": proposal.created_at.isoformat(),
    }
