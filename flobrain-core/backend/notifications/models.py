import uuid

from django.db import models
from django.utils import timezone


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="notifications")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=40)
    payload = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]


class PushSubscription(models.Model):
    """A browser's Web Push subscription (Phase 10). Endpoints must belong to a known push service."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField(max_length=800, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    last_error = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "push_subscriptions"


class NotificationPreference(models.Model):
    """Per-type on/off and sound (Phase 11). A missing row means on, with the default sound."""

    SOUNDS = ("none", "chime", "pop", "ping", "bell", "soft", "knock")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="notification_preferences")
    type = models.CharField(max_length=40)
    enabled = models.BooleanField(default=True)
    sound_key = models.CharField(max_length=16, default="chime")
    push = models.BooleanField(default=True)

    class Meta:
        db_table = "notification_preferences"
        constraints = [models.UniqueConstraint(fields=["user", "type"], name="unique_notification_pref")]
