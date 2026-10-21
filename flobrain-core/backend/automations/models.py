"""Workflows: a trigger and up to 12 steps, run by ``automations.engine`` (growth round W1).

A workflow runs with the access of ``run_as``, the person who last saved it. Steps that write
outside FloBrain (email, outgoing webhooks) and ``wait_for_approval`` steps create an approval for
that person; the run pauses at ``waiting_approval`` until it is decided.
"""

import uuid

from django.db import models
from django.utils import timezone


class Workflow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="workflows")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    enabled = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_workflows"
    )
    # The person whose access the steps use and who decides its approvals: whoever saved it last.
    run_as = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    trigger = models.JSONField(default=dict)
    trigger_type = models.CharField(max_length=32, db_index=True, default="manual")
    steps = models.JSONField(default=list)
    template_key = models.CharField(max_length=64, blank=True, default="")
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "automation_workflows"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["org", "enabled", "trigger_type"], name="automation_wf_trigger")]


class WorkflowRun(models.Model):
    QUEUED, RUNNING, WAITING, DONE, FAILED, CANCELLED = (
        "queued",
        "running",
        "waiting_approval",
        "done",
        "failed",
        "cancelled",
    )
    STATUS_CHOICES = [
        (QUEUED, "Queued"),
        (RUNNING, "Running"),
        (WAITING, "Waiting for approval"),
        (DONE, "Done"),
        (FAILED, "Failed"),
        (CANCELLED, "Cancelled"),
    ]
    FINISHED = (DONE, FAILED, CANCELLED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="workflow_runs")
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=QUEUED, db_index=True)
    reason = models.CharField(max_length=32, blank=True, default="")  # manual | schedule | trigger type
    event_key = models.CharField(max_length=160, blank=True, default="")
    triggered_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    trigger_payload = models.JSONField(default=dict, blank=True)
    steps = models.JSONField(default=list)  # snapshot taken when the run was created
    step_log = models.JSONField(default=list, blank=True)
    current_step = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "automation_runs"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "event_key"], condition=~models.Q(event_key=""), name="unique_automation_event_run"
            )
        ]


class RunApproval(models.Model):
    """Links a paused run step to the ``ActionProposal`` that decides it."""

    PENDING, APPROVED, REJECTED, FAILED, EXPIRED = "pending", "approved", "rejected", "failed", "expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(WorkflowRun, on_delete=models.CASCADE, related_name="approvals")
    step = models.PositiveSmallIntegerField()
    proposal = models.OneToOneField(
        "actions.ActionProposal", on_delete=models.CASCADE, related_name="automation_approval"
    )
    state = models.CharField(max_length=10, default=PENDING)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "automation_run_approvals"
        constraints = [models.UniqueConstraint(fields=["run", "step"], name="unique_automation_run_step_approval")]


class InboundHook(models.Model):
    """Signing secret for a workflow's inbound webhook, encrypted with ``integrations.crypto``."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    workflow = models.OneToOneField(Workflow, on_delete=models.CASCADE, related_name="inbound_hook")
    secret_ciphertext = models.BinaryField()
    key_version = models.PositiveSmallIntegerField(default=1)
    last4 = models.CharField(max_length=4)
    last_received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    rotated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "automation_inbound_hooks"


class AutomationSettings(models.Model):
    """Per-org rules: which hosts ``call_webhook`` may reach, and which of them skip the approval."""

    org = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, primary_key=True, related_name="+")
    webhook_hosts = models.JSONField(default=list, blank=True)
    trusted_hosts = models.JSONField(default=list, blank=True)
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "automation_settings"


class BriefOptOut(models.Model):
    """A person who does not want the proactive daily brief or overdue nudges."""

    DAILY_BRIEF, NUDGES = "daily_brief", "nudges"
    KINDS = (DAILY_BRIEF, NUDGES)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=16)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "automation_brief_opt_outs"
        constraints = [models.UniqueConstraint(fields=["org", "user", "kind"], name="unique_automation_opt_out")]
