import uuid

from django.db import models
from django.utils import timezone


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="documents")
    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=200)
    content_text = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    updated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "documents"


class DocumentRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="revisions")
    version = models.PositiveIntegerField()
    content_text = models.TextField(blank=True, default="")
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "document_revisions"
        constraints = [
            models.UniqueConstraint(fields=["document", "version"], name="unique_document_revision"),
        ]


class StoredFile(models.Model):
    STATUS_PENDING = "pending"
    STATUS_READY = "ready"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="stored_files")
    room = models.ForeignKey(
        "rooms.Room",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="files",
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=120, blank=True, default="application/octet-stream")
    status = models.CharField(max_length=16, default=STATUS_PENDING)
    local_path = models.CharField(max_length=500, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "stored_files"
