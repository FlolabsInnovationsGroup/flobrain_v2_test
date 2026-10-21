"""Import runner: analyse an upload, import what the admin picked, cancel, resume and undo.

Rules that hold everywhere:

- One active import per org (analysing, queued, running or undoing).
- Every created row is recorded in ``ImportedObject`` with its source key. A re-run (or a second
  import of the same export) skips anything whose key exists, so a crash or a cancel can be
  resumed by running again. Undo deletes only the rows its own run created; a room or team the
  run created is kept when someone has since added their own messages or documents to it.
- Room visibility: Slack public channels go to a team's room (only that team and org admins can
  read it); private channels and DMs become private rooms whose members are the matched people
  only. Documents go to a room the importer can open.
- Imported messages carry their original time and author (people matched by email to active
  members of the org; anyone else is shown as "Imported: Name"). Rooms get an announcement that
  names the source; documents start with a "Source:" line and a link back.
- Indexing: documents are saved normally, so ``knowledge.signals`` indexes them. Messages are
  bulk-created (a normal save would send one push notification per imported message in private
  rooms) and then queued on the same ``knowledge.index`` job the signal uses.
- Logs and audit events hold ids and counts only, never message or document text.
"""

import hashlib
import io
import logging
import tempfile
import time
import zipfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower
from django.utils import timezone

from imports import drive, notion, slack, textract
from imports.models import ImportedObject, ImportRun
from imports.safezip import Limits, SafeZip, ZipSafetyError

logger = logging.getLogger(__name__)

FLAG = "imports"
PERM = "imports.run"
BATCH = 500
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_PREFIX = "fixture:"
SAMPLES = {"slack": ("slack_export", "slack-export-demo.zip"), "notion": ("notion_export", "notion-export-demo.zip")}
TARGETS = ("team", "new_team", "private", "skip")
MAX_DOCUMENT_ITEMS = 2000
LEASE_SECONDS = 15 * 60


class ImportFailure(Exception):
    def __init__(self, code: str, details: str = "", status: int = 400):
        super().__init__(details or code)
        self.code, self.details, self.status = code, details or code, status


# --- settings ---------------------------------------------------------------------------------


def _int(name, default) -> int:
    value = getattr(settings, name, None)
    try:
        return default if value is None or value == "" else int(value)
    except (TypeError, ValueError):
        return default


def max_upload_bytes() -> int:
    return _int("IMPORTS_MAX_UPLOAD_MB", 500) * 1024 * 1024


def max_files_per_upload() -> int:
    return _int("IMPORTS_MAX_FILES_PER_UPLOAD", 20)


def zip_limits() -> Limits:
    return Limits(
        max_files=_int("IMPORTS_MAX_ZIP_ENTRIES", 20000),
        max_total=_int("IMPORTS_MAX_UNPACKED_MB", 2048) * 1024 * 1024,
        max_member=_int("IMPORTS_MAX_ZIP_MEMBER_MB", 200) * 1024 * 1024,
        max_ratio=_int("IMPORTS_MAX_ZIP_RATIO", 100),
    )


def max_file_bytes() -> int:
    """One document's file (inside an archive or uploaded alone)."""
    return _int("IMPORTS_MAX_FILE_MB", 50) * 1024 * 1024


def job_seconds() -> int:
    """How long one job slice runs before it hands over to a fresh job (resumable by design)."""
    return _int("IMPORTS_JOB_SECONDS", 240)


# --- access -------------------------------------------------------------------------------------


def flag_on(user, org) -> bool:
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership

    return effective_flag(org, OrgMembership.objects.filter(org=org, user=user).first(), FLAG, default=False)


def is_demo_org(org) -> bool:
    return (org.settings or {}).get("demo") is True


def active_run(org):
    return ImportRun.objects.filter(org=org, status__in=ImportRun.ACTIVE).first()


# --- stored files -------------------------------------------------------------------------------


def storage_key(run, n: int, name: str) -> str:
    from content_studio.storage import SAFE

    safe = SAFE.sub("_", name or "file")[-80:] or "file"
    return f"imports/{run.org_id}/{run.id}/{n}-{safe}"


def store_upload(run, n: int, upload) -> dict:
    from content_studio import storage

    key = storage_key(run, n, getattr(upload, "name", "file"))
    if not storage.put_file(key, upload, "application/octet-stream"):
        raise ImportFailure("not_implemented", "File storage is not set up", 501)
    return {"key": key, "name": str(getattr(upload, "name", "file"))[-200:], "size": int(getattr(upload, "size", 0) or 0)}


def fixture_zip(folder: str) -> io.BytesIO:
    """A ZIP built in memory from a bundled fixture folder (demo and tests; no network, no storage)."""
    root = FIXTURES / folder
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root).as_posix())
    buf.seek(0)
    return buf


def open_stored(entry: dict):
    """A readable binary file for one stored upload (caller closes it)."""
    key = entry.get("key") or ""
    if key.startswith(FIXTURE_PREFIX):
        folder = key[len(FIXTURE_PREFIX):]
        if folder not in {f for f, _ in SAMPLES.values()}:
            raise ImportFailure("missing_file", "The uploaded file is gone. Upload it again")
        return fixture_zip(folder)
    from content_studio import storage

    tmp = tempfile.TemporaryFile()
    if not storage.download_to(key, tmp, max_bytes=max_upload_bytes()):
        tmp.close()
        raise ImportFailure("missing_file", "The uploaded file is gone. Upload it again")
    tmp.seek(0)
    return tmp


def delete_stored(run) -> None:
    from content_studio import storage

    for entry in run.files or []:
        key = entry.get("key") or ""
        if key and not key.startswith(FIXTURE_PREFIX):
            try:
                storage.delete(key)
            except Exception:  # noqa: BLE001 - cleanup must not fail the undo
                logger.warning("import %s: could not delete a stored file", run.id)


def is_zip_name(name: str) -> bool:
    return (name or "").lower().endswith(".zip")


# --- people -------------------------------------------------------------------------------------


def match_people(org, slack_users: dict) -> dict:
    """Slack user id -> FloBrain User, by email, active members of this org only."""
    from users.models import User

    emails = {u.email for u in slack_users.values() if u.email}
    if not emails:
        return {}
    found = {
        u.email_lower: u
        for u in User.objects.annotate(email_lower=Lower("email")).filter(
            email_lower__in=emails, org_memberships__org=org, org_memberships__employment_status="active"
        )
    }
    return {sid: found[u.email] for sid, u in slack_users.items() if u.email in found}


def member_name(user) -> str:
    from rooms.services import display_name

    return display_name(user)


# --- analysis -----------------------------------------------------------------------------------


def _iso(dt) -> str:
    return dt.isoformat() if dt else ""


def analyze_slack(run, zf: SafeZip) -> dict:
    from organizations.models import Team

    export = slack.SlackExport(zf)
    matched = match_people(run.org, export.users)
    teams = {t.name.strip().lower(): t for t in Team.objects.filter(org=run.org, is_active=True)}
    channels, total = [], 0
    for ch in export.channels:
        msgs = export.messages(ch)
        total += len(msgs)
        replies = sum(1 for m in msgs if m.is_reply)
        names = [export.user_name(uid) for uid in ch.members]
        suggested = teams.get(ch.name.lower()) if ch.kind == "public" else None
        channels.append({
            "id": ch.id,
            "name": ch.name if ch.kind not in ("dm", "group_dm") else "Direct message: " + ", ".join(sorted(names))[:150],
            "kind": ch.kind,
            "archived": ch.archived,
            "messages": len(msgs),
            "threads": replies,
            "first": _iso(msgs[0].when) if msgs else "",
            "last": _iso(msgs[-1].when) if msgs else "",
            "members": len(ch.members),
            "matched": sum(1 for uid in ch.members if uid in matched),
            "suggested_team": str(suggested.id) if suggested else "",
        })
    people = []
    for sid, user in sorted(export.users.items(), key=lambda kv: kv[1].name.lower()):
        if user.is_bot:
            continue
        member = matched.get(sid)
        people.append({
            "slack_id": sid,
            "name": user.name,
            "matched": member is not None,
            "member_id": str(member.id) if member else "",
            "member_name": member_name(member) if member else "",
            "shown_as": member_name(member) if member else f"Imported: {user.name}",
        })
    firsts = [c["first"] for c in channels if c["first"]]
    lasts = [c["last"] for c in channels if c["last"]]
    return {
        "channels": channels[:2000],
        "people": people[:5000],
        "totals": {
            "channels": len(channels),
            "messages": total,
            "people": len(people),
            "matched": sum(1 for p in people if p["matched"]),
            "first": min(firsts) if firsts else "",
            "last": max(lasts) if lasts else "",
        },
        "has_private": any(c["kind"] == "private" for c in channels),
        "has_dms": any(c["kind"] in ("dm", "group_dm") for c in channels),
    }


def _doc_item(ref, name, kind, size, supported=True, reason="", notion_id="") -> dict:
    return {"ref": ref, "name": name[:200], "kind": kind, "size": int(size or 0), "supported": supported, "reason": reason, "notion_id": notion_id}


def analyze_notion_zip(run, zf: SafeZip) -> dict:
    export = notion.NotionExport(zf)
    items = [
        _doc_item(f"{i}", it["title"], "notion_" + it["kind"], it["size"], notion_id=it["notion_id"])
        for i, it in enumerate(export.items[:MAX_DOCUMENT_ITEMS])
    ]
    return {"items": items, "totals": {"items": len(items), "pages": sum(1 for i in items if i["kind"] == "notion_page"), "databases": sum(1 for i in items if i["kind"] == "notion_database")}}


def _file_support(name: str) -> tuple[bool, str]:
    kind = textract.kind_of(name)
    if not kind:
        return False, "unsupported"
    if kind == "pdf" and not textract.pdf_supported():
        return False, "pdf_unavailable"
    return True, ""


def analyze_files(run) -> dict:
    items = []
    for n, entry in enumerate(run.files or []):
        if is_zip_name(entry["name"]):
            with open_stored(entry) as fh, SafeZip(fh, zip_limits()) as zf:
                for name in zf.names():
                    base = name.rsplit("/", 1)[-1]
                    if base.startswith(".") or "__MACOSX" in name or not textract.kind_of(name):
                        continue
                    ok, reason = _file_support(name)
                    items.append(_doc_item(f"{n}:{name}", base, textract.kind_of(name), zf.size(name), ok, reason))
                    if len(items) >= MAX_DOCUMENT_ITEMS:
                        break
        else:
            ok, reason = _file_support(entry["name"])
            items.append(_doc_item(f"{n}", entry["name"], textract.kind_of(entry["name"]) or "file", entry.get("size"), ok, reason))
    return {"items": items[:MAX_DOCUMENT_ITEMS], "totals": {"items": len(items), "supported": sum(1 for i in items if i["supported"])}}


def analyze(run) -> None:
    """Build the preview for an uploaded run. Status: analyzing -> ready (or failed)."""
    try:
        if run.source == ImportRun.SOURCE_FILES:
            preview = analyze_files(run)
        else:
            with open_stored(run.files[0]) as fh, SafeZip(fh, zip_limits()) as zf:
                preview = analyze_slack(run, zf) if run.source == ImportRun.SOURCE_SLACK else analyze_notion_zip(run, zf)
    except ZipSafetyError as exc:
        return _fail(run, exc.code, exc.details)
    except (slack.SlackError, notion.NotionError, ImportFailure) as exc:
        return _fail(run, exc.code, exc.details)
    ImportRun.objects.filter(pk=run.pk, status=ImportRun.ANALYZING).update(preview=preview, status=ImportRun.READY, updated_at=timezone.now())


def _fail(run, code, details="") -> None:
    ImportRun.objects.filter(pk=run.pk).update(
        status=ImportRun.FAILED, error=f"{code}: {details}"[:200], finished_at=timezone.now(), lease_until=None, updated_at=timezone.now()
    )
    logger.info("import %s failed: %s", run.id, code)


# --- mapping validation ---------------------------------------------------------------------------


def clean_slack_mapping(user, org, run, data) -> dict:
    from organizations.models import Team
    from organizations.permissions import is_org_owner_or_admin
    from rooms.services import ensure_team_room, user_can_access_room

    preview = run.preview or {}
    by_id = {c["id"]: c for c in preview.get("channels") or []}
    raw = data.get("channels") if isinstance(data.get("channels"), dict) else {}
    include_private = data.get("include_private") is True
    include_dms = data.get("include_dms") is True
    out = {}
    for cid, choice in raw.items():
        ch = by_id.get(cid)
        if ch is None or not isinstance(choice, dict):
            raise ImportFailure("invalid", "Unknown channel in the mapping")
        target = choice.get("target")
        if target not in TARGETS:
            raise ImportFailure("invalid", "Pick team, new team, private room or skip for each channel")
        if target == "skip":
            continue
        if ch["kind"] == "private" and not include_private:
            continue
        if ch["kind"] in ("dm", "group_dm") and not include_dms:
            continue
        if ch["kind"] != "public" and target != "private":
            raise ImportFailure("invalid", "Private channels and direct messages can only become private rooms")
        if ch["kind"] == "public" and target == "private":
            raise ImportFailure("invalid", "Public channels go to a team room")
        entry = {"target": target}
        if target == "team":
            team = Team.objects.filter(org=org, pk=choice.get("team_id"), is_active=True).first() if _uuid_ok(choice.get("team_id")) else None
            if team is None:
                raise ImportFailure("invalid", f"Pick a team for #{ch['name']}")
            if not user_can_access_room(user, ensure_team_room(team)):
                raise ImportFailure("forbidden", "You can only import into a team room you can open", 403)
            entry["team_id"] = str(team.id)
        if target == "new_team" and not is_org_owner_or_admin(user, org):
            raise ImportFailure("forbidden", "Only an org owner or admin can create teams", 403)
        out[cid] = entry
    if not out:
        raise ImportFailure("invalid", "Pick at least one channel to import")
    return {"channels": out, "include_private": include_private, "include_dms": include_dms, "include_bots": data.get("include_bots") is True}


def _uuid_ok(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def target_room(user, org, room_id):
    from rooms.models import Room
    from rooms.services import user_can_access_room

    room = Room.objects.filter(org=org, pk=room_id, is_active=True).first() if _uuid_ok(room_id) else None
    if room is None or not user_can_access_room(user, room):
        raise ImportFailure("invalid", "Pick a room you can open")
    return room


def clean_document_mapping(user, org, run, data) -> dict:
    room = target_room(user, org, data.get("room_id"))
    items = (run.preview or {}).get("items") or []
    supported = [i["ref"] for i in items if i.get("supported")]
    refs = data.get("refs")
    if refs is None:
        chosen = supported
    elif isinstance(refs, list):
        wanted = {str(r) for r in refs}
        chosen = [r for r in supported if r in wanted]
    else:
        raise ImportFailure("invalid", "refs must be a list")
    if not chosen:
        raise ImportFailure("invalid", "Pick at least one page or file to import")
    return {"room_id": str(room.id), "refs": chosen[:MAX_DOCUMENT_ITEMS]}


# --- running --------------------------------------------------------------------------------------


class Cancelled(Exception):
    pass


class OutOfTime(Exception):
    pass


class Runner:
    """One slice of an import. Holds counters and the time budget, checks cancel between batches."""

    def __init__(self, run, budget: float | None):
        self.run = run
        self.org = run.org
        self.deadline = time.monotonic() + budget if budget else None
        self.counts = dict(run.counts or {})
        self.progress = dict(run.progress or {})

    def bump(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    def checkpoint(self, done_delta=0, current=None):
        self.progress["done"] = self.progress.get("done", 0) + done_delta
        if current is not None:
            self.progress["current"] = current
        ImportRun.objects.filter(pk=self.run.pk).update(
            progress=self.progress, counts=self.counts, updated_at=timezone.now(), lease_until=timezone.now() + timedelta(seconds=LEASE_SECONDS)
        )
        if ImportRun.objects.filter(pk=self.run.pk, cancel_requested=True).exists():
            raise Cancelled()
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise OutOfTime()

    def record(self, kind, objects, keys=None):
        rows = [
            ImportedObject(org=self.org, run=self.run, kind=kind, object_id=str(obj.pk), source_key=(keys[i] if keys else ""))
            for i, obj in enumerate(objects)
        ]
        ImportedObject.objects.bulk_create(rows)

    def existing_keys(self, kind, prefix, other_runs=False) -> set:
        qs = ImportedObject.objects.filter(org=self.org, kind=kind, source_key__startswith=prefix)
        if other_runs:
            qs = qs.exclude(run=self.run)
        return set(qs.values_list("source_key", flat=True))

    def announce(self, room, key, text) -> bool:
        """One announcement per room and run, naming the source; a later slice updates it. True when new."""
        from rooms.models import Announcement

        row = ImportedObject.objects.filter(org=self.org, kind=ImportedObject.KIND_ANNOUNCEMENT, source_key=key).first()
        if row is not None and Announcement.objects.filter(pk=row.object_id).update(body=text[:8000]):
            return False
        ann = Announcement.objects.create(org=self.org, room=room, body=text[:8000], pinned=False, created_by=self.run.created_by)
        if row is not None:
            ImportedObject.objects.filter(pk=row.pk).update(object_id=str(ann.pk))
        else:
            self.record(ImportedObject.KIND_ANNOUNCEMENT, [ann], [key])
        return True


def _index_messages(org, ids) -> None:
    from knowledge import index
    from knowledge.models import KnowledgeChunk

    if not ids or not index.org_indexing_enabled(org):
        return
    for mid in ids:
        index.request_index(KnowledgeChunk.SOURCE_ROOM_MESSAGE, mid)


def _unique_team_name(org, base: str) -> str:
    from organizations.models import Team

    base = (base or "Imported")[:180]
    name, n = base, 1
    while Team.objects.filter(org=org, name=name).exists():
        n += 1
        name = f"{base} (Slack {n})" if n > 2 else f"{base} (Slack)"
    return name


def _created(runner, kind, key):
    """The object a previous run made for ``key`` (room or team), or None."""
    row = ImportedObject.objects.filter(org=runner.org, kind=kind, source_key=key).first()
    return row.object_id if row else None


def _slack_room(runner, ch, choice, matched):
    """The room for one channel, made on the first run and reused on later ones."""
    from organizations.models import Team, TeamMembership
    from rooms.models import Room, RoomMember
    from rooms.services import ensure_team_room

    key = f"slack:{ch.id}"
    members = [matched[uid] for uid in ch.members if uid in matched]
    if choice["target"] == "team":
        team = Team.objects.filter(org=runner.org, pk=choice["team_id"], is_active=True).first()
        return ensure_team_room(team) if team else None
    if choice["target"] == "new_team":
        team_id = _created(runner, ImportedObject.KIND_TEAM, key)
        team = Team.objects.filter(org=runner.org, pk=team_id).first() if team_id else None
        if team is None:
            team = Team.objects.create(org=runner.org, name=_unique_team_name(runner.org, ch.name), description=f"Imported from Slack #{ch.name}"[:500])
            runner.record(ImportedObject.KIND_TEAM, [team], [key])
            runner.bump("teams_created")
        new = []
        have = set(TeamMembership.objects.filter(team=team).values_list("user_id", flat=True))
        for user in members:
            if user.id not in have:
                new.append(TeamMembership.objects.create(team=team, user=user))
        runner.record(ImportedObject.KIND_TEAM_MEMBER, new)
        return ensure_team_room(team)
    # private channel or DM: a private room, matched people only
    if not members:
        runner.bump("channels_without_people")
        return None
    room_id = _created(runner, ImportedObject.KIND_ROOM, key)
    room = Room.objects.filter(org=runner.org, pk=room_id).first() if room_id else None
    if room is None:
        name = ch.name if ch.kind == "private" else "Direct message (Slack)"
        room = Room.objects.create(org=runner.org, name=name[:200], kind=Room.KIND_GROUP)
        runner.record(ImportedObject.KIND_ROOM, [room], [key])
        runner.bump("rooms_created")
    have = set(RoomMember.objects.filter(room=room).values_list("user_id", flat=True))
    new = [RoomMember.objects.create(room=room, user=u) for u in {u.id: u for u in members}.values() if u.id not in have]
    runner.record(ImportedObject.KIND_ROOM_MEMBER, new)
    return room


def _message_body(msg, export, names, channel_names, author, parents) -> str:
    max_len = getattr(settings, "FLOBRAIN_V2", {}).get("ROOM_MESSAGE_MAX_LENGTH", 8000)
    lines = []
    if author is None:
        lines.append(f"Imported: {msg.user_name}")
    if msg.is_reply:
        parent = parents.get(msg.thread_ts)
        lines.append(f"↳ Reply in thread: “{parent}”" if parent else "↳ Reply in thread")
    text = slack.convert_text(msg.text, names, channel_names).strip()
    if msg.edited and text:
        text += " (edited)"
    if text:
        lines.append(text)
    for name, url in msg.files:
        lines.append(f"File: {name} ({url})" if url else f"File: {name}")
    if msg.reactions:
        lines.append(slack.reactions_line(msg.reactions))
    body = "\n".join(lines)
    return body if len(body) <= max_len else body[: max_len - 1] + "…"


def run_slack(runner, zf: SafeZip) -> None:
    from rooms.models import RoomMessage

    export = slack.SlackExport(zf)
    mapping = runner.run.mapping or {}
    matched = match_people(runner.org, export.users)
    names = {sid: member_name(matched[sid]) if sid in matched else u.name for sid, u in export.users.items()}
    channel_names = {c.id: c.name for c in export.channels}
    chosen = [(ch, mapping["channels"][ch.id]) for ch in export.channels if ch.id in (mapping.get("channels") or {})]
    chosen_ids = {ch.id for ch, _ in chosen}
    runner.progress["total"] = sum(c["messages"] for c in (runner.run.preview or {}).get("channels") or [] if c["id"] in chosen_ids)
    runner.progress["done"] = 0
    for ch, choice in chosen:
        msgs = export.messages(ch, include_bots=mapping.get("include_bots") is True)
        room = _slack_room(runner, ch, choice, matched)
        if room is None:
            runner.bump("messages_skipped", len(msgs))
            runner.checkpoint(len(msgs), ch.name)
            continue
        prefix = f"slack:{ch.id}:"
        have = runner.existing_keys(ImportedObject.KIND_MESSAGE, prefix)
        before = runner.existing_keys(ImportedObject.KIND_MESSAGE, prefix, other_runs=True)
        parents = {m.ts: slack.snippet(slack.convert_text(m.text, names, channel_names), 60) for m in msgs if not m.is_reply}
        for start in range(0, len(msgs), BATCH):
            batch = [m for m in msgs[start:start + BATCH] if prefix + m.ts not in have]
            runner.bump("messages_existing", sum(1 for m in msgs[start:start + BATCH] if prefix + m.ts in before))
            if batch:
                rows, keys = [], []
                for m in batch:
                    author = matched.get(m.user)
                    rows.append(RoomMessage(room=room, author=author, body=_message_body(m, export, names, channel_names, author, parents), created_at=m.when))
                    keys.append(prefix + m.ts)
                with transaction.atomic():
                    RoomMessage.objects.bulk_create(rows)
                    runner.record(ImportedObject.KIND_MESSAGE, rows, keys)
                _index_messages(runner.org, [r.id for r in rows])
                runner.bump("messages", len(rows))
            runner.checkpoint(min(BATCH, len(msgs) - start), ch.name)
        mine = sorted(float(k[len(prefix):]) for k in runner.existing_keys(ImportedObject.KIND_MESSAGE, prefix) - before)
        if mine:
            first, last = slack.ts_datetime(str(mine[0])), slack.ts_datetime(str(mine[-1]))
            label = f"#{ch.name}" if ch.kind in ("public", "private") else "a direct message"
            text = (
                f"Imported from Slack {label}: {len(mine)} messages from {first:%d %b %Y} to {last:%d %b %Y}. "
                f"Imported by {member_name(runner.run.created_by)}."
            )
            if runner.announce(room, f"announce:{runner.run.id}:{ch.id}", text):
                runner.bump("channels")


# --- documents --------------------------------------------------------------------------------------


def _create_document(runner, room, title, text, key, source_line) -> bool:
    """Create one Document unless ``key`` was imported before. True when created."""
    from docs_app.models import Document

    if ImportedObject.objects.filter(org=runner.org, kind=ImportedObject.KIND_DOCUMENT, source_key=key).exists():
        runner.bump("documents_existing")
        return False
    body = f"{source_line}\n\n{text}".strip()
    try:
        with transaction.atomic():
            doc = Document.objects.create(org=runner.org, room=room, title=(title or "Untitled")[:200], content_text=body, created_by=runner.run.created_by)
            runner.record(ImportedObject.KIND_DOCUMENT, [doc], [key])
    except IntegrityError:
        runner.bump("documents_existing")
        return False
    runner.bump("documents")
    return True


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_notion_zip(runner, room, zf: SafeZip) -> None:
    export = notion.NotionExport(zf)
    refs = set((runner.run.mapping or {}).get("refs") or [])
    chosen = [(str(i), it) for i, it in enumerate(export.items[:MAX_DOCUMENT_ITEMS]) if str(i) in refs]
    runner.progress.update({"total": len(chosen), "done": 0})
    for ref, item in chosen:
        title, text = export.document(item)
        if item["notion_id"]:
            key, link = notion.source_key(item["notion_id"]), notion.page_url(item["notion_id"])
            source = f"Source: Notion · {link}"
        else:
            key = "notion:file:" + _sha(text.encode())[:40]
            source = "Source: Notion export"
        _create_document(runner, room, title, text, key, source)
        runner.checkpoint(1, title)


def run_files(runner, room) -> None:
    refs = (runner.run.mapping or {}).get("refs") or []
    by_file: dict[int, list[str]] = {}
    for ref in refs:
        n, _, member = ref.partition(":")
        by_file.setdefault(int(n), []).append(member)
    runner.progress.update({"total": len(refs), "done": 0})
    for n, members in sorted(by_file.items()):
        entry = (runner.run.files or [])[n]
        with open_stored(entry) as fh:
            if is_zip_name(entry["name"]):
                with SafeZip(fh, zip_limits()) as zf:
                    origin = "Google Takeout" if "takeout" in entry["name"].lower() or any(m.startswith("Takeout/") for m in members) else entry["name"]
                    for member in members:
                        base = member.rsplit("/", 1)[-1]
                        try:
                            data = zf.read(member, max_bytes=max_file_bytes())
                        except (KeyError, ZipSafetyError):
                            runner.bump("files_too_big")
                        else:
                            _file_document(runner, room, base, data, origin)
                        runner.checkpoint(1, base)
            else:
                data = fh.read(max_file_bytes() + 1)
                if len(data) > max_file_bytes():
                    runner.bump("files_too_big")
                else:
                    _file_document(runner, room, entry["name"], data, "")
                runner.checkpoint(1, entry["name"])


def _file_document(runner, room, name, data, origin) -> None:
    try:
        text = textract.extract(name, data)
    except textract.ExtractError as exc:
        runner.bump(f"files_{exc.code}")
        return
    title = name.rsplit(".", 1)[0] if "." in name else name
    source = f"Source: {origin} ({name})" if origin and origin != name else f"Source: uploaded file ({name})"
    _create_document(runner, room, title, text, "file:" + _sha(data), source)


def run_notion_api(runner, room) -> None:
    from connectors.models import Connection

    mapping = runner.run.mapping or {}
    conn = Connection.objects.filter(org=runner.org, pk=mapping.get("connection_id"), connector="notion", status=Connection.ACTIVE).first()
    if conn is None:
        raise ImportFailure("not_connected", "The Notion connection is gone. Connect Notion again")
    items = mapping.get("items") or []
    runner.progress.update({"total": len(items), "done": 0})
    client = notion_client(conn)
    for item in items:
        kind, raw_id = item.get("type"), item.get("id")
        key = notion.source_key(raw_id)
        if ImportedObject.objects.filter(org=runner.org, kind=ImportedObject.KIND_DOCUMENT, source_key=key).exists():
            runner.bump("documents_existing")
            runner.checkpoint(1)
            continue
        try:
            title, text = client.database_document(raw_id) if kind == "database" else client.page_document(raw_id)
        except notion.NotionError as exc:
            if exc.code in ("invalid_credential", "unreachable", "rate_limited"):
                raise ImportFailure(exc.code, exc.details) from exc
            runner.bump(f"notion_{exc.code}")
            runner.checkpoint(1)
            continue
        _create_document(runner, room, title, text, key, f"Source: Notion · {notion.page_url(raw_id)}")
        runner.checkpoint(1, title)


def notion_client(conn):
    """A real client, or the canned demo one for demo connections (never the network)."""
    from connectors.jobs import is_demo, secret_of

    if is_demo(conn):
        if not getattr(settings, "DEMO_MODE", False):
            raise ImportFailure("demo_only", "Demo connection: imports are off outside demo mode")
        return DemoNotion()
    if getattr(settings, "DEMO_MODE", False):
        raise ImportFailure("demo_only", "Demo servers never call Notion")
    from integrations.crypto import CredentialCryptoError

    try:
        return notion.Client(secret_of(conn))
    except CredentialCryptoError as exc:
        raise ImportFailure("invalid_credential", "The Notion token can't be read. Connect Notion again") from exc


class DemoNotion:
    """Canned pages for the demo Notion connection."""

    PAGES = {
        "5e6f708192a3b4c5d6e7f8091a2b3c4d": ("page", "Brand voice (demo)", "# Brand voice\n\nDemo data.\n\n- Short sentences\n- Say what happens next\n- Arabic first for Egyptian customers"),
        "6f708192a3b4c5d6e7f8091a2b3c4d5e": ("page", "Meeting notes template (demo)", "## Agenda\n\n## Decisions\n\n## Action items\n- [ ] Owner, due date"),
        "708192a3b4c5d6e7f8091a2b3c4d5e6f": ("database", "Hiring pipeline (demo)", "Name | Stage | Owner\nCandidate A | Interview | Omar\nCandidate B | Offer | Nadia"),
    }

    def search(self, query=""):
        return [
            {"id": pid, "type": kind, "title": title, "url": notion.page_url(pid), "last_edited": "2026-10-01T09:00:00.000Z"}
            for pid, (kind, title, _) in self.PAGES.items()
            if not query or query.lower() in title.lower()
        ]

    def _doc(self, raw_id):
        row = self.PAGES.get((raw_id or "").replace("-", "").lower())
        if row is None:
            raise notion.NotionError("not_found", "Notion did not find it")
        return row[1], row[2]

    page_document = database_document = _doc


def run_drive_api(runner, room) -> None:
    mapping = runner.run.mapping or {}
    conn, status, message = drive.connection(runner.run.created_by, runner.org)
    if conn is None:
        raise ImportFailure(status, message)
    if conn.demo and not getattr(settings, "DEMO_MODE", False):
        raise ImportFailure("demo_only", "Demo connection: imports are off outside demo mode")
    ids = mapping.get("file_ids") or []
    runner.progress.update({"total": len(ids), "done": 0})
    for fid in ids:
        key = f"drive:{fid}"
        if ImportedObject.objects.filter(org=runner.org, kind=ImportedObject.KIND_DOCUMENT, source_key=key).exists():
            runner.bump("documents_existing")
            runner.checkpoint(1)
            continue
        try:
            meta = drive.file_meta(conn, fid)
            if not meta["supported"]:
                runner.bump("files_pdf_unavailable")
                runner.checkpoint(1, meta["name"])
                continue
            text = drive.file_text(conn, meta)
        except drive.DriveError as exc:
            if exc.code in ("expired", "unreachable", "rate_limited", "blocked_host"):
                raise ImportFailure(exc.code, exc.details) from exc
            runner.bump(f"files_{exc.code}")
            runner.checkpoint(1)
            continue
        except textract.ExtractError as exc:
            runner.bump(f"files_{exc.code}")
            runner.checkpoint(1)
            continue
        title = meta["name"].rsplit(".", 1)[0] if meta["kind"] in ("pdf", "docx") else meta["name"]
        _create_document(runner, room, title, text, key, f"Source: Google Drive · {meta['url']}")
        runner.checkpoint(1, meta["name"])


def _document_room(run):
    from rooms.models import Room

    room = Room.objects.filter(org=run.org, pk=(run.mapping or {}).get("room_id"), is_active=True).first()
    if room is None:
        raise ImportFailure("invalid", "The chosen room is gone")
    return room


def claim(run_id) -> ImportRun | None:
    """Take the run for this job slice unless another worker holds a fresh lease."""
    now = timezone.now()
    from django.db.models import Q

    updated = ImportRun.objects.filter(pk=run_id, status__in=(ImportRun.QUEUED, ImportRun.RUNNING)).filter(
        Q(lease_until__isnull=True) | Q(lease_until__lt=now)
    ).update(status=ImportRun.RUNNING, lease_until=now + timedelta(seconds=LEASE_SECONDS), updated_at=now)
    if not updated:
        return None
    run = ImportRun.objects.select_related("org", "created_by").get(pk=run_id)
    if run.started_at is None:
        ImportRun.objects.filter(pk=run.pk).update(started_at=now)
    return run


def execute(run_id, budget: float | None = None) -> str:
    """Run (or continue) one import. Returns the status it ended in, or "busy"."""
    run = claim(run_id)
    if run is None:
        return "busy"
    if run.cancel_requested:
        return _finish(run, ImportRun.CANCELLED, run.counts or {})
    runner = Runner(run, budget)
    try:
        if run.source in (ImportRun.SOURCE_SLACK, ImportRun.SOURCE_NOTION_ZIP):
            with open_stored(run.files[0]) as fh, SafeZip(fh, zip_limits()) as zf:
                if run.source == ImportRun.SOURCE_SLACK:
                    run_slack(runner, zf)
                else:
                    run_notion_zip(runner, _document_room(run), zf)
        elif run.source == ImportRun.SOURCE_FILES:
            run_files(runner, _document_room(run))
        elif run.source == ImportRun.SOURCE_NOTION_API:
            run_notion_api(runner, _document_room(run))
        elif run.source == ImportRun.SOURCE_DRIVE_API:
            run_drive_api(runner, _document_room(run))
    except Cancelled:
        return _finish(run, ImportRun.CANCELLED, runner.counts)
    except OutOfTime:
        ImportRun.objects.filter(pk=run.pk).update(lease_until=None, counts=runner.counts, progress=runner.progress)
        from jobs.queue import enqueue

        enqueue(RUN_JOB, {"run_id": str(run.id)})  # the next slice skips what is already in
        return ImportRun.RUNNING
    except ZipSafetyError as exc:
        return _finish(run, ImportRun.FAILED, runner.counts, f"{exc.code}: {exc.details}")
    except (ImportFailure, slack.SlackError, notion.NotionError, drive.DriveError) as exc:
        return _finish(run, ImportRun.FAILED, runner.counts, f"{exc.code}: {exc.details}")
    return _finish(run, ImportRun.DONE, runner.counts)


RUN_JOB = "imports.run"


def _finish(run, status, counts, error="") -> str:
    from organizations.services.core import audit

    now = timezone.now()
    ImportRun.objects.filter(pk=run.pk).update(status=status, counts=counts, finished_at=now, lease_until=None, error=error[:200], updated_at=now)
    action = {ImportRun.DONE: "imports.finished", ImportRun.CANCELLED: "imports.cancelled"}.get(status, "imports.failed")
    audit(run.created_by, action, target=run, org=run.org, payload={"source": run.source, "status": status, "counts": counts})
    _notify(run, status, counts)
    logger.info("import %s %s", run.id, status)
    return status


def _notify(run, status, counts) -> None:
    from notifications.services import notify

    if run.created_by_id is None:
        return
    label = dict(ImportRun.SOURCES).get(run.source, "Import")
    if status == ImportRun.DONE:
        made = counts.get("messages", 0) + counts.get("documents", 0)
        text = f"{label} import finished: {made} items added"
    elif status == ImportRun.CANCELLED:
        text = f"{label} import stopped"
    else:
        text = f"{label} import failed"
    notify(run.org, [run.created_by], "import_finished", {"text": text, "run": str(run.id), "status": status}, link="settings/imports")


# --- undo -----------------------------------------------------------------------------------------


def undo(run_id, user_id=None) -> dict:
    """Delete everything this run created. Rooms and teams with other people's content stay."""
    from docs_app.models import Document
    from organizations.models import Team, TeamMembership
    from rooms.models import Announcement, Room, RoomMember, RoomMessage

    run = ImportRun.objects.select_related("org", "created_by").filter(pk=run_id, status=ImportRun.UNDOING).first()
    if run is None:
        return {"ok": False}
    rows = ImportedObject.objects.filter(run=run)

    def ids(kind):
        return list(rows.filter(kind=kind).values_list("object_id", flat=True))

    removed = {}
    for kind, model in ((ImportedObject.KIND_MESSAGE, RoomMessage), (ImportedObject.KIND_DOCUMENT, Document), (ImportedObject.KIND_ANNOUNCEMENT, Announcement)):
        all_ids = ids(kind)
        n = 0
        for start in range(0, len(all_ids), BATCH):
            n += model.objects.filter(pk__in=all_ids[start:start + BATCH], **({"room__org": run.org} if model is not Document else {"org": run.org})).delete()[1].get(model._meta.label, 0)
        removed[kind] = n
    kept = 0
    room_ids = ids(ImportedObject.KIND_ROOM)
    for room in Room.objects.filter(org=run.org, pk__in=room_ids):
        if RoomMessage.objects.filter(room=room).exists() or Document.objects.filter(room=room).exists():
            kept += 1
            continue
        room.delete()
    RoomMember.objects.filter(pk__in=ids(ImportedObject.KIND_ROOM_MEMBER), room__org=run.org).delete()
    team_ids = ids(ImportedObject.KIND_TEAM)
    our_memberships = ids(ImportedObject.KIND_TEAM_MEMBER)
    for team in Team.objects.filter(org=run.org, pk__in=team_ids):
        others = TeamMembership.objects.filter(team=team).exclude(pk__in=our_memberships).exists()
        content = RoomMessage.objects.filter(room__team=team).exists() or Document.objects.filter(room__team=team).exists()
        if others or content:
            kept += 1
            continue
        team.delete()  # its memberships and team room go with it
    TeamMembership.objects.filter(pk__in=our_memberships, team__org=run.org).delete()
    rows.delete()
    delete_stored(run)
    result = {"messages": removed.get(ImportedObject.KIND_MESSAGE, 0), "documents": removed.get(ImportedObject.KIND_DOCUMENT, 0), "kept_containers": kept}
    now = timezone.now()
    ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.UNDONE, undone_at=now, undone_by_id=user_id, files=[], updated_at=now)
    from organizations.services.core import audit

    audit(_user(user_id) if user_id else None, "imports.undone", target=run, org=run.org, payload={"source": run.source, "removed": result})
    return {"ok": True, **result}


def _user(user_id):
    from users.models import User

    return User.objects.filter(pk=user_id).first()


# --- serialisation --------------------------------------------------------------------------------


def run_payload(run, detail=False) -> dict:
    out = {
        "id": str(run.id),
        "source": run.source,
        "label": run.label,
        "status": run.status,
        "error": run.error,
        "progress": run.progress or {},
        "counts": run.counts or {},
        "cancel_requested": run.cancel_requested,
        "is_demo": run.is_demo,
        "files": [{"name": f.get("name", ""), "size": f.get("size", 0)} for f in run.files or []],  # never storage keys
        "created_by": member_name(run.created_by) if run.created_by_id else "",
        "created_at": run.created_at.isoformat(),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "undone_at": _iso(run.undone_at),
        "can_undo": run.status in (ImportRun.DONE, ImportRun.FAILED, ImportRun.CANCELLED) and ImportedObject.objects.filter(run=run).exists(),
        "can_resume": run.status in (ImportRun.FAILED, ImportRun.CANCELLED) and bool(run.mapping),
    }
    if detail:
        out["preview"] = run.preview or {}
        out["mapping"] = run.mapping or {}
    return out

