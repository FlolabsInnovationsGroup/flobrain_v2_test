"""Outgoing webhooks (Phase 14c): signed, retried, minimal payloads.

Signature header ``FloBrain-Signature: t=<unix>,v1=<hex HMAC-SHA256 of "<t>.<body>">``.
Payloads carry ids and short fields only, never message bodies, and nothing
about direct or group rooms.
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from jobs.queue import enqueue, register
from platform_api import demo_hosts, net
from platform_api.models import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)
JOB = "webhooks.deliver"
MAX_ATTEMPTS = 6


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def queue(delivery):
    # After commit: never send from inside the transaction that triggered the event.
    transaction.on_commit(lambda delivery_id=str(delivery.id): enqueue(JOB, {"delivery_id": delivery_id}))


def _envelope(org, event, data):
    return {"id": str(uuid.uuid4()), "event": event, "org": str(org.id), "created_at": timezone.now().isoformat(), "data": data}


def send_test(endpoint):
    """A ``ping`` to one endpoint, so a receiver can check its signature code."""
    delivery = WebhookDelivery.objects.create(endpoint=endpoint, event="ping", payload=_envelope(endpoint.org, "ping", {"test": True}))
    queue(delivery)
    return delivery


def retry_now(delivery) -> bool:
    """Manual retry: one more attempt now for a failed or waiting delivery (not one being sent)."""
    updated = WebhookDelivery.objects.filter(pk=delivery.pk, status__in=[WebhookDelivery.PENDING, WebhookDelivery.FAILED]).update(
        status=WebhookDelivery.PENDING, next_attempt_at=timezone.now(), attempts=min(delivery.attempts, MAX_ATTEMPTS - 1)
    )
    if updated:
        queue(delivery)
    return bool(updated)


def emit(org, event, data: dict):
    """Queue one delivery per active endpoint subscribed to ``event``."""
    if event not in WebhookEndpoint.EVENTS:
        return 0
    from organizations.flags import effective_flag

    if not effective_flag(org, None, "webhooks", default=False):
        return 0
    count = 0
    for endpoint in WebhookEndpoint.objects.filter(org=org, is_active=True):
        if event not in (endpoint.events or []):
            continue
        delivery = WebhookDelivery.objects.create(endpoint=endpoint, event=event, payload=_envelope(org, event, data))
        queue(delivery)
        count += 1
    return count


SENDING = "sending"
SENDING_STALE = timedelta(minutes=5)


def deliver(delivery_id):
    now = timezone.now()
    # Claim the row so the queued job and a retry tick never both send it.
    claimed = WebhookDelivery.objects.filter(
        pk=delivery_id, status=WebhookDelivery.PENDING, next_attempt_at__lte=now, endpoint__is_active=True
    ).update(status=SENDING, next_attempt_at=now + SENDING_STALE)
    delivery = WebhookDelivery.objects.select_related("endpoint").filter(pk=delivery_id).first()
    if not claimed:
        return delivery
    endpoint = delivery.endpoint
    body = json.dumps(delivery.payload, sort_keys=True).encode()
    ts = int(time.time())
    delivery.attempts += 1
    try:
        headers = {"Content-Type": "application/json", "FloBrain-Event": delivery.event, "FloBrain-Signature": sign(endpoint.secret(), ts, body)}
        if demo_hosts.is_demo_url(endpoint.url, demo_hosts.DEMO_INBOX_HOST):
            from platform_api import demo_inbox

            code = demo_inbox.receive(endpoint, body, headers)  # in-process, demo mode only
        else:
            code = net.post(endpoint.url, body, headers)
        delivery.response_code = code
        ok = 200 <= code < 300
        error = "" if ok else f"http_{code}"
    except net.UnsafeURL as exc:
        ok, error = False, f"unsafe_url: {exc}"[:200]
        delivery.attempts = MAX_ATTEMPTS  # never retried
    except crypto_error() as exc:
        ok, error = False, type(exc).__name__
        delivery.attempts = MAX_ATTEMPTS
    except Exception as exc:  # noqa: BLE001 - recorded, retried
        ok, error = False, type(exc).__name__
    if ok:
        delivery.status, delivery.delivered_at, delivery.error = WebhookDelivery.DELIVERED, timezone.now(), ""
    elif delivery.attempts >= MAX_ATTEMPTS:
        delivery.status, delivery.error = WebhookDelivery.FAILED, error
    else:
        delivery.status = WebhookDelivery.PENDING
        delivery.error = error
        delivery.next_attempt_at = timezone.now() + timedelta(seconds=min(30 * 4 ** (delivery.attempts - 1), 6 * 3600))
    delivery.save()
    return delivery


@register(JOB)
def deliver_job(payload):
    row = deliver(payload["delivery_id"])
    return {"ok": True, "status": row.status if row else "missing"}


def crypto_error():
    from integrations.crypto import CredentialCryptoError

    return CredentialCryptoError


def retry_due():
    now = timezone.now()
    # A row stuck in "sending" (worker died mid-send) goes back to pending after the stale window.
    WebhookDelivery.objects.filter(status=SENDING, next_attempt_at__lte=now).update(status=WebhookDelivery.PENDING)
    due = WebhookDelivery.objects.filter(status=WebhookDelivery.PENDING, next_attempt_at__lte=now)
    n = 0
    for delivery_id in due.values_list("id", flat=True)[:200]:
        deliver(delivery_id)
        n += 1
    return n
