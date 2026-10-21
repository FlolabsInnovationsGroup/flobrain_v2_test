from django.db import models
from django.utils import timezone


class CockpitLayout(models.Model):
    """A person's cockpit: Default, Focus or Custom, with the Custom choices saved server-side."""

    MODES = ("default", "focus", "custom")

    user = models.OneToOneField("users.User", on_delete=models.CASCADE, primary_key=True, related_name="cockpit_layout")
    mode = models.CharField(max_length=8, default="default")
    layout = models.JSONField(default=dict, blank=True)
    low_bandwidth = models.BooleanField(default=False)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "cockpit_layouts"
