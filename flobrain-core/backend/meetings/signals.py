"""Losing access to a room takes you out of its live call (2026-10-21).

Join tokens last 10 minutes and only FloBrain creates rooms, but someone already connected would
stay until they leave. When a person is removed from a room, a team, or stops being an active
member, FloBrain removes them from every live call they can no longer open.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _kick(user_id, meetings):
    from meetings import livekit
    from rooms.services import user_can_access_room
    from users.models import User

    if not livekit.configured():
        return 0
    user = User.objects.filter(pk=user_id).first()
    removed = 0
    for meeting in meetings:
        if user is None or not user_can_access_room(user, meeting.room):
            livekit.remove_participant(meeting, str(user_id))
            removed += 1
    return removed


def _later(user_id, meetings_qs):
    def run():
        try:
            _kick(user_id, list(meetings_qs.select_related("room")))
        except Exception:  # noqa: BLE001 - never break the save that triggered it
            logger.exception("could not remove a participant from a call")

    transaction.on_commit(run)


@receiver(post_delete, sender="rooms.RoomMember", dispatch_uid="meetings_room_member_removed")
def _room_member_removed(sender, instance, **kwargs):
    from meetings.models import Meeting

    _later(instance.user_id, Meeting.objects.filter(room_id=instance.room_id, ended_at__isnull=True))


@receiver(post_delete, sender="organizations.TeamMembership", dispatch_uid="meetings_team_member_removed")
def _team_member_removed(sender, instance, **kwargs):
    from meetings.models import Meeting

    _later(instance.user_id, Meeting.objects.filter(room__team_id=instance.team_id, ended_at__isnull=True))


@receiver(post_save, sender="organizations.OrgMembership", dispatch_uid="meetings_membership_changed")
def _membership_changed(sender, instance, created=False, **kwargs):
    from meetings.models import Meeting

    if created or instance.employment_status == "active":
        return
    _later(instance.user_id, Meeting.objects.filter(org_id=instance.org_id, ended_at__isnull=True))
