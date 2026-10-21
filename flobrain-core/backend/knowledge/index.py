"""Indexing org sources into knowledge chunks (Phase 7i).

Sources today: documents and room messages. Each source is split into chunks,
each chunk is embedded once per model, and re-indexing is idempotent: a chunk
whose text hash is unchanged is not embedded again.

Indexing only runs while the org's ``memory_search`` flag is on. A source that
is gone, soft-deleted, or saved while its org has the flag off loses its chunks.
Each chunk records the source version it was built from; retrieval drops a
chunk whose source has changed since.
"""

import hashlib
import logging

from django.conf import settings
from django.db import transaction

from jobs.queue import enqueue, register
from knowledge.embeddings import EmbeddingError, get_embedder
from knowledge.models import KnowledgeChunk
from knowledge.store import get_store

logger = logging.getLogger(__name__)

INDEX_JOB = "knowledge.index"
FLAG = "memory_search"
EMBED_BATCH = 32
MAX_CHUNKS_PER_SOURCE = 200


def _setting(name, default):
    return int(getattr(settings, name, default) or default)


def org_indexing_enabled(org) -> bool:
    """Indexing follows the org flag and the plan. Per-member flags decide who may ask."""
    if not bool(((org.settings or {}).get("flags") or {}).get(FLAG, False)):
        return False
    from billing_v2.entitlements import allows

    return allows(org, FLAG)


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """Split on paragraph or sentence breaks near ``size`` characters, with overlap."""
    size = size or _setting("KNOWLEDGE_CHUNK_CHARS", 1500)
    overlap = overlap if overlap is not None else _setting("KNOWLEDGE_CHUNK_OVERLAP", 200)
    overlap = max(0, min(overlap, size // 2))
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text) and len(chunks) < MAX_CHUNKS_PER_SOURCE:
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            for sep in ("\n\n", "\n", ". ", "؟ ", "? ", "! ", " "):
                cut = window.rfind(sep)
                if cut > size // 2:
                    end = start + cut + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _load_source(source_type: str, source_id):
    """Return (org, room, chunks, updated_at) for a live source, or None when it should have no chunks."""
    if source_type == KnowledgeChunk.SOURCE_DOC:
        from docs_app.models import Document

        doc = Document.objects.select_related("org", "room").filter(pk=source_id).first()
        if doc is None:
            return None
        body = f"{doc.title}\n\n{doc.content_text or ''}".strip()
        return doc.org, doc.room, chunk_text(body), doc.updated_at
    if source_type == KnowledgeChunk.SOURCE_ROOM_MESSAGE:
        from rooms.models import RoomMessage

        msg = RoomMessage.objects.select_related("room", "room__org").filter(pk=source_id).first()
        if msg is None or msg.deleted_at is not None:
            return None
        limit = _setting("KNOWLEDGE_CHUNK_CHARS", 1500)
        return msg.room.org, msg.room, chunk_text(msg.body, size=max(limit, 8000), overlap=0), msg.updated_at
    if source_type == KnowledgeChunk.SOURCE_TRANSCRIPT:
        from meetings.models import Transcript

        tr = Transcript.objects.select_related("recording__meeting__room", "recording__meeting__org").filter(pk=source_id).first()
        if tr is None or not tr.text:
            return None
        meeting = tr.recording.meeting
        speaker = tr.recording.speaker_name
        body = f"Meeting: {meeting.title}\n\n" + (f"{speaker}: " if speaker else "") + tr.text
        return meeting.org, meeting.room, chunk_text(body), tr.created_at
    if source_type == KnowledgeChunk.SOURCE_SUMMARY:
        from meetings.models import MeetingSummary

        summary = MeetingSummary.objects.select_related("meeting__room", "meeting__org").filter(pk=source_id).first()
        if summary is None or not summary.text:
            return None
        meeting = summary.meeting
        lines = [f"Meeting summary: {meeting.title}", "", summary.text]
        decisions = [str(d) for d in (summary.decisions or []) if d]
        if decisions:
            lines += ["", "Decisions:"] + [f"- {d}" for d in decisions]
        items = [i for i in (summary.action_items or []) if isinstance(i, dict)]
        if items:
            lines += ["", "Action items:"] + [f"- {i.get('text') or i.get('title') or ''}" + (f" ({i['owner']})" if i.get("owner") else "") for i in items]
        return meeting.org, meeting.room, chunk_text("\n".join(lines)), summary.created_at
    raise ValueError(f"unknown source type {source_type!r}")


def delete_source(source_type: str, source_id) -> int:
    """Delete every chunk (all models) of one source, and their vectors."""
    rows = list(KnowledgeChunk.objects.filter(source_type=source_type, source_id=source_id))
    _delete_chunks(rows)
    return len(rows)


def _delete_chunks(rows) -> None:
    """Delete chunk rows. The post_delete handler removes their vectors."""
    ids = [row.id for row in rows]
    if ids:
        KnowledgeChunk.objects.filter(pk__in=ids).delete()


def delete_vectors(rows) -> None:
    by_dim: dict[int, list] = {}
    for row in rows:
        by_dim.setdefault(row.dimension, []).append(row.id)
    for dimension, ids in by_dim.items():
        store = get_store(dimension)
        if store is not None:
            store.delete(ids)


def index_source(source_type: str, source_id) -> dict:
    """Bring one source's chunks in line with its current text. Safe to repeat."""
    loaded = _load_source(source_type, source_id)
    if loaded is None:
        removed = delete_source(source_type, source_id)
        return {"ok": True, "status": "removed", "removed": removed}
    org, room, texts, version = loaded
    if not org_indexing_enabled(org):
        removed = delete_source(source_type, source_id)
        return {"ok": True, "status": "disabled", "removed": removed}

    from brain.llm.policy import check_ai

    if check_ai(org, "embeddings"):
        return {"ok": False, "reason": "private_only"}  # org content never leaves to an external embedder
    embedder = get_embedder()
    if embedder is None:
        return {"ok": False, "reason": "not_configured"}
    model, dimension = embedder.info.model, embedder.info.dimension
    store = get_store(dimension)
    if store is None:
        return {"ok": False, "reason": "not_configured"}

    existing = {
        row.seq: row
        for row in KnowledgeChunk.objects.filter(source_type=source_type, source_id=source_id, model=model)
    }
    stale_models = list(
        KnowledgeChunk.objects.filter(source_type=source_type, source_id=source_id).exclude(model=model)
    )
    todo = []
    for seq, text in enumerate(texts):
        digest = content_hash(text)
        row = existing.get(seq)
        if row is not None and row.content_hash == digest and row.dimension == dimension:
            if row.room_id != room.id or row.org_id != org.id or row.source_updated_at != version:
                KnowledgeChunk.objects.filter(pk=row.pk).update(room=room, org=org, source_updated_at=version)
            continue
        todo.append((seq, text, digest))

    vectors = []
    try:
        for start in range(0, len(todo), EMBED_BATCH):
            batch = todo[start : start + EMBED_BATCH]
            vectors.extend(embedder.embed([text for _, text, _ in batch]))
    except EmbeddingError as exc:
        # Raise so the job is retried with backoff; nothing was written yet.
        raise RuntimeError(f"embedding failed: {exc.code}") from exc

    with transaction.atomic():
        for (seq, text, digest), vector in zip(todo, vectors):
            row = existing.get(seq)
            if row is None:
                row = KnowledgeChunk.objects.create(
                    org=org,
                    room=room,
                    source_type=source_type,
                    source_id=source_id,
                    seq=seq,
                    text=text,
                    content_hash=digest,
                    model=model,
                    dimension=dimension,
                    source_updated_at=version,
                )
            else:
                row.org, row.room, row.text, row.content_hash, row.dimension = org, room, text, digest, dimension
                row.source_updated_at = version
                row.save(
                    update_fields=["org", "room", "text", "content_hash", "dimension", "source_updated_at", "updated_at"]
                )
            store.upsert(row.id, vector, model)
        extra = [row for seq, row in existing.items() if seq >= len(texts)]
        if extra or stale_models:
            _delete_chunks(extra + stale_models)
    return {"ok": True, "status": "indexed", "embedded": len(todo), "chunks": len(texts)}


@register(INDEX_JOB)
def index_job(payload: dict):
    result = index_source(payload["source_type"], payload["source_id"])
    if not result.get("ok") and result.get("reason") == "not_configured":
        logger.info("knowledge.index skipped: embeddings or vector store not configured")
    return result


def request_index(source_type: str, source_id) -> dict:
    """Queue (or, in eager mode, run) indexing for one source. Never raises."""
    try:
        return enqueue(INDEX_JOB, {"source_type": source_type, "source_id": str(source_id)})
    except Exception:  # noqa: BLE001 - indexing must never break the save that triggered it
        logger.exception("knowledge.index could not be requested for %s %s", source_type, source_id)
        return {"ok": False, "reason": "error"}
