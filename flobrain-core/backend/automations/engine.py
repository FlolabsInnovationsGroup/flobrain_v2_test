"""Run workflows step by step (growth round W1).

- ``start_run`` creates a run (deduplicated by ``event_key``, rate limited for event triggers)
  and queues it after the current transaction commits.
- ``process_run`` claims a queued run (one processor wins), executes the remaining steps of the
  run's own snapshot of steps, and records each one in ``step_log``. A failed step stops the run.
- Steps that leave FloBrain, and ``wait_for_approval``, create an ``ActionProposal`` for the
  workflow's ``run_as`` and pause the run at ``waiting_approval``. ``apply_decision`` resumes
  (approved), cancels (declined or expired) or fails it. Nothing external runs without an
  approved proposal, except ``call_webhook`` to a host an admin marked trusted.
- Every step runs with ``run_as``'s access at run time, through the same services as the API.
- Writes made by a run never fire triggers (``RUNNING``), so workflows cannot loop.
"""

import contextlib
import contextvars
import logging
import re
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from automations.models import RunApproval, Workflow, WorkflowRun
from automations.schema import TEMPLATED

logger = logging.getLogger(__name__)

JOB = "automations.process_run"
FLAG = "automations"
MAX_EVENT_RUNS_PER_HOUR = 30
OUTPUT_MAX = 4000
APPROVAL_TTL = timedelta(hours=72)
STALE_AFTER = timedelta(minutes=30)

OUTSIDE_TX = {"ai_prompt", "call_webhook"}

RUNNING = contextvars.ContextVar("automations_running", default=False)


class StepFailed(Exception):
    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = detail or {}


class StopRun(Exception):
    """End the run early as done (a condition was not met)."""


# --- flags and people --------------------------------------------------------------


def org_enabled(org) -> bool:
    from organizations.flags import effective_flag

    return effective_flag(org, None, FLAG, default=False)


def active_member(org, user) -> bool:
    from organizations.models import OrgMembership

    if user is None:
        return False
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return bool(membership and membership.is_active_member)


# --- creating runs -----------------------------------------------------------------


def _over_rate(workflow) -> bool:
    since = timezone.now() - timedelta(hours=1)
    return (
        WorkflowRun.objects.filter(workflow=workflow, created_at__gte=since).exclude(reason="manual").count()
        >= MAX_EVENT_RUNS_PER_HOUR
    )


def start_run(workflow, reason, payload=None, event_key="", triggered_by=None):
    """Create and queue a run. Returns None when deduplicated or rate limited."""
    if reason != "manual" and _over_rate(workflow):
        logger.info("automation %s over its hourly run limit", workflow.pk)
        return None
    try:
        with transaction.atomic():
            run = WorkflowRun.objects.create(
                org=workflow.org,
                workflow=workflow,
                reason=reason[:32],
                event_key=(event_key or "")[:160],
                trigger_payload=payload or {},
                steps=list(workflow.steps or []),
                triggered_by=triggered_by,
            )
    except IntegrityError:
        return None
    Workflow.objects.filter(pk=workflow.pk).update(last_run_at=run.created_at)
    dispatch(run.id)
    return run


def dispatch(run_id):
    """Process the run after commit: inline when jobs are eager, on the worker when one exists,
    otherwise ``tick_automations`` picks it up."""
    run_id = str(run_id)

    def go():
        from jobs.queue import enqueue

        try:
            enqueue(JOB, {"run_id": run_id})
        except Exception:  # noqa: BLE001 - the tick retries queued runs
            logger.exception("automation run %s could not be queued", run_id)

    transaction.on_commit(go)


# --- templating ----------------------------------------------------------------------

PLACEHOLDER = re.compile(r"\{\{\s*(steps\.(\d+)\.output|trigger\.([a-z_]{1,40})|workflow\.name|today)\s*\}\}")


def render(text, ctx) -> str:
    """Replace ``{{steps.N.output}}``, ``{{trigger.key}}``, ``{{workflow.name}}`` and ``{{today}}``.
    Plain substitution: nothing is evaluated."""

    def sub(match):
        if match.group(2):
            return str(ctx["steps"].get(int(match.group(2)), ""))
        if match.group(3):
            value = ctx["trigger"].get(match.group(3), "")
            return value if isinstance(value, str) else str(value) if isinstance(value, (int, float)) else ""
        if match.group(1) == "workflow.name":
            return ctx["workflow"]
        return ctx["today"]

    return PLACEHOLDER.sub(sub, text or "")


def _context(run):
    outputs = {}
    for entry in run.step_log or []:
        if entry and entry.get("output") is not None:
            outputs[int(entry["step"])] = entry["output"]
    return {
        "trigger": run.trigger_payload or {},
        "steps": outputs,
        "workflow": run.workflow.name,
        "today": timezone.localdate().isoformat(),
    }


# --- processing -----------------------------------------------------------------------


def _log(run, index, status, output=None, detail=None, step=None):
    log = list(run.step_log or [])
    entry = {
        "step": index + 1,
        "type": (step or {}).get("type", ""),
        "label": (step or {}).get("label", ""),
        "status": status,
        "output": (output[:OUTPUT_MAX] if isinstance(output, str) else output),
        "detail": detail or {},
        "at": timezone.now().isoformat(),
    }
    while len(log) <= index:
        log.append(None)
    log[index] = entry
    run.step_log = log


def _finish(run, status, error=""):
    run.status, run.error, run.finished_at = status, (error or "")[:300], timezone.now()
    run.save(update_fields=["status", "error", "finished_at", "step_log", "current_step"])


def process_run(run_id):
    """Execute the remaining steps of a queued run. Safe to call twice: only one call claims it."""
    now = timezone.now()
    claimed = WorkflowRun.objects.filter(pk=run_id, status=WorkflowRun.QUEUED).update(status=WorkflowRun.RUNNING)
    if not claimed:
        return None
    run = WorkflowRun.objects.select_related("workflow", "workflow__run_as", "org").get(pk=run_id)
    if run.started_at is None:
        run.started_at = now
        run.save(update_fields=["started_at"])
    workflow, org = run.workflow, run.org
    owner = workflow.run_as
    if not org_enabled(org):
        _finish(run, WorkflowRun.CANCELLED, "Automations are switched off.")
        return run
    if not active_member(org, owner):
        _finish(run, WorkflowRun.FAILED, "The person this workflow runs as is no longer an active member.")
        return run
    token = RUNNING.set(True)
    try:
        return _steps(run, org, owner)
    finally:
        RUNNING.reset(token)


def _steps(run, org, owner):
    steps = run.steps or []
    while run.current_step < len(steps):
        index = run.current_step
        step = dict(steps[index])
        ctx = _context(run)
        for field in TEMPLATED.get(step.get("type"), ()):
            if field in step:
                step[field] = render(step[field], ctx)
        handler = HANDLERS.get(step.get("type"))
        try:
            if handler is None:
                raise StepFailed("Unknown step type.")
            # Model calls and outgoing requests do not hold a transaction open; a trusted webhook
            # commits its "started" marker first so an interrupted call is never repeated.
            scope = contextlib.nullcontext() if step.get("type") in OUTSIDE_TX else transaction.atomic()
            with scope:
                outcome = handler(run, index, step, org, owner)
                if outcome == "waiting":
                    run.save(update_fields=["status", "step_log", "current_step"])
                    return run
                status, output, detail = outcome
                _log(run, index, status, output, detail, step)
                run.current_step = index + 1
                run.save(update_fields=["step_log", "current_step"])
        except StopRun as exc:
            _log(run, index, "done", str(exc), {"stopped": True}, step)
            run.current_step = len(steps)
            _finish(run, WorkflowRun.DONE)
            return run
        except StepFailed as exc:
            _log(run, index, "failed", None, {"error": str(exc)[:300], **exc.detail}, step)
            _finish(run, WorkflowRun.FAILED, str(exc))
            return run
        except Exception as exc:  # noqa: BLE001 - recorded on the run, never retried blindly
            logger.exception("automation run %s step %s failed", run.pk, index + 1)
            _log(run, index, "failed", None, {"error": type(exc).__name__}, step)
            _finish(run, WorkflowRun.FAILED, f"Step {index + 1} failed.")
            return run
    _finish(run, WorkflowRun.DONE)
    return run


# --- approvals ----------------------------------------------------------------------


def _propose(run, index, step, org, owner, tool_key, args):
    """Pause ``run`` on an approval for ``owner``. Never runs the tool."""
    from actions.models import ActionProposal
    from actions.registry import TOOLS
    from actions.schema import SchemaError, validate
    from actions.service import ActionDenied, check
    from organizations.services.core import audit

    run.status = WorkflowRun.WAITING
    run.save(update_fields=["status"])
    try:
        args = validate(TOOLS[tool_key]["schema"], args)
        summary = check(tool_key, owner, org, args)
    except (SchemaError, ValueError) as exc:
        raise StepFailed(f"The step is not valid: {exc}") from exc
    except ActionDenied as exc:
        raise StepFailed(f"The approval could not be created ({exc.code}).") from exc
    proposal = ActionProposal.objects.create(
        org=org,
        user=owner,
        tool_key=tool_key,
        arguments=args,
        summary=summary[:300],
        expires_at=timezone.now() + APPROVAL_TTL,
    )
    RunApproval.objects.create(run=run, step=index, proposal=proposal)
    audit(owner, "action.proposed", target=proposal, payload={"tool": tool_key, "status": proposal.status, "workflow": str(run.workflow_id)}, org=org)
    _log(run, index, "waiting", None, {"approval": str(proposal.id), "summary": proposal.summary}, step)
    run.current_step = index
    return "waiting"


DECISION = {
    "executed": RunApproval.APPROVED,
    "rejected": RunApproval.REJECTED,
    "failed": RunApproval.FAILED,
    "expired": RunApproval.EXPIRED,
}


def apply_decision(approval_id):
    """Move a paused run on once its proposal was decided. Idempotent."""
    with transaction.atomic():
        approval = (
            RunApproval.objects.select_for_update()
            .select_related("proposal", "run", "run__workflow")
            .filter(pk=approval_id, state=RunApproval.PENDING)
            .first()
        )
        if approval is None:
            return None
        state = DECISION.get(approval.proposal.status)
        if state is None:
            return None
        approval.state = state
        approval.save(update_fields=["state"])
        run = WorkflowRun.objects.select_for_update().select_related("workflow").get(pk=approval.run_id)
        if run.status != WorkflowRun.WAITING or run.current_step != approval.step:
            return run
        step = (run.steps or [])[approval.step] if approval.step < len(run.steps or []) else {}
        proposal = approval.proposal
        if state == RunApproval.APPROVED:
            result = proposal.result or {}
            output = "Approved." if step.get("type") == "wait_for_approval" else proposal.summary
            _log(run, approval.step, "done", output, {"approval": str(proposal.id), "result": _safe_result(result)}, step)
            run.current_step = approval.step + 1
            run.status = WorkflowRun.QUEUED
            run.save(update_fields=["step_log", "current_step", "status"])
            dispatch(run.id)
        elif state == RunApproval.FAILED:
            _log(run, approval.step, "failed", None, {"approval": str(proposal.id), "error": proposal.error[:200]}, step)
            _finish(run, WorkflowRun.FAILED, proposal.error or "The approved step failed.")
        else:
            why = "The approval was declined." if state == RunApproval.REJECTED else "The approval expired."
            _log(run, approval.step, "skipped", None, {"approval": str(proposal.id), "error": why}, step)
            _finish(run, WorkflowRun.CANCELLED, why)
        return run


def _safe_result(result):
    return {k: v for k, v in (result or {}).items() if k in ("sent", "simulated", "recipients", "status", "approved")}


def reconcile(now=None) -> int:
    """Expire overdue approvals, apply decisions that were missed, fail runs stuck while running."""
    from actions.models import ActionProposal

    now = now or timezone.now()
    moved = 0
    pending = RunApproval.objects.filter(state=RunApproval.PENDING, run__status=WorkflowRun.WAITING).select_related("proposal")
    for approval in pending[:500]:
        proposal = approval.proposal
        if proposal.status == ActionProposal.STATUS_PROPOSED and proposal.expires_at <= now:
            ActionProposal.objects.filter(pk=proposal.pk, status=ActionProposal.STATUS_PROPOSED).update(
                status=ActionProposal.STATUS_EXPIRED
            )
        proposal.refresh_from_db(fields=["status"])
        if proposal.status != ActionProposal.STATUS_PROPOSED and apply_decision(approval.pk):
            moved += 1
    for run in WorkflowRun.objects.filter(status=WorkflowRun.RUNNING, started_at__lt=now - STALE_AFTER)[:200]:
        _finish(run, WorkflowRun.FAILED, "The run was interrupted.")
        moved += 1
    return moved


# --- step handlers ----------------------------------------------------------------


def _room(org, owner, ref, run):
    from rooms.models import Room
    from rooms.services import user_can_access_room

    room_id = (run.trigger_payload or {}).get("room") if ref == "trigger" else ref
    room = Room.objects.filter(pk=room_id, org=org, is_active=True).first() if room_id else None
    if room is None or not user_can_access_room(owner, room):
        raise StepFailed("Room not found or not available to the workflow's owner.")
    return room


def _ai_prompt(run, index, step, org, owner):
    from automations import ai, briefs

    data = briefs.context_text(org, owner, step.get("context") or "none", run, step.get("room"))
    text = ai.step_answer(org, owner, step["prompt"], data)
    return "done", text, {"context": step.get("context") or "none"}


def _post_to_room(run, index, step, org, owner):
    from rooms.services import post_message

    room = _room(org, owner, step["room"], run)
    message, reason = post_message(room, owner, step["text"][:8000])
    if reason:
        raise StepFailed(f"Could not post the message ({reason}).")
    return "done", step["text"][:300], {"room": str(room.id), "message": str(message.id)}


def _create_task(run, index, step, org, owner):
    from tasks.services import create_task

    room_id = None
    if step.get("room"):
        room_id = _room(org, owner, step["room"], run).id
    due = timezone.localdate() + timedelta(days=step["due_in_days"]) if "due_in_days" in step else None
    task, error = create_task(
        owner, org, step["title"][:200], description=(step.get("description") or "")[:4000], room_id=room_id, due_on=due
    )
    if error:
        raise StepFailed(f"Could not create the task ({error}).")
    return "done", task.title, {"task": str(task.id)}


def _notify(run, index, step, org, owner):
    from automations.briefs import recipients
    from notifications.services import notify

    users = recipients(org, owner, step.get("people") or [], step.get("roles") or [], run.trigger_payload or {})
    if not users:
        return "done", "Nobody to notify.", {"notified": 0}
    sent = notify(
        org,
        users,
        "automation.notice",
        {"text": step["text"][:1000], "title": run.workflow.name, "workflow": str(run.workflow_id)},
        link="automations",
    )
    return "done", step["text"][:300], {"notified": sent}


def _send_email(run, index, step, org, owner):
    from automations.tools import SEND_EMAIL

    args = {"workflow": str(run.workflow_id), "run": str(run.id), "to": step["to"], "subject": step["subject"][:200], "body": step["body"][:20000]}
    return _propose(run, index, step, org, owner, SEND_EMAIL, args)


def _call_webhook(run, index, step, org, owner):
    from actions.service import ActionDenied
    from automations import tools

    allowed, trusted = tools.host_allowed(org, step["url"])
    if not allowed:
        raise StepFailed("That address is not on the allowed list in automation settings.")
    method, body = step.get("method", "POST"), (step.get("body") or "")[:20000]
    if not trusted:
        args = {"workflow": str(run.workflow_id), "run": str(run.id), "url": step["url"], "method": method, "body": body}
        with transaction.atomic():
            return _propose(run, index, step, org, owner, tools.CALL_WEBHOOK, args)
    previous = (run.step_log or [])[index] if index < len(run.step_log or []) else None
    if previous and previous.get("status") == "started":
        raise StepFailed("The call was interrupted earlier and is not repeated.")
    _log(run, index, "started", None, {"trusted": True}, step)
    WorkflowRun.objects.filter(pk=run.pk).update(step_log=run.step_log)
    try:
        result = tools.call(org, run.id, run.workflow_id, step["url"], method, body)
    except ActionDenied as exc:
        raise StepFailed(str(exc)) from exc
    return "done", f"Sent to {step['url'].split('/')[2]}", {"trusted": True, **_safe_result(result)}


def _wait_for_approval(run, index, step, org, owner):
    from automations.tools import CONTINUE

    args = {"workflow": str(run.workflow_id), "run": str(run.id), "message": step["message"][:300]}
    return _propose(run, index, step, org, owner, CONTINUE, args)


def _daily_brief(run, index, step, org, owner):
    from automations import briefs

    sent = briefs.send_daily_briefs(org)
    return "done", f"Sent {sent} daily brief(s).", {"notified": sent}


def _nudge_overdue(run, index, step, org, owner):
    from automations import briefs

    sent = briefs.send_nudges(org, owner, int(step.get("min_days_overdue", 1)))
    return "done", f"Nudged {sent} person(s).", {"notified": sent}


def _check_budget(run, index, step, org, owner):
    from automations import briefs

    text = briefs.budget_status(org, int(step.get("threshold_pct", 80)))
    return "done", text, {}


HANDLERS = {
    "ai_prompt": _ai_prompt,
    "post_to_room": _post_to_room,
    "create_task": _create_task,
    "notify": _notify,
    "send_email": _send_email,
    "call_webhook": _call_webhook,
    "wait_for_approval": _wait_for_approval,
    "daily_brief": _daily_brief,
    "nudge_overdue": _nudge_overdue,
    "check_budget": _check_budget,
}
