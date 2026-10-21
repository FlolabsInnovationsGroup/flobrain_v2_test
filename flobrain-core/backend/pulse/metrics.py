"""Every Pulse number comes from ``UsageEvent``, ``AITrace``, ``ActionProposal`` or eval records.

Nothing is sampled or invented; if there is no data the answer is zero or "none".
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from telemetry.models import AITrace, UsageEvent
from telemetry.pricing import money_for_event


def _percentile(values, q):
    if not values:
        return None
    import math

    values = sorted(values)  # nearest-rank percentile
    return values[min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))]


def _usage(org, since, team_ids=None):
    qs = UsageEvent.objects.filter(org=org, created_at__gte=since)
    if team_ids is not None:
        qs = qs.filter(team_id__in=team_ids)
    return qs


def _traces(org, since):
    return AITrace.objects.filter(org=org, created_at__gte=since)


def overview(org, days=7, team_ids=None) -> dict:
    since = timezone.now() - timedelta(days=days)
    usage = list(_usage(org, since, team_ids).only("created_at", "status", "latency_ms", "total_tokens", "credential_source", "provider", "model", "input_tokens", "output_tokens"))
    calls = len(usage)
    errors = sum(1 for u in usage if u.status != "ok")
    latencies = [u.latency_ms for u in usage if u.latency_ms is not None]
    cost, unpriced = Decimal("0"), 0
    for u in usage:
        amount = money_for_event(u)
        if amount is None:
            unpriced += u.credential_source == UsageEvent.CREDENTIAL_PLATFORM
        else:
            cost += amount
    by_day = {}
    for u in usage:
        day = u.created_at.date().isoformat()
        row = by_day.setdefault(day, {"day": day, "calls": 0, "errors": 0, "tokens": 0})
        row["calls"] += 1
        row["errors"] += u.status != "ok"
        row["tokens"] += u.total_tokens or 0
    from actions.models import ActionProposal

    proposals = ActionProposal.objects.filter(org=org, created_at__gte=since).values("status").annotate(n=Count("id"))
    governance = {row["status"]: row["n"] for row in proposals}
    from pulse.models import EvalRun

    latest = EvalRun.objects.filter(suite__org=org, status="done").order_by("-finished_at").select_related("suite")[:5]
    return {
        "days": days,
        "calls": calls,
        "errors": errors,
        "error_rate": round(errors / calls, 4) if calls else None,
        "tokens": sum(u.total_tokens or 0 for u in usage),
        "cost": str(cost.quantize(Decimal("0.0001"))),
        "unpriced_calls": unpriced,
        "byok_calls": sum(1 for u in usage if u.credential_source != UsageEvent.CREDENTIAL_PLATFORM),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "series": sorted(by_day.values(), key=lambda r: r["day"]),
        # Review 10-13: a team lead's view stays inside their teams; org-wide figures are left out.
        "governance": governance if team_ids is None else {},
        "evals": [
            {"suite": r.suite.name, "model": r.model, "pass_rate": r.pass_rate, "threshold": r.suite.threshold, "at": r.finished_at.isoformat()}
            for r in latest
        ] if team_ids is None else [],
    }


def models_table(org, days=7) -> list:
    since = timezone.now() - timedelta(days=days)
    rows = {}
    for u in _usage(org, since):
        key = (u.provider or "", u.model or "")
        r = rows.setdefault(key, {"provider": key[0], "model": key[1], "calls": 0, "errors": 0, "tokens": 0, "latencies": [], "cost": Decimal("0")})
        r["calls"] += 1
        r["errors"] += u.status != "ok"
        r["tokens"] += u.total_tokens or 0
        if u.latency_ms is not None:
            r["latencies"].append(u.latency_ms)
        amount = money_for_event(u)
        if amount is not None:
            r["cost"] += amount
    out = []
    for r in rows.values():
        lat = r.pop("latencies")
        out.append({**r, "cost": str(r["cost"].quantize(Decimal("0.0001"))), "error_rate": round(r["errors"] / r["calls"], 4), "latency_p95_ms": _percentile(lat, 0.95)})
    return sorted(out, key=lambda r: -r["calls"])


def surfaces_table(org, days=7) -> list:
    since = timezone.now() - timedelta(days=days)
    rows = (
        _traces(org, since)
        .values("surface")
        .annotate(total=Count("id"), failed=Count("id", filter=~Q(outcome="completed")))
        .order_by("-total")
    )
    return [{"surface": r["surface"], "total": r["total"], "failed": r["failed"]} for r in rows]


def metric_value(org, metric, window_minutes) -> float | None:
    since = timezone.now() - timedelta(minutes=window_minutes)
    usage = list(_usage(org, since).only("status", "latency_ms", "credential_source", "provider", "model", "input_tokens", "output_tokens", "total_tokens", "created_at"))
    if metric == "error_rate":
        return (sum(1 for u in usage if u.status != "ok") / len(usage)) if usage else None
    if metric == "p95_latency_ms":
        return _percentile([u.latency_ms for u in usage if u.latency_ms is not None], 0.95)
    if metric == "daily_cost":
        total = sum((money_for_event(u) or Decimal("0") for u in usage), Decimal("0"))
        return float(total)
    return None


# --- Agents, cost, governance and incidents (spec 9 Phase 13) ------------------------


def _q(amount) -> str:
    return str((amount or Decimal("0")).quantize(Decimal("0.0001")))


def agents_table(org, days=7) -> dict:
    """Buddies and scheduled agents: calls, errors, cost, proposals (holds) and runs."""
    from actions.models import ActionProposal
    from agents.models import AgentRun, AgentSchedule
    from buddies.models import Buddy
    from telemetry.pricing import PriceBook

    since = timezone.now() - timedelta(days=days)
    book = PriceBook()
    buddies = {}

    def row(buddy_id, name):
        return buddies.setdefault(
            str(buddy_id),
            {"buddy": str(buddy_id), "name": name, "calls": 0, "errors": 0, "tokens": 0, "cost": Decimal("0"),
             "proposals": 0, "executed": 0, "rejected": 0, "pending": 0, "expired": 0, "failed": 0},
        )

    names = dict(Buddy.objects.filter(org=org).values_list("id", "name"))
    for u in _usage(org, since).filter(chat__buddy_id__isnull=False).values("chat__buddy_id", "status", "total_tokens", "credential_source", "provider", "model", "input_tokens", "output_tokens", "created_at"):
        r = row(u["chat__buddy_id"], names.get(u["chat__buddy_id"], ""))
        r["calls"] += 1
        r["errors"] += u["status"] != "ok"
        r["tokens"] += u["total_tokens"] or 0
        amount = money_for_event(_Row(u), book)
        if amount is not None:
            r["cost"] += amount
    status_key = {"executed": "executed", "rejected": "rejected", "proposed": "pending", "expired": "expired", "failed": "failed"}
    for p in ActionProposal.objects.filter(org=org, created_at__gte=since, buddy_id__isnull=False).values("buddy_id", "status").annotate(n=Count("id")):
        r = row(p["buddy_id"], names.get(p["buddy_id"], ""))
        r["proposals"] += p["n"]
        key = status_key.get(p["status"])
        if key:
            r[key] += p["n"]
    out_buddies = []
    for r in buddies.values():
        r["cost"] = _q(r["cost"])
        r["error_rate"] = round(r["errors"] / r["calls"], 4) if r["calls"] else None
        decided = r["executed"] + r["rejected"]
        r["approval_rate"] = round(r["executed"] / decided, 4) if decided else None
        out_buddies.append(r)
    out_buddies.sort(key=lambda r: (-r["calls"], -r["proposals"], r["name"]))

    schedules = []
    runs = AgentRun.objects.filter(org=org, created_at__gte=since)
    by_schedule = {}
    for r in runs.values("schedule_id", "status").annotate(n=Count("id")):
        by_schedule.setdefault(r["schedule_id"], {})[r["status"]] = r["n"]
    from django.db.models import Sum

    proposals_by_schedule = {
        r["schedule_id"]: r["n"] or 0 for r in runs.values("schedule_id").annotate(n=Sum("proposals"))
    }
    run_cost = {}
    for u in _usage(org, since).filter(chat__agent_runs__isnull=False).values(
        "chat__agent_runs__schedule_id", "credential_source", "provider", "model", "input_tokens", "output_tokens", "total_tokens", "created_at"
    ):
        amount = money_for_event(_Row(u), book)
        if amount is not None:
            key = u["chat__agent_runs__schedule_id"]
            run_cost[key] = run_cost.get(key, Decimal("0")) + amount
    for s in AgentSchedule.objects.filter(org=org).select_related("buddy", "created_by"):
        counts = by_schedule.get(s.id, {})
        total = sum(counts.values())
        cost = run_cost.get(s.id, Decimal("0"))
        schedules.append({
            "id": str(s.id),
            "name": s.name or s.buddy.name,
            "buddy": s.buddy.name,
            "owner": s.created_by.username or s.created_by.email,
            "is_active": s.is_active,
            "paused_reason": s.paused_reason,
            "runs": total,
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "proposals": proposals_by_schedule.get(s.id, 0),
            "cost": _q(cost),
            "cost_per_run": _q(cost / counts.get("done", 1)) if counts.get("done") else None,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        })
    schedules.sort(key=lambda r: (-r["runs"], r["name"]))
    return {"days": days, "buddies": out_buddies, "schedules": schedules}


class _Row:
    """A ``values()`` dict seen as a usage row for ``money_for_event``."""

    def __init__(self, data):
        self.credential_source = data.get("credential_source")
        self.provider = data.get("provider") or ""
        self.model = data.get("model") or ""
        self.input_tokens = data.get("input_tokens")
        self.output_tokens = data.get("output_tokens")
        self.total_tokens = data.get("total_tokens")
        self.created_at = data.get("created_at")


def cost_report(org, days=30) -> dict:
    """Platform cost by day, model, team, member and surface; own-key usage beside it; GPU renders."""
    from telemetry.pricing import PriceBook, money_for_render

    since = timezone.now() - timedelta(days=days)
    book = PriceBook()
    rows = list(_usage(org, since).values(
        "user_id", "team_id", "provider", "model", "surface", "credential_source", "input_tokens", "output_tokens", "total_tokens", "created_at"
    ))
    from organizations.models import Team
    from users.models import User

    users = {u.id: (u.username or u.email) for u in User.objects.filter(pk__in={r["user_id"] for r in rows if r["user_id"]})}
    from telemetry.v2_views import PRIVATE_LABEL, private_users

    for uid in private_users(org):
        users[uid] = PRIVATE_LABEL  # "keep my insights personal": no row of their own
    teams = dict(Team.objects.filter(org=org).values_list("id", "name"))
    groups = {k: {} for k in ("model", "team", "member", "surface")}
    by_day = {}
    total, unpriced, own_calls, own_tokens = Decimal("0"), 0, 0, 0
    for r in rows:
        tokens = r["total_tokens"] or 0
        day = r["created_at"].date().isoformat()
        d = by_day.setdefault(day, {"day": day, "cost": Decimal("0"), "own_key_tokens": 0, "platform_tokens": 0})
        if r["credential_source"] != UsageEvent.CREDENTIAL_PLATFORM:
            own_calls += 1
            own_tokens += tokens
            d["own_key_tokens"] += tokens
            continue
        d["platform_tokens"] += tokens
        amount = money_for_event(_Row(r), book)
        if amount is None:
            unpriced += 1
            amount = Decimal("0")
        total += amount
        d["cost"] += amount
        keys = {
            "model": r["model"] or "unknown",
            "team": teams.get(r["team_id"], "No team") if r["team_id"] else "No team",
            "member": users.get(r["user_id"], "Unknown") if r["user_id"] else "Unknown",
            "surface": r["surface"] or "other",
        }
        for group, key in keys.items():
            g = groups[group].setdefault(key, {"label": key, "cost": Decimal("0"), "calls": 0, "tokens": 0})
            g["cost"] += amount
            g["calls"] += 1
            g["tokens"] += tokens
    gpu_seconds, gpu_cost, gpu_unpriced = 0.0, Decimal("0"), 0
    try:
        from content_studio.models import RenderJob

        for job in RenderJob.objects.filter(org=org, queued_at__gte=since, gpu_seconds__gt=0).only("gpu_seconds", "finished_at", "queued_at"):
            gpu_seconds += job.gpu_seconds
            amount = money_for_render(job, book)
            if amount is None:
                gpu_unpriced += 1
            else:
                gpu_cost += amount
    except Exception:  # noqa: BLE001 - Content Studio not installed
        pass

    def top(group, n=10):
        items = sorted(groups[group].values(), key=lambda g: -g["cost"])[:n]
        return [{**g, "cost": _q(g["cost"])} for g in items]

    platform_calls = sum(1 for r in rows if r["credential_source"] == UsageEvent.CREDENTIAL_PLATFORM)
    return {
        "days": days,
        "platform_cost": _q(total),
        "platform_calls": platform_calls,
        "cost_per_call": _q(total / platform_calls) if platform_calls else None,
        "unpriced_calls": unpriced,
        "own_key_calls": own_calls,
        "own_key_tokens": own_tokens,
        "gpu_seconds": round(gpu_seconds, 1),
        "gpu_cost": _q(gpu_cost),
        "gpu_unpriced_renders": gpu_unpriced,
        "series": [{**d, "cost": _q(d["cost"])} for d in sorted(by_day.values(), key=lambda d: d["day"])],
        "by_model": top("model"),
        "by_team": top("team"),
        "by_member": top("member"),
        "by_surface": top("surface"),
    }


def governance_report(org, days=30) -> dict:
    """Approvals and holds: counts by status and tool, edits, decision time, denials, paused agents.
    No proposal text is returned (people's proposals can name private work)."""
    from actions.models import ActionProposal
    from agents.models import AgentSchedule
    from buddies.models import Buddy
    from organizations.models import AuditEvent

    since = timezone.now() - timedelta(days=days)
    proposals = ActionProposal.objects.filter(org=org, created_at__gte=since)
    by_status = {r["status"]: r["n"] for r in proposals.values("status").annotate(n=Count("id"))}
    by_tool = {}
    for r in proposals.values("tool_key", "status").annotate(n=Count("id")):
        t = by_tool.setdefault(r["tool_key"], {"tool": r["tool_key"], "total": 0})
        t["total"] += r["n"]
        t[r["status"]] = r["n"]
    waits = [
        (p["decided_at"] - p["created_at"]).total_seconds()
        for p in proposals.filter(decided_at__isnull=False).values("created_at", "decided_at")
        if p["decided_at"] and p["created_at"]
    ]
    executed = by_status.get("executed", 0)
    decided = executed + by_status.get("rejected", 0) + by_status.get("failed", 0)
    audits = AuditEvent.objects.filter(org=org, created_at__gte=since)
    from brain.llm.policy import inference_scope

    return {
        "days": days,
        "proposals": sum(by_status.values()),
        "by_status": by_status,
        "by_tool": sorted(by_tool.values(), key=lambda t: -t["total"]),
        "approval_rate": round(executed / decided, 4) if decided else None,
        "edited_before_approval": proposals.filter(original_arguments__isnull=False).count(),
        "median_decision_seconds": _percentile(waits, 0.5),
        "denied_at_approval": audits.filter(action="action.denied").count(),
        "blocked_traces": _traces(org, since).filter(outcome="blocked").count(),
        "pending_buddy_shares": Buddy.objects.filter(org=org, share_status=Buddy.SHARE_PENDING).count(),
        "paused_agents": [
            {"name": s.name or s.buddy.name, "reason": s.paused_reason}
            for s in AgentSchedule.objects.filter(org=org, is_active=False).select_related("buddy")[:20]
        ],
        "inference_scope": inference_scope(org),
    }


def incidents_report(org, days=90) -> list:
    """The org's incidents (and public platform ones) with the AI error rate while each was open."""
    from platform_api.models import Incident

    since = timezone.now() - timedelta(days=days)
    rows = (Incident.objects.filter(org=org) | Incident.objects.filter(org__isnull=True, is_public=True)).filter(
        created_at__gte=since
    ).order_by("-created_at")[:50]
    out = []
    for i in rows:
        end = i.resolved_at or timezone.now()
        calls = UsageEvent.objects.filter(org=org, created_at__gte=i.created_at, created_at__lte=end)
        total = calls.count()
        errors = calls.exclude(status="ok").count()
        out.append({
            "id": str(i.id),
            "title": i.title,
            "severity": i.severity,
            "status": i.status,
            "platform": i.org_id is None,
            "components": i.components,
            "started_at": i.created_at.isoformat(),
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
            "ai_calls": total,
            "ai_errors": errors,
            "ai_error_rate": round(errors / total, 4) if total else None,
        })
    return out
