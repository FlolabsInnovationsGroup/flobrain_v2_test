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
        defaults = {
            "plan": plan,
            "status": "active",
            "stripe_customer_id": str(obj.get("customer") or "")[:80],
            "stripe_subscription_id": str(obj.get("subscription") or "")[:80],
            "last_event_at": created,
        }
        if meta.get("interval") in ("month", "year"):
            defaults["interval"] = meta["interval"]
        if plan.per_workspace:
            defaults["seats"] = plan.included_seats or 1
        Subscription.objects.update_or_create(org=org, defaults=defaults)
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
            price_obj = items[0].get("price") or {}
            price = (price_obj.get("id") if isinstance(price_obj, dict) else "") or ""
            plan, interval = plan_for_price(price) if price else (None, None)
            if plan is not None:
                sub.plan = plan
            recurring = (price_obj.get("recurring") or {}) if isinstance(price_obj, dict) else {}
            interval = recurring.get("interval") if isinstance(recurring, dict) and recurring.get("interval") in ("month", "year") else interval
            if interval in ("month", "year"):
                sub.interval = interval
            quantity = items[0].get("quantity")
            if sub.plan.per_workspace:
                sub.seats = sub.plan.included_seats or 1  # one price for the workspace; the cap is the plan's
            elif isinstance(quantity, int) and quantity > 0:
                sub.seats = quantity
        sub.status = status
        sub.current_period_end = _ts(obj.get("current_period_end")) or sub.current_period_end
        sub.last_event_at = created or sub.last_event_at
        sub.save()
        return "applied"
    if kind in ("invoice.finalized", "invoice.paid", "invoice.payment_failed", "invoice.voided"):
        return _apply_invoice(obj, kind)
    return "ignored"


INVOICE_HOSTS = ("invoice.stripe.com", "pay.stripe.com")


def _safe_invoice_url(value) -> str:
    from urllib.parse import urlparse

    if not isinstance(value, str) or len(value) > 500:
        return ""
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.hostname in INVOICE_HOSTS else ""


def _apply_invoice(obj, kind) -> str:
    """Keep a copy of the invoice for the billing page. Only for a subscription we know."""
    from billing_v2.models import Invoice

    sub = None
    if obj.get("subscription"):
        sub = Subscription.objects.select_related("plan").filter(stripe_subscription_id=str(obj.get("subscription"))[:80]).first()
    if sub is None and obj.get("customer"):
        sub = Subscription.objects.select_related("plan").filter(stripe_customer_id=str(obj.get("customer"))[:80]).first()
    invoice_id = str(obj.get("id") or "")[:80]
    if sub is None or not invoice_id:
        return "ignored"
    status = {"invoice.paid": "paid", "invoice.payment_failed": "open", "invoice.voided": "void"}.get(kind) or str(obj.get("status") or "open")[:16]
    amount = obj.get("amount_due") if kind != "invoice.paid" else obj.get("amount_paid", obj.get("amount_due"))
    Invoice.objects.update_or_create(
        org=sub.org,
        stripe_invoice_id=invoice_id,
        defaults={
            "number": str(obj.get("number") or "")[:40],
            "status": status,
            "amount_cents": int(amount) if isinstance(amount, int) else 0,
            "currency": str(obj.get("currency") or "usd")[:3].upper(),
            "plan_code": sub.plan.code,
            "period_start": _ts(obj.get("period_start")),
            "period_end": _ts(obj.get("period_end")),
            "hosted_url": _safe_invoice_url(obj.get("hosted_invoice_url")),
            "created_at": _ts(obj.get("created")) or datetime.now(tz=dt_timezone.utc),
        },
    )
    return "applied"


# --- Stripe price ids: from the environment, per plan and interval (M8) ----------------------
# STRIPE_PRICE_<PLAN CODE>_<MONTH|YEAR>, e.g. STRIPE_PRICE_STUDIO_YEAR=price_...; or the Django
# setting STRIPE_PRICE_IDS = {"studio": {"month": "price_...", "year": "price_..."}}. The plan row's
# own ``stripe_price_id`` is the fallback for its ``interval``. Never written in code.


def _env_key(code: str, interval: str) -> str:
    import re

    return f"STRIPE_PRICE_{re.sub(r'[^A-Z0-9]', '_', code.upper())}_{interval.upper()}"


def price_id(plan, interval: str) -> str:
    import os

    value = os.environ.get(_env_key(plan.code, interval), "")
    if not value:
        value = ((getattr(settings, "STRIPE_PRICE_IDS", None) or {}).get(plan.code) or {}).get(interval, "")
    if not value and interval == plan.interval:
        value = plan.stripe_price_id
    return str(value or "")[:80]


def plan_for_price(price: str):
    """(plan, interval) for a Stripe price id, or (None, None)."""
    if not price:
        return None, None
    for plan in Plan.objects.all():
        for interval in ("month", "year"):
            if price_id(plan, interval) == price:
                return plan, interval
    return None, None


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
    return _request("POST", path, params)


def _get(path: str) -> dict:
    return _request("GET", path, None)


def _request(method: str, path: str, params) -> dict:
    import urllib.error
    import urllib.parse
    import urllib.request

    body = urllib.parse.urlencode(_flatten(params)).encode() if params is not None else None
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        method=method,
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


def create_checkout_session(org, plan, seats: int, customer_id: str, success_url: str, cancel_url: str, interval: str | None = None) -> str:
    interval = interval if interval in ("month", "year") else plan.interval
    meta = {"org_id": str(org.id), "plan": plan.code}
    if interval != plan.interval:
        meta["interval"] = interval  # only when it differs, so per-seat checkouts look as before
    params = {
        "mode": "subscription",
        "line_items": [{"price": price_id(plan, interval), "quantity": 1 if plan.per_workspace else seats}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(org.id),
        "metadata": meta,
        "subscription_data": {"metadata": dict(meta)},
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


def change_subscription(subscription_id: str, plan, interval: str, seats: int) -> dict:
    """Move an existing Stripe subscription to another plan or interval. Stripe prorates
    (``create_prorations``); our row changes when the verified ``customer.subscription.updated``
    webhook arrives, never here."""
    import re

    if not re.fullmatch(r"sub_[A-Za-z0-9]{1,64}", subscription_id or ""):
        raise StripeAPIError("Unknown subscription")
    price = price_id(plan, interval)
    if not price:
        raise StripeAPIError("This plan has no Stripe price yet")
    current = _get(f"/subscriptions/{subscription_id}")
    items = ((current.get("items") or {}).get("data")) or []
    if not items or not isinstance(items[0], dict) or not isinstance(items[0].get("id"), str):
        raise StripeAPIError("Stripe did not return the subscription item")
    data = _post(
        f"/subscriptions/{subscription_id}",
        {
            "items": [{"id": items[0]["id"], "price": price, "quantity": 1 if plan.per_workspace else seats}],
            "proration_behavior": "create_prorations",
            "metadata": {"plan": plan.code, "interval": interval},
        },
    )
    if not isinstance(data.get("id"), str):
        raise StripeAPIError("Stripe did not confirm the change")
    return {"id": data["id"], "status": str(data.get("status") or "")}
