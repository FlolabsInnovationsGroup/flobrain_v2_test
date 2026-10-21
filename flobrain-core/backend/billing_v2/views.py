"""Billing endpoints (Phase 17b)."""

from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from billing_v2.entitlements import NOT_COUNTED
from billing_v2 import stripe
from billing_v2.models import Plan, Subscription, UsageInvoiceLine
from core_v2.views import V2APIView, V2PublicAPIView
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit


def _plan_payload(p):
    return {
        "id": str(p.id),
        "code": p.code,
        "name": p.name,
        "price_cents": p.price_cents,
        "currency": p.currency,
        "interval": p.interval,
        "entitlements": p.entitlements,
        "is_public": p.is_public,
    }


class OrgBillingView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Plan, seats and this month's model usage at cost (BYOK at zero markup)")
    def get(self, request, org_id):
        from telemetry.models import UsageEvent
        from telemetry.pricing import money_for_event

        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        HasPerm("billing.view").has_permission(request, self)
        sub = Subscription.objects.select_related("plan").filter(org=org).first()
        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        platform = Decimal("0")
        unknown = 0
        for row in UsageEvent.objects.filter(org=org, created_at__gte=start, credential_source=UsageEvent.CREDENTIAL_PLATFORM):
            amount = money_for_event(row)
            if amount is None:
                unknown += 1
            else:
                platform += amount
        byok = UsageEvent.objects.filter(org=org, created_at__gte=start, credential_source=UsageEvent.CREDENTIAL_CUSTOMER).count()
        lines = UsageInvoiceLine.objects.filter(org=org).order_by("-period", "metric")[:36]
        return Response(
            {
                "checkout": checkout_mode(),
                "can_manage": _is_owner(request.user, org),
                "plans": [_plan_payload(p) for p in Plan.objects.filter(is_public=True).order_by("price_cents", "code")],
                "invoice_lines": [
                    {"period": line.period, "metric": line.metric, "quantity": str(line.quantity), "unit_price": str(line.unit_price), "amount": str(line.amount)}
                    for line in lines
                ],
                "has_billing_account": bool(sub and sub.stripe_customer_id),
                "plan": _plan_payload(sub.plan) if sub else None,
                "status": sub.status if sub else "none",
                "seats": sub.seats if sub else None,
                "seats_used": OrgMembership.objects.filter(org=org).exclude(employment_status__in=NOT_COUNTED).count(),  # same count as the seat cap
                "current_period_end": sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
                "usage_this_month": {
                    "platform_cost": str(platform),
                    "platform_events_unpriced": unknown,
                    "byok_events": byok,
                    "byok_markup": "0",
                },
            }
        )


def checkout_mode() -> str:
    """"stripe" when the Stripe API key is set, "demo" in demo mode (fake, no payment), else "off"."""
    from django.conf import settings

    if stripe.api_configured():
        return "stripe"
    return "demo" if getattr(settings, "DEMO_MODE", False) else "off"


def _is_owner(user, org) -> bool:
    """Billing changes: owner only (spec 5.2: owner F, admin V). No platform-admin bypass here."""
    m = OrgMembership.objects.filter(org=org, user=user).first()
    return bool(m and m.is_active_member and m.org_role == OrgMembership.ORG_ROLE_OWNER)


def _owner_org(request, view, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm("billing.view").has_permission(request, view)
    if not _is_owner(request.user, org):
        return org, Response({"error": "permission_denied", "details": "Only the owner can change billing"}, status=403)
    return org, None


def _seats(value, org):
    try:
        seats = int(value if value is not None else 0)
    except (TypeError, ValueError):
        return None
    if seats <= 0:
        seats = max(1, OrgMembership.objects.filter(org=org).exclude(employment_status__in=NOT_COUNTED).count())
    return seats if seats <= 10000 else None


def _billing_page(org, suffix=""):
    from django.conf import settings

    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/w/{org.slug}/settings/billing{suffix}"


class OrgCheckoutView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Owner: start a checkout for a public plan (Stripe, or the labelled demo checkout)")
    def post(self, request, org_id):
        org, error = _owner_org(request, self, org_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        plan = Plan.objects.filter(code=str(data.get("plan") or "")[:40], is_public=True).first()
        if plan is None:
            return Response({"error": "not_found", "details": "Plan not found"}, status=404)
        seats = _seats(data.get("seats"), org)
        if seats is None:
            return Response({"error": "invalid", "details": "seats must be 1..10000"}, status=400)
        mode = checkout_mode()
        if mode == "stripe":
            if not plan.stripe_price_id:
                return Response({"error": "not_configured", "details": "This plan has no Stripe price yet"}, status=501)
            sub = Subscription.objects.filter(org=org).first()
            try:
                url = stripe.create_checkout_session(
                    org, plan, seats, sub.stripe_customer_id if sub else "", _billing_page(org, "?checkout=done"), _billing_page(org, "?checkout=canceled")
                )
            except stripe.StripeAPIError as exc:
                return Response({"error": "provider_error", "details": str(exc)[:200]}, status=502)
            audit(request.user, "billing.checkout_started", payload={"plan": plan.code, "seats": seats}, request=request, org=org)
            return Response({"mode": "stripe", "url": url})
        if mode == "demo":
            return Response({"mode": "demo", "url": f"/w/{org.slug}/settings/billing/checkout?plan={plan.code}&seats={seats}"})
        return Response({"error": "not_configured", "details": "Checkout is not set up on this server"}, status=501)


class OrgBillingPortalView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Owner: open Stripe's billing portal (or the demo one)")
    def post(self, request, org_id):
        org, error = _owner_org(request, self, org_id)
        if error:
            return error
        mode = checkout_mode()
        sub = Subscription.objects.filter(org=org).first()
        if mode == "stripe":
            if not sub or not sub.stripe_customer_id:
                return Response({"error": "conflict", "details": "There is no billing account yet. Choose a plan first."}, status=409)
            try:
                url = stripe.create_portal_session(sub.stripe_customer_id, _billing_page(org))
            except stripe.StripeAPIError as exc:
                return Response({"error": "provider_error", "details": str(exc)[:200]}, status=502)
            return Response({"mode": "stripe", "url": url})
        if mode == "demo":
            return Response({"mode": "demo", "url": f"/w/{org.slug}/settings/billing/checkout?manage=1"})
        return Response({"error": "not_configured", "details": "Billing is not set up on this server"}, status=501)


class OrgDemoBillingView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Demo mode only: the fake checkout. Sets the subscription; no payment, no card")
    def post(self, request, org_id):
        from datetime import timedelta

        from django.conf import settings

        if not getattr(settings, "DEMO_MODE", False):
            return Response({"error": "not_found"}, status=404)
        org, error = _owner_org(request, self, org_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        action = data.get("action")
        if action == "cancel":
            updated = Subscription.objects.filter(org=org).update(status="canceled")
            audit(request.user, "billing.demo_cancel", payload={"demo": True}, request=request, org=org)
            return Response({"status": "canceled" if updated else "none", "demo": True})
        if action != "subscribe":
            return Response({"error": "invalid", "details": "action must be subscribe or cancel"}, status=400)
        plan = Plan.objects.filter(code=str(data.get("plan") or "")[:40], is_public=True).first()
        if plan is None:
            return Response({"error": "not_found", "details": "Plan not found"}, status=404)
        seats = _seats(data.get("seats"), org)
        if seats is None:
            return Response({"error": "invalid", "details": "seats must be 1..10000"}, status=400)
        sub, _ = Subscription.objects.update_or_create(
            org=org,
            defaults={"plan": plan, "status": "active", "seats": seats, "current_period_end": timezone.now() + timedelta(days=30), "stripe_customer_id": "", "stripe_subscription_id": ""},
        )
        audit(request.user, "billing.demo_checkout", target=sub, payload={"plan": plan.code, "seats": seats, "demo": True}, request=request, org=org)
        return Response({"status": sub.status, "plan": plan.code, "seats": sub.seats, "demo": True})


class PlatformPlanListView(V2APIView):
    permission_classes = []

    def _admin(self, request):
        return bool(request.user and request.user.is_authenticated and getattr(request.user, "is_platform_admin", False))

    @extend_schema(summary="Plans (platform admins)")
    def get(self, request):
        if not self._admin(request):
            return Response({"error": "permission_denied", "details": "Platform admins only"}, status=403)
        return Response([_plan_payload(p) for p in Plan.objects.order_by("code")])

    @extend_schema(summary="Create or update a plan by code (platform admins)")
    def post(self, request):
        if not self._admin(request):
            return Response({"error": "permission_denied", "details": "Platform admins only"}, status=403)
        data = request.data if isinstance(request.data, dict) else {}
        code = str(data.get("code") or "").strip()
        ent = data.get("entitlements") or {}
        if not code or not isinstance(ent, dict) or not isinstance(ent.get("flags", []), list):
            return Response({"error": "invalid", "details": "code and entitlements {flags, limits} are required"}, status=400)
        limits = ent.get("limits") or {}
        if not isinstance(limits, dict) or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in limits.values()):
            return Response({"error": "invalid", "details": "limits must be whole numbers"}, status=400)
        try:
            price = int(data.get("price_cents") or 0)
        except (TypeError, ValueError):
            return Response({"error": "invalid", "details": "price_cents must be a number"}, status=400)
        plan, _ = Plan.objects.update_or_create(
            code=code[:40],
            defaults={
                "name": str(data.get("name") or code)[:80],
                "price_cents": max(0, price),
                "currency": str(data.get("currency") or "USD")[:3].upper(),
                "interval": "year" if data.get("interval") == "year" else "month",
                "entitlements": {"flags": [str(f)[:40] for f in ent.get("flags", [])], "limits": limits},
                "stripe_price_id": str(data.get("stripe_price_id") or "")[:80],
                "is_public": bool(data.get("is_public")),
            },
        )
        return Response(_plan_payload(plan), status=201)


class PlatformSubscriptionView(V2APIView):
    permission_classes = []

    @extend_schema(summary="Assign a plan to an org (platform admins; Stripe does this in production)")
    def put(self, request, org_id):
        if not (request.user and request.user.is_authenticated and getattr(request.user, "is_platform_admin", False)):
            return Response({"error": "permission_denied", "details": "Platform admins only"}, status=403)
        org = get_object_or_404(Organization, pk=org_id)
        data = request.data if isinstance(request.data, dict) else {}
        plan = Plan.objects.filter(code=data.get("plan")).first()
        if plan is None:
            return Response({"error": "not_found", "details": "Plan not found"}, status=404)
        status = data.get("status") or "active"
        if status not in ("trialing", "active", "past_due", "canceled"):
            return Response({"error": "invalid", "details": "unknown status"}, status=400)
        defaults = {"plan": plan, "status": status}
        if data.get("seats") is not None:
            seats = _seats(data.get("seats"), org)
            if seats is None:
                return Response({"error": "invalid", "details": "seats must be 1..10000"}, status=400)
            defaults["seats"] = seats
        sub, _ = Subscription.objects.update_or_create(org=org, defaults=defaults)
        audit(request.user, "billing.subscription_set", target=sub, payload={"plan": plan.code, "status": status, "seats": sub.seats}, org=org)
        return Response({"org": str(org.id), "plan": plan.code, "status": sub.status, "seats": sub.seats})


class StripeWebhookView(V2PublicAPIView):
    throttle_classes = []

    @extend_schema(summary="Stripe webhook (signature verified, idempotent)")
    def post(self, request):
        try:
            event = stripe.verify(request.body, request.META.get("HTTP_STRIPE_SIGNATURE", ""))
        except stripe.BadSignature:
            return Response({"error": "invalid_signature"}, status=400)
        return Response({"result": stripe.handle(event)})

