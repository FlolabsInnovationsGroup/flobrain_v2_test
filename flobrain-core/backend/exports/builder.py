"""Build the org memory export zip (Phase 17e).

Included: documents and non-deleted messages from **team and project rooms**,
with their sources (room, author, timestamps, ids), as JSON Lines + Markdown.
Excluded by construction: direct and group rooms, AI threads (brain chats and
buddy threads), memory nodes and anything personal. ``manifest.json`` says so.
"""

import io
import json
import re
import shutil
import tempfile

from django.conf import settings
from django.utils import timezone

from docs_app.models import Document
from rooms.models import Room, RoomMessage

SAFE = re.compile(r"[^A-Za-z0-9._-]+")
EXCLUDED = ["direct rooms", "group rooms", "AI threads (chats and buddy threads)", "mentor notes", "memory graph", "personal data outside team/project rooms"]


def _name(text, fallback):
    return (SAFE.sub("-", text or "").strip("-")[:60] or fallback).lower()


def _who(user):
    return {"id": str(user.id), "email": user.email} if user is not None else None


def build(org, out):
    """Write the zip to ``out`` (a binary file object). Returns counts."""
    import zipfile

    cap = int(getattr(settings, "EXPORT_MAX_MESSAGES", 500_000))
    counts = {"rooms": 0, "messages": 0, "documents": 0, "truncated": False}
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        rooms = Room.objects.filter(org=org, kind__in=[Room.KIND_TEAM, Room.KIND_PROJECT]).order_by("created_at")
        room_index = []
        for room in rooms.iterator():
            folder = f"rooms/{room.kind}-{_name(room.name, 'room')}-{str(room.id)[:8]}"
            room_index.append({"id": str(room.id), "name": room.name, "kind": room.kind, "active": room.is_active, "folder": folder})
            counts["rooms"] += 1
            messages = (
                RoomMessage.objects.filter(room=room, deleted_at__isnull=True).select_related("author").order_by("created_at", "id")
            )
            # A zip takes one write handle at a time: Markdown goes to a spooled file, then in.
            with tempfile.SpooledTemporaryFile(max_size=16 << 20) as md, zf.open(f"{folder}/messages.jsonl", "w", force_zip64=True) as jl:
                md.write(f"# {room.name}\n\nRoom `{room.id}` ({room.kind}).\n\n".encode())
                for message in messages.iterator(chunk_size=2000):
                    if counts["messages"] >= cap:
                        counts["truncated"] = True
                        break
                    counts["messages"] += 1
                    row = {
                        "id": str(message.id),
                        "room": str(room.id),
                        "author": _who(message.author),
                        "created_at": message.created_at.isoformat(),
                        "body": message.body,
                    }
                    jl.write((json.dumps(row, ensure_ascii=False) + "\n").encode())
                    author = message.author.email if message.author else "(deleted user)"
                    md.write(f"**{author}** · {message.created_at.isoformat()} · `{message.id}`\n\n{message.body}\n\n---\n\n".encode())
                jl.close()
                md.seek(0)
                with zf.open(f"{folder}/messages.md", "w", force_zip64=True) as out:
                    shutil.copyfileobj(md, out, 1 << 20)
        documents = Document.objects.filter(org=org, room__kind__in=[Room.KIND_TEAM, Room.KIND_PROJECT]).select_related("room", "created_by")
        folders = {r["id"]: r["folder"] for r in room_index}
        with tempfile.SpooledTemporaryFile(max_size=16 << 20) as dl:
            for doc in documents.order_by("created_at").iterator(chunk_size=500):
                counts["documents"] += 1
                path = f"{folders.get(str(doc.room_id), 'rooms/unknown')}/documents/{_name(doc.title, 'document')}-{str(doc.id)[:8]}.md"
                meta = {
                    "id": str(doc.id),
                    "room": str(doc.room_id),
                    "title": doc.title,
                    "version": doc.version,
                    "created_by": _who(doc.created_by),
                    "created_at": doc.created_at.isoformat(),
                    "updated_at": doc.updated_at.isoformat(),
                    "path": path,
                }
                dl.write((json.dumps(meta, ensure_ascii=False) + "\n").encode())
                zf.writestr(path, f"# {doc.title}\n\nDocument `{doc.id}`, version {doc.version}, updated {doc.updated_at.isoformat()}.\n\n{doc.content_text}\n")
            dl.seek(0)
            with zf.open("documents.jsonl", "w", force_zip64=True) as out:
                shutil.copyfileobj(dl, out, 1 << 20)
        manifest = {
            "format": "flobrain-memory-export/1",
            "org": {"id": str(org.id), "name": org.name},
            "exported_at": timezone.now().isoformat(),
            "counts": counts,
            "rooms": room_index,
            "included": ["team rooms", "project rooms", "documents in those rooms"],
            "excluded": EXCLUDED,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return counts


def build_bytes(org) -> tuple[bytes, dict]:
    buffer = io.BytesIO()
    counts = build(org, buffer)
    return buffer.getvalue(), counts
