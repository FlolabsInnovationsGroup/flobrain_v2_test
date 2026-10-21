"""Academy progress and installed industry packs (growth round, W6).

Lessons and packs are shipped content (``growth.lessons`` and ``growth.packs``), so only what a
person did and what an install created is stored here.
"""

import uuid

from django.db import models
from django.utils import timezone


class LessonProgress(models.Model):
    """One person's progress on one Academy lesson in one org. Visible to that person only."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    lesson = models.CharField(max_length=40)
    read_at = models.DateTimeField(null=True, blank=True)
    tried_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    best_score = models.PositiveSmallIntegerField(default=0)  # percent
    completed_at = models.DateTimeField(null=True, blank=True)  # the check was passed
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "growth_lesson_progress"
        constraints = [models.UniqueConstraint(fields=["org", "user", "lesson"], name="unique_lesson_progress")]


class AcademyBadge(models.Model):
    """Awarded once, when every lesson's check is passed."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    awarded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "growth_academy_badges"
        constraints = [models.UniqueConstraint(fields=["org", "user"], name="one_academy_badge")]


class InstalledPack(models.Model):
    """What one install of a pack created, so uninstall removes exactly that and nothing else.

    ``items`` is ``[{key, kind, label, model, id, fingerprint}]``: ``model`` is ``app_label.ModelName``
    and ``fingerprint`` a hash of the object's fields right after it was created. Uninstall deletes
    an object only while its fingerprint still matches (nobody changed it) and nothing was added to it.
    """

    INSTALLED, UNINSTALLED = "installed", "uninstalled"
    STATUS_CHOICES = [(INSTALLED, "Installed"), (UNINSTALLED, "Uninstalled")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    pack = models.CharField(max_length=40)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=INSTALLED)
    items = models.JSONField(default=list)
    skipped = models.JSONField(default=list)  # [{key, kind, label, needs}] at the last install
    kept = models.JSONField(default=list)  # [{key, kind, label, reason}] at uninstall
    installed_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    installed_at = models.DateTimeField(default=timezone.now)
    uninstalled_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    uninstalled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "growth_installed_packs"
        ordering = ["-installed_at"]
        constraints = [
            models.UniqueConstraint(fields=["org", "pack"], condition=models.Q(status="installed"), name="one_active_install_per_pack")
        ]
