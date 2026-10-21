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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    body = models.TextField()
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
