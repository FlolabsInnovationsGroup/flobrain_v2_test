import uuid

from django.db import models
from django.utils import timezone


class Connection(models.Model):
    """One connected integration. Its secret is encrypted and never returned. Imported items are
    visible only to people who can open ``room`` (imported content respects room visibility)."""

    ACTIVE, REVOKED, ERROR = "active", "revoked", "error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="connections")
    connector = models.CharField(max_length=32)
    label = models.CharField(max_length=120, blank=True, default="")
    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="connections")
    config = models.JSONField(default=dict, blank=True)
    secret_ciphertext = models.BinaryField(null=True, blank=True)
    key_version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, default=ACTIVE)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "integration_connections"


class ExternalItem(models.Model):
    """A read-only copy of something outside FloBrain (a GitHub issue, a calendar event)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=24)
    external_id = models.CharField(max_length=128)
    title = models.CharField(max_length=300)
    url = models.URLField(max_length=500, blank=True, default="")
    state = models.CharField(max_length=24, blank=True, default="")
    # Small, connector-defined facts used for filtering (Notion: the audience property's values).
    meta = models.JSONField(default=dict, blank=True)
    external_updated_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "integration_items"
        constraints = [models.UniqueConstraint(fields=["connection", "kind", "external_id"], name="unique_external_item")]


class TaskLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="external_links")
    item = models.ForeignKey(ExternalItem, on_delete=models.CASCADE, related_name="task_links")
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "integration_task_links"
        constraints = [models.UniqueConstraint(fields=["task", "item"], name="unique_task_link")]
