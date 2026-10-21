import uuid

from django.db import models
from django.utils import timezone


class Task(models.Model):
    STATUS_TODO = "to_do"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE = "done"
    STATUS_CHOICES = [
        (STATUS_TODO, "To do"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_DONE, "Done"),
    ]
    STATUSES = (STATUS_TODO, STATUS_IN_PROGRESS, STATUS_DONE)

    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    PRIORITY_URGENT = "urgent"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_NORMAL, "Normal"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]
    PRIORITIES = (PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH, PRIORITY_URGENT)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="tasks")
    project = models.ForeignKey(
        "organizations.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    team = models.ForeignKey(
        "organizations.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    room = models.ForeignKey(
        "rooms.Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_TODO, db_index=True)
    priority = models.CharField(max_length=8, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL)
    # Order inside a Kanban column (lower first). Renumbered 0..n by tasks.services.move_task.
    position = models.IntegerField(default=0)
    due_on = models.DateField(blank=True, null=True, db_index=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    is_blocked = models.BooleanField(default=False)
    blocked_reason = models.TextField(blank=True, default="")
    blocked_since = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tasks",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tasks"
        indexes = [
            models.Index(fields=["org", "status"]),
            models.Index(fields=["org", "due_on"]),
            models.Index(fields=["org", "status", "position"]),
        ]


class TaskAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="task_assignments")
    assigned_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "task_assignments"
        constraints = [
            models.UniqueConstraint(fields=["task", "user"], name="unique_task_assignment"),
        ]


class TaskActivity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    verb = models.CharField(max_length=32)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "task_activities"


class TaskReminder(models.Model):
    """One row per reminder sent, so ``tick_tasks`` never sends the same one twice. A new due date
    is a new reminder (the key includes ``due_on``)."""

    KIND_DUE_SOON = "task.due_soon"
    KIND_OVERDUE = "task.overdue"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="reminders")
    kind = models.CharField(max_length=24)
    due_on = models.DateField()
    sent_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "task_reminders"
        constraints = [
            models.UniqueConstraint(fields=["task", "kind", "due_on"], name="unique_task_reminder"),
        ]


class ProjectTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="project_templates",
    )
    name = models.CharField(max_length=200)
    spec = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "project_templates"
