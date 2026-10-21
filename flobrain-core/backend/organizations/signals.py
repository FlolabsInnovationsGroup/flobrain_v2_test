from django.db.models.signals import post_save
from django.dispatch import receiver

from organizations.models import OrgMembership, Project, TeamMembership
from organizations.services import sync_user_type


@receiver(post_save, sender=OrgMembership)
def _sync_on_org_membership(sender, instance, **kwargs):
    sync_user_type(instance.user)


@receiver(post_save, sender=TeamMembership)
def _sync_on_team_membership(sender, instance, **kwargs):
    sync_user_type(instance.user)


@receiver(post_save, sender=Project)
def _sync_on_project_lead(sender, instance, **kwargs):
    if instance.lead_id:
        sync_user_type(instance.lead)
