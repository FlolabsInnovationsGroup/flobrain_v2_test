from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from organizations.models import Project, ProjectMembership, TeamMembership
from rooms.services import ensure_project_room, ensure_team_room


@receiver(post_save, sender=TeamMembership)
def _sync_team_room(sender, instance, **kwargs):
    ensure_team_room(instance.team)


@receiver(post_save, sender=Project)
def _sync_project_room(sender, instance, **kwargs):
    ensure_project_room(instance)


@receiver(post_save, sender=ProjectMembership)
def _sync_project_member_room(sender, instance, **kwargs):
    ensure_project_room(instance.project)


@receiver(m2m_changed, sender=Project.teams.through)
def _sync_project_teams_room(sender, instance, **kwargs):
    if kwargs.get("action") in {"post_add", "post_remove", "post_clear"}:
        ensure_project_room(instance)
