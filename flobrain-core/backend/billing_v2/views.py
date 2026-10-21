"""Billing endpoints (Phase 17b)."""

from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from billing_v2.entitlements import NOT_COUNTED
from billing_v2 import pricing, stripe, switching
from billing_v2.models import Invoice, Plan, Subscription, UsageInvoiceLine
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
        # M8 (additive): how the plan is billed. Prices are samples until confirmed.
        "billing_unit": p.billing_unit,
        "included_seats": p.included_seats,
        "overage_policy": p.overage_policy,
        "ai_allowance_per_workspace": p.ai_allowance_per_workspace,
        "price_yearly_cents": pricing.unit_prices(p)["year"],
        "price_monthly_cents": pricing.unit_prices(p)["month"],
        "tier": p.tier or p.code,
        "sample": pricing.is_sample(),
    }


def _workspace_pricing_on(request, org) -> bool:
    from organizations.flags import effective_flag

    membership = OrgMembership.objects.filter(org=org, user=request.user).first() if request.user.is_authenticated else None
    return effective_flag(org, membership, "workspace_pricing")


def _visible_plans(on: bool):
    plans = Plan.objects.filter(is_public=True)
    if not on:
        plans = plans.exclude(billing_unit=Plan.UNIT_PER_WORKSPACE)
    return plans.order_by("price_cents", "code")


def _workspace_block(org, sub) -> dict:
    """Seats vs cap, AI allowance and invoices for the billing page (flag ``workspace_pricing``)."""
    from billing_v2.entitlements import seat_status
    from billing_v2.switching import ai_included

    status = seat_status(org)
    ai = None
    if sub is not None and sub.status in Subscription.ACTIVE_STATES:
        ai = ai_included(sub.plan, sub.seats)
        try:
            from growth.allowance import counted, month_bounds

            start, end, _ = month_bounds(timezone.now())
            ai["used"] = counted(org, start, end).count()
        except Exception:  # noqa: BLE001 - the meter is optional; billing still renders
            ai["used"] = None
    return {
        "enabled": True,
        "sample": pricing.is_sample(),
        "interval": sub.interval if sub else None,
        "seat_status": status,
        "ai": ai,
        "price": switching.describe(sub.plan, sub.interval if sub.interval in pricing.INTERVALS else "month", sub.seats) if sub and sub.status != "canceled" else None,
        "invoices": [_invoice_payload(i) for i in Invoice.objects.filter(org=org).order_by("-created_at")[:24]],
    }


def _invoice_payload(i):
    return {
        "id": str(i.id),
        "number": i.number,
        "status": i.status,
        "amount_cents": i.amount_cents,
        "currency": i.currency,
        "plan": i.plan_code,
        "period_start": i.period_start.isoformat() if i.period_start else None,
        "period_end": i.period_end.isoformat() if i.period_end else None,
        "created_at": i.created_at.isoformat(),
        "url": i.hosted_url,
        "demo": i.demo,
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
        workspace_on = _workspace_pricing_on(request, org)
        extra = {"workspace_pricing": _workspace_block(org, sub)} if workspace_on else {}
        return Response(
            {
                **extra,
                "checkout": checkout_mode(),
                "can_manage": _is_owner(request.user, org),
                "plans": [_plan_payload(p) for p in _visible_plans(workspace_on)],
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
        error = _workspace_guard(request, org, plan)
        if error:
            return error
        interval = data.get("interval") or plan.interval
        if interval not in pricing.INTERVALS or pricing.unit_prices(plan).get(interval) is None:
            return Response({"error": "invalid", "details": "interval must be month or year, and offered by the plan"}, status=400)
        seats = _seats(data.get("seats"), org)
        if seats is None:
            return Response({"error": "invalid", "details": "seats must be 1..10000"}, status=400)
        if plan.per_workspace:
            seats = plan.included_seats or 1
        mode = checkout_mode()
        if mode == "stripe":
            if not stripe.price_id(plan, interval):
                return Response({"error": "not_configured", "details": "This plan has no Stripe price yet"}, status=501)
            sub = Subscription.objects.filter(org=org).first()
            try:
                url = stripe.create_checkout_session(
                    org, plan, seats, sub.stripe_customer_id if sub else "", _billing_page(org, "?checkout=done"), _billing_page(org, "?checkout=canceled"), interval
                )
            except stripe.StripeAPIError as exc:
                return Response({"error": "provider_error", "details": str(exc)[:200]}, status=502)
            audit(request.user, "billing.checkout_started", payload={"plan": plan.code, "seats": seats}, request=request, org=org)
            return Response({"mode": "stripe", "url": url})
        if mode == "demo":
            suffix = f"&interval={interval}" if interval != plan.interval else ""
            return Response({"mode": "demo", "url": f"/w/{org.slug}/settings/billing/checkout?plan={plan.code}&seats={seats}{suffix}"})
        return Response({"error": "not_configured", "details": "Checkout is not set up on this server"}, status=501)


def _workspace_guard(request, org, plan):
    """Per-workspace plans need the ``workspace_pricing`` flag and must fit the people already here."""
    if not plan.per_workspace:
        return None
    if not _workspace_pricing_on(request, org):
        return Response({"error": "not_implemented"}, status=501)
    from billing_v2.entitlements import seats_used

    used = seats_used(org)
    if plan.included_seats is not None and used > plan.included_seats:
        return Response(
            {"error": "seat_limit", "details": f"{plan.name} includes up to {plan.included_seats} people and you have {used}.", "seats": plan.included_seats, "used": used},
            status=409,
        )
    return None


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
        error = _workspace_guard(request, org, plan)
        if error:
            return error
        interval = data.get("interval") or plan.interval
        if interval not in pricing.INTERVALS or pricing.unit_prices(plan).get(interval) is None:
            return Response({"error": "invalid", "details": "interval must be month or year, and offered by the plan"}, status=400)
        seats = _seats(data.get("seats"), org)
        if seats is None:
            return Response({"error": "invalid", "details": "seats must be 1..10000"}, status=400)
        if plan.per_workspace:
            seats = plan.included_seats or 1
        sub, _ = Subscription.objects.update_or_create(
            org=org,
            defaults={
                "plan": plan, "status": "active", "seats": seats, "interval": interval,
                "current_period_end": timezone.now() + timedelta(days=365 if interval == "year" else 30), "stripe_customer_id": "", "stripe_subscription_id": "",
            },
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
        workspace, problem = _workspace_fields(data)
        if problem:
            return Response({"error": "invalid", "details": problem}, status=400)
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
                **workspace,
            },
        )
        return Response(_plan_payload(plan), status=201)


def _whole(value, name):
    if value is None or value == "":
        return None, None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, f"{name} must be a whole number"
    return value, None


def _workspace_fields(data) -> tuple[dict, str | None]:
    """Optional M8 fields on a plan. Only keys that were sent are changed."""
    out = {}
    if "billing_unit" in data:
        if data["billing_unit"] not in (Plan.UNIT_PER_SEAT, Plan.UNIT_PER_WORKSPACE):
            return {}, "billing_unit must be per_seat or per_workspace"
        out["billing_unit"] = data["billing_unit"]
    if "overage_policy" in data:
        if data["overage_policy"] not in (Plan.OVERAGE_BLOCK, Plan.OVERAGE_PROMPT):
            return {}, "overage_policy must be block or prompt_upgrade"
        out["overage_policy"] = data["overage_policy"]
    for key in ("included_seats", "ai_allowance_per_workspace", "price_yearly_cents"):
        if key in data:
            value, problem = _whole(data[key], key)
            if problem:
                return {}, problem
            out[key] = value if key != "price_yearly_cents" else (value or 0)
    if "tier" in data:
        out["tier"] = str(data["tier"] or "")[:40]
    if out.get("billing_unit") == Plan.UNIT_PER_WORKSPACE and not out.get("included_seats"):
        return {}, "a per_workspace plan needs included_seats"
    return out, None


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



class OrgPlanSwitchView(V2APIView):
    """Preview, then confirm, a move between plans (per seat and per workspace, monthly and yearly)."""

    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Owner: preview or switch plan (flag workspace_pricing). Stripe prorates; nothing is charged here")
    def post(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        if not _workspace_pricing_on(request, org):
            return Response({"error": "not_implemented"}, status=501)
        org, error = _owner_org(request, self, org_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        target = Plan.objects.filter(code=str(data.get("plan") or "")[:40], is_public=True).first()
        if target is None:
            return Response({"error": "not_found", "details": "Plan not found"}, status=404)
        sub = Subscription.objects.select_related("plan").filter(org=org).first()
        interval = str(data.get("interval") or (sub.interval if sub else "month"))
        try:
            summary = switching.plan_change(org, sub, target, interval, data.get("seats"))
        except switching.SwitchError as exc:
            return Response(exc.body(), status=exc.status)
        if not data.get("confirm"):
            return Response({"preview": True, **summary})
        seats = summary["to"]["seats"]
        mode = checkout_mode()
        live = sub is not None and sub.status != "canceled"
        if mode == "stripe":
            if not stripe.price_id(target, interval):
                return Response({"error": "not_configured", "details": "This plan has no Stripe price yet"}, status=501)
            try:
                if live and sub.stripe_subscription_id:
                    stripe.change_subscription(sub.stripe_subscription_id, target, interval, seats)
                    audit(request.user, "billing.plan_switch_requested", target=sub, payload={"plan": target.code, "interval": interval, "seats": seats}, request=request, org=org)
                    return Response({"mode": "stripe", "status": "pending", **summary})
                url = stripe.create_checkout_session(
                    org, target, seats, sub.stripe_customer_id if sub else "", _billing_page(org, "?checkout=done"), _billing_page(org, "?checkout=canceled"), interval
                )
            except stripe.StripeAPIError as exc:
                return Response({"error": "provider_error", "details": str(exc)[:200]}, status=502)
            audit(request.user, "billing.checkout_started", payload={"plan": target.code, "seats": seats, "interval": interval}, request=request, org=org)
            return Response({"mode": "stripe", "url": url, **summary})
        if mode == "demo":
            from datetime import timedelta

            sub, _ = Subscription.objects.update_or_create(
                org=org,
                defaults={
                    "plan": target, "status": "active", "seats": seats, "interval": interval,
                    "current_period_end": timezone.now() + timedelta(days=365 if interval == "year" else 30),
                },
            )
            audit(request.user, "billing.demo_plan_switch", target=sub, payload={"plan": target.code, "interval": interval, "seats": seats, "demo": True}, request=request, org=org)
            return Response({"mode": "demo", "status": "applied", "demo": True, **summary})
        return Response({"error": "not_configured", "details": "Checkout is not set up on this server"}, status=501)


class OrgInvoicesView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Invoices copied from Stripe by the webhook (flag workspace_pricing; billing.view)")
    def get(self, request, org_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        request.org = org
        if not _workspace_pricing_on(request, org):
            return Response({"error": "not_implemented"}, status=501)
        HasPerm("billing.view").has_permission(request, self)
        return Response({"invoices": [_invoice_payload(i) for i in Invoice.objects.filter(org=org).order_by("-created_at")[:100]]})


class PricingCalculatorThrottle(AnonRateThrottle):
    scope = "pricing_calculator"
    rate = "30/min"


def calculator_public() -> bool:
    """Off by default: on with WORKSPACE_PRICING_PUBLIC (setting or env) or in demo mode."""
    import os

    from django.conf import settings

    flag = getattr(settings, "WORKSPACE_PRICING_PUBLIC", None)
    if flag is None:
        flag = os.environ.get("WORKSPACE_PRICING_PUBLIC", "False") == "True"
    return bool(flag) or bool(getattr(settings, "DEMO_MODE", False))


class PricingCalculatorView(V2PublicAPIView):
    """Public (no sign-in), rate limited. The same math as the site's slider and sales."""

    throttle_classes = [PricingCalculatorThrottle]

    @extend_schema(summary="Price for a team size and interval, per plan, and which option is cheaper (sample prices)")
    def get(self, request):
        if not calculator_public():
            return Response({"error": "not_implemented"}, status=501)
        try:
            team = int(request.query_params.get("team") or request.query_params.get("team_size") or "")
        except ValueError:
            return Response({"error": "invalid", "details": "team must be a whole number"}, status=400)
        if team < 1 or team > pricing.MAX_TEAM:
            return Response({"error": "invalid", "details": "team must be 1..10000"}, status=400)
        interval = request.query_params.get("interval") or "month"
        if interval not in pricing.INTERVALS:
            return Response({"error": "invalid", "details": "interval must be month or year"}, status=400)
        plans = Plan.objects.filter(is_public=True).order_by("price_cents", "code")
        return Response(pricing.calculate(list(plans), team, interval))
