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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="time_entries")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="time_entries")
    task = models.ForeignKey("tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="time_entries")
    description = models.TextField(blank=True, default="")
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

    @property
    def seconds(self) -> int:
        end = self.ended_at or timezone.now()
        return max(int((end - self.started_at).total_seconds()), 0)
