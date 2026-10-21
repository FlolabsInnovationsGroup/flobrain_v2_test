"""Object storage for Content Studio (presigned URLs only; the API never streams media from S3).

``CONTENT_STORAGE=s3`` with ``CONTENT_S3_BUCKET`` uses S3 presigned URLs.
``CONTENT_STORAGE=local`` (dev, tests, demo) keeps files under ``CONTENT_LOCAL_DIR``. Its
"presigned" URLs point at ``/api/v2/content/local/<key>`` and carry an HMAC signature with an
expiry, like S3's, so the same upload and playback code works. Without ``CONTENT_LOCAL_DIR``
the URLs are placeholders and nothing is written (tests).
In a running demo, local storage defaults to a folder in the system temp dir.
Anything else is "Not configured" (None). Keys are always built by the
server: ``content/<org>/<asset or job>/<name>``.
"""

import hashlib
import hmac
import os
import re
import tempfile
import time
from urllib.parse import quote, urlencode

from django.conf import settings

SAFE = re.compile(r"[^A-Za-z0-9._-]")
LOCAL_PREFIX = "/api/v2/content/local/"


def _demo_default() -> bool:
    return bool(getattr(settings, "DEMO_MODE", False)) and not (getattr(settings, "CONTENT_STORAGE", "") or "").strip()


def backend() -> str:
    kind = (getattr(settings, "CONTENT_STORAGE", "") or "").strip()
    return kind or ("local" if _demo_default() else "")


def local_root() -> str:
    """``CONTENT_LOCAL_DIR``; in a running demo (not tests) a folder in the system temp dir."""
    root = getattr(settings, "CONTENT_LOCAL_DIR", "") or ""
    if not root and getattr(settings, "DEMO_MODE", False) and not getattr(settings, "TESTING", False):
        root = os.path.join(tempfile.gettempdir(), "flobrain-demo-content")
    return root


def local_path(key):
    """The file for ``key`` under the local root, or "" when there is no root or the key escapes it."""
    root = local_root()
    if not root or not key or "\\" in key or "\x00" in key:
        return ""
    real_root = os.path.realpath(root)
    path = os.path.realpath(os.path.join(real_root, *key.split("/")))
    return path if path.startswith(real_root + os.sep) else ""


def sign_local(method, key, expires_at, content_type="") -> str:
    msg = f"{method}\n{key}\n{int(expires_at)}\n{content_type}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def check_local(method, key, expires_at, signature, content_type="") -> bool:
    try:
        expires_at = int(expires_at)
    except (TypeError, ValueError):
        return False
    if expires_at < time.time():
        return False
    return hmac.compare_digest(sign_local(method, key, expires_at, content_type), str(signature or ""))


def _local_url(method, key, expires, content_type=""):
    exp = int(time.time()) + int(expires)
    query = {"exp": exp, "sig": sign_local(method, key, exp, content_type)}
    if content_type:
        query["ct"] = content_type
    base = (getattr(settings, "PUBLIC_API_BASE_URL", "") or "").rstrip("/")
    return f"{base}{LOCAL_PREFIX}{quote(key)}?{urlencode(query)}"


def local_etag(path) -> str:
    stat = os.stat(path)
    return hashlib.sha256(f"{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()[:32]


def is_configured() -> bool:
    kind = backend()
    return kind == "local" or (kind == "s3" and bool(getattr(settings, "CONTENT_S3_BUCKET", "")))


def key_for(org_id, owner_id, filename) -> str:
    name = SAFE.sub("_", filename or "file")[-80:] or "file"
    return f"content/{org_id}/{owner_id}/{name}"


def _client():
    import boto3

    return boto3.client("s3", region_name=getattr(settings, "CONTENT_S3_REGION", None) or None)


def presign_put(key, content_type, expires=900):
    kind = backend()
    if kind == "local":
        return _local_url("PUT", key, expires, content_type)
    if kind == "s3" and getattr(settings, "CONTENT_S3_BUCKET", ""):
        return _client().generate_presigned_url(
            "put_object",
            Params={"Bucket": settings.CONTENT_S3_BUCKET, "Key": key, "ContentType": content_type},
            ExpiresIn=int(expires),
        )
    return None


def presign_get(key, expires=900):
    kind = backend()
    if kind == "local":
        return _local_url("GET", key, expires)
    if kind == "s3" and getattr(settings, "CONTENT_S3_BUCKET", ""):
        return _client().generate_presigned_url(
            "get_object", Params={"Bucket": settings.CONTENT_S3_BUCKET, "Key": key}, ExpiresIn=int(expires)
        )
    return None


def head(key):
    """Return {"size", "content_type", "etag"} for an uploaded object, or None if missing."""
    kind = backend()
    if kind == "local":
        if not local_root():
            return {"size": None, "content_type": None, "etag": ""}  # placeholder backend (tests)
        path = local_path(key)
        if not path or not os.path.isfile(path):
            return None
        return {"size": os.path.getsize(path), "content_type": None, "etag": local_etag(path)}
    if kind == "s3" and getattr(settings, "CONTENT_S3_BUCKET", ""):
        from botocore.exceptions import ClientError

        try:
            meta = _client().head_object(Bucket=settings.CONTENT_S3_BUCKET, Key=key)
        except ClientError:
            return None
        return {
            "size": int(meta.get("ContentLength", 0)),
            "content_type": meta.get("ContentType", ""),
            "etag": str(meta.get("ETag", "")).strip('"')[:128],
        }
    return None


def put_file(key, fileobj, content_type):
    """Upload a server-built file (exports). Local backend writes under ``CONTENT_LOCAL_DIR`` when set."""
    kind = backend()
    if kind == "local":
        if local_root():
            path = local_path(key)
            if not path:
                return False
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as out:
                fileobj.seek(0)
                while chunk := fileobj.read(1 << 20):
                    out.write(chunk)
        return True
    if kind == "s3" and getattr(settings, "CONTENT_S3_BUCKET", ""):
        fileobj.seek(0)
        _client().upload_fileobj(fileobj, settings.CONTENT_S3_BUCKET, key, ExtraArgs={"ContentType": content_type})
        return True
    return False


def delete(key):
    kind = backend()
    if not key:
        return
    if kind == "local":
        path = local_path(key)
        if path and os.path.isfile(path):
            os.remove(path)
    elif kind == "s3" and getattr(settings, "CONTENT_S3_BUCKET", ""):
        _client().delete_object(Bucket=settings.CONTENT_S3_BUCKET, Key=key)


def read_bytes(key, max_bytes=1 << 30):
    """Read a stored object (meeting audio for transcription). None when missing or too big."""
    kind = backend()
    if not key:
        return None
    if kind == "local":
        path = local_path(key)
        if not path or not os.path.isfile(path):
            return None
        if os.path.getsize(path) > max_bytes:
            return None
        with open(path, "rb") as fh:
            return fh.read()
    if kind == "s3" and getattr(settings, "CONTENT_S3_BUCKET", ""):
        from botocore.exceptions import ClientError

        try:
            obj = _client().get_object(Bucket=settings.CONTENT_S3_BUCKET, Key=key)
        except ClientError:
            return None
        if int(obj.get("ContentLength", 0)) > max_bytes:
            return None
        return obj["Body"].read()
    return None


def download_to(key, fileobj, max_bytes=1 << 31) -> bool:
    """Stream a stored object into ``fileobj`` without holding it in memory. False when missing or too big."""
    kind = backend()
    if not key:
        return False
    if kind == "local":
        import shutil

        path = local_path(key)
        if not path or not os.path.isfile(path) or os.path.getsize(path) > max_bytes:
            return False
        with open(path, "rb") as fh:
            shutil.copyfileobj(fh, fileobj, 1 << 20)
        return True
    if kind == "s3" and getattr(settings, "CONTENT_S3_BUCKET", ""):
        from botocore.exceptions import BotoCoreError, ClientError

        meta = head(key)
        if meta is None or (meta.get("size") or 0) > max_bytes:
            return False
        try:
            _client().download_fileobj(settings.CONTENT_S3_BUCKET, key, fileobj)
        except (ClientError, BotoCoreError):
            return False
        return True
    return False
