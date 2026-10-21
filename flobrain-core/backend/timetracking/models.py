import uuid

from django.db import models
from django.utils import timezone


class Tag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="time_tags")
    name = models.CharField(max_length=80)

    class Meta:
        db_table = "time_tags"
        constraints = [models.UniqueConstraint(fields=["org", "name"], name="unique_time_tag_per_org")]


class TimeEntry(models.Model):
    # Decision 16: hour categories, default "projects".
    CATEGORY_ONBOARDING = "onboarding"
    CATEGORY_MASTERCLASS = "masterclass"
    CATEGORY_PROJECTS = "projects"
    CATEGORY_CHOICES = [
        (CATEGORY_ONBOARDING, "Onboarding"),
        (CATEGORY_MASTERCLASS, "Masterclass"),
        (CATEGORY_PROJECTS, "Projects"),
    ]
    CATEGORIES = (CATEGORY_ONBOARDING, CATEGORY_MASTERCLASS, CATEGORY_PROJECTS)

    SOURCE_TIMER = "timer"
    SOURCE_MANUAL = "manual"
    SOURCE_IMPORT = "import"
    SOURCE_CHOICES = [(SOURCE_TIMER, "Timer"), (SOURCE_MANUAL, "Manual"), (SOURCE_IMPORT, "Import")]

    # Approval: the person submits closed entries, a lead of one of their teams (or an admin) decides.
    APPROVAL_DRAFT = "draft"
    APPROVAL_SUBMITTED = "submitted"
    APPROVAL_APPROVED = "approved"
    APPROVAL_REJECTED = "rejected"
    APPROVAL_CHOICES = [
        (APPROVAL_DRAFT, "Draft"),
        (APPROVAL_SUBMITTED, "Submitted"),
        (APPROVAL_APPROVED, "Approved"),
        (APPROVAL_REJECTED, "Rejected"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="time_entries")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="time_entries")
    task = models.ForeignKey("tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="time_entries")
    project = models.ForeignKey(
        "organizations.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="time_entries"
    )
    room = models.ForeignKey("rooms.Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="time_entries")
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default=CATEGORY_PROJECTS)
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, default=SOURCE_TIMER)
    approval_status = models.CharField(max_length=10, choices=APPROVAL_CHOICES, default=APPROVAL_DRAFT)
    approval_note = models.CharField(max_length=300, blank=True, default="")
    submitted_at = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(blank=True, null=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="entries")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "time_entries"
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(ended_at__isnull=True),
                name="unique_open_timer_per_user",
            )
        ]
        indexes = [models.Index(fields=["org", "user", "started_at"])]

    @property
    def seconds(self) -> int:
        end = self.ended_at or timezone.now()
        return max(int((end - self.started_at).total_seconds()), 0)
