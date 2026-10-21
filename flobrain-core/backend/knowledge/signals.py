"""Keep knowledge chunks in line with their sources (Phase 7i).

- Save of a document or a live message: index it when the org's
  ``memory_search`` flag is on (queued on the 7g worker, inline in eager mode).
- Delete of a document or a message, or a soft-deleted message: its chunks go
  synchronously, whatever the flag says.
- Delete of a chunk row (directly or by cascade from a room or an org): its
  vector goes too.

Handlers never raise into the save or delete that triggered them.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from docs_app.models import Document
from knowledge import index
from knowledge.models import KnowledgeChunk
from meetings.models import MeetingSummary, Transcript
from rooms.models import RoomMessage

logger = logging.getLogger(__name__)


def _safe(fn, *args):
    try:
        with transaction.atomic():  # a failure rolls back to this savepoint only
            fn(*args)
    except Exception:  # noqa: BLE001
        logger.exception("knowledge signal handler failed")


@receiver(post_save, sender=Document, dispatch_uid="knowledge_doc_saved")
def _doc_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    if index.org_indexing_enabled(instance.org):
        index.request_index(KnowledgeChunk.SOURCE_DOC, instance.pk)
    else:
        # Saved while the flag is off: old chunks would hold pre-edit text.
        _safe(index.delete_source, KnowledgeChunk.SOURCE_DOC, instance.pk)


@receiver(post_delete, sender=Document, dispatch_uid="knowledge_doc_deleted")
def _doc_deleted(sender, instance, **kwargs):
    _safe(index.delete_source, KnowledgeChunk.SOURCE_DOC, instance.pk)


@receiver(post_save, sender=RoomMessage, dispatch_uid="knowledge_message_saved")
def _message_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    if instance.deleted_at is not None:
        _safe(index.delete_source, KnowledgeChunk.SOURCE_ROOM_MESSAGE, instance.pk)
        return
    if index.org_indexing_enabled(instance.room.org):
        index.request_index(KnowledgeChunk.SOURCE_ROOM_MESSAGE, instance.pk)
    else:
        _safe(index.delete_source, KnowledgeChunk.SOURCE_ROOM_MESSAGE, instance.pk)


@receiver(post_delete, sender=RoomMessage, dispatch_uid="knowledge_message_deleted")
def _message_deleted(sender, instance, **kwargs):
    _safe(index.delete_source, KnowledgeChunk.SOURCE_ROOM_MESSAGE, instance.pk)


@receiver(post_save, sender=Transcript, dispatch_uid="knowledge_transcript_saved")
def _transcript_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    org = instance.recording.meeting.org
    if index.org_indexing_enabled(org) and instance.text:
        index.request_index(KnowledgeChunk.SOURCE_TRANSCRIPT, instance.pk)
    else:
        _safe(index.delete_source, KnowledgeChunk.SOURCE_TRANSCRIPT, instance.pk)


@receiver(post_delete, sender=Transcript, dispatch_uid="knowledge_transcript_deleted")
def _transcript_deleted(sender, instance, **kwargs):
    _safe(index.delete_source, KnowledgeChunk.SOURCE_TRANSCRIPT, instance.pk)


@receiver(post_delete, sender=KnowledgeChunk, dispatch_uid="knowledge_chunk_deleted")
def _chunk_deleted(sender, instance, **kwargs):
    _safe(index.delete_vectors, [instance])


@receiver(post_save, sender=MeetingSummary, dispatch_uid="knowledge_summary_saved")
def _summary_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    if index.org_indexing_enabled(instance.meeting.org) and instance.text:
        index.request_index(KnowledgeChunk.SOURCE_SUMMARY, instance.pk)
    else:
        _safe(index.delete_source, KnowledgeChunk.SOURCE_SUMMARY, instance.pk)


@receiver(post_delete, sender=MeetingSummary, dispatch_uid="knowledge_summary_deleted")
def _summary_deleted(sender, instance, **kwargs):
    _safe(index.delete_source, KnowledgeChunk.SOURCE_SUMMARY, instance.pk)
