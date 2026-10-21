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


def seat_limit(org):
    """Seats the org may fill, or None when not enforced. A canceled subscription allows no new seats."""
    plan = plan_for(org)
    if plan is None:
        return None
    if plan is False:
        return 0
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
