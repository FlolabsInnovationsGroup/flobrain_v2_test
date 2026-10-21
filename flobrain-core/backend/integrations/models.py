import uuid

from django.db import models
from django.utils import timezone

DEFAULT_TOOLS = (
    ("Figma", "https://www.figma.com"),
    ("Canva", "https://www.canva.com"),
    ("Cursor", "https://cursor.com"),
    ("Notion", "https://www.notion.so"),
    ("Discord", "https://discord.com"),
    ("GitHub", "https://github.com"),
)


class ExternalTool(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="external_tools")
    name = models.CharField(max_length=80)
    url = models.URLField()
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "external_tools"
        ordering = ["sort_order", "name"]
