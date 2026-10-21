"""Local storage endpoint (``CONTENT_STORAGE=local`` with a local folder; dev and demo only).

It stands in for S3's presigned URLs: ``PUT`` stores the body under the key, ``GET`` serves it
(with byte ranges, so video seeking works). The request is authorised only by the HMAC
signature and expiry that ``storage.presign_put`` / ``presign_get`` put in the URL. With S3
configured, or without a local folder, this endpoint does not exist (404).
"""

import os
import re
import tempfile

from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from content_studio import storage

RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
TYPES = {
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
    ".wav": "audio/wav", ".ogg": "audio/ogg", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".json": "application/json", ".zip": "application/zip", ".srt": "application/x-subrip",
    ".vtt": "text/vtt",
}


def _error(status, code):
    return JsonResponse({"error": code}, status=status)


def _type_for(path):
    return TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


@method_decorator(csrf_exempt, name="dispatch")
class LocalMediaView(View):
    http_method_names = ["get", "head", "put", "options"]

    def _enabled(self):
        return storage.backend() == "local" and bool(storage.local_root())

    def put(self, request, key):
        if not self._enabled():
            return _error(404, "not_found")
        content_type = request.GET.get("ct", "")
        if not storage.check_local("PUT", key, request.GET.get("exp"), request.GET.get("sig"), content_type):
            return _error(403, "bad_signature")
        if (request.META.get("CONTENT_TYPE") or "").split(";")[0].strip().lower() != content_type.lower():
            return _error(400, "wrong_content_type")
        path = storage.local_path(key)
        if not path:
            return _error(400, "bad_key")
        limit = int(getattr(settings, "CONTENT_MAX_UPLOAD_MB", 4096)) * 1024 * 1024
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            declared = 0
        if declared > limit:
            return _error(413, "too_large")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        written = 0
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := request.read(1 << 20):
                    written += len(chunk)
                    if written > limit:
                        raise OverflowError
                    out.write(chunk)
            os.replace(tmp, path)
        except OverflowError:
            os.unlink(tmp)
            return _error(413, "too_large")
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            return _error(500, "write_failed")
        response = HttpResponse(status=200)
        response["ETag"] = f'"{storage.local_etag(path)}"'
        return response

    def get(self, request, key):
        if not self._enabled():
            return _error(404, "not_found")
        if not storage.check_local("GET", key, request.GET.get("exp"), request.GET.get("sig")):
            return _error(403, "bad_signature")
        path = storage.local_path(key)
        if not path or not os.path.isfile(path):
            return _error(404, "not_found")
        size = os.path.getsize(path)
        content_type = _type_for(path)
        match = RANGE.match(request.META.get("HTTP_RANGE", "").strip())
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)) if match.group(2) else size - 1, size - 1)
            else:
                start, end = max(size - int(match.group(2)), 0), size - 1
            if start > end or start >= size:
                response = HttpResponse(status=416)
                response["Content-Range"] = f"bytes */{size}"
                return response
            length = end - start + 1

            def chunks():
                with open(path, "rb") as fh:
                    fh.seek(start)
                    left = length
                    while left > 0:
                        data = fh.read(min(1 << 16, left))
                        if not data:
                            break
                        left -= len(data)
                        yield data

            response = StreamingHttpResponse(chunks(), status=206, content_type=content_type)
            response["Content-Range"] = f"bytes {start}-{end}/{size}"
            response["Content-Length"] = str(length)
        else:
            response = FileResponse(open(path, "rb"), content_type=content_type)
        response["Accept-Ranges"] = "bytes"
        response["Cache-Control"] = "private, max-age=300"
        response["X-Content-Type-Options"] = "nosniff"
        if not content_type.startswith(("video/", "audio/", "image/")):
            response["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
        return response

