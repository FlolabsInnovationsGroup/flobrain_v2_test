"""Demo model answers for Content Studio (``DEMO_AI`` only): clip suggestions, auto-edit cuts and
per-platform copy. Clips and cuts are computed from the asset's real word timings, so they pass
the same validation as a real model's answer (inside the media, on word boundaries, fillers only).
Every hook, reason and description says it is demo output."""

import json
import re

from brain.llm.demo_ai import _result

LINE = re.compile(r"^\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\]\s+(.*)$")
TRANSCRIPT = re.compile(r"<transcript>\n(.*)\n</transcript>", re.DOTALL)
SENTENCE_END = (".", "?", "!", "؟")


def _transcript(user):
    match = TRANSCRIPT.search(user or "")
    return match.group(1) if match else ""


def _asset_for(text):
    """The asset whose transcript the model was shown (demo data is small, so a scan is fine)."""
    from content_studio.ai import transcript_text
    from content_studio.models import MediaAsset

    if not text:
        return None
    for asset in MediaAsset.objects.exclude(transcript_words=[]).order_by("-created_at")[:200]:
        if transcript_text(asset) == text:
            return asset
    return None


def _sentences(words):
    out, current = [], []
    for w in words:
        current.append(w)
        if w["w"].endswith(SENTENCE_END):
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def _lines(text):
    rows = []
    for line in text.splitlines():
        match = LINE.match(line.strip())
        if match:
            rows.append((float(match.group(1)), float(match.group(2)), match.group(3)))
    return rows


def _hook(words):
    text = " ".join(w["w"] for w in words[:12]).strip(" ,")
    return f"(Demo) {text[:150]}"


def clips(user):
    text = _transcript(user)
    asset = _asset_for(text)
    found = []
    if asset is not None:
        sentences = _sentences(asset.transcript_words)
        # Windows of whole sentences, 8 to 60 seconds long, scored by position and length.
        for i in range(len(sentences)):
            span = []
            for sentence in sentences[i:]:
                span += sentence
                length = span[-1]["end"] - span[0]["start"]
                if length >= 8:
                    break
            length = span[-1]["end"] - span[0]["start"] if span else 0
            if 8 <= length <= 60:
                found.append((span[0]["start"], span[-1]["end"], span))
    else:
        lines = _lines(text)
        for i in range(len(lines)):
            j = i
            while j < len(lines) and lines[j][1] - lines[i][0] < 8:
                j += 1
            if j < len(lines) and lines[j][1] - lines[i][0] <= 60:
                found.append((lines[i][0], lines[j][1], [{"w": w} for line in lines[i : j + 1] for w in line[2].split()]))
    picked, last_end = [], -1.0
    for start, end, span in found:
        if start >= last_end:  # no overlapping clips
            picked.append((start, end, span))
            last_end = end
    reasons = [
        "Demo suggestion: a clear announcement with a date, good as a hook.",
        "Demo suggestion: opens with context and ends on a result.",
        "Demo suggestion: a concrete detail viewers can repeat.",
    ]
    out = []
    for n, (start, end, span) in enumerate(sorted(picked, key=lambda c: -(c[1] - c[0]))[:5]):
        out.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "hook_text": _hook(span),
                "score": round(0.88 - n * 0.09, 2),
                "reason": reasons[n % len(reasons)],
            }
        )
    return {"clips": out}


def cuts(user):
    from content_studio.ai import FILLERS

    text = _transcript(user)
    asset = _asset_for(text)
    out = []
    if asset is not None:
        words = asset.transcript_words
        for i, w in enumerate(words):
            if w["w"].strip(".,!?؟").lower() in FILLERS and w["end"] - w["start"] <= 2:
                out.append({"start": w["start"], "end": w["end"], "reason": "filler"})
            if i + 1 < len(words) and words[i + 1]["start"] - w["end"] > 0.8:
                out.append({"start": round(w["end"] + 0.05, 3), "end": round(words[i + 1]["start"] - 0.05, 3), "reason": "silence"})
    else:
        lines = _lines(text)
        for (_, end, _), (start, _, _) in zip(lines, lines[1:]):
            if start - end > 0.8:
                out.append({"start": round(end + 0.05, 3), "end": round(start - 0.05, 3), "reason": "silence"})
    return {"cuts": out}


STYLE = {
    "youtube": ("{title}: the full update", "{lead} Watch to the end for the launch date. (Demo copy)", ["launch", "productupdate", "NileLabs"]),
    "linkedin": ("{title}", "We have news to share. {lead} Thank you to everyone who tested the app with us. (Demo copy)", ["product", "launch", "teamwork"]),
    "tiktok": ("{title} in 30 seconds", "{lead} (Demo copy)", ["launch", "app", "behindthescenes"]),
    "instagram": ("{title}", "{lead} Link in bio. (Demo copy)", ["launchday", "mobileapp", "NileLabs"]),
    "facebook": ("{title}", "{lead} Tell us what you want to see next. (Demo copy)", ["NileLabs", "launch"]),
    "x": ("{title}", "{lead} (Demo copy)", ["launch"]),
}


def copy(user):
    lines = (user or "").splitlines()
    platforms_line = next((l for l in lines if l.startswith("Platforms:")), "Platforms: youtube")
    title_line = next((l for l in lines if l.startswith("Project title:")), "Project title: Our video")
    platforms = [p.strip() for p in platforms_line.split(":", 1)[1].split(",") if p.strip()]
    title = title_line.split(":", 1)[1].strip().replace("&lt;", "<")[:80] or "Our video"
    words = " ".join(l.split("] ", 1)[1] for l in _transcript(user).splitlines() if "] " in l).split()
    lead = " ".join(words[:24]).strip()
    lead = (lead + "...") if lead else "A short update from our team."
    out = {}
    for p in platforms:
        t, d, tags = STYLE.get(p, STYLE["youtube"])
        out[p] = {"title": t.format(title=title)[:100], "description": d.format(lead=lead), "hashtags": tags}
    return {"copy": out}


def handle(system, user, messages, tools):
    from content_studio import ai

    if system == ai.SYSTEM_CLIPS:
        return _result(json.dumps(clips(user)))
    if system == ai.SYSTEM_CUTS:
        return _result(json.dumps(cuts(user)))
    if system == ai.SYSTEM_COPY:
        return _result(json.dumps(copy(user)))
    return None
