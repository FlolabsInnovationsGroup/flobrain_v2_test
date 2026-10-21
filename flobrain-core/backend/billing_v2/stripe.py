"""Stripe webhook verification and handling (Phase 17b).

Signature: header ``Stripe-Signature: t=<ts>,v1=<hex>[,v1=…]``, HMAC-SHA256 of
``"<ts>.<raw body>"`` with ``STRIPE_WEBHOOK_SECRET``; timestamps older than the
tolerance are refused (replay). Each event id is applied once.
"""

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db import IntegrityError, transaction

from billing_v2.models import Plan, StripeEvent, Subscription


class BadSignature(Exception):
    pass


def verify(raw: bytes, header: str, now=None) -> dict:
    secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or ""
    if not secret:
        raise BadSignature("not configured")
    parts = {}
    for item in (header or "").split(","):
        key, _, value = item.strip().partition("=")
        parts.setdefault(key, []).append(value)
    try:
        ts = int(parts.get("t", [""])[0])
    except ValueError as exc:
        raise BadSignature("bad timestamp") from exc
    now = now or time.time()
    if abs(now - ts) > int(getattr(settings, "STRIPE_WEBHOOK_TOLERANCE", 300)):
        raise BadSignature("timestamp outside tolerance")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", [])):
        raise BadSignature("signature mismatch")
    try:
        event = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadSignature("bad body") from exc
    if not isinstance(event, dict) or not isinstance(event.get("id"), str):
        raise BadSignature("bad event")
    return event


def _ts(value):
    return datetime.fromtimestamp(int(value), tz=dt_timezone.utc) if isinstance(value, int) else None


def handle(event) -> str:
    """Apply one verified event. Returns "applied", "duplicate" or "ignored".

    Ignored events are not recorded, so a retry after the subscription exists still applies.
    Events older than the last applied one are ignored (Stripe does not guarantee order).
    """
    with transaction.atomic():
        try:
            with transaction.atomic():
                StripeEvent.objects.create(event_id=event["id"], type=str(event.get("type", ""))[:80])
        except IntegrityError:
            return "duplicate"
        result = _apply(event)
        if result != "applied":
            transaction.set_rollback(True)
        return result


def _apply(event) -> str:
    obj = ((event.get("data") or {}).get("object")) or {}
    if not isinstance(obj, dict):
        return "ignored"
    kind = event.get("type")
    created = _ts(event.get("created"))
    if kind == "checkout.session.completed":
        if obj.get("payment_status") not in ("paid", "no_payment_required"):
            return "ignored"  # async payments arrive later as subscription events
        meta = obj.get("metadata") or {}
        from organizations.models import Organization

        org = Organization.objects.filter(pk=meta.get("org_id")).first() if _uuid_ok(meta.get("org_id")) else None
        plan = Plan.objects.filter(code=meta.get("plan")).first()
        if org is None or plan is None:
            return "ignored"
        Subscription.objects.update_or_create(
            org=org,
            defaults={
                "plan": plan,
                "status": "active",
                "stripe_customer_id": str(obj.get("customer") or "")[:80],
                "stripe_subscription_id": str(obj.get("subscription") or "")[:80],
                "last_event_at": created,
            },
        )
        return "applied"
    if kind in ("customer.subscription.updated", "customer.subscription.deleted", "customer.subscription.created"):
        sub = Subscription.objects.select_for_update().filter(stripe_subscription_id=str(obj.get("id") or "")).first()
        if sub is None:
            return "ignored"
        if created and sub.last_event_at and created < sub.last_event_at:
            return "stale"
        if sub.status == "canceled" and kind != "customer.subscription.deleted":
            return "stale"  # canceled is final in Stripe; a late update must not revive it (a new checkout does)
        status = "canceled" if kind == "customer.subscription.deleted" else str(obj.get("status") or sub.status)[:12]
        items = ((obj.get("items") or {}).get("data")) or []
        if items and isinstance(items[0], dict):
            price = ((items[0].get("price") or {}).get("id")) or ""
            plan = Plan.objects.filter(stripe_price_id=price).first() if price else None
            if plan is not None:
                sub.plan = plan
            quantity = items[0].get("quantity")
            if isinstance(quantity, int) and quantity > 0:
                sub.seats = quantity
        sub.status = status
        sub.current_period_end = _ts(obj.get("current_period_end")) or sub.current_period_end
        sub.last_event_at = created or sub.last_event_at
        sub.save()
        return "applied"
    return "ignored"


def _uuid_ok(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


# --- server-side Checkout and Customer Portal (Stripe API) ---------------------------------
# Sessions are created here, never in the browser, so the plan and org in the metadata that the
# webhook later trusts were set by FloBrain (review 17 #11).

API_BASE = "https://api.stripe.com/v1"


class StripeAPIError(Exception):
    pass


def api_configured() -> bool:
    return bool(getattr(settings, "STRIPE_SECRET_KEY", ""))


def _flatten(params: dict, prefix="") -> list[tuple[str, str]]:
    out = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            out.extend(_flatten(value, name))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                out.extend(_flatten(item, f"{name}[{i}]") if isinstance(item, dict) else [(f"{name}[{i}]", str(item))])
        elif value is not None:
            out.append((name, str(value)))
    return out


def _post(path: str, params: dict) -> dict:
    import urllib.error
    import urllib.parse
    import urllib.request

    body = urllib.parse.urlencode(_flatten(params)).encode()
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # fixed Stripe host, not user input
            return json.loads(response.read(1_000_000).decode())
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read(20_000).decode()).get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            message = ""
        raise StripeAPIError(message or f"Stripe answered {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise StripeAPIError("Stripe could not be reached") from exc


def create_checkout_session(org, plan, seats: int, customer_id: str, success_url: str, cancel_url: str) -> str:
    params = {
        "mode": "subscription",
        "line_items": [{"price": plan.stripe_price_id, "quantity": seats}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(org.id),
        "metadata": {"org_id": str(org.id), "plan": plan.code},
        "subscription_data": {"metadata": {"org_id": str(org.id), "plan": plan.code}},
    }
    if customer_id:
        params["customer"] = customer_id
    data = _post("/checkout/sessions", params)
    if not isinstance(data.get("url"), str):
        raise StripeAPIError("Stripe did not return a checkout link")
    return data["url"]


def create_portal_session(customer_id: str, return_url: str) -> str:
    data = _post("/billing_portal/sessions", {"customer": customer_id, "return_url": return_url})
    if not isinstance(data.get("url"), str):
        raise StripeAPIError("Stripe did not return a portal link")
    return data["url"]
