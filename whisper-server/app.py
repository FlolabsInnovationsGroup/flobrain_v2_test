"""FloBrain's own speech-to-text service (Whisper via faster-whisper), OpenAI-style API.

    POST /v1/audio/transcriptions   multipart: file, model (ignored: one model per server),
                                    language (optional), response_format=json|verbose_json
    GET  /health

Settings: WHISPER_MODEL (default large-v3; "small" for CPU), WHISPER_DEVICE (auto|cpu|cuda),
WHISPER_COMPUTE_TYPE (default auto), WHISPER_API_KEY (bearer token, required unless
WHISPER_ALLOW_NO_KEY=1 for a private test box), PORT (8000), MAX_UPLOAD_MB (600),
MAX_CONCURRENT_UPLOADS (2). The body streams to a temp file (no full copy in memory), the audio part
is cut out of it, transcribed and deleted; nothing is kept.
"""

import hmac
import json
import mmap
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "600")) << 20
API_KEY = os.environ.get("WHISPER_API_KEY", "")
ALLOW_NO_KEY = os.environ.get("WHISPER_ALLOW_NO_KEY", "") == "1"
_model = None
_lock = threading.Lock()  # one transcription at a time per process; run more replicas for more
_uploads = threading.BoundedSemaphore(int(os.environ.get("MAX_CONCURRENT_UPLOADS", "2")))
_BOUNDARY = re.compile(r'boundary="?([^";]{1,200})"?')


def model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            os.environ.get("WHISPER_MODEL", "large-v3"),
            device=os.environ.get("WHISPER_DEVICE", "auto"),
            compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "auto"),
        )
    return _model


_NAME = re.compile(rb'name="([^"]{1,64})"')
_FILENAME = re.compile(rb'filename="([^"]{0,200})"')


def parse_multipart_file(content_type: str, body_file, audio_out) -> tuple[dict, str | None]:
    """Parse a multipart body stored in ``body_file`` without loading it: small fields come back as
    text, the ``file`` part is copied into ``audio_out``. Returns (fields, filename or None)."""
    match = _BOUNDARY.search(content_type)
    if not match:
        return {}, None
    delimiter = b"--" + match.group(1).encode()
    fields, filename = {}, None
    size = os.fstat(body_file.fileno()).st_size
    if size == 0:
        return {}, None
    with mmap.mmap(body_file.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        pos = mm.find(delimiter)
        while pos != -1:
            start = pos + len(delimiter)
            if mm[start:start + 2] == b"--":
                break
            head_end = mm.find(b"\r\n\r\n", start)
            nxt = mm.find(b"\r\n" + delimiter, head_end + 4) if head_end != -1 else -1
            if head_end == -1 or nxt == -1:
                break
            headers = mm[start:head_end]
            name = _NAME.search(headers)
            data_start, data_end = head_end + 4, nxt
            if name and name.group(1) == b"file":
                fn = _FILENAME.search(headers)
                filename = fn.group(1).decode("utf-8", "ignore") if fn else "audio.ogg"
                for offset in range(data_start, data_end, 1 << 20):
                    audio_out.write(mm[offset:min(offset + (1 << 20), data_end)])
            elif name and data_end - data_start <= 4096:
                fields[name.group(1).decode("utf-8", "ignore")] = mm[data_start:data_end].decode("utf-8", "ignore")
            pos = nxt + 2
    return fields, filename


def transcribe(path: str, language):
    with _lock:
        segments, info = model().transcribe(path, language=language or None, vad_filter=True)
        rows = [{"id": i, "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for i, s in enumerate(segments)]
    return {"text": " ".join(r["text"] for r in rows).strip(), "language": getattr(info, "language", "") or "", "duration": getattr(info, "duration", None), "segments": rows}


class Handler(BaseHTTPRequestHandler):
    server_version = "flobrain-whisper"

    def _send(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # no audio details in logs
        pass

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not_found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/audio/transcriptions":
            return self._send(404, {"error": "not_found"})
        if not API_KEY and not ALLOW_NO_KEY:
            return self._send(503, {"error": "not_configured", "details": "Set WHISPER_API_KEY"})
        if API_KEY and not hmac.compare_digest(self.headers.get("Authorization", "").encode(), f"Bearer {API_KEY}".encode()):
            return self._send(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, {"error": "bad length"})
        if length <= 0:
            return self._send(400, {"error": "empty body"})
        if length > MAX_BYTES:
            return self._send(413, {"error": "too_large"})
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            return self._send(400, {"error": "multipart required"})
        if not _uploads.acquire(timeout=1):
            return self._send(429, {"error": "busy"})
        try:
            with tempfile.TemporaryFile() as body, tempfile.NamedTemporaryFile(suffix=".audio") as audio:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    body.write(chunk)
                    remaining -= len(chunk)
                body.flush()
                fields, filename = parse_multipart_file(ctype, body, audio)
                audio.flush()
                if filename is None or os.path.getsize(audio.name) == 0:
                    return self._send(400, {"error": "file required"})
                language = (fields.get("language") or "")[:8] or None
                fmt = fields.get("response_format") or "json"
                try:
                    result = transcribe(audio.name, language)
                except Exception as exc:  # noqa: BLE001 - the caller only needs to know it failed
                    return self._send(500, {"error": "transcription_failed", "details": type(exc).__name__})
        finally:
            _uploads.release()
        return self._send(200, result if fmt == "verbose_json" else {"text": result["text"]})


def main():
    port = int(os.environ.get("PORT", "8000"))
    if os.environ.get("WHISPER_PRELOAD", "1") == "1":
        model()
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
