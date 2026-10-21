from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from organizations.models import Project, ProjectMembership, Team, TeamMembership
from rooms.models import Room, RoomMember
from rooms.services import ensure_project_room, ensure_team_room


@receiver(pre_save, sender=TeamMembership)
def _remember_old_team(sender, instance, **kwargs):
    if instance.pk:
        instance._old_team_id = (
            TeamMembership.objects.filter(pk=instance.pk).values_list("team_id", flat=True).first()
        )


@receiver(post_save, sender=TeamMembership)
def _sync_team_room(sender, instance, **kwargs):
    from rooms.services import prune_project_room

    ensure_team_room(instance.team)
    old_team_id = getattr(instance, "_old_team_id", None)
    if old_team_id and old_team_id != instance.team_id:
        # Moved to another team: leave the old team's room and its projects' rooms.
        old_team = Team.objects.filter(pk=old_team_id).first()
        if old_team is not None:
            ensure_team_room(old_team)
        for project in Project.objects.filter(teams__id=old_team_id):
            prune_project_room(project)


@receiver(pre_delete, sender=Team)
def _remember_team_projects(sender, instance, **kwargs):
    # The cascade removes Project.teams rows before TeamMembership post_delete runs.
    instance._project_ids = list(Project.objects.filter(teams=instance).values_list("pk", flat=True))


@receiver(post_delete, sender=Team)
def _prune_after_team_delete(sender, instance, **kwargs):
    from rooms.services import prune_project_room

    for project in Project.objects.filter(pk__in=getattr(instance, "_project_ids", [])):
        prune_project_room(project)


@receiver(post_delete, sender=TeamMembership)
def _leave_team_rooms(sender, instance, **kwargs):
    """Only removes access; never creates rows (safe during cascades)."""
    from rooms.services import prune_project_room

    RoomMember.objects.filter(
        room__team_id=instance.team_id, room__kind=Room.KIND_TEAM, user_id=instance.user_id
    ).delete()
    for project in Project.objects.filter(teams__id=instance.team_id):
        prune_project_room(project)


@receiver(post_save, sender=Project)
def _sync_project_room(sender, instance, **kwargs):
    ensure_project_room(instance)


@receiver(post_save, sender=ProjectMembership)
def _sync_project_member_room(sender, instance, **kwargs):
    ensure_project_room(instance.project)


@receiver(post_delete, sender=ProjectMembership)
def _leave_project_room(sender, instance, **kwargs):
    from rooms.services import prune_project_room

    project = Project.objects.filter(pk=instance.project_id).first()
    if project is not None:
        prune_project_room(project)


@receiver(m2m_changed, sender=Project.teams.through)
def _sync_project_teams_room(sender, instance, **kwargs):
    if kwargs.get("action") in {"post_add", "post_remove", "post_clear"}:
        ensure_project_room(instance)


@receiver(post_save, sender="rooms.RoomMessage")
def _push_direct_message(sender, instance, created, **kwargs):
    """A new DM or group message pushes "New message from X" (no text) to the other members (Phase 10)."""
    from django.db import transaction

    from notifications.push import configured

    if not created or not configured() or instance.room.kind not in (Room.KIND_DIRECT, Room.KIND_GROUP):
        return
    recipients = list(
        RoomMember.objects.filter(
            room=instance.room,
            user__org_memberships__org_id=instance.room.org_id,
            user__org_memberships__employment_status="active",
        )
        .exclude(user_id=instance.author_id)
        .values_list("user_id", flat=True)
        .distinct()
    )
    if not recipients:
        return
    from jobs.queue import enqueue

    payload = {
        "users": [str(u) for u in recipients],
        "title": f"New message from {getattr(instance.author, 'username', None) or 'a colleague'}",
        "url": f"/w/{instance.room.org.slug}/rooms/{instance.room_id}",
        "kind": "direct_message",
    }
    transaction.on_commit(lambda: enqueue("notifications.push", payload))
