"""Edit decision lists: validation, versions, captions (Phase 9c).

Operations are structured data the worker turns into FFmpeg arguments; no
free-form filter strings are accepted. Cut and keep boundaries may not fall
inside a word when the asset has a transcript.

Keep ranges play in the order they are listed (so segments can be reordered);
without keeps the whole source plays. Cuts remove time from whatever is kept.
"""

import bisect

from django.db import IntegrityError, transaction

from content_studio.models import EditDecisionList

MAX_OPS = 2000
ASPECTS = {"9:16", "1:1", "16:9"}
POSITIONS = {"top", "bottom", "center", "top_left", "top_right", "bottom_left", "bottom_right"}
LANG_OK = set("abcdefghijklmnopqrstuvwxyz-")


class EDLInvalid(ValueError):
    pass


def _num(op, key, low=0.0, high=None):
    value = op.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise EDLInvalid(f"{op.get('op')}.{key} must be a number")
    value = float(value)
    if value < low or (high is not None and value > high):
        raise EDLInvalid(f"{op.get('op')}.{key} is out of range")
    return value


def mid_word(words, t) -> bool:
    """True when ``t`` falls strictly inside a word. Words are sorted by start (validated),
    so this is a binary search plus a short look-back for overlapping words."""
    if not words:
        return False
    starts = _starts(words)
    i = bisect.bisect_left(starts, t) - 1
    for j in range(i, max(i - 4, -1), -1):
        if words[j]["start"] < t < words[j]["end"]:
            return True
    return False


_STARTS_CACHE: dict = {}


def _starts(words):
    key = id(words)
    cached = _STARTS_CACHE.get(key)
    if cached is not None and cached[0] is words:
        return cached[1]
    starts = [w["start"] for w in words]
    _STARTS_CACHE.clear()  # one transcript at a time; keeps memory bounded
    _STARTS_CACHE[key] = (words, starts)
    return starts


def words_inside(words, start, end):
    """Words fully or partly inside [start, end]."""
    starts = _starts(words)
    lo = max(bisect.bisect_left(starts, start) - 4, 0)
    hi = bisect.bisect_right(starts, end)
    return [w for w in words[lo:hi] if w["end"] > start and w["start"] < end]


def validate_words(words, duration):
    if not isinstance(words, list) or len(words) > 200_000:
        raise EDLInvalid("words must be a list (at most 200000)")
    out, last = [], 0.0
    for i, w in enumerate(words):
        if not isinstance(w, dict) or not isinstance(w.get("w"), str) or not 0 < len(w["w"]) <= 100:
            raise EDLInvalid(f"word {i} needs text")
        start, end = w.get("start"), w.get("end")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (start, end)):
            raise EDLInvalid(f"word {i} needs start and end")
        if start < last - 0.001 or end < start or (duration and end > duration + 0.5):
            raise EDLInvalid(f"word {i} timing is out of order or past the end")
        last = start
        item = {"w": w["w"], "start": round(float(start), 3), "end": round(float(end), 3)}
        if isinstance(w.get("speaker"), str):
            item["speaker"] = w["speaker"][:20]
        out.append(item)
    return out


def validate_operations(project, operations):
    """Return cleaned operations or raise EDLInvalid."""
    if not isinstance(operations, list) or len(operations) > MAX_OPS:
        raise EDLInvalid(f"operations must be a list of at most {MAX_OPS}")
    assets = {str(a.id): a for a in project.source_assets.all()}
    music_ok = {str(a.id) for a in project.source_assets.filter(kind="audio")}
    out = []
    for op in operations:
        if not isinstance(op, dict):
            raise EDLInvalid("each operation must be an object")
        kind = op.get("op")
        if kind in ("cut", "keep"):
            asset = assets.get(str(op.get("asset")))
            if asset is None:
                raise EDLInvalid(f"{kind}.asset must be one of the project's sources")
            limit = asset.duration_seconds or 0
            start, end = _num(op, "start", 0, limit), _num(op, "end", 0, limit)
            if end <= start:
                raise EDLInvalid(f"{kind} needs end after start")
            words = asset.transcript_words or []
            if words and (mid_word(words, start) or mid_word(words, end)):
                raise EDLInvalid(f"{kind} {start}-{end} falls inside a word")
            item = {"op": kind, "asset": str(asset.id), "start": round(start, 3), "end": round(end, 3)}
            if isinstance(op.get("reason"), str):
                item["reason"] = op["reason"][:40]
            if op.get("by") in ("ai", "user"):
                item["by"] = op["by"]
            out.append(item)
        elif kind == "captions":
            lang = str(op.get("language") or "en").lower()
            if not 2 <= len(lang) <= 8 or not set(lang) <= LANG_OK:
                raise EDLInvalid("captions.language must be a language code")
            out.append({"op": "captions", "language": lang, "burn_in": bool(op.get("burn_in", True))})
        elif kind == "reframe":
            if op.get("aspect") not in ASPECTS:
                raise EDLInvalid("reframe.aspect must be 9:16, 1:1 or 16:9")
            item = {"op": "reframe", "aspect": op["aspect"], "mode": "manual" if op.get("crop") else "auto"}
            if op.get("crop"):
                crop = op["crop"]
                if not isinstance(crop, dict):
                    raise EDLInvalid("reframe.crop must be an object")
                item["crop"] = {k: _num(crop | {"op": "crop"}, k, 0, 1) for k in ("x", "y", "w", "h")}
            out.append(item)
        elif kind == "overlay":
            text = op.get("text")
            if op.get("kind") not in ("text", "logo") or (op.get("kind") == "text" and not isinstance(text, str)):
                raise EDLInvalid("overlay needs kind text (with text) or logo")
            if isinstance(text, str) and len(text) > 200:
                raise EDLInvalid("overlay.text is at most 200 characters")
            position = op.get("position") or "bottom"
            if position not in POSITIONS:
                raise EDLInvalid("overlay.position is not known")
            start, end = _num(op, "start"), _num(op, "end")
            if end <= start:
                raise EDLInvalid("overlay needs end after start")
            out.append(
                {"op": "overlay", "kind": op["kind"], "text": text or "", "position": position, "start": start, "end": end}
            )
        elif kind in ("intro", "outro"):
            out.append({"op": kind})
        elif kind == "music":
            if str(op.get("asset")) not in music_ok:
                raise EDLInvalid("music.asset must be one of the project's audio sources")
            out.append({"op": "music", "asset": str(op["asset"]), "volume": _num(op, "volume", 0, 1)})
        else:
            raise EDLInvalid(f"unknown operation {kind!r}")
    return out


def latest(project):
    return project.edls.order_by("-version").first()


def save_version(project, operations, user, kind=EditDecisionList.BY_USER, note="", base_version=None):
    """Append a new version. ``base_version`` guards against overwriting someone else's edit."""
    with transaction.atomic():
        current = project.edls.select_for_update().order_by("-version").first()
        current_version = current.version if current else 0
        if base_version is not None and int(base_version) != current_version:
            raise EDLInvalid(f"stale: the latest version is {current_version}")
        try:
            return EditDecisionList.objects.create(
                org=project.org,
                project=project,
                version=current_version + 1,
                operations=operations,
                created_by_kind=kind,
                created_by=user,
                note=note[:200],
            )
        except IntegrityError as exc:
            raise EDLInvalid("stale: another edit landed first") from exc


def kept_ranges(asset, operations):
    """Source ranges that survive the edit, for one asset, in playing order (keeps as listed)."""
    duration = asset.duration_seconds or 0
    ops = [o for o in operations if o.get("asset") == str(asset.id)]
    keeps = [(o["start"], o["end"]) for o in ops if o["op"] == "keep"]
    ranges = keeps or [(0.0, duration)]
    for cut in sorted((o["start"], o["end"]) for o in ops if o["op"] == "cut"):
        next_ranges = []
        for a, b in ranges:
            if cut[1] <= a or cut[0] >= b:
                next_ranges.append((a, b))
                continue
            if cut[0] > a:
                next_ranges.append((a, cut[0]))
            if cut[1] < b:
                next_ranges.append((cut[1], b))
        ranges = next_ranges
    return ranges


def captions(asset, operations, fmt="srt", max_chars=42, max_seconds=3.0):
    """Caption cues on the **edited** timeline, from the transcript."""
    ranges = kept_ranges(asset, operations)
    offsets, total = [], 0.0
    for a, b in ranges:
        offsets.append((a, b, total))  # output offset follows the playing order
        total += b - a
    offsets.sort(key=lambda r: r[0])  # lookups by source time
    range_starts = [a for a, _, _ in offsets]

    def place(start, end):
        """Output times of a word that lies inside one kept range, else None."""
        i = bisect.bisect_right(range_starts, start) - 1
        if i >= 0:
            a, b, off = offsets[i]
            if a <= start and end <= b:
                return off + (start - a), off + (end - a)
        return None

    placed = []
    for w in asset.transcript_words or []:
        spot = place(w["start"], w["end"])
        if spot is not None:
            placed.append((spot[0], spot[1], w["w"]))
    placed.sort(key=lambda x: x[0])

    cues, current = [], []
    for start, end, text in placed:
        if current and (
            len(" ".join(x[0] for x in current) + " " + text) > max_chars or end - current[0][1] > max_seconds
        ):
            cues.append(current)
            current = []
        current.append((text, start, end))
    if current:
        cues.append(current)

    def stamp(t, sep):
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"

    lines = ["WEBVTT", ""] if fmt == "vtt" else []
    sep = "." if fmt == "vtt" else ","
    for n, cue in enumerate(cues, start=1):
        if fmt == "srt":
            lines.append(str(n))
        lines.append(f"{stamp(cue[0][1], sep)} --> {stamp(cue[-1][2], sep)}")
        lines.append(" ".join(x[0] for x in cue))
        lines.append("")
    return "\n".join(lines)
