import uuid

from django.db import models
from django.utils import timezone


class KnowledgeVectorJSON(models.Model):
    """Vectors as JSON for local dev and tests (KNOWLEDGE_VECTOR_STORE=json). Never the production store."""

    chunk_id = models.UUIDField(primary_key=True)
    model = models.CharField(max_length=128)
    dimension = models.PositiveIntegerField()
    vector = models.JSONField()

    class Meta:
        db_table = "knowledge_vectors_json"


class KnowledgeChunk(models.Model):
    """One indexed piece of an org source (Decision 12, E16a).

    The row carries org and room so retrieval can filter by the asker's live
    access before ranking. The vector lives in the store for ``dimension``
    (pgvector table or JSON rows) under the same id.
    """

    SOURCE_DOC = "doc"
    SOURCE_ROOM_MESSAGE = "room_message"
    SOURCE_TRANSCRIPT = "transcript"  # meeting transcripts (2026-10-21), visible to people who can open the room
    SOURCE_SUMMARY = "summary"  # meeting summaries with decisions and action items, same visibility as transcripts
    SOURCE_CHOICES = [
        (SOURCE_DOC, "Document"),
        (SOURCE_ROOM_MESSAGE, "Room message"),
        (SOURCE_TRANSCRIPT, "Meeting transcript"),
        (SOURCE_SUMMARY, "Meeting summary"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="knowledge_chunks")
    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="knowledge_chunks")
    source_type = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    source_id = models.UUIDField()
    seq = models.PositiveIntegerField(default=0)
    text = models.TextField()
    content_hash = models.CharField(max_length=64)
    model = models.CharField(max_length=128)
    dimension = models.PositiveIntegerField()
    # The source's updated_at when this chunk was built. Retrieval drops a chunk whose
    # source changed since (an edit not yet re-indexed never serves old text).
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_chunks"
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_id", "seq", "model"], name="unique_knowledge_chunk"
            ),
        ]
        indexes = [
            models.Index(fields=["org", "room", "model"], name="knowledge_chunk_scope"),
            models.Index(fields=["source_type", "source_id"], name="knowledge_chunk_source"),
        ]
