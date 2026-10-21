"""Web Push (Phase 10). Sends only when VAPID keys are set; otherwise a no-op.

Payloads carry a title and a link, never message text: the push service only relays
encrypted bytes, but the lock screen shows what we send.
"""

import json
import logging
import urllib.parse

from django.conf import settings
from django.db.models import Q

logger = logging.getLogger(__name__)

# Push services browsers actually use. Anything else is refused (no SSRF through subscriptions).
PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
)


def endpoint_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == s or host.endswith("." + s) for s in PUSH_HOST_SUFFIXES)


def configured() -> bool:
    return bool(getattr(settings, "VAPID_PRIVATE_KEY", "") and getattr(settings, "VAPID_PUBLIC_KEY", ""))


def send_to_user(user_id, title: str, url: str, kind: str = "") -> int:
    from notifications.models import NotificationPreference, PushSubscription

    if not configured():
        return 0
    if kind and NotificationPreference.objects.filter(user_id=user_id, type=kind).filter(Q(push=False) | Q(enabled=False)).exists():
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # optional dependency
        return 0
    sent = 0
    for sub in PushSubscription.objects.filter(user_id=user_id):
        if not endpoint_allowed(sub.endpoint):
            sub.delete()
            continue
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps({"title": title[:120], "url": url[:300]}),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": getattr(settings, "VAPID_SUBJECT", "") or "mailto:support@flobrain.ai"},
                timeout=10,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                sub.delete()  # the browser unsubscribed
            else:
                PushSubscription.objects.filter(pk=sub.pk).update(last_error=f"push_failed_{status}")
        except Exception:  # noqa: BLE001 - never break the request that triggered a push
            logger.warning("web push failed", exc_info=False)
    return sent
