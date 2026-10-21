"""Short-audio Whisper calls for voice notes (W7). Same server and settings as ``meetings.asr``.

``meetings.asr.transcribe`` has no ``prompt`` and waits up to ``ASR_TIMEOUT`` (meeting length).
Voice notes are at most five minutes, so this adds:

- ``prompt``: Whisper's initial text, used to steer Arabic dialect spelling (Egyptian, Gulf);
- a shorter timeout (``VOICE_ASR_TIMEOUT``, default 180 s);
- the clip ``duration`` from ``verbose_json`` when the server sends it.

Only the configured ``ASR_BASE_URL`` is called (the org's own Whisper server). Nothing here
runs in tests or the demo: callers check ``meetings.demo.asr()`` first and tests mock
``urllib.request.urlopen``.
"""

import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from meetings.asr import ASRError, _multipart, _num, _s, _segments


def configured() -> bool:
    """A real Whisper backend is set (the demo stand-in does not count here)."""
    backend = _s("ASR_BACKEND")
    return (backend == "http" and bool(_s("ASR_BASE_URL"))) or backend == "local"


def _timeout() -> int:
    try:
        return max(5, int(getattr(settings, "VOICE_ASR_TIMEOUT", 180) or 180))
    except (TypeError, ValueError):
        return 180


def _endpoint() -> str:
    base = _s("ASR_BASE_URL").rstrip("/")
    parts = urllib.parse.urlsplit(base)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.username or parts.password:
        raise ASRError("not_configured")
    return f"{base}/v1/audio/transcriptions"


def _result(data) -> dict:
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str):
        raise ASRError("bad_response")
    segments = _segments(data.get("segments"))
    duration = _num(data.get("duration")) or (segments[-1]["end"] if segments else 0.0)
    return {"text": text.strip(), "segments": segments, "language": str(data.get("language") or "")[:16], "duration": duration}


def transcribe(audio: bytes, file_name="voice.webm", content_type="audio/webm", language=None, prompt=None) -> dict:
    """Returns {"text", "segments", "language", "duration"}. Raises ``ASRError``."""
    backend = _s("ASR_BACKEND")
    if backend == "local":
        return _local(audio, file_name, language, prompt)
    if backend != "http" or not _s("ASR_BASE_URL"):
        raise ASRError("not_configured")
    fields = {"model": _s("ASR_MODEL", "Systran/faster-whisper-large-v3"), "response_format": "verbose_json"}
    if language:
        fields["language"] = language
    if prompt:
        fields["prompt"] = prompt[:800]
    body, ctype = _multipart(fields, os.path.basename(file_name) or "voice", audio, content_type)
    headers = {"Content-Type": ctype}
    if _s("ASR_API_KEY"):
        headers["Authorization"] = f"Bearer {_s('ASR_API_KEY')}"
    request = urllib.request.Request(_endpoint(), data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_timeout()) as response:
            data = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise ASRError(f"http_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise ASRError("unavailable") from exc
    return _result(data)


def _local(audio: bytes, file_name: str, language, prompt):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ASRError("not_configured") from exc
    model = WhisperModel(_s("ASR_MODEL", "small"), device=_s("ASR_DEVICE", "auto"), compute_type=_s("ASR_COMPUTE_TYPE", "default"))
    suffix = os.path.splitext(file_name)[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:  # removed on close
        tmp.write(audio)
        tmp.flush()
        segments, info = model.transcribe(tmp.name, language=language, initial_prompt=prompt or None, vad_filter=True)
        rows = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
    return {
        "text": " ".join(r["text"] for r in rows).strip(),
        "segments": rows,
        "language": getattr(info, "language", "") or "",
        "duration": float(getattr(info, "duration", 0) or (rows[-1]["end"] if rows else 0)),
    }
