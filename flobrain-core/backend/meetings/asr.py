"""Speech to text with Whisper inside FloBrain (decided 2026-10-21; the multimodal service is not used).

``ASR_BACKEND``:
- ``http``: a self-hosted Whisper server with the OpenAI-style endpoint
  ``POST {ASR_BASE_URL}/v1/audio/transcriptions`` (for example faster-whisper in the ``whisper``
  compose service). ``ASR_MODEL`` names the model, ``ASR_API_KEY`` is optional.
- ``local``: faster-whisper inside the jobs worker (``pip install faster-whisper``).
Empty: transcription returns "not configured". Audio never leaves our infrastructure.
"""

import json
import os
import tempfile
import urllib.error
import urllib.request
import uuid

from django.conf import settings


class ASRError(Exception):
    pass


def _s(name, default=""):
    return (getattr(settings, name, "") or default).strip()


def configured() -> bool:
    backend = _s("ASR_BACKEND")
    if not backend:
        from meetings import demo

        return demo.asr()  # the demo answers with sample transcripts
    return (backend == "http" and bool(_s("ASR_BASE_URL"))) or backend == "local"


def _multipart(fields: dict, file_name: str, data: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _num(value) -> float:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return n if n == n and abs(n) < 1e7 else 0.0  # NaN and absurd values become 0


def _segments(raw) -> list[dict]:
    out = []
    for seg in raw if isinstance(raw, list) else []:
        if isinstance(seg, dict) and isinstance(seg.get("text"), str):
            out.append({"start": round(_num(seg.get("start")), 2), "end": round(_num(seg.get("end")), 2), "text": seg["text"].strip()[:2000]})
    return out


def transcribe(audio: bytes, file_name="audio.ogg", content_type="audio/ogg", language: str | None = None) -> dict:
    """Returns {"text", "segments": [{start, end, text}], "language"}."""
    backend = _s("ASR_BACKEND")
    if backend == "local":
        return _local(audio, file_name, language)
    if backend != "http" or not _s("ASR_BASE_URL"):
        raise ASRError("not_configured")
    fields = {"model": _s("ASR_MODEL", "Systran/faster-whisper-large-v3"), "response_format": "verbose_json"}
    if language:
        fields["language"] = language
    body, ctype = _multipart(fields, file_name, audio, content_type)
    headers = {"Content-Type": ctype}
    if _s("ASR_API_KEY"):
        headers["Authorization"] = f"Bearer {_s('ASR_API_KEY')}"
    request = urllib.request.Request(f"{_s('ASR_BASE_URL').rstrip('/')}/v1/audio/transcriptions", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=int(getattr(settings, "ASR_TIMEOUT", 1800) or 1800)) as response:
            data = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise ASRError(f"http_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise ASRError("unavailable") from exc
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str):
        raise ASRError("bad_response")
    return {"text": text.strip(), "segments": _segments(data.get("segments")), "language": str(data.get("language") or "")[:8]}


def transcribe_file(path: str, file_name="audio.ogg", content_type="audio/ogg", language: str | None = None) -> dict:
    """Same as ``transcribe`` but streams the audio from disk (meeting recordings can be hundreds of MB)."""
    backend = _s("ASR_BACKEND")
    if backend == "local":
        return _local_path(path, language)
    if backend != "http" or not _s("ASR_BASE_URL"):
        raise ASRError("not_configured")
    boundary = uuid.uuid4().hex
    fields = {"model": _s("ASR_MODEL", "Systran/faster-whisper-large-v3"), "response_format": "verbose_json"}
    if language:
        fields["language"] = language
    head = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items())
    head += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{os.path.basename(file_name)}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    with tempfile.TemporaryFile() as body:
        body.write(head)
        with open(path, "rb") as audio:
            while chunk := audio.read(1 << 20):
                body.write(chunk)
        body.write(tail)
        size = body.tell()
        body.seek(0)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(size)}
        if _s("ASR_API_KEY"):
            headers["Authorization"] = f"Bearer {_s('ASR_API_KEY')}"
        request = urllib.request.Request(f"{_s('ASR_BASE_URL').rstrip('/')}/v1/audio/transcriptions", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=int(getattr(settings, "ASR_TIMEOUT", 1800) or 1800)) as response:
                data = json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            raise ASRError(f"http_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise ASRError("unavailable") from exc
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str):
        raise ASRError("bad_response")
    return {"text": text.strip(), "segments": _segments(data.get("segments")), "language": str(data.get("language") or "")[:8]}


def _local_path(path: str, language):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ASRError("not_configured") from exc
    model = WhisperModel(_s("ASR_MODEL", "small"), device=_s("ASR_DEVICE", "auto"), compute_type=_s("ASR_COMPUTE_TYPE", "default"))
    segments, info = model.transcribe(path, language=language, vad_filter=True)
    rows = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
    return {"text": " ".join(r["text"] for r in rows).strip(), "segments": rows, "language": getattr(info, "language", "") or ""}


def _local(audio: bytes, file_name: str, language):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ASRError("not_configured") from exc
    model = WhisperModel(_s("ASR_MODEL", "small"), device=_s("ASR_DEVICE", "auto"), compute_type=_s("ASR_COMPUTE_TYPE", "default"))
    suffix = os.path.splitext(file_name)[1] or ".ogg"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(audio)
        tmp.flush()
        segments, info = model.transcribe(tmp.name, language=language, vad_filter=True)
        rows = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
    return {"text": " ".join(r["text"] for r in rows).strip(), "segments": rows, "language": getattr(info, "language", "") or ""}
