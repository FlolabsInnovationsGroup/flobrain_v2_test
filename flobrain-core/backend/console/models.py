import uuid

from django.db import models
from django.utils import timezone


class ImpersonationSession(models.Model):
    """A platform admin viewing an org as one member: read-only, time-limited, audited (17e)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="impersonations")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    reason = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(blank=True, null=True)
    ended_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        db_table = "impersonation_sessions"
        ordering = ["-created_at"]

    @property
    def is_live(self) -> bool:
        return self.ended_at is None and self.expires_at > timezone.now()
