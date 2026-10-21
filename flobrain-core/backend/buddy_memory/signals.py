"""Erase a person's memories when they leave an org or their deletion request is approved.

Connected from ``BuddyMemoryConfig.ready`` so the privacy and organizations apps stay untouched.
Account deletion needs nothing: personal memories cascade with the user row.
"""

from django.db.models.signals import post_delete, post_save

LEAVING = {"terminated", "offboarding", "graduated"}


def _deletion_done(sender, instance, **kwargs):
    if getattr(instance, "status", "") == "done" and instance.user_id and instance.org_id:
        from buddy_memory.services import erase_person

        erase_person(instance.org, instance.user)


def _membership_saved(sender, instance, **kwargs):
    if instance.employment_status in LEAVING:
        from buddy_memory.services import erase_person

        erase_person(instance.org, instance.user)


def _membership_deleted(sender, instance, **kwargs):
    from buddy_memory.services import erase_person

    erase_person(instance.org, instance.user)


def connect():
    from organizations.models import OrgMembership
    from privacy.models import DeletionRequest

    post_save.connect(_deletion_done, sender=DeletionRequest, dispatch_uid="buddy_memory_deletion_done")
    post_save.connect(_membership_saved, sender=OrgMembership, dispatch_uid="buddy_memory_membership_saved")
    post_delete.connect(_membership_deleted, sender=OrgMembership, dispatch_uid="buddy_memory_membership_deleted")
