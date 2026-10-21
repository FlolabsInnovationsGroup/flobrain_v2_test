"""Word timings for a studio asset from the self-hosted speech-to-text (spec 8.7 step 2).

Whisper (``meetings.asr``) returns segments; the editor needs words, so each segment's
words are spread over the segment by length. Cuts are then validated against these
timings, so a cut never lands inside a word as the editor shows it.

In ``DEMO_MODE`` without a speech-to-text server, the asset gets the bundled demo
transcript (it says it is a demo recording), fitted to the asset's length.
"""

import logging
import os
import tempfile

from django.conf import settings

from jobs.queue import enqueue, register

logger = logging.getLogger(__name__)


def _real_asr() -> bool:
    from meetings import asr

    return bool((getattr(settings, "ASR_BACKEND", "") or "").strip()) and asr.configured()


def demo() -> bool:
    return bool(getattr(settings, "DEMO_MODE", False)) and not _real_asr()


def available() -> bool:
    return _real_asr() or demo()


def words_from_segments(segments) -> list[dict]:
    words = []
    for seg in segments or []:
        tokens = str(seg.get("text") or "").split()
        start, end = float(seg.get("start") or 0), float(seg.get("end") or 0)
        if not tokens or end <= start:
            continue
        if words and start < words[-1]["end"]:
            start = words[-1]["end"]
            if end <= start:
                continue
        letters = sum(len(t) for t in tokens)
        t = start
        for token in tokens:
            share = (end - start) * len(token) / letters
            words.append({"w": token[:100], "start": round(t, 3), "end": round(t + share * 0.95, 3)})
            t += share
    return words


def demo_words(duration) -> list[dict]:
    from content_studio import demo_media

    words = demo_media.source_words()
    total = words[-1]["end"] if words else 0
    if not words or not duration:
        return []
    scale = min(1.0, (float(duration) - 0.1) / total) if total else 1.0
    return [{**w, "start": round(w["start"] * scale, 3), "end": round(w["end"] * scale, 3)} for w in words]


def _save(asset, words, status):
    from content_studio.edl import EDLInvalid, validate_words
    from content_studio.models import MediaAsset

    try:
        cleaned = validate_words(words, asset.duration_seconds)
    except EDLInvalid:
        cleaned, status = [], "failed"
    MediaAsset.objects.filter(pk=asset.pk).update(transcript_words=cleaned, transcript_status=status)


def start(asset, language=None) -> dict:
    from content_studio.models import MediaAsset

    if demo():
        _save(asset, demo_words(asset.duration_seconds), "done")
        return {"ok": True, "demo": True}
    MediaAsset.objects.filter(pk=asset.pk).update(transcript_status="running")
    result = enqueue("content.transcribe", {"asset_id": str(asset.id), "language": language or ""})
    if isinstance(result, dict) and result.get("ok") is False and result.get("reason") == "unavailable":
        MediaAsset.objects.filter(pk=asset.pk).update(transcript_status="failed")
    return result if isinstance(result, dict) else {"ok": True}


@register("content.transcribe")
def transcribe_job(payload):
    from content_studio import storage
    from content_studio.models import MediaAsset
    from meetings import asr

    asset = MediaAsset.objects.filter(pk=payload.get("asset_id")).first()
    if asset is None:
        return {"ok": False, "reason": "gone"}
    suffix = os.path.splitext(asset.name)[1] or ".mp4"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            if not storage.download_to(asset.storage_key, tmp):
                raise asr.ASRError("missing_file")
            tmp.flush()
            out = asr.transcribe_file(tmp.name, asset.name, asset.content_type, payload.get("language") or None)
    except asr.ASRError as exc:
        MediaAsset.objects.filter(pk=asset.pk).update(transcript_status="failed")
        return {"ok": False, "reason": str(exc)}
    except Exception:  # noqa: BLE001 - recorded as failed, never re-raised into the queue loop
        logger.exception("transcribe %s failed", asset.id)
        MediaAsset.objects.filter(pk=asset.pk).update(transcript_status="failed")
        return {"ok": False, "reason": "error"}
    _save(asset, words_from_segments(out.get("segments")), "done")
    return {"ok": True}
