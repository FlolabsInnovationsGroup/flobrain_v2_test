"""Triggers: schedules (``tick``), and receivers on existing models connected from
``AutomationsConfig.ready`` (no other app is edited).

- ``task_created``: ``Task`` post_save, created.
- ``task_blocked``: ``Task`` saved with ``is_blocked`` turning true.
- ``room_message``: a new ``RoomMessage`` containing the keyword (whole word, any case).
- ``meeting_ended``: ``Meeting.ended_at`` set.
- ``customer_conversation``: ``fire_event(org, "customer_conversation", payload, key)`` for the
  channels app to call; a post_save receiver is also connected when a conversation model exists.
- ``webhook``: ``automations.views.InboundHookView``.

A workflow fires only when the automations flag is on, the workflow is enabled, and its
``run_as`` may see the item (room access, task visibility). Writes made by a run never fire.
A receiver failure is logged and never breaks the save.
"""

import logging
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from automations import engine
from automations.models import Workflow, WorkflowRun

logger = logging.getLogger(__name__)
BLOCKED_WINDOW = timedelta(minutes=10)


def _safe(fn, org, *args):
    if engine.RUNNING.get() or org is None or not engine.org_enabled(org):
        return  # cheap exit before any savepoint: most orgs have automations off
    args = (org, *args)
    try:
        with transaction.atomic():
            fn(*args)
    except Exception:  # noqa: BLE001
        logger.exception("automation trigger failed")


def _workflows(org, trigger_type):
    if org is None or not engine.org_enabled(org):
        return []
    return list(
        Workflow.objects.filter(org=org, enabled=True, trigger_type=trigger_type).select_related("run_as", "org")
    )


def fire_event(org, trigger_type, payload, key, match=None, visible=None) -> int:
    """Start a run for each matching workflow (once per ``key``). Returns how many started."""
    started = 0
    for workflow in _workflows(org, trigger_type):
        if match is not None and not match(workflow.trigger or {}):
            continue
        owner = workflow.run_as
        if owner is None or (visible is not None and not visible(owner)):
            continue
        if engine.start_run(workflow, trigger_type, payload, event_key=f"{trigger_type}:{key}"):
            started += 1
    return started


# --- tasks -------------------------------------------------------------------------


def _task_payload(task):
    return {
        "task": str(task.id),
        "title": task.title[:200],
        "team": str(task.team_id) if task.team_id else "",
        "room": str(task.room_id) if task.room_id else "",
        "status": task.status,
        "reason": (task.blocked_reason or "")[:300],
    }


def _task_visible(task):
    from organizations.permissions import can

    return lambda user: can(user, "task.view", {"org": task.org, "team": task.team, "project": task.project})


def _team_match(task):
    return lambda trigger: not trigger.get("team") or trigger["team"] == str(task.team_id)


def task_saved(sender, instance, created, raw=False, **kwargs):
    """``blocked_since`` is set only when a task becomes blocked, so (task, blocked_since) is the
    event: later saves of the same blocked task are deduplicated by the run's ``event_key``."""
    if raw:
        return
    if created:
        _safe(fire_event, instance.org, "task_created", _task_payload(instance), str(instance.id), _team_match(instance), _task_visible(instance))
    if instance.is_blocked and instance.blocked_since and instance.blocked_since >= timezone.now() - BLOCKED_WINDOW:
        _safe(
            fire_event, instance.org, "task_blocked", _task_payload(instance), f"{instance.id}:{instance.blocked_since.isoformat()}",
            _team_match(instance), _task_visible(instance),
        )


# --- rooms and meetings ----------------------------------------------------------------


def _keyword_match(body):
    def match(trigger):
        keyword = (trigger.get("keyword") or "").strip()
        return bool(keyword) and re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", body or "", re.IGNORECASE) is not None

    return match


def message_saved(sender, instance, created, raw=False, **kwargs):
    if raw or not created or instance.deleted_at:
        return
    from rooms.services import display_name, user_can_access_room

    room = instance.room
    payload = {
        "room": str(room.id),
        "room_name": room.name[:200],
        "message": str(instance.id),
        "title": (instance.body or "")[:200],
        "text": (instance.body or "")[:500],
        "author": display_name(instance.author),
    }
    body = instance.body

    def match(trigger):
        return trigger.get("room") == str(room.id) and _keyword_match(body)(trigger)

    _safe(fire_event, room.org, "room_message", payload, str(instance.id), match, lambda user: user_can_access_room(user, room))


def meeting_remember(sender, instance, **kwargs):
    instance._automation_was_open = bool(
        instance.ended_at
        and not instance._state.adding
        and sender.objects.filter(pk=instance.pk, ended_at__isnull=True).exists()
    )


def meeting_saved(sender, instance, raw=False, **kwargs):
    if raw or not instance.ended_at or not getattr(instance, "_automation_was_open", False):
        return
    from rooms.services import user_can_access_room

    room = instance.room
    payload = {"meeting": str(instance.id), "room": str(room.id), "room_name": room.name[:200], "title": instance.title[:200]}

    def match(trigger):
        return not trigger.get("room") or trigger["room"] == str(room.id)

    _safe(fire_event, instance.org, "meeting_ended", payload, str(instance.id), match, lambda user: user_can_access_room(user, room))


# --- customer conversations (channels app) -------------------------------------------------


def customer_conversation(org, conversation_id, title="", channel=""):
    """For the channels app: a new customer conversation started."""
    payload = {"conversation": str(conversation_id), "title": (title or "New customer conversation")[:200], "channel": channel[:32]}
    _safe(fire_event, org, "customer_conversation", payload, str(conversation_id))


def conversation_saved(sender, instance, created, raw=False, **kwargs):
    if raw or not created or getattr(instance, "org", None) is None:
        return
    title = getattr(instance, "title", "") or getattr(instance, "subject", "") or getattr(instance, "contact_name", "") or ""
    customer_conversation(instance.org, instance.pk, str(title), str(getattr(instance, "channel", "") or ""))


# --- approvals -------------------------------------------------------------------------


def proposal_saved(sender, instance, raw=False, **kwargs):
    if raw or not instance.tool_key.startswith("automations.") or instance.status == "proposed":
        return
    from automations.models import RunApproval

    approval_id = RunApproval.objects.filter(proposal_id=instance.pk, state=RunApproval.PENDING).values_list("id", flat=True).first()
    if approval_id:
        transaction.on_commit(lambda: _apply(approval_id))


def _apply(approval_id):
    try:
        engine.apply_decision(approval_id)
    except Exception:  # noqa: BLE001 - the tick reconciles it later
        logger.exception("automation approval %s could not be applied", approval_id)


# --- schedules -----------------------------------------------------------------------------


def tick(now=None) -> dict:
    """Fire due schedules, process queued runs, and reconcile approvals. Safe to repeat."""
    from automations.schedule import next_run

    now = now or timezone.now()
    fired = 0
    due = Workflow.objects.filter(enabled=True, trigger_type="schedule", next_run_at__lte=now).select_related("org")
    for workflow in due[:500]:
        old = workflow.next_run_at
        nxt = next_run(workflow.trigger or {}, workflow.org, now, last=old)
        # Claim this slot: only one ticker moves next_run_at from ``old``.
        if not Workflow.objects.filter(pk=workflow.pk, next_run_at=old).update(next_run_at=nxt):
            continue
        if not engine.org_enabled(workflow.org) or workflow.run_as is None:
            continue
        if engine.start_run(workflow, "schedule", {"scheduled_for": old.isoformat()}, event_key=f"schedule:{old.isoformat()}"):
            fired += 1
    processed = 0
    for run_id in list(WorkflowRun.objects.filter(status=WorkflowRun.QUEUED).order_by("created_at").values_list("id", flat=True)[:100]):
        if engine.process_run(run_id) is not None:
            processed += 1
    moved = engine.reconcile(now)
    return {"fired": fired, "processed": processed, "reconciled": moved}


def connect():
    from django.apps import apps
    from django.db.models.signals import post_save, pre_save

    from actions.models import ActionProposal
    from meetings.models import Meeting
    from rooms.models import RoomMessage
    from tasks.models import Task

    post_save.connect(task_saved, sender=Task, dispatch_uid="automations_task_saved")
    post_save.connect(message_saved, sender=RoomMessage, dispatch_uid="automations_message_saved")
    pre_save.connect(meeting_remember, sender=Meeting, dispatch_uid="automations_meeting_remember")
    post_save.connect(meeting_saved, sender=Meeting, dispatch_uid="automations_meeting_saved")
    post_save.connect(proposal_saved, sender=ActionProposal, dispatch_uid="automations_proposal_saved")
    for name in ("Conversation", "CustomerConversation"):
        try:
            model = apps.get_model("channels", name)
        except LookupError:
            continue
        post_save.connect(conversation_saved, sender=model, dispatch_uid=f"automations_channels_{name}")
        break
