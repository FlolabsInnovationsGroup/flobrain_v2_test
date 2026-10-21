import uuid

from django.db import models
from django.utils import timezone


class Lead(models.Model):
    STAGES = ("contacted", "meeting_1", "in_progress", "won", "lost")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="leads")
    owner_user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="leads")
    project_or_product = models.CharField(max_length=160)
    contact_name = models.CharField(max_length=160)
    contact_email = models.EmailField(blank=True, null=True)
    stage = models.CharField(max_length=12, default="contacted")
    estimated_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leads"


class Commission(models.Model):
    STATUSES = ("pending", "under_review", "approved", "rejected", "scheduled", "paid", "reversed")
    EARNED = ("approved", "scheduled", "paid")
    WAITING = ("pending", "under_review")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="commissions")
    # Review 10-13: PROTECT blocked account and org deletion (500). The record survives its lead.
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, related_name="commissions")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="commissions")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=12, default="pending")
    recorded_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "commissions"
