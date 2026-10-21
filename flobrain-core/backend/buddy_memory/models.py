"""What buddies remember about a person or a team (growth round M4).

Short facts only (300 characters), always visible to the person they are about, editable and
deletable. Deleting removes the row: there is no soft delete. Sensitive facts are refused before
anything is written (``buddy_memory.filters``).
"""

import uuid

from django.db import models
from django.utils import timezone

CATEGORIES = ("preference", "work_context", "project", "people", "other")
CATEGORY_CHOICES = [
    ("preference", "Preference"),
    ("work_context", "Work context"),
    ("project", "Project"),
    ("people", "People they work with"),
    ("other", "Other"),
]
MAX_TEXT = 300


class MemoryItem(models.Model):
    SCOPE_PERSON = "person"
    SCOPE_TEAM = "team"
    SCOPE_CHOICES = [(SCOPE_PERSON, "Person"), (SCOPE_TEAM, "Team")]

    SOURCE_BUDDY = "buddy"  # proposed after a buddy turn
    SOURCE_CHAT = "chat"  # "remember that ..." in a chat
    SOURCE_MANUAL = "manual"  # added on the Memory page
    SOURCE_CHOICES = [(SOURCE_BUDDY, "Buddy turn"), (SOURCE_CHAT, "Chat command"), (SOURCE_MANUAL, "Manual")]

    STATUS_ACTIVE = "active"
    STATUS_PENDING = "pending"  # a suggestion waiting for the person's yes or no
    STATUS_CHOICES = [(STATUS_ACTIVE, "Active"), (STATUS_PENDING, "Pending")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="buddy_memories")
    scope = models.CharField(max_length=8, choices=SCOPE_CHOICES, default=SCOPE_PERSON)
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, null=True, blank=True, related_name="buddy_memories")
    team = models.ForeignKey("organizations.Team", on_delete=models.CASCADE, null=True, blank=True, related_name="buddy_memories")
    text = models.CharField(max_length=MAX_TEXT)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default="other")
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    source_message = models.ForeignKey("brain.Message", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_by_buddy = models.ForeignKey("buddies.Buddy", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    confirmed = models.BooleanField(default=False)  # the person said yes, or wrote it themselves
    pinned = models.BooleanField(default=False)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    # The chat that asked "Should I remember this?" so a plain "yes" or "no" there answers it.
    asked_chat = models.ForeignKey("brain.Chat", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    digest = models.CharField(max_length=64, db_index=True)  # keyed hash of the normalised text, for duplicates
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buddy_memory_items"
        ordering = ["-pinned", "-created_at"]
        indexes = [
            models.Index(fields=["org", "user", "status"], name="bmem_person"),
            models.Index(fields=["org", "team", "status"], name="bmem_team"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(scope="person", user__isnull=False, team__isnull=True) | models.Q(scope="team", team__isnull=False, user__isnull=True)),
                name="bmem_scope_owner",
            ),
        ]

    def __str__(self):
        return f"memory {self.id} ({self.scope})"


class MemorySettings(models.Model):
    """The org's memory rules (``memory.manage``). No row means the defaults below."""

    org = models.OneToOneField("organizations.Organization", on_delete=models.CASCADE, primary_key=True, related_name="buddy_memory_settings")
    enabled = models.BooleanField(default=True)
    ask_before_saving = models.BooleanField(default=True)
    retention_days = models.PositiveIntegerField(null=True, blank=True, default=180)  # empty: kept until deleted
    blocked_categories = models.JSONField(default=list, blank=True)
    team_memory = models.BooleanField(default=True)
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buddy_memory_settings"


class MemoryPreference(models.Model):
    """One person's choice in one org: pause memory (buddies neither save nor use it)."""

    id = models.BigAutoField(primary_key=True)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    paused = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buddy_memory_preferences"
        constraints = [models.UniqueConstraint(fields=["org", "user"], name="bmem_pref_unique")]


class MemoryDeclined(models.Model):
    """A keyed hash (never the text) of a fact the person said no to or deleted, so a buddy
    does not suggest it again. Removed with the person and after ``DECLINED_DAYS``."""

    id = models.BigAutoField(primary_key=True)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "buddy_memory_declined"
        indexes = [models.Index(fields=["org", "user", "digest"], name="bmem_declined")]
