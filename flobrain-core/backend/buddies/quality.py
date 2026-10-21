"""Buddy quality numbers (growth round W5). Aggregates only: counts, rates, medians and money.

Nothing here returns message text, feedback notes, routing reasons or who rated what. Sources:
- answers: assistant messages in buddy threads (``brain.Message``)
- helpful rate and "not helpful" reasons: ``BuddyFeedback`` (reason codes only)
- approvals: ``actions.ActionProposal`` by buddy
- latency and "answers with sources": ``BuddyAnswer`` (measured replies only, see ``measured``)
- tokens and cost: ``telemetry.UsageEvent`` for buddy threads, priced like Pulse
- routing share: ``BuddyRouteHop`` over Flo's decisions in the window
"""

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from statistics import median

from django.db.models import Count
from django.utils import timezone

from brain.models import Message
from buddies.models import Buddy, BuddyAnswer, BuddyFeedback, BuddyRoute, BuddyRouteHop
from buddies.services import visible_buddies
from organizations.permissions import can

WINDOWS = (7, 30)
APPROVED = {"approved", "executed", "failed"}  # a person said yes; "failed" happened after approval


def scope(user, org):
    """``pulse.view`` sees every buddy in the org; ``ai.usage.view`` sees the buddies they can use."""
    if can(user, "pulse.view", org):
        return Buddy.objects.filter(org=org)
    return visible_buddies(user, org)


def _rate(part, whole):
    return round(part / whole, 4) if whole else None


def stats(org, user, days) -> dict:
    from actions.models import ActionProposal
    from telemetry.models import UsageEvent
    from telemetry.pricing import PriceBook, money_for_event

    # Whole local days ending today, so the totals and the daily trend count the same rows.
    first_day = timezone.localdate() - timedelta(days=days - 1)
    since = timezone.make_aware(datetime.combine(first_day, time.min))
    buddies = list(scope(user, org).order_by("position", "name"))
    ids = [b.id for b in buddies]
    rows = {
        b.id: {
            "id": str(b.id),
            "slug": b.slug,
            "name": b.name,
            "icon": b.icon,
            "builtin": b.is_builtin,
            "answers": 0,
            "ratings": 0,
            "helpful": 0,
            "not_helpful": 0,
            "helpful_rate": None,
            "approvals": {"proposed": 0, "approved": 0, "rejected": 0, "waiting": 0},
            "median_latency_ms": None,
            "measured": 0,
            "with_sources_rate": None,
            "tokens": 0,
            "cost": "0.0000",
            "unpriced_calls": 0,
            "routed": 0,
            "routing_share": None,
            "top_reasons": [],
        }
        for b in buddies
    }
    days_map = {
        (first_day + timedelta(days=i)).isoformat(): {"answers": 0, "helpful": 0, "not_helpful": 0} for i in range(days)
    }

    answers = Message.objects.filter(
        chat__org=org, chat__buddy_id__in=ids, role=Message.ROLE_ASSISTANT, created_at__gte=since
    )
    for row in answers.values("chat__buddy_id").annotate(n=Count("id")):
        rows[row["chat__buddy_id"]]["answers"] = row["n"]
    for created in answers.values_list("created_at", flat=True):
        day = timezone.localtime(created).date().isoformat()
        if day in days_map:
            days_map[day]["answers"] += 1

    feedback = BuddyFeedback.objects.filter(org=org, buddy_id__in=ids, created_at__gte=since)
    reasons = defaultdict(Counter)
    overall = Counter()
    for fb in feedback.values("buddy_id", "rating", "reason", "created_at"):
        row = rows[fb["buddy_id"]]
        row["ratings"] += 1
        key = "helpful" if fb["rating"] == BuddyFeedback.UP else "not_helpful"
        row[key] += 1
        day = timezone.localtime(fb["created_at"]).date().isoformat()
        if day in days_map:
            days_map[day][key] += 1
        if fb["rating"] == BuddyFeedback.DOWN and fb["reason"]:
            reasons[fb["buddy_id"]][fb["reason"]] += 1
            overall[fb["reason"]] += 1

    for p in ActionProposal.objects.filter(org=org, buddy_id__in=ids, created_at__gte=since).values("buddy_id", "status").annotate(n=Count("id")):
        bucket = rows[p["buddy_id"]]["approvals"]
        bucket["proposed"] += p["n"]
        if p["status"] in APPROVED:
            bucket["approved"] += p["n"]
        elif p["status"] == "rejected":
            bucket["rejected"] += p["n"]
        elif p["status"] == "proposed":
            bucket["waiting"] += p["n"]

    latencies, cited = defaultdict(list), Counter()
    for fact in BuddyAnswer.objects.filter(org=org, buddy_id__in=ids, created_at__gte=since).values("buddy_id", "latency_ms", "cited"):
        rows[fact["buddy_id"]]["measured"] += 1
        cited[fact["buddy_id"]] += bool(fact["cited"])
        if fact["latency_ms"] is not None:
            latencies[fact["buddy_id"]].append(fact["latency_ms"])

    book = PriceBook()
    costs = defaultdict(lambda: Decimal("0"))
    for event in UsageEvent.objects.filter(org=org, chat__buddy_id__in=ids, created_at__gte=since).select_related("chat"):
        row = rows[event.chat.buddy_id]
        row["tokens"] += event.total_tokens or 0
        amount = money_for_event(event, book)
        if amount is None:
            row["unpriced_calls"] += event.credential_source == UsageEvent.CREDENTIAL_PLATFORM
        else:
            costs[event.chat.buddy_id] += amount

    routes = BuddyRoute.objects.filter(org=org, created_at__gte=since, surface=BuddyRoute.SURFACE_BUDDY)  # hints are not answers
    decisions = routes.count()
    for hop in BuddyRouteHop.objects.filter(route__in=routes, buddy_id__in=ids, status=200).values("buddy_id").annotate(n=Count("id")):
        rows[hop["buddy_id"]]["routed"] = hop["n"]

    for buddy_id, row in rows.items():
        row["helpful_rate"] = _rate(row["helpful"], row["ratings"])
        row["with_sources_rate"] = _rate(cited[buddy_id], row["measured"])
        row["median_latency_ms"] = int(median(latencies[buddy_id])) if latencies[buddy_id] else None
        row["cost"] = str(costs[buddy_id].quantize(Decimal("0.0001")))
        row["routing_share"] = _rate(row["routed"], decisions)
        row["top_reasons"] = [{"reason": r, "count": n} for r, n in reasons[buddy_id].most_common(3)]

    out_rows = sorted(rows.values(), key=lambda r: (-r["answers"], -r["ratings"], r["name"]))
    total_ratings = sum(r["ratings"] for r in out_rows)
    by_method = {row["method"]: row["n"] for row in routes.values("method").annotate(n=Count("id"))}
    return {
        "days": days,
        "since": since.isoformat(),
        "buddies": out_rows,
        "totals": {
            "answers": sum(r["answers"] for r in out_rows),
            "ratings": total_ratings,
            "helpful_rate": _rate(sum(r["helpful"] for r in out_rows), total_ratings),
            "proposed": sum(r["approvals"]["proposed"] for r in out_rows),
            "approved": sum(r["approvals"]["approved"] for r in out_rows),
            "rejected": sum(r["approvals"]["rejected"] for r in out_rows),
        },
        "reasons": [{"reason": r, "count": n} for r, n in overall.most_common(6)],
        "routing": {"decisions": decisions, "by_method": by_method},
        "trend": [{"day": day, **values} for day, values in days_map.items()],
    }
