"""The built-in demo webhook receiver (DEMO_MODE only).

``receive`` acts like a customer's endpoint: it checks ``FloBrain-Signature`` with the
endpoint's secret and the timestamp tolerance, stores what arrived and answers 200 (or 401
when the signature is wrong, like a careful receiver would). Only the last 50 per org are kept.
"""

import hashlib
import hmac
import time

from platform_api.models import DemoInboxDelivery

TOLERANCE = 300
KEEP = 50


def verify(secret: str, header: str, body: bytes, now=None) -> bool:
    parts = dict(item.split("=", 1) for item in (header or "").split(",") if "=" in item)
    try:
        ts = int(parts.get("t", ""))
    except ValueError:
        return False
    if abs((now or time.time()) - ts) > TOLERANCE:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))


def receive(endpoint, body: bytes, headers: dict) -> int:
    signature = str(headers.get("FloBrain-Signature") or "")
    valid = verify(endpoint.secret(), signature, body)
    DemoInboxDelivery.objects.create(
        org=endpoint.org,
        endpoint=endpoint,
        event=str(headers.get("FloBrain-Event") or "")[:40],
        body=body.decode("utf-8", errors="replace")[:20000],
        signature=signature[:200],
        signature_valid=valid,
    )
    old = DemoInboxDelivery.objects.filter(org=endpoint.org).values_list("id", flat=True)[KEEP:]
    DemoInboxDelivery.objects.filter(pk__in=list(old)).delete()
    return 200 if valid else 401
