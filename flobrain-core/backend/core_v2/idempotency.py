import hashlib
import json

from django.core.cache import cache


def idempotency_key(request) -> str | None:
    return request.headers.get("Idempotency-Key") if hasattr(request, "headers") else None


def remember_response(key: str, status_code: int, data, ttl=86400):
    payload = json.dumps({"status": status_code, "data": data}, default=str)
    cache.set(f"v2:idem:{hashlib.sha256(key.encode()).hexdigest()}", payload, ttl)


def replay_response(key: str):
    raw = cache.get(f"v2:idem:{hashlib.sha256(key.encode()).hexdigest()}")
    if not raw:
        return None
    return json.loads(raw)
