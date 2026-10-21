"""Data buddy (W3): datasets, saved questions (cards) and scheduled reports.

A dataset's rows never live in the main database. Uploads and Google Sheets are copied into one
SQLite file per dataset under the private data folder (``datasets.store``); a PostgreSQL source is
queried live, read-only, with its connection string encrypted here (``integrations.crypto``).
"""

import uuid

from django.db import models
from django.utils import timezone


class Dataset(models.Model):
    KIND_UPLOAD = "upload"
    KIND_SHEET = "sheet"
    KIND_POSTGRES = "postgres"
    KIND_CHOICES = [(KIND_UPLOAD, "Uploaded file"), (KIND_SHEET, "Google Sheet"), (KIND_POSTGRES, "PostgreSQL")]

    STATUS_READY = "ready"
    STATUS_REFRESHING = "refreshing"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [(STATUS_READY, "Ready"), (STATUS_REFRESHING, "Refreshing"), (STATUS_ERROR, "Error")]

    VISIBILITY_ORG = "org"
    VISIBILITY_TEAM = "team"
    VISIBILITY_OWNER = "owner"
    VISIBILITY_CHOICES = [(VISIBILITY_ORG, "Everyone"), (VISIBILITY_TEAM, "A team"), (VISIBILITY_OWNER, "Only me")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="datasets")
    owner = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="datasets")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_READY)
    last_error = models.CharField(max_length=300, blank=True, default="")
    visibility = models.CharField(max_length=8, choices=VISIBILITY_CHOICES, default=VISIBILITY_OWNER)
    team = models.ForeignKey("organizations.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # [{"name", "label", "columns": [{"name", "label", "type"}], "sample_rows": [[...]], "row_count"}]
    tables = models.JSONField(default=list, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    source_name = models.CharField(max_length=200, blank=True, default="")  # original file name
    file_key = models.CharField(max_length=200, blank=True, default="")  # relative path of the SQLite copy
    sheet_url = models.URLField(max_length=500, blank=True, default="")
    refresh_every_hours = models.PositiveSmallIntegerField(default=0)  # 0: only on demand
    next_refresh_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    dsn_ciphertext = models.BinaryField(null=True, blank=True)  # never returned
    key_version = models.PositiveSmallIntegerField(default=1)
    dsn_hint = models.CharField(max_length=300, blank=True, default="")  # masked, safe to show
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["org", "visibility"])]

    def __repr__(self):  # never print the connection string
        return f"<Dataset {self.id} {self.kind}>"

    __str__ = __repr__


class SavedQuestion(models.Model):
    """A card: a question with the SQL that answers it and its chart, re-run to refresh the numbers."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="data_cards")
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="cards")
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name="+")
    title = models.CharField(max_length=160)
    question = models.CharField(max_length=500, blank=True, default="")
    sql = models.TextField()
    chart = models.JSONField(default=dict, blank=True)
    answer = models.TextField(blank=True, default="")
    last_result = models.JSONField(default=dict, blank=True)  # {"columns", "rows" (capped), "truncated"}
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


class Report(models.Model):
    CADENCE_WEEKLY = "weekly"
    CADENCE_MONTHLY = "monthly"
    CADENCE_CHOICES = [(CADENCE_WEEKLY, "Weekly"), (CADENCE_MONTHLY, "Monthly")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="data_reports")
    created_by = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=120)
    cards = models.ManyToManyField(SavedQuestion, related_name="reports", blank=True)
    recipients = models.ManyToManyField("users.User", related_name="+", blank=True)
    cadence = models.CharField(max_length=8, choices=CADENCE_CHOICES, default=CADENCE_WEEKLY)
    weekday = models.PositiveSmallIntegerField(default=0)  # 0 Monday .. 6 Sunday (weekly)
    day_of_month = models.PositiveSmallIntegerField(default=1)  # 1..28 (monthly)
    hour = models.PositiveSmallIntegerField(default=8)  # UTC
    room = models.ForeignKey("rooms.Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=16, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]


class ReportRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="runs")
    ran_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=16, default="ok")  # ok | partial | failed
    results = models.JSONField(default=list, blank=True)  # [{"card", "title", "headline", "error"}]
    notified = models.PositiveIntegerField(default=0)
    posted_to_room = models.BooleanField(default=False)

    class Meta:
        ordering = ["-ran_at"]
