import uuid

from django.db import models
from django.utils import timezone


class MemoryExport(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(s, s) for s in (STATUS_QUEUED, STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="memory_exports")
    requested_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    storage_key = models.CharField(max_length=300, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    counts = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "memory_exports"
        ordering = ["-created_at"]
