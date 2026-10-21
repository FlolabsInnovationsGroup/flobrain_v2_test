import uuid

from django.db import models
from django.utils import timezone


class Room(models.Model):
    KIND_TEAM = "team"
    KIND_PROJECT = "project"
    KIND_DIRECT = "direct"
    KIND_GROUP = "group"
    KIND_CHOICES = [
        (KIND_TEAM, "Team"),
        (KIND_PROJECT, "Project"),
        (KIND_DIRECT, "Direct"),
        (KIND_GROUP, "Group"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_GROUP)
    team = models.ForeignKey(
        "organizations.Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="rooms",
    )
    project = models.ForeignKey(
        "organizations.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="rooms",
    )
    pair_key = models.CharField(max_length=80, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rooms"
        constraints = [
            models.UniqueConstraint(
                fields=["org", "team"],
                condition=models.Q(kind="team", team__isnull=False),
                name="unique_team_room",
            ),
            models.UniqueConstraint(
                fields=["org", "project"],
                condition=models.Q(kind="project", project__isnull=False),
                name="unique_project_room",
            ),
            models.UniqueConstraint(
                fields=["org", "pair_key"],
                condition=models.Q(kind="direct") & ~models.Q(pair_key=""),
                name="unique_direct_pair",
            ),
        ]


class RoomMember(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="room_memberships")
    last_read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "room_members"
        constraints = [models.UniqueConstraint(fields=["room", "user"], name="unique_room_member")]


class RoomMessage(models.Model):
    KIND_TEXT = "text"
    KIND_VOICE = "voice"
    KIND_CHOICES = [(KIND_TEXT, "Text"), (KIND_VOICE, "Voice note")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    body = models.TextField()
    # W7 voice notes: a voice message keeps its transcript in ``body`` once it is ready.
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_TEXT)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    edited_at = models.DateTimeField(blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "room_messages"
        ordering = ["-created_at"]


class MessageTranslation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(RoomMessage, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=8)
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "message_translations"
        constraints = [
            models.UniqueConstraint(fields=["message", "language"], name="unique_message_translation"),
        ]


class Announcement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="announcements")
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="announcements")
    body = models.TextField()
    pinned = models.BooleanField(default=True)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "announcements"


class VoiceNote(models.Model):
    """Audio behind a ``RoomMessage(kind="voice")`` (W7, flag ``voice_notes``).

    The audio lives in private storage (``content_studio.storage``) under a key the server
    builds, and is only streamed to people who can read the room. Translations of the
    transcript are cached per language in ``MessageTranslation`` (the message body holds
    the transcript once it is ready).
    """

    STATUS_PENDING = "pending"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending"), (STATUS_DONE, "Done"), (STATUS_FAILED, "Failed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="voice_notes")
    message = models.OneToOneField(RoomMessage, on_delete=models.CASCADE, related_name="voice")
    storage_key = models.CharField(max_length=300, blank=True, default="")
    content_type = models.CharField(max_length=40, default="audio/webm")
    size_bytes = models.PositiveIntegerField(default=0)
    duration_seconds = models.FloatField(default=0)
    language_hint = models.CharField(max_length=16, blank=True, default="")
    language = models.CharField(max_length=16, blank=True, default="")
    transcript = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error = models.CharField(max_length=80, blank=True, default="")
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "room_voice_notes"
        indexes = [models.Index(fields=["org", "status"], name="voice_org_status")]
