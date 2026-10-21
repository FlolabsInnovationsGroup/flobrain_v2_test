"""Imports from Slack, Notion and Google Drive (M6, flag ``imports``, permission ``imports.run``).

``ImportRun`` is one import: its uploaded files (private storage keys, never served), the preview
(counts and names, never message text), the admin's mapping, live progress and the outcome.
``ImportedObject`` records every row the run created, keyed by where it came from, so a re-run
skips what is already there and undo deletes exactly what this run made.
"""

import uuid

from django.db import models
from django.utils import timezone


class ImportRun(models.Model):
    SOURCE_SLACK = "slack"
    SOURCE_NOTION_ZIP = "notion_zip"
    SOURCE_NOTION_API = "notion_api"
    SOURCE_DRIVE_API = "drive_api"
    SOURCE_FILES = "files"
    SOURCES = [
        (SOURCE_SLACK, "Slack export"),
        (SOURCE_NOTION_ZIP, "Notion export"),
        (SOURCE_NOTION_API, "Notion"),
        (SOURCE_DRIVE_API, "Google Drive"),
        (SOURCE_FILES, "Files or Google Takeout"),
    ]

    ANALYZING = "analyzing"
    READY = "ready"  # preview done, waiting for the mapping
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNDOING = "undoing"
    UNDONE = "undone"
    STATUSES = [(s, s) for s in (ANALYZING, READY, QUEUED, RUNNING, DONE, FAILED, CANCELLED, UNDOING, UNDONE)]
    ACTIVE = (ANALYZING, QUEUED, RUNNING, UNDOING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="import_runs")
    source = models.CharField(max_length=16, choices=SOURCES)
    status = models.CharField(max_length=12, choices=STATUSES, default=ANALYZING)
    label = models.CharField(max_length=200, blank=True, default="")
    # [{key, name, size}] in private storage under imports/<org>/<run>/. Deleted after undo.
    files = models.JSONField(default=list, blank=True)
    preview = models.JSONField(default=dict, blank=True)
    mapping = models.JSONField(default=dict, blank=True)
    progress = models.JSONField(default=dict, blank=True)
    counts = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=200, blank=True, default="")
    cancel_requested = models.BooleanField(default=False)
    # The job slice working on this run holds the lease; a second worker backs off until it expires.
    lease_until = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField(default=False)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    undone_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    undone_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "import_runs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["org", "status"], name="import_org_status")]


class ImportedObject(models.Model):
    KIND_ROOM = "room"
    KIND_ROOM_MEMBER = "room_member"
    KIND_TEAM = "team"
    KIND_TEAM_MEMBER = "team_member"
    KIND_MESSAGE = "message"
    KIND_DOCUMENT = "document"
    KIND_ANNOUNCEMENT = "announcement"
    KINDS = [(k, k) for k in (KIND_ROOM, KIND_ROOM_MEMBER, KIND_TEAM, KIND_TEAM_MEMBER, KIND_MESSAGE, KIND_DOCUMENT, KIND_ANNOUNCEMENT)]

    id = models.BigAutoField(primary_key=True)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    run = models.ForeignKey(ImportRun, on_delete=models.CASCADE, related_name="objects_created")
    kind = models.CharField(max_length=16, choices=KINDS)
    object_id = models.CharField(max_length=64)
    # Where it came from, e.g. ``slack:C024BE91L:1726900000.000200`` or ``notion:<32 hex>``.
    # Empty for helper rows (room members) that are found through their room.
    source_key = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "imported_objects"
        indexes = [models.Index(fields=["run", "kind"], name="imported_run_kind")]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "kind", "source_key"], condition=~models.Q(source_key=""), name="unique_imported_source"
            )
        ]
