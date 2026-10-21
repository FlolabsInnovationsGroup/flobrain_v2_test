import uuid

from django.db import models
from django.utils import timezone


class PrivacySettings(models.Model):
    """Per person, per org (Decision 44): personal analytics stay personal unless shared."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="privacy_settings")
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    share_time_details_with_org = models.BooleanField(default=True)  # off: leads see totals, not descriptions
    analytics_personal_only = models.BooleanField(default=False)
    consents = models.JSONField(default=dict, blank=True)  # {product_analytics: bool, ...}
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "privacy_settings"
        constraints = [models.UniqueConstraint(fields=["user", "org"], name="unique_privacy_settings")]


class DataExportJob(models.Model):
    """A person's own data, as a zip they download."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="data_exports")
    status = models.CharField(max_length=10, default="queued")
    storage_key = models.CharField(max_length=300, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    error = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "privacy_data_exports"


class DeletionRequest(models.Model):
    STATUSES = ("pending", "approved", "rejected", "done")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="deletion_requests")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=1000, blank=True, default="")
    status = models.CharField(max_length=10, default="pending")
    decided_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "privacy_deletion_requests"


class RetentionPolicy(models.Model):
    """Days to keep each kind of data. Empty means keep forever (Q20 default: nothing is deleted)."""

    org = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, primary_key=True, related_name="retention_policy")
    messages_days = models.PositiveIntegerField(null=True, blank=True)
    recordings_days = models.PositiveIntegerField(null=True, blank=True)
    transcripts_days = models.PositiveIntegerField(null=True, blank=True)
    time_entries_days = models.PositiveIntegerField(null=True, blank=True)
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(default=timezone.now)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_summary = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "privacy_retention_policies"
