"""Event triggers for agents: member.joined and meeting.ended. Never break the save."""

import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from meetings.models import Meeting
from organizations.models import OrgMembership

logger = logging.getLogger(__name__)


def _safe(fn, *args):
    try:
        with transaction.atomic():
            fn(*args)
    except Exception:  # noqa: BLE001
        logger.exception("agent event failed")


@receiver(post_save, sender=OrgMembership, dispatch_uid="agents_member_joined")
def _member_joined(sender, instance, created, raw=False, **kwargs):
    if raw or not created or not instance.is_active_member:
        return  # pending invites are not "joined"
    from agents.service import fire_event

    _safe(fire_event, instance.org, "member.joined", {"user": str(instance.user_id)}, str(instance.user_id))


@receiver(pre_save, sender=Meeting, dispatch_uid="agents_meeting_was_open")
def _remember_open(sender, instance, **kwargs):
    instance._was_open = (
        not instance._state.adding
        and Meeting.objects.filter(pk=instance.pk, ended_at__isnull=True).exists()
    )


@receiver(post_save, sender=Meeting, dispatch_uid="agents_meeting_ended")
def _meeting_ended(sender, instance, raw=False, **kwargs):
    if raw or not instance.ended_at or not getattr(instance, "_was_open", False):
        return
    from agents.service import fire_event

    from rooms.services import user_can_access_room

    room = instance.room
    _safe(
        fire_event,
        instance.org,
        "meeting.ended",
        {"meeting": str(instance.id)},
        str(instance.id),
        lambda user: user_can_access_room(user, room),
    )
