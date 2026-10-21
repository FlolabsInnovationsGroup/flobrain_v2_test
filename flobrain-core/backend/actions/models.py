import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone

PROPOSAL_TTL = timedelta(hours=24)


class ToolDefinition(models.Model):
    """Registered tools (spec 6.15). Schemas live in ``actions/registry.py``; this row holds the switch."""

    key = models.CharField(max_length=64, primary_key=True)
    perm_key = models.CharField(max_length=64)
    json_schema = models.JSONField(default=dict)
    risk = models.CharField(max_length=8, default="write")
    requires_approval = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "tool_definitions"


def _expiry():
    return timezone.now() + PROPOSAL_TTL


class ActionProposal(models.Model):
    STATUS_PROPOSED = "proposed"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_EXECUTED = "executed"
    STATUS_FAILED = "failed"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PROPOSED, "Proposed"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_EXECUTED, "Executed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_EXPIRED, "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="action_proposals")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="action_proposals")
    thread = models.ForeignKey(
        "brain.Chat", on_delete=models.SET_NULL, null=True, blank=True, related_name="action_proposals"
    )
    buddy = models.ForeignKey(
        "buddies.Buddy", on_delete=models.SET_NULL, null=True, blank=True, related_name="action_proposals"
    )
    tool_key = models.CharField(max_length=64)
    arguments = models.JSONField(default=dict)
    # What the model proposed, kept when a person edits the arguments before approving (spec 8.6).
    original_arguments = models.JSONField(null=True, blank=True)
    summary = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PROPOSED, db_index=True)
    decided_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="action_decisions"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=200, blank=True, default="")
    expires_at = models.DateTimeField(default=_expiry)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "action_proposals"
        indexes = [models.Index(fields=["org", "user", "status"], name="action_proposal_inbox")]

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()


class EmailDraft(models.Model):
    """Output of ``email.draft``. Never sent by FloBrain (sending is a Phase 15 connector)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="email_drafts")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="email_drafts")
    to = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "email_drafts"


class AutoReport(models.Model):
    """Daily standup / weekly report draft for a team (spec 6.15). Deterministic; cites its rows."""

    KIND_DAILY = "daily_standup"
    KIND_WEEKLY = "weekly_report"
    KIND_CHOICES = [(KIND_DAILY, "Daily standup"), (KIND_WEEKLY, "Weekly report")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="auto_reports")
    team = models.ForeignKey("organizations.Team", on_delete=models.CASCADE, related_name="auto_reports")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    content = models.TextField()
    sources = models.JSONField(default=dict)
    generated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="auto_reports")
    generated_at = models.DateTimeField(default=timezone.now)
    posted_room = models.ForeignKey(
        "rooms.Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="auto_reports"
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "auto_reports"
        ordering = ["-generated_at"]
