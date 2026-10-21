"""Voice notes in rooms and buddy chat (W7, flag ``voice_notes``).

Upload → validate (size, magic bytes, duration) → private storage → ``RoomMessage(kind="voice")``
plus a ``VoiceNote`` (pending) → a job sends the audio to the org's own Whisper server
(``meetings.voice_asr``, the same ``ASR_*`` settings as meeting transcripts) with an Arabic
dialect hint → the transcript becomes the message body → readers get it translated into their
language through ``rooms.translation.translate_page`` (cached per language in
``MessageTranslation``).

Public entry point for other apps (the channels app, for inbound WhatsApp and Telegram voice):
``transcribe_bytes(org, data, mime) -> (text, language)``. It raises ``VoiceError``.

In the demo (``DEMO_MODE`` without ``ASR_BACKEND``) transcription answers with labelled demo
transcripts (Egyptian Arabic, Gulf Arabic, English). Nothing here touches the network in tests.
"""

import io
import logging
import math
import re
import struct
import wave

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from jobs.queue import enqueue, register
from rooms.models import RoomMessage, VoiceNote

logger = logging.getLogger(__name__)

JOB = "rooms.voice_transcribe"
MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 300
DURATION_SLACK = 1.0  # containers round; a 5:00 recording may read 300.02 s

# Declared type → container family. The family must match the magic bytes.
MIME_FAMILY = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "application/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/m4a": "mp4",
    "audio/x-m4a": "mp4",
    "video/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
}
FAMILY = {  # family → (content type we store and serve, file extension)
    "webm": ("audio/webm", "webm"),
    "ogg": ("audio/ogg", "ogg"),
    "mp4": ("audio/mp4", "m4a"),
    "mp3": ("audio/mpeg", "mp3"),
}
MP4_BRANDS = {b"M4A ", b"M4B ", b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"dash", b"3gp4", b"3gp5", b"3g2a", b"avc1"}

GULF = ("ar-SA", "ar-AE", "ar-KW", "ar-QA", "ar-BH", "ar-OM")
HINT_RE = re.compile(r"^[a-z]{2}(?:-[A-Za-z]{2})?$")

# Whisper's initial text ("prompt") steers spelling toward the dialect people actually speak.
DIALECT_PROMPTS = {
    "ar-EG": "إزيك؟ أنا كويس الحمد لله. بص بقى، أنا عايز أقولك إن الموضوع ده لازم يخلص النهارده، ماشي؟ تمام كده.",
    "gulf": "شلونك؟ زين الحمد لله. اسمع، أبي أقول لك إن هالشي لازم يخلص اليوم إن شاء الله. وايد زين، يعطيك العافية.",
}

DEMO_LABEL = "Demo transcript"
DEMO_TRANSCRIPTS = {
    "ar-EG": {
        "text": "صباح الخير يا جماعة. أنا لسه مخلصة الشاشات الجديدة بتاعة التسجيل، وعايزة حد يراجعها النهارده لو ينفع. لو في أي حاجة مش واضحة قولولي وأنا أظبطها على طول.",
        "seconds": 14.0,
        "translations": {
            "en": "Good morning, everyone. I just finished the new sign-up screens, and I'd like someone to review them today if possible. If anything is unclear, tell me and I'll fix it right away.",
        },
    },
    "ar-SA": {
        "text": "هلا والله. اسمعوا، العميل في دبي يبي نسخة تجريبية من التطبيق قبل الخميس. أبي واحد منكم يرسل له الرابط الحين، وإذا عنده ملاحظات نجمعها في مهمة وحدة.",
        "seconds": 12.0,
        "translations": {
            "en": "Hi, everyone. Listen, the client in Dubai wants a test build of the app before Thursday. I need one of you to send him the link now, and if he has feedback we'll collect it in one task.",
        },
    },
    "en": {
        "text": "Quick update on the launch. The Android login fix passed QA this morning, so the only thing left is the store screenshots. I'll check in with Sara after lunch and post the final timeline here.",
        "seconds": 15.0,
        "translations": {
            "ar": "تحديث سريع عن الإطلاق. إصلاح تسجيل الدخول على أندرويد اجتاز اختبار الجودة صباح اليوم، فلم يتبقَّ سوى لقطات المتجر. سأتواصل مع سارة بعد الغداء وأنشر الجدول النهائي هنا.",
        },
    },
}


class VoiceError(Exception):
    """``code`` is one of: empty, too_large, unsupported_type, type_mismatch, too_long,
    not_configured, unavailable, bad_response, http_<status>, no_speech, audio_missing."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


MESSAGES = {
    "empty": "The recording is empty.",
    "too_large": "Voice notes can be up to 10 MB.",
    "unsupported_type": "Send a WebM, Ogg, M4A or MP3 recording.",
    "type_mismatch": "The file does not match its type.",
    "too_long": "Voice notes can be up to 5 minutes.",
    "bad_duration": "duration must be a number of seconds.",
    "bad_language": "language must be a language code such as ar-EG.",
}


# ---------------------------------------------------------------- validation


def sniff(data: bytes) -> str | None:
    """The container from its magic bytes: webm, ogg, mp4, mp3 or None."""
    if len(data) < 12:
        return None
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm" if b"webm" in data[:128] else None
    if data[:4] == b"OggS":
        return "ogg"
    if data[4:8] == b"ftyp":
        brands = {data[8:12]} | {data[i : i + 4] for i in range(16, min(_u(data, 0, 4), 64), 4)}
        return "mp4" if brands & MP4_BRANDS else None
    if _mp3_first_frame(data) is not None:
        return "mp3"
    return None


def validate(data: bytes, mime: str | None, declared_duration=None, strict_mime=True) -> dict:
    """Check one recording. Returns {family, content_type, ext, duration} or raises ``VoiceError``.

    ``strict_mime``: the declared type must be one we accept (browser uploads). Channels pass
    False: an unknown type falls back to the magic bytes, a known one must still match them.
    """
    if not data:
        raise VoiceError("empty")
    if len(data) > MAX_BYTES:
        raise VoiceError("too_large")
    declared = (mime or "").split(";")[0].strip().lower()
    family = MIME_FAMILY.get(declared)
    if family is None and strict_mime:
        raise VoiceError("unsupported_type")
    found = sniff(data)
    if found is None:
        raise VoiceError("type_mismatch" if family else "unsupported_type")
    if family is not None and found != family:
        raise VoiceError("type_mismatch")
    seconds = duration_of(data, found)
    if seconds is None and declared_duration is not None:
        seconds = float(declared_duration)  # the container did not say; the recorder's own count
    if seconds is not None and seconds > MAX_SECONDS + DURATION_SLACK:
        raise VoiceError("too_long")
    content_type, ext = FAMILY[found]
    return {"family": found, "content_type": content_type, "ext": ext, "duration": round(seconds, 2) if seconds else 0.0}


def parse_declared_duration(value):
    if value in (None, ""):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise VoiceError("bad_duration") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise VoiceError("bad_duration")
    return seconds


def parse_hint(value) -> str:
    """``ar-EG``, ``ar-SA``, ``en``... or "" (detect). Region upper-cased."""
    text = str(value or "").strip()
    if not text:
        return ""
    if not HINT_RE.match(text):
        raise VoiceError("bad_language")
    base, _, region = text.partition("-")
    return f"{base.lower()}-{region.upper()}" if region else base.lower()


# ---------------------------------------------------------------- durations


def _u(data, off, n, little=False) -> int:
    return int.from_bytes(data[off : off + n], "little" if little else "big")


def duration_of(data: bytes, family: str) -> float | None:
    """Seconds read from the container, or None when it does not say."""
    try:
        seconds = {"ogg": _ogg_duration, "mp4": _mp4_duration, "mp3": _mp3_duration, "webm": _webm_duration}[family](data)
    except (IndexError, ValueError, struct.error, KeyError):
        return None
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _ogg_duration(data):
    rate = skip = 0
    head = data.find(b"OpusHead", 0, 8192)
    if head >= 0:
        rate, skip = 48000, _u(data, head + 10, 2, little=True)
    else:
        vorbis = data.find(b"\x01vorbis", 0, 8192)
        if vorbis >= 0:
            rate = _u(data, vorbis + 12, 4, little=True)
    if not rate:
        return None
    pos = len(data)
    for _ in range(256):  # the last page with a real position
        pos = data.rfind(b"OggS", 0, pos)
        if pos < 0 or pos + 14 > len(data):
            return None
        granule = int.from_bytes(data[pos + 6 : pos + 14], "little", signed=True)
        if granule > 0:
            return max(0.0, (granule - skip) / rate)
    return None


def _mp4_box_value(data, name, version_offsets):
    i = data.find(name)
    if i < 4 or i + 8 > len(data):
        return None
    version = data[i + 4]
    off, size = version_offsets[1 if version == 1 else 0]
    return i, version, _u(data, i + off, size)


def _mp4_duration(data):
    found = _mp4_box_value(data, b"mvhd", {0: (20, 4), 1: (28, 8)})
    if found is None:
        return None
    i, version, duration = found
    timescale = _u(data, i + (24 if version == 1 else 16), 4)
    if not timescale:
        return None
    if duration and duration not in (0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
        return duration / timescale
    mehd = _mp4_box_value(data, b"mehd", {0: (8, 4), 1: (8, 8)})
    if mehd is not None and mehd[2]:
        return mehd[2] / timescale
    # Fragmented recording (Safari): the last fragment's start time is a lower bound.
    mdhd = data.find(b"mdhd")
    tfdt = data.rfind(b"tfdt")
    if mdhd < 0 or tfdt < 0:
        return None
    media_scale = _u(data, mdhd + (24 if data[mdhd + 4] == 1 else 16), 4)
    base = _u(data, tfdt + 8, 8 if data[tfdt + 4] == 1 else 4)
    return base / media_scale if media_scale else None


_MP3_KBPS = {
    3: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],  # MPEG-1 layer III
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],  # MPEG-2 / 2.5 layer III
}
_MP3_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _mp3_header(data, off):
    if off + 4 > len(data) or data[off] != 0xFF or data[off + 1] & 0xE0 != 0xE0:
        return None
    version = (data[off + 1] >> 3) & 3
    layer = (data[off + 1] >> 1) & 3
    bitrate_idx = (data[off + 2] >> 4) & 0xF
    rate_idx = (data[off + 2] >> 2) & 3
    if version == 1 or layer != 1 or bitrate_idx in (0, 15) or rate_idx == 3:
        return None
    kbps = _MP3_KBPS[3 if version == 3 else 2][bitrate_idx]
    return {"version": version, "kbps": kbps, "rate": _MP3_RATES[version][rate_idx]}


def _mp3_first_frame(data):
    off = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        size = (data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14 | (data[8] & 0x7F) << 7 | (data[9] & 0x7F)
        off = 10 + size + (10 if data[5] & 0x10 else 0)
        for pos in range(off, min(off + 4096, len(data) - 4)):
            if _mp3_header(data, pos):
                return pos
        return None
    return 0 if _mp3_header(data, 0) else None


def _mp3_duration(data):
    off = _mp3_first_frame(data)
    if off is None:
        return None
    header = _mp3_header(data, off)
    samples = 1152 if header["version"] == 3 else 576
    window = data[off : off + 200]
    for tag in (b"Xing", b"Info"):
        i = window.find(tag)
        if i >= 0 and _u(window, i + 4, 4) & 1:
            return _u(window, i + 8, 4) * samples / header["rate"]
    if window[36:40] == b"VBRI":
        return _u(window, 50, 4) * samples / header["rate"]
    return (len(data) - off) * 8 / (header["kbps"] * 1000)


class _Stop(Exception):
    pass


def _vint(data, pos, keep_marker):
    if pos >= len(data) or data[pos] == 0:
        raise _Stop
    length = 9 - data[pos].bit_length()
    if pos + length > len(data):
        raise _Stop
    value = int.from_bytes(data[pos : pos + length], "big")
    if not keep_marker:
        value &= (1 << (7 * length)) - 1
    return value, length


_EBML_CONTAINERS = {0x18538067, 0x1549A966, 0x1F43B675, 0xA0}  # Segment, Info, Cluster, BlockGroup


def _webm_duration(data):
    """Info/Duration when the recorder wrote it; otherwise the last block's timestamp.

    Browser recorders stream WebM with unknown sizes and no Duration, so containers are read
    in place (their children follow) and every block's time is cluster time + block offset.
    """
    pos, scale, declared, cluster_time, last = 0, 1_000_000, None, 0, None
    for _ in range(500_000):
        if pos >= len(data):
            break
        try:
            eid, id_len = _vint(data, pos, True)
            size, size_len = _vint(data, pos + id_len, False)
        except _Stop:
            break
        body = pos + id_len + size_len
        if eid in _EBML_CONTAINERS:
            pos = body
            continue
        if size == (1 << (7 * size_len)) - 1:
            break  # unknown size outside a container: nothing more we can read
        end = body + size
        if eid == 0x2AD7B1:  # TimecodeScale
            scale = _u(data, body, size) or scale
        elif eid == 0x4489 and size in (4, 8) and end <= len(data):  # Duration (float)
            declared = struct.unpack(">f" if size == 4 else ">d", data[body:end])[0]
        elif eid == 0xE7:  # Cluster Timecode
            cluster_time = _u(data, body, size)
        elif eid in (0xA3, 0xA1):  # SimpleBlock, Block
            try:
                _, track_len = _vint(data, body, False)
            except _Stop:
                break
            if body + track_len + 2 <= len(data):
                offset = int.from_bytes(data[body + track_len : body + track_len + 2], "big", signed=True)
                stamp = cluster_time + offset
                last = stamp if last is None else max(last, stamp)
        pos = end
    if declared is not None and math.isfinite(declared) and declared > 0:
        return declared * scale / 1e9
    if last is not None:
        return last * scale / 1e9 + 0.02  # plus one Opus frame
    return None


# ---------------------------------------------------------------- language


LANGUAGE_NAMES = {
    "arabic": "ar", "english": "en", "turkish": "tr", "french": "fr", "portuguese": "pt", "spanish": "es",
    "german": "de", "italian": "it", "urdu": "ur", "hindi": "hi", "persian": "fa", "russian": "ru", "chinese": "zh",
}
_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})
_WORD = re.compile(r"[ء-ي]+")
EGYPTIAN_WORDS = {
    "ازيك", "ازيكم", "عايز", "عايزه", "عاوز", "عاوزه", "دلوقتي", "كده", "كدا", "ازاي", "بتاع", "بتاعه", "بتاعت",
    "النهارده", "اوي", "خالص", "بقي", "ماشي", "حاجه", "ده", "دي", "احنا", "ليه", "مخلص", "مخلصه", "اظبطها", "قولولي",
    "بص", "هنعمل", "جماعه", "ينفع", "لسه",
}
GULF_WORDS = {
    "شلون", "شلونك", "وايد", "زين", "ابي", "ابغي", "يبي", "يبغي", "الحين", "هالشي", "وش", "ايش", "شنو", "مب", "مو",
    "ترا", "باجر", "هلا", "حق", "وحده", "نبي", "تبي", "يعطيك", "العافيه",
}


def normalize_language(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[lowered]
    try:
        return parse_hint(text)
    except VoiceError:
        return ""


def guess_dialect(text: str) -> str:
    """ar-EG, ar-SA (Gulf) or plain ar, from words only one dialect uses."""
    words = {w.translate(_ALEF) for w in _WORD.findall(text or "")}
    egypt = len(words & EGYPTIAN_WORDS)
    gulf = len(words & GULF_WORDS)
    if egypt > gulf:
        return "ar-EG"
    if gulf > egypt:
        return "ar-SA"
    return "ar"


def is_gulf(code: str) -> bool:
    return code in GULF


def whisper_hints(hint: str) -> tuple[str | None, str | None]:
    """(language, prompt) for Whisper. Whisper takes a bare language code."""
    if not hint:
        return None, None
    base = hint.split("-")[0]
    if hint == "ar-EG":
        return "ar", DIALECT_PROMPTS["ar-EG"]
    if is_gulf(hint):
        return "ar", DIALECT_PROMPTS["gulf"]
    return base, None


def resolve_language(detected: str, hint: str, text: str) -> str:
    """The language we show: the dialect when Arabic, else what Whisper detected."""
    code = normalize_language(detected)
    if not code:
        arabic = sum(1 for ch in text or "" if "؀" <= ch <= "ۿ")
        code = "ar" if arabic and arabic * 2 >= len((text or "").replace(" ", "")) else (hint.split("-")[0] if hint else "")
    if code.split("-")[0] != "ar":
        return code.split("-")[0]
    if hint.startswith("ar-"):
        return hint
    return guess_dialect(text)


def default_hint(org=None, user=None) -> str:
    """Org setting ``voice_language_hint`` (e.g. ar-EG), else a dialect locale on the person."""
    for raw in ((org.settings or {}).get("voice_language_hint") if org is not None else "", getattr(user, "locale", "")):
        try:
            hint = parse_hint(raw)
        except VoiceError:
            continue
        if hint.startswith("ar-"):
            return hint
    return ""


# ---------------------------------------------------------------- transcription


def _demo_pick(hint: str, user=None, data: bytes = b"") -> str:
    if hint == "ar-EG" or (hint.startswith("ar") and not is_gulf(hint)):
        return "ar-EG"
    if is_gulf(hint):
        return "ar-SA"
    if hint:
        return "en"
    if user is not None:
        return "ar-EG" if str(getattr(user, "locale", "")).startswith("ar") else "en"
    return ("ar-EG", "ar-SA", "en")[sum(data[:64]) % 3]


def recognize(data: bytes, info: dict, hint: str = "", user=None) -> dict:
    """Whisper (or the demo stand-in). Returns {text, language, duration, demo}. Raises ``VoiceError``."""
    from meetings import demo as meeting_demo
    from meetings import voice_asr
    from meetings.asr import ASRError

    if not voice_asr.configured():
        if meeting_demo.asr():
            key = _demo_pick(hint, user, data)
            return {"text": DEMO_TRANSCRIPTS[key]["text"], "language": key, "duration": 0.0, "demo": True}
        raise VoiceError("not_configured")
    language, prompt = whisper_hints(hint)
    try:
        out = voice_asr.transcribe(
            data, file_name=f"voice.{info['ext']}", content_type=info["content_type"], language=language, prompt=prompt
        )
    except ASRError as exc:
        raise VoiceError(str(exc) or "unavailable") from exc
    return {"text": out["text"], "language": resolve_language(out.get("language"), hint, out["text"]), "duration": out.get("duration") or 0.0, "demo": False}


def transcribe_bytes(org, data: bytes, mime: str | None, hint: str = "") -> tuple[str, str]:
    """Transcribe one short recording for another app (channels: WhatsApp, Telegram).

    ``data`` is the raw audio (Ogg/Opus, WebM, M4A or MP3, up to 10 MB and 5 minutes),
    ``mime`` the sender's declared type (may be empty). Returns ``(text, language)`` where
    language is ``ar-EG``, ``ar-SA`` (Gulf), ``ar``, ``en``... Raises ``VoiceError`` with a code.
    Synchronous; nothing is stored. The caller decides whether the org may use it.
    """
    info = validate(data, mime, strict_mime=False)
    out = recognize(data, info, hint=parse_hint(hint) if hint else default_hint(org))
    text = (out["text"] or "").strip()
    if not text:
        raise VoiceError("no_speech")
    return text, out["language"]


# ---------------------------------------------------------------- room voice notes


def storage_key_for(note, ext) -> str:
    return f"voice/{note.org_id}/{note.message.room_id}/{note.id}.{ext}"


def create_room_voice_note(room, user, data: bytes, info: dict, hint: str = "") -> VoiceNote:
    """Store the audio and post the message; transcription starts after commit. Raises ``VoiceError``."""
    from content_studio import storage

    with transaction.atomic():
        message = RoomMessage.objects.create(room=room, author=user, body="", kind=RoomMessage.KIND_VOICE)
        note = VoiceNote.objects.create(
            org=room.org, message=message, content_type=info["content_type"], size_bytes=len(data),
            duration_seconds=info["duration"], language_hint=hint,
        )
        key = storage_key_for(note, info["ext"])
        if not storage.put_file(key, io.BytesIO(data), info["content_type"]):
            raise VoiceError("storage_unavailable")
        VoiceNote.objects.filter(pk=note.pk).update(storage_key=key)
        note.storage_key = key
    queue_transcription(note)
    return note


def queue_transcription(note) -> None:
    """Through the jobs queue when it runs; otherwise right after the request commits."""
    from meetings.pipeline import can_queue

    payload = {"voice_id": str(note.id)}
    if can_queue():
        transaction.on_commit(lambda: enqueue(JOB, payload))
    else:
        transaction.on_commit(lambda: transcribe_note(payload))


def _fail(note_id, code):
    VoiceNote.objects.filter(pk=note_id).update(status=VoiceNote.STATUS_FAILED, error=str(code)[:80])
    return {"ok": False, "reason": code}


@register(JOB)
def transcribe_note(payload):
    note_id = (payload or {}).get("voice_id")
    note = VoiceNote.objects.filter(pk=note_id, status=VoiceNote.STATUS_PENDING).select_related("message", "message__room", "message__author", "org").first()
    if note is None:
        return {"ok": False, "reason": "not_pending"}
    try:
        return _transcribe(note)
    except Exception as exc:  # noqa: BLE001 - a note must never stay pending for good
        logger.exception("voice note %s failed", note_id)
        return _fail(note_id, type(exc).__name__)


def _transcribe(note):
    from content_studio import storage

    if note.message.deleted_at:
        return _fail(note.pk, "deleted")
    data = storage.read_bytes(note.storage_key, MAX_BYTES) if note.storage_key else None
    if data is None and not note.is_demo:
        return _fail(note.pk, "audio_missing")
    family = next((f for f, (ctype, _) in FAMILY.items() if ctype == note.content_type), "webm")
    info = {"family": family, "content_type": note.content_type, "ext": FAMILY[family][1]}
    try:
        out = recognize(data or b"", info, hint=note.language_hint, user=note.message.author)
    except VoiceError as exc:
        return _fail(note.pk, exc.code)
    text = (out["text"] or "").strip()
    if not text:
        return _fail(note.pk, "no_speech")
    if out["duration"] and out["duration"] > MAX_SECONDS + DURATION_SLACK:
        return _fail(note.pk, "too_long")
    max_len = int(getattr(settings, "FLOBRAIN_V2", {}).get("ROOM_MESSAGE_MAX_LENGTH", 8000))
    with transaction.atomic():
        fields = {"transcript": text, "language": out["language"][:16], "status": VoiceNote.STATUS_DONE, "error": "", "is_demo": out["demo"]}
        if out["duration"] and not note.duration_seconds:
            fields["duration_seconds"] = round(float(out["duration"]), 2)
        if out["demo"] and not note.duration_seconds:
            fields["duration_seconds"] = DEMO_TRANSCRIPTS[out["language"]]["seconds"]
        updated = VoiceNote.objects.filter(pk=note.pk, status=VoiceNote.STATUS_PENDING).update(**fields)
        if not updated:
            return {"ok": False, "reason": "not_pending"}
        message = note.message
        message.body = text[:max_len]
        message.save(update_fields=["body", "updated_at"])  # a new version: any cached translation is stale
    # Rooms have no realtime push yet (``realtime`` answers "use polling"); readers see it on their next poll.
    return {"ok": True}


def retry(note) -> bool:
    """Queue a failed note again (its audio must still be stored)."""
    if note.status != VoiceNote.STATUS_FAILED or not note.storage_key:
        return False
    VoiceNote.objects.filter(pk=note.pk).update(status=VoiceNote.STATUS_PENDING, error="")
    note.status = VoiceNote.STATUS_PENDING
    queue_transcription(note)
    return True


def translations_for(notes, language: str, user, org, allow_calls: bool) -> dict:
    """{message_id: (text or None, error)} for done notes in another language than ``language``.

    Uses ``rooms.translation.translate_page`` (one call per message, cached per language and
    message version). With ``allow_calls`` False only cached translations are returned.
    """
    from rooms.translation import _cached, translate_page

    base = language.split("-")[0]
    wanted = [
        n.message for n in notes
        if n.status == VoiceNote.STATUS_DONE and (n.message.body or "").strip() and (n.language or "").split("-")[0] != base
    ]
    if not wanted:
        return {}
    if allow_calls:
        return translate_page(wanted, language, user, org)
    out = {}
    for message in wanted:
        text, _ = _cached(message, language)
        out[message.id] = (text, "") if text is not None else (None, "deferred")
    return out


def needs_translation_calls(notes, language: str) -> bool:
    from rooms.translation import _cached

    base = language.split("-")[0]
    for n in notes:
        if n.status == VoiceNote.STATUS_DONE and (n.message.body or "").strip() and (n.language or "").split("-")[0] != base:
            if _cached(n.message, language)[0] is None:
                return True
    return False


def payload(note, translation=None) -> dict:
    message = note.message
    data = {
        "id": str(note.id),
        "message": str(message.id),
        "room": str(message.room_id),
        "author": str(message.author_id) if message.author_id else None,
        "status": note.status,
        "error": note.error,
        "duration": note.duration_seconds,
        "content_type": note.content_type,
        "language": note.language,
        "transcript": message.body if note.status == VoiceNote.STATUS_DONE else "",
        "demo": note.is_demo,
        "audio_url": f"/orgs/{note.org_id}/rooms/{message.room_id}/voice/{note.id}/audio",
        "created_at": message.created_at.isoformat(),
        "translated": False,
    }
    if translation is not None:
        text, error = translation
        if text is not None and not error:
            data["translation"] = text
            data["translated"] = True
        else:
            data["translation_error"] = error or "provider_error"
    return data


# ---------------------------------------------------------------- demo audio


def demo_audio(seconds: float, seed: int = 0) -> bytes:
    """A soft, speech-paced tone (8 kHz WAV) standing in for a demo recording. No real voice."""
    rate = 8000
    frames = bytearray()
    total = int(rate * max(1.0, seconds))
    syllable = int(rate * 0.22)
    for i in range(total):
        n = i // syllable
        pause = (n + seed) % 7 == 6 or (n + seed) % 11 == 10
        within = (i % syllable) / syllable
        envelope = 0.0 if pause else math.sin(math.pi * within) ** 2
        pitch = 170 + 40 * math.sin((n + seed) * 1.7)
        sample = envelope * 0.35 * math.sin(2 * math.pi * pitch * i / rate)
        frames.append(int(128 + 127 * sample))
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))
    return out.getvalue()


# ---------------------------------------------------------------- cleanup


def _delete_audio(key):
    if not key:
        return
    from content_studio import storage

    try:
        storage.delete(key)
    except Exception:  # noqa: BLE001 - storage outages must not break deletes
        logger.warning("could not delete voice audio %s", key)


@receiver(post_save, sender=RoomMessage)
def _drop_audio_of_deleted_message(sender, instance, **kwargs):
    """A deleted voice message keeps no audio."""
    if instance.kind != RoomMessage.KIND_VOICE or not instance.deleted_at:
        return
    note = VoiceNote.objects.filter(message=instance).exclude(storage_key="").first()
    if note is not None:
        key = note.storage_key
        VoiceNote.objects.filter(pk=note.pk).update(storage_key="")
        transaction.on_commit(lambda: _delete_audio(key))


@receiver(post_delete, sender=VoiceNote)
def _drop_audio_of_deleted_note(sender, instance, **kwargs):
    key = instance.storage_key
    if key:
        transaction.on_commit(lambda: _delete_audio(key))
