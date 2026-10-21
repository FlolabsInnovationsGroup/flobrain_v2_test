import uuid

from django.db import models
from django.utils import timezone


class AgentSchedule(models.Model):
    """A buddy that runs on a schedule or on an event (spec 6.19, Phase 8f).

    A run uses the creator's permissions **at run time**. Write tools still
    create proposals the creator must approve.
    """

    TRIGGER_CRON = "cron"
    TRIGGER_EVENT = "event"
    TRIGGER_CHOICES = [(TRIGGER_CRON, "Cron"), (TRIGGER_EVENT, "Event")]

    EVENTS = ("task.overdue", "member.joined", "meeting.ended")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="agent_schedules")
    buddy = models.ForeignKey("buddies.Buddy", on_delete=models.CASCADE, related_name="schedules")
    created_by = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="agent_schedules")
    name = models.CharField(max_length=80, blank=True, default="")
    trigger_type = models.CharField(max_length=8, choices=TRIGGER_CHOICES)
    cron = models.CharField(max_length=64, blank=True, null=True)
    event = models.CharField(max_length=32, blank=True, null=True)
    instructions = models.TextField()
    is_active = models.BooleanField(default=True)
    paused_reason = models.CharField(max_length=80, blank=True, default="")
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "agent_schedules"


class AgentRun(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="agent_runs")
    schedule = models.ForeignKey(AgentSchedule, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    reason = models.CharField(max_length=40, blank=True, default="")  # cron | manual | event name
    event_key = models.CharField(max_length=120, blank=True, default="")  # dedupe for events
    context = models.JSONField(default=dict, blank=True)  # ids only, never message bodies
    chat = models.ForeignKey("brain.Chat", on_delete=models.SET_NULL, null=True, blank=True, related_name="agent_runs")
    trace = models.ForeignKey(
        "telemetry.AITrace", on_delete=models.SET_NULL, null=True, blank=True, related_name="agent_runs"
    )
    error = models.CharField(max_length=200, blank=True, default="")
    proposals = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "agent_runs"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "event_key"],
                condition=~models.Q(event_key=""),
                name="unique_agent_event_run",
            )
        ]
