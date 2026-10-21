"""Plan entitlements AND org/user flags (spec Phase 17): an org admin cannot switch on what the plan lacks.

Enforced only when ``BILLING_ENFORCE_ENTITLEMENTS`` is on, and only for orgs that
have a subscription (internal orgs without one keep today's behaviour).
"""

from django.conf import settings


def plan_for(org):
    if org is None or not getattr(settings, "BILLING_ENFORCE_ENTITLEMENTS", False):
        return None
    cached = getattr(org, "_billing_plan_cache", "unset")
    if cached != "unset":
        return cached
    from billing_v2.models import Subscription

    sub = Subscription.objects.select_related("plan").filter(org=org).first()
    plan = None
    if sub is not None:
        plan = sub.plan if sub.status in Subscription.ACTIVE_STATES else False  # canceled → nothing
    org._billing_plan_cache = plan
    return plan


def allows(org, key) -> bool:
    plan = plan_for(org)
    if plan is None:
        return True
    if plan is False:
        return False
    return key in plan.flags()


def limit(org, name, default):
    plan = plan_for(org)
    if not plan:
        return default
    value = plan.limit(name)
    return default if value is None else min(default, value)


def workspace_subscription(org):
    """The org's active subscription when it is on a per-workspace plan (M8), else None.
    Independent of ``BILLING_ENFORCE_ENTITLEMENTS``: "up to N people" is the plan's promise."""
    if org is None:
        return None
    from billing_v2.models import Plan, Subscription

    sub = Subscription.objects.select_related("plan").filter(org=org, status__in=Subscription.ACTIVE_STATES).first()
    if sub is None or sub.plan.billing_unit != Plan.UNIT_PER_WORKSPACE:
        return None
    return sub


def seat_limit(org):
    """Seats the org may fill, or None when not enforced. A canceled subscription allows no new seats.
    A per-workspace plan always caps at its included seats (M8)."""
    plan = plan_for(org)
    if plan is False:
        return 0
    ws = workspace_subscription(org)
    if ws is not None and ws.plan.included_seats is not None:
        cap = ws.plan.limit("seats")
        return ws.plan.included_seats if cap is None else min(ws.plan.included_seats, cap)
    if plan is None:
        return None
    from billing_v2.models import Subscription

    sub = Subscription.objects.filter(org=org).first()
    seats = sub.seats if sub else 0
    cap = plan.limit("seats")
    return seats if cap is None else min(seats, cap)


NOT_COUNTED = ("terminated", "graduated")


def seat_blocked(org, adding_user_id=None, email: str = "") -> int | None:
    """Review 15-16: one check for every path that adds or reactivates a member.
    Returns the seat count when the org is full, else None. Call inside ``transaction.atomic()``;
    it locks the org row so two requests can't both take the last seat."""
    seats = seat_limit(org)
    if seats is None:
        return None
    from organizations.models import OrgMembership, Organization

    Organization.objects.select_for_update().filter(pk=org.pk).first()
    counted = OrgMembership.objects.filter(org=org).exclude(employment_status__in=NOT_COUNTED)
    if adding_user_id is not None and counted.filter(user_id=adding_user_id).exists():
        return None  # already holds a seat
    if email and counted.filter(user__email__iexact=email).exists():
        return None
    return seats if counted.count() >= seats else None


def seats_used(org) -> int:
    from organizations.models import OrgMembership

    return OrgMembership.objects.filter(org=org).exclude(employment_status__in=NOT_COUNTED).count()


def seat_status(org) -> dict:
    """What the billing page and the seat-limit error show: unit, cap, used, policy, upgrade target."""
    from billing_v2.models import Plan, Subscription

    sub = Subscription.objects.select_related("plan").filter(org=org).first()
    plan = sub.plan if sub else None
    ws = workspace_subscription(org)
    upgrade = None
    if ws is not None and ws.plan.overage_policy == Plan.OVERAGE_PROMPT:
        pair = Plan.objects.filter(is_public=True, billing_unit=Plan.UNIT_PER_SEAT, tier=ws.plan.tier or ws.plan.code).exclude(pk=ws.plan.pk).first()
        upgrade = pair.code if pair else None
    return {
        "unit": plan.billing_unit if plan else None,
        "limit": seat_limit(org),
        "used": seats_used(org),
        "policy": ws.plan.overage_policy if ws else Plan.OVERAGE_BLOCK,
        "upgrade_to": upgrade,
        "plan": plan.code if plan else None,
        "plan_name": plan.name if plan else None,
    }


def seat_error(org, seats) -> dict:
    """The one error body for "the org is full", for every path that adds people
    (invite, register, accept, reactivate, SCIM, HR intake). Never a silent charge."""
    status = seat_status(org)
    if status["unit"] == "per_workspace":
        details = f"Your {status['plan_name']} plan includes up to {seats} people and every seat is taken. Remove someone or switch to a per-person plan in billing."
    else:
        details = f"All {seats} seats are taken. Add seats in billing first."
    body = {"error": "seat_limit", "details": details, "seats": seats, "policy": status["policy"]}
    if status["upgrade_to"]:
        body["upgrade"] = {"plan": status["upgrade_to"], "url": f"/w/{org.slug}/settings/billing?upgrade={status['upgrade_to']}"}
    return body


def ai_allowance(org):
    """Buddy answers included per month for the whole workspace on a per-workspace plan, else None
    (per-seat plans keep growth.allowance: per seat x seats)."""
    ws = workspace_subscription(org)
    if ws is None or ws.plan.ai_allowance_per_workspace is None:
        return None
    return int(ws.plan.ai_allowance_per_workspace)
