"""Reading a standard Slack workspace export (Settings > Import/Export Data > Export).

Layout (optionally inside one top folder):

- ``users.json``: people (``id``, ``name``, ``real_name``, ``profile.email``, ``is_bot``)
- ``channels.json``: public channels (``id``, ``name``, ``members``, ``is_archived``)
- ``groups.json``: private channels; ``dms.json`` and ``mpims.json``: direct messages (only in
  exports that include them, and only imported when the admin opts in)
- one folder per channel (DMs: per conversation id) holding one JSON file per day.

Parsing rules: joins, leaves, topic and purpose changes and other housekeeping subtypes are
skipped; bot messages are skipped unless asked for; ``message_changed`` replaces the text of the
original (marked edited) and ``message_deleted`` drops it; thread replies keep their
``thread_ts``. Files are kept as links only (nothing is downloaded). Mentions, channel links and
Slack's ``<url|label>`` markup become plain text.
"""

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as dt_timezone

from imports.safezip import SafeZip

SKIP_SUBTYPES = frozenset({
    "channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name",
    "channel_archive", "channel_unarchive", "group_join", "group_leave", "group_topic",
    "group_purpose", "group_name", "group_archive", "group_unarchive", "pinned_item",
    "unpinned_item", "tombstone", "joiner_notification", "bot_add", "bot_remove",
    "reminder_add", "huddle_thread", "sh_room_created", "channel_convert_to_private",
    "channel_convert_to_public", "app_conversation_leave",
})
BOT_SUBTYPES = frozenset({"bot_message"})
TS = re.compile(r"^\d{9,11}(\.\d{1,6})?$")
DAY_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
SLACK_ID = re.compile(r"^[A-Z0-9]{2,20}$")
MARKUP = re.compile(r"<([^<>\n]{1,1000})>")
URL_SCHEMES = ("https://", "http://", "mailto:")
MAX_JSON = 50 * 1024 * 1024  # one daily file or one metadata file
MAX_TEXT = 7000


class SlackError(Exception):
    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code
        self.details = details or code


@dataclass
class SlackUser:
    id: str
    name: str
    email: str = ""
    is_bot: bool = False


@dataclass
class Channel:
    id: str
    name: str
    kind: str  # public | private | dm | group_dm
    folder: str
    members: list = field(default_factory=list)
    archived: bool = False


@dataclass
class Message:
    ts: str
    user: str
    user_name: str
    text: str
    thread_ts: str = ""
    edited: bool = False
    reactions: list = field(default_factory=list)  # [(name, count)]
    files: list = field(default_factory=list)  # [(name, https url or "")]

    @property
    def is_reply(self) -> bool:
        return bool(self.thread_ts) and self.thread_ts != self.ts

    @property
    def when(self) -> datetime:
        return ts_datetime(self.ts)


def ts_datetime(ts: str) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=dt_timezone.utc)


def _load_json(zf: SafeZip, name: str):
    try:
        return json.loads(zf.read(name, max_bytes=MAX_JSON).decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SlackError("bad_json", "A file in the export is not valid JSON") from exc


def _str(value, limit=200) -> str:
    return str(value).strip()[:limit] if isinstance(value, (str, int, float)) else ""


def _https(url) -> str:
    text = _str(url, 1000)
    return text if text.startswith("https://") else ""


class SlackExport:
    """The parts of an export we use. Raises ``SlackError("not_slack")`` when it isn't one."""

    def __init__(self, zf: SafeZip):
        self.zf = zf
        names = zf.names()
        self._names = set(names)
        roots = sorted(
            {n.rsplit("/", 1)[0] + "/" if "/" in n else "" for n in names if n.rsplit("/", 1)[-1] in ("channels.json", "users.json") and n.count("/") <= 1},
            key=len,
        )
        if not roots:
            raise SlackError("not_slack", "This is not a Slack export: users.json and channels.json are missing")
        self.root = roots[0]
        self.folders: dict[str, list[str]] = {}
        for name in names:
            if not name.startswith(self.root):
                continue
            rel = name[len(self.root):]
            parts = rel.split("/")
            if len(parts) == 2 and DAY_FILE.match(parts[1]):
                self.folders.setdefault(parts[0], []).append(name)
        for files in self.folders.values():
            files.sort()
        self.users = self._users()
        self.channels = self._channels()

    def _optional(self, filename):
        name = self.root + filename
        return _load_json(self.zf, name) if name in self._names else None

    def _users(self) -> dict[str, SlackUser]:
        out = {}
        for row in self._optional("users.json") or []:
            if not isinstance(row, dict) or not SLACK_ID.match(_str(row.get("id"), 20)):
                continue
            profile = row.get("profile") if isinstance(row.get("profile"), dict) else {}
            name = (
                _str(profile.get("real_name")) or _str(row.get("real_name")) or _str(profile.get("display_name")) or _str(row.get("name")) or "Slack user"
            )
            email = _str(profile.get("email"), 254).lower()
            out[row["id"]] = SlackUser(
                id=row["id"], name=name, email=email if "@" in email else "", is_bot=bool(row.get("is_bot") or row.get("is_app_user"))
            )
        return out

    def _channels(self) -> list[Channel]:
        out = []
        sources = (("channels.json", "public"), ("groups.json", "private"), ("dms.json", "dm"), ("mpims.json", "group_dm"))
        seen = set()
        for filename, kind in sources:
            for row in self._optional(filename) or []:
                if not isinstance(row, dict):
                    continue
                cid = _str(row.get("id"), 20)
                if not SLACK_ID.match(cid) or cid in seen:
                    continue
                seen.add(cid)
                members = [m for m in row.get("members") or [] if isinstance(m, str) and SLACK_ID.match(m)]
                if kind == "dm":
                    name = ""
                    folder = cid
                else:
                    name = _str(row.get("name"), 80) or cid
                    folder = name
                if folder not in self.folders and cid in self.folders:
                    folder = cid
                out.append(Channel(id=cid, name=name, kind=kind, folder=folder, members=members[:5000], archived=bool(row.get("is_archived"))))
        return out

    def channel(self, channel_id: str) -> Channel | None:
        return next((c for c in self.channels if c.id == channel_id), None)

    def user_name(self, user_id: str, fallback: str = "") -> str:
        user = self.users.get(user_id)
        return user.name if user else (fallback or "Slack user")

    def raw_messages(self, channel: Channel):
        for name in self.folders.get(channel.folder, []):
            data = _load_json(self.zf, name)
            if isinstance(data, list):
                yield from data

    def messages(self, channel: Channel, include_bots: bool = False) -> list[Message]:
        return parse_messages(self.raw_messages(channel), self, include_bots=include_bots)


def _reactions(raw) -> list:
    out = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        name = re.sub(r"[^a-z0-9_+\-]", "", _str(r.get("name"), 60).lower())
        count = r.get("count")
        if not isinstance(count, int):
            count = len(r.get("users") or []) if isinstance(r.get("users"), list) else 0
        if name and count > 0:
            out.append((name, count))
    return out[:20]


def _files(raw) -> list:
    out = []
    for f in raw if isinstance(raw, list) else []:
        if not isinstance(f, dict):
            continue
        name = _str(f.get("title") or f.get("name"), 150) or "file"
        out.append((name, _https(f.get("permalink")) or _https(f.get("url_private"))))
    return out[:20]


def parse_messages(raw, export=None, include_bots: bool = False) -> list[Message]:
    """Turn the raw daily records of one channel into messages, oldest first."""
    by_ts: dict[str, Message] = {}
    for m in raw:
        if not isinstance(m, dict) or (m.get("type") or "message") != "message":
            continue
        subtype = _str(m.get("subtype"), 40)
        if subtype == "message_changed":
            inner = m.get("message") if isinstance(m.get("message"), dict) else {}
            target = by_ts.get(_str(inner.get("ts"), 20))
            if target is not None and isinstance(inner.get("text"), str):
                target.text = inner["text"]
                target.edited = True
            continue
        if subtype == "message_deleted":
            by_ts.pop(_str(m.get("deleted_ts"), 20), None)
            continue
        if subtype in SKIP_SUBTYPES:
            continue
        is_bot = subtype in BOT_SUBTYPES or bool(m.get("bot_id"))
        user = _str(m.get("user"), 20)
        if not is_bot and export is not None and user in export.users and export.users[user].is_bot:
            is_bot = True
        if is_bot and not include_bots:
            continue
        ts = _str(m.get("ts"), 20)
        if not TS.match(ts):
            continue
        text = m.get("text") if isinstance(m.get("text"), str) else ""
        profile = m.get("user_profile") if isinstance(m.get("user_profile"), dict) else {}
        fallback = _str(profile.get("real_name")) or _str(profile.get("display_name")) or _str(m.get("username"))
        name = export.user_name(user, fallback) if export is not None else (fallback or "Slack user")
        files = _files(m.get("files"))
        if not text.strip() and not files:
            continue
        thread_ts = _str(m.get("thread_ts"), 20)
        by_ts[ts] = Message(
            ts=ts,
            user=user,
            user_name=name,
            text=text,
            thread_ts=thread_ts if TS.match(thread_ts) else "",
            edited=bool(m.get("edited")),
            reactions=_reactions(m.get("reactions")),
            files=files,
        )
    return sorted(by_ts.values(), key=lambda msg: float(msg.ts))


def convert_text(text: str, names: dict, channel_names: dict) -> str:
    """Slack markup to plain text. ``names``: Slack user id -> display name; ``channel_names``: id -> name."""

    def repl(match):
        inner = match.group(1)
        target, _, label = inner.partition("|")
        if target.startswith("@"):
            uid = target[1:]
            return "@" + (names.get(uid) or label or "someone")
        if target.startswith("#"):
            return "#" + (label or channel_names.get(target[1:]) or "channel")
        if target.startswith("!"):
            word = target[1:]
            if word in ("here", "channel", "everyone"):
                return "@" + word
            return label or ""
        if target.lower().startswith(URL_SCHEMES):
            url = target
            if url.lower().startswith("mailto:"):
                return label or url[len("mailto:"):]
            return f"{label} ({url})" if label and label != url else url
        return label or ""

    return html.unescape(MARKUP.sub(repl, text or ""))


def reactions_line(reactions) -> str:
    return "Reactions: " + ", ".join(f":{name}: {count}" for name, count in reactions) if reactions else ""


def snippet(text: str, limit: int = 80) -> str:
    one = " ".join((text or "").split())
    return one if len(one) <= limit else one[: limit - 1].rstrip() + "…"
