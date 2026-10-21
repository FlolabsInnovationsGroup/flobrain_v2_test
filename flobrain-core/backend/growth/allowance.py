"""AI included per seat: allowance, use this month and a month-end projection.

SAMPLE NUMBERS. Prices and allowances are not confirmed (docs/v2/DECISIONS_NEEDED.md Q22), so every
response says ``sample: true``. Override without a code change with the Django setting
``GROWTH_AI_ALLOWANCE = {"per_seat": {...}, "default_plan": "...", "sample": bool}``.

Counted unit: one "buddy answer" is one successful AI chat answer (buddies, rooms, Ask) made with
FloBrain's AI keys (``UsageEvent`` with ``operation=chat``, ``status=ok``, ``credential_source=platform``).
Answers on the org's or a member's own key (BYOK) are not counted: they are not part of the allowance.
"""

import calendar
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

UNIT = "buddy answers"

# Buddy answers included per seat per month, by plan code. Placeholders until pricing is confirmed.
DEFAULT_PER_SEAT = {
    "free": 100,
    "crew": 500,
    "pro": 500,
    "fleet": 1500,
    "teams": 1500,
    "team": 1500,
    "mission": 5000,
    "enterprise": 5000,
}
DEFAULT_PLAN = "fleet"  # used for orgs without a subscription (internal and demo orgs)


def config() -> dict:
    custom = getattr(settings, "GROWTH_AI_ALLOWANCE", None) or {}
    per_seat = dict(DEFAULT_PER_SEAT)
    per_seat.update({str(k): int(v) for k, v in (custom.get("per_seat") or {}).items()})
    return {"per_seat": per_seat, "default_plan": str(custom.get("default_plan") or DEFAULT_PLAN), "sample": bool(custom.get("sample", True))}


def month_bounds(now):
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days = calendar.monthrange(now.year, now.month)[1]
    return start, start + timedelta(days=days), days


def project(used: int, now: datetime) -> int:
    """Straight-line projection to the end of the month. The first hours are counted as at least
    one day so a busy first morning doesn't project a huge month."""
    start, end, _ = month_bounds(now)
    elapsed = max((now - start).total_seconds(), 86400.0)
    total = (end - start).total_seconds()
    return int(round(used * total / elapsed))


def plan_and_seats(org):
    """(plan code, plan name, seats). Seats: the subscription's, else the members who hold a seat."""
    from billing_v2.entitlements import NOT_COUNTED
    from billing_v2.models import Subscription
    from organizations.models import OrgMembership

    sub = Subscription.objects.select_related("plan").filter(org=org).first()
    if sub is not None and sub.status in Subscription.ACTIVE_STATES:
        return sub.plan.code, sub.plan.name, max(int(sub.seats or 0), 1)
    seats = OrgMembership.objects.filter(org=org).exclude(employment_status__in=NOT_COUNTED).count()
    code = config()["default_plan"]
    return code, None, max(seats, 1)


def counted(org, since, until):
    from telemetry.models import UsageEvent

    return UsageEvent.objects.filter(
        org=org,
        operation="chat",
        status="ok",
        credential_source=UsageEvent.CREDENTIAL_PLATFORM,
        created_at__gte=since,
        created_at__lt=until,
    )


def pct(part: int, whole: int) -> int:
    return int(round(100 * part / whole)) if whole else 0


def summary(org, user, admin: bool, now=None) -> dict:
    now = now or timezone.now()
    cfg = config()
    code, plan_name, seats = plan_and_seats(org)
    per_seat = cfg["per_seat"].get(code, cfg["per_seat"].get(cfg["default_plan"], 0))
    start, end, days = month_bounds(now)
    rows = counted(org, start, end)
    used = rows.count()
    mine = rows.filter(user=user).count()
    included = per_seat * seats
    projected = project(used, now)
    data = {
        "sample": cfg["sample"],
        "unit": UNIT,
        "plan": {"code": code, "name": plan_name, "subscribed": plan_name is not None},
        "included_per_seat": per_seat,
        "seats": seats,
        "included_total": included,
        "used": used,
        "used_pct": pct(used, included),
        "projected": projected,
        "projected_pct": pct(projected, included),
        "over_projected": projected > included,
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days_in_month": days,
            "days_elapsed": round((now - start).total_seconds() / 86400, 1),
        },
        "mine": {"used": mine, "included_per_seat": per_seat, "pct": pct(mine, per_seat)},
        "own_keys_not_counted": True,
    }
    if admin:
        data["people"] = people(org, rows, user)
    return data


def people(org, rows, viewer) -> list[dict]:
    """Per person, for admins. People who keep their insights personal are one combined row
    (same promise as the usage page)."""
    from django.db.models import Count

    from telemetry.v2_views import PRIVATE_KEY, PRIVATE_LABEL, private_users
    from users.models import User

    private = private_users(org) - {viewer.id}
    counts = {r["user_id"]: r["n"] for r in rows.values("user_id").annotate(n=Count("id"))}
    names = {u.id: (u.username or u.email) for u in User.objects.filter(pk__in=[k for k in counts if k]).only("username", "email")}
    out, hidden = [], 0
    for uid, n in counts.items():
        if uid in private:
            hidden += n
            continue
        out.append({"user_id": str(uid) if uid else None, "name": names.get(uid, "") if uid else "", "used": n})
    if hidden:
        out.append({"user_id": PRIVATE_KEY, "name": PRIVATE_LABEL, "used": hidden})
    return sorted(out, key=lambda r: (-r["used"], r["name"]))
