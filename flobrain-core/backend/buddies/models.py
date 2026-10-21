import uuid

from django.db import models
from django.utils import timezone


class Buddy(models.Model):
    """An AI helper with its own prompt, preset prompts, sources and tools (spec 6.10, Decision 34).

    ``created_by`` empty means a built-in buddy. A custom buddy starts private and
    becomes visible to a team or the org only after the share is approved.
    """

    VIS_PRIVATE = "private"
    VIS_TEAM = "team"
    VIS_ORG = "org"
    VISIBILITY_CHOICES = [(VIS_PRIVATE, "Private"), (VIS_TEAM, "Team"), (VIS_ORG, "Org")]

    SHARE_NONE = "none"
    SHARE_PENDING = "pending"
    SHARE_APPROVED = "approved"
    SHARE_REJECTED = "rejected"
    SHARE_CHOICES = [
        (SHARE_NONE, "None"),
        (SHARE_PENDING, "Pending"),
        (SHARE_APPROVED, "Approved"),
        (SHARE_REJECTED, "Rejected"),
    ]

    SOURCES_NONE = "none"
    SOURCES_ACCESSIBLE = "accessible"
    SOURCES_ROOMS = "rooms"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="buddies")
    slug = models.SlugField(max_length=80)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=300, blank=True, default="")
    icon = models.CharField(max_length=40, blank=True, default="")
    system_prompt = models.TextField(blank=True, default="")
    preset_prompts = models.JSONField(default=list, blank=True)
    # {"mode": "none" | "accessible" | "rooms", "rooms": [room ids], "source_types": ["doc", "room_message"]}
    allowed_sources = models.JSONField(default=dict, blank=True)
    allowed_tools = models.JSONField(default=list, blank=True)
    default_model = models.CharField(max_length=128, blank=True, null=True)
    created_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="buddies_created"
    )
    is_builtin = models.BooleanField(default=False)
    visibility = models.CharField(max_length=8, choices=VISIBILITY_CHOICES, default=VIS_PRIVATE)
    team = models.ForeignKey(
        "organizations.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="buddies"
    )
    share_status = models.CharField(max_length=10, choices=SHARE_CHOICES, default=SHARE_NONE)
    share_target = models.CharField(max_length=8, blank=True, default="")  # team | org while pending
    share_team = models.ForeignKey(
        "organizations.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="buddy_share_requests"
    )
    share_decided_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="buddy_share_decisions"
    )
    is_enabled = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buddies"
        ordering = ["position", "name"]
        constraints = [models.UniqueConstraint(fields=["org", "slug"], name="unique_buddy_slug")]

    def __str__(self):
        return f"{self.name} ({self.org_id})"


class BuddyPin(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="buddy_pins")
    buddy = models.ForeignKey(Buddy, on_delete=models.CASCADE, related_name="pins")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "buddy_pins"
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["user", "buddy"], name="unique_buddy_pin")]
