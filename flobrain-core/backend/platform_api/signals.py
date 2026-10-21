"""Event catalog for automations (Phase 14c). Ids and short fields only; never DM/group content."""

import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from meetings.models import Meeting
from organizations.models import OrgMembership
from tasks.models import Task

logger = logging.getLogger(__name__)


def _safe(fn, *args):
    try:
        with transaction.atomic():
            fn(*args)
    except Exception:  # noqa: BLE001
        logger.exception("webhook emit failed")


def _emit(org, event, data):
    from platform_api.webhooks import emit

    _safe(emit, org, event, data)


@receiver(pre_save, sender=Task, dispatch_uid="webhooks_task_status_before")
def _task_before(sender, instance, **kwargs):
    instance._was_status = (
        None if instance._state.adding else Task.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    )


@receiver(post_save, sender=Task, dispatch_uid="webhooks_task_events")
def _task_events(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    data = {"task": str(instance.id), "team": str(instance.team_id) if instance.team_id else None}
    if created:
        _emit(instance.org, "task.created", data)
    elif instance.status == Task.STATUS_DONE and getattr(instance, "_was_status", None) != Task.STATUS_DONE:
        _emit(instance.org, "task.completed", data)


@receiver(pre_save, sender=OrgMembership, dispatch_uid="webhooks_member_before")
def _member_before(sender, instance, **kwargs):
    previous = None if instance._state.adding else OrgMembership.objects.filter(pk=instance.pk).first()
    instance._was_active = bool(previous and previous.is_active_member)


@receiver(post_save, sender=OrgMembership, dispatch_uid="webhooks_member_joined")
def _member_joined(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    if instance.is_active_member and (created or not getattr(instance, "_was_active", False)):
        _emit(instance.org, "member.joined", {"user": str(instance.user_id)})  # active members only, not invites
    if not instance.is_active_member:
        _safe(_revoke_tokens, instance)


def _revoke_tokens(membership):
    """Deactivation revokes the user's tokens for that org at once (not only on next use)."""
    from django.utils import timezone

    from platform_api.models import PersonalAccessToken

    PersonalAccessToken.objects.filter(user_id=membership.user_id, org_id=membership.org_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


@receiver(pre_save, sender=Meeting, dispatch_uid="webhooks_meeting_open_before")
def _meeting_before(sender, instance, **kwargs):
    instance._webhook_was_open = (
        not instance._state.adding and Meeting.objects.filter(pk=instance.pk, ended_at__isnull=True).exists()
    )


@receiver(post_save, sender=Meeting, dispatch_uid="webhooks_meeting_ended")
def _meeting_ended(sender, instance, raw=False, **kwargs):
    from rooms.services import PRIVATE_ROOM_KINDS

    if raw or not instance.ended_at or not getattr(instance, "_webhook_was_open", False):
        return
    if instance.room.kind in PRIVATE_ROOM_KINDS:
        return  # nothing about direct or group rooms leaves FloBrain
    _emit(instance.org, "meeting.ended", {"meeting": str(instance.id), "room": str(instance.room_id)})
