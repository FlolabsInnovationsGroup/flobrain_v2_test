"""Retrieval before ranking (Decision 12, E16).

1. Build the set of chunk ids the asker may read **now**: same org, a room
   from ``accessible_rooms`` (live team/project membership, E37), and doc
   chunks only with ``docs.view``.
2. Rank only that set in the vector store.
3. Drop any hit whose source no longer exists or is soft-deleted.

Nothing outside step 1 is ever scored, so it cannot reach the prompt.
"""

from dataclasses import dataclass

from organizations.permissions import can
from knowledge.models import KnowledgeChunk
from rooms.services import accessible_rooms


@dataclass
class Hit:
    chunk: KnowledgeChunk
    score: float
    title: str


def allowed_chunks(user, org, model: str, rooms=None, source_types=None):
    """QuerySet of chunk ids the user may read right now.

    ``rooms`` and ``source_types`` can only narrow the set (a buddy's sources);
    the user's live access is always applied.
    """
    qs = KnowledgeChunk.objects.filter(org=org, model=model, room__in=accessible_rooms(user, org).values("pk"))
    if rooms is not None:
        qs = qs.filter(room__in=rooms)
    if source_types is not None:
        qs = qs.filter(source_type__in=list(source_types))
    if not can(user, "docs.view", org):
        qs = qs.exclude(source_type=KnowledgeChunk.SOURCE_DOC)
    if not can(user, "room.view", org):
        qs = qs.exclude(source_type=KnowledgeChunk.SOURCE_ROOM_MESSAGE)
    if not can(user, "meeting.view", org):
        qs = qs.exclude(source_type__in=[KnowledgeChunk.SOURCE_TRANSCRIPT, KnowledgeChunk.SOURCE_SUMMARY])
    return qs.values_list("id", flat=True)


def _live_titles(chunks) -> dict:
    """Map (source_type, source_id) -> (title, room_id, updated_at) for sources that still exist."""
    from docs_app.models import Document
    from rooms.models import RoomMessage

    doc_ids = {c.source_id for c in chunks if c.source_type == KnowledgeChunk.SOURCE_DOC}
    msg_ids = {c.source_id for c in chunks if c.source_type == KnowledgeChunk.SOURCE_ROOM_MESSAGE}
    live = {}
    for doc in Document.objects.filter(pk__in=doc_ids).only("id", "title", "room_id", "updated_at"):
        live[(KnowledgeChunk.SOURCE_DOC, doc.id)] = (doc.title, doc.room_id, doc.updated_at)
    from meetings.models import Transcript

    tr_ids = {c.source_id for c in chunks if c.source_type == KnowledgeChunk.SOURCE_TRANSCRIPT}
    for tr in Transcript.objects.filter(pk__in=tr_ids).select_related("recording__meeting").only(
        "id", "created_at", "recording__meeting__title", "recording__meeting__room_id"
    ):
        meeting = tr.recording.meeting
        live[(KnowledgeChunk.SOURCE_TRANSCRIPT, tr.id)] = (f"Meeting transcript: {meeting.title}", meeting.room_id, tr.created_at)
    from meetings.models import MeetingSummary

    sum_ids = {c.source_id for c in chunks if c.source_type == KnowledgeChunk.SOURCE_SUMMARY}
    for s in MeetingSummary.objects.filter(pk__in=sum_ids).select_related("meeting").only("id", "created_at", "meeting__title", "meeting__room_id"):
        live[(KnowledgeChunk.SOURCE_SUMMARY, s.id)] = (f"Meeting summary: {s.meeting.title}", s.meeting.room_id, s.created_at)
    for msg in (
        RoomMessage.objects.filter(pk__in=msg_ids, deleted_at__isnull=True)
        .select_related("room")
        .only("id", "room_id", "room__name", "updated_at")
    ):
        live[(KnowledgeChunk.SOURCE_ROOM_MESSAGE, msg.id)] = (f"Message in {msg.room.name}", msg.room_id, msg.updated_at)
    return live


def retrieve(user, org, vector, model: str, store, k: int = 8, rooms=None, source_types=None) -> list[Hit]:
    ranked = store.search(vector, model, allowed_chunks(user, org, model, rooms, source_types), k=k)
    if not ranked:
        return []
    by_id = {row.id: row for row in KnowledgeChunk.objects.filter(pk__in=[cid for cid, _ in ranked])}
    live = _live_titles(by_id.values())
    hits = []
    for chunk_id, score in ranked:
        chunk = by_id.get(chunk_id)
        if chunk is None:
            continue
        source = live.get((chunk.source_type, chunk.source_id))
        # The source must still exist, sit in the room the chunk was filtered on,
        # and be the version the chunk was built from (no pre-edit text).
        if source is None or source[1] != chunk.room_id:
            continue
        if chunk.source_updated_at is None or chunk.source_updated_at != source[2]:
            continue
        hits.append(Hit(chunk=chunk, score=score, title=source[0]))
    return hits
