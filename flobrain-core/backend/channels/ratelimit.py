"""Fixed-window counters in the Django cache (per IP, per conversation, per sender, per connection)."""

import hashlib

from django.conf import settings
from django.core.cache import cache


def _key(scope: str, ident: str, window: int) -> str:
    digest = hashlib.sha256(f"{scope}:{ident}".encode()).hexdigest()[:32]
    return f"channels:rl:{scope}:{window}:{digest}"


def hit(scope: str, ident: str, limit: int, window: int = 60) -> bool:
    """Count one hit. True while within ``limit`` per ``window`` seconds, False once over."""
    key = _key(scope, ident, window)
    if cache.add(key, 1, timeout=window):
        return True
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, timeout=window)
        return True
    return count <= limit


def count(scope: str, ident: str, window: int = 60) -> int:
    return int(cache.get(_key(scope, ident, window)) or 0)


def limit(name: str, default: int) -> int:
    return int((getattr(settings, "CHANNELS_LIMITS", None) or {}).get(name, default))
