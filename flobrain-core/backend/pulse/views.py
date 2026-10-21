"""Pulse console (Phase 13). Admins with ``pulse.view``; team leads see their teams' overview.

Routing policies are stored and previewed here; customer keys are never routed and an org's
``private_only`` policy always wins.
"""

import re
import uuid
from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization, TeamMembership
from organizations.permissions import IsActiveOrgMember
from organizations.permissions.engine import can
from organizations.services.core import audit
from pulse import metrics
from pulse.models import AlertRule, EvalCase, EvalResult, EvalRun, EvalSuite, RoutingPolicy
from telemetry.models import AITrace

MODEL = re.compile(r"^[A-Za-z0-9._:/@-]{1,128}$")


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _bad(details):
    return Response({"error": "invalid", "details": details}, status=400)


class PulseOff(APIException):
    status_code = 501
    default_detail = "Pulse is not enabled"
    default_code = "not_implemented"


def _org(request, org_id):
    """Review 10-13: Pulse honours its feature flag (plan, org and member) like every other module."""
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    if not effective_flag(org, membership, "pulse", default=False):
        raise PulseOff()
    return org


def _admin(request, org):
    return can(request.user, "pulse.view", org)


def _denied():
    return Response({"error": "permission_denied", "details": "Missing permission: pulse.view"}, status=403)


def _days(request):
    try:
        return max(1, min(90, int(request.query_params.get("days", 7))))
    except ValueError:
        return 7


class OverviewView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Pulse overview (admins: the org; team leads: their teams)")
    def get(self, request, org_id):
        org = _org(request, org_id)
        if _admin(request, org):
            return Response({"scope": "org", **metrics.overview(org, _days(request))})
        teams = list(TeamMembership.objects.filter(team__org=org, user=request.user, team_role=TeamMembership.ROLE_LEAD).values_list("team_id", flat=True))
        if not teams:
            return _denied()
        return Response({"scope": "teams", **metrics.overview(org, _days(request), team_ids=teams)})


class ModelsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Per-model calls, errors, latency and cost")
    def get(self, request, org_id):
        org = _org(request, org_id)
        return Response(metrics.models_table(org, _days(request))) if _admin(request, org) else _denied()


class SurfacesView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Per-surface (room AI, buddies, agents…) totals and failures")
    def get(self, request, org_id):
        org = _org(request, org_id)
        return Response(metrics.surfaces_table(org, _days(request))) if _admin(request, org) else _denied()


class AgentsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Buddies and scheduled agents: calls, cost, proposals (holds) and runs")
    def get(self, request, org_id):
        org = _org(request, org_id)
        return Response(metrics.agents_table(org, _days(request))) if _admin(request, org) else _denied()


class CostView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Platform cost by day, model, team, member and surface; own keys and GPU apart")
    def get(self, request, org_id):
        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        data = metrics.cost_report(org, _days_or(request, 30))
        membership = OrgMembership.objects.filter(org=org, user=request.user).first()
        if effective_flag(org, membership, "budgets", default=False):
            from telemetry.models import Budget
            from telemetry.pricing import PriceBook, budget_spend, scope_label, state_for

            book = PriceBook()
            data["budgets"] = []
            for budget in Budget.objects.filter(org=org).select_related("org"):
                spent = budget_spend(budget, book)
                data["budgets"].append({
                    "id": str(budget.id), "scope_type": budget.scope_type, "scope_name": scope_label(budget),
                    "limit": str(budget.cap_amount), "currency": budget.currency, "spent": str(spent.quantize(Decimal("0.0001"))),
                    "state": state_for(budget, spent), "on_exceed": budget.on_exceed,
                })
        return Response(data)


class GovernanceView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Approvals and holds: proposals by status and tool, edits, denials, paused agents")
    def get(self, request, org_id):
        org = _org(request, org_id)
        return Response(metrics.governance_report(org, _days_or(request, 30))) if _admin(request, org) else _denied()


class IncidentsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Incidents with the AI error rate while each was open")
    def get(self, request, org_id):
        org = _org(request, org_id)
        return Response(metrics.incidents_report(org)) if _admin(request, org) else _denied()


def _days_or(request, default):
    try:
        return max(1, min(90, int(request.query_params.get("days", default))))
    except ValueError:
        return default


def _trace_payload(t, detail=False):
    data = {
        "id": str(t.id),
        "surface": t.surface,
        "model": t.model,
        "outcome": t.outcome,
        "latency_ms": t.latency_ms,
        "user": t.user.username if t.user_id else None,
        "created_at": t.created_at.isoformat(),
    }
    if detail:
        # Ids and types only: traces never hold message or document text.
        data.update({"context_sources": t.context_sources, "tool_calls": t.tool_calls, "permission_decisions": t.permission_decisions, "room": t.room, "buddy": t.buddy})
    return data


class TraceListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Traces (no content), filterable by surface and outcome")
    def get(self, request, org_id):
        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        qs = AITrace.objects.filter(org=org).select_related("user").order_by("-created_at")
        for key in ("surface", "outcome", "model"):
            value = request.query_params.get(key)
            if value:
                qs = qs.filter(**{key: value[:128]})
        return Response([_trace_payload(t) for t in qs[:200]])


class TraceDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="One trace: context sources, tool calls and permission decisions (ids only)")
    def get(self, request, org_id, trace_id):
        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        return Response(_trace_payload(get_object_or_404(AITrace.objects.select_related("user"), pk=trace_id, org=org), detail=True))


def _suite_payload(s):
    last = s.runs.order_by("-created_at").first()
    return {
        "id": str(s.id),
        "name": s.name,
        "description": s.description,
        "threshold": s.threshold,
        "cases": [
            {"id": str(c.id), "name": c.name, "prompt": c.prompt, "must_contain": c.must_contain, "must_not_contain": c.must_not_contain, "max_latency_ms": c.max_latency_ms}
            for c in s.cases.all()
        ],
        "last_run": {"id": str(last.id), "status": last.status, "pass_rate": last.pass_rate, "model": last.model} if last else None,
    }


def _strings(value, label):
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > 20 or not all(isinstance(v, str) and 0 < len(v) <= 200 for v in value):
        raise ValueError(f"{label} must be a list of up to 20 short strings")
    return value


class SuiteListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Evaluation suites")
    def get(self, request, org_id):
        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        return Response([_suite_payload(s) for s in EvalSuite.objects.filter(org=org).prefetch_related("cases").order_by("name")])

    @extend_schema(summary="Create a suite with its cases")
    def post(self, request, org_id):
        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        data = _body(request)
        name = str(data.get("name") or "").strip()[:120]
        threshold = data.get("threshold", 80)
        cases = data.get("cases") or []
        if not name or not isinstance(threshold, int) or isinstance(threshold, bool) or not 0 <= threshold <= 100:
            return _bad("name and a threshold of 0..100 are required")
        if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
            return _bad("cases must be a list of 1 to 100")
        clean = []
        try:
            for c in cases:
                if not isinstance(c, dict) or not str(c.get("prompt") or "").strip():
                    raise ValueError("each case needs a prompt")
                latency = c.get("max_latency_ms")
                if latency is not None and (not isinstance(latency, int) or isinstance(latency, bool) or not 1 <= latency <= 600000):
                    raise ValueError("max_latency_ms must be 1..600000")
                clean.append(
                    EvalCase(
                        name=str(c.get("name") or c["prompt"])[:120],
                        prompt=str(c["prompt"])[:8000],
                        must_contain=_strings(c.get("must_contain"), "must_contain"),
                        must_not_contain=_strings(c.get("must_not_contain"), "must_not_contain"),
                        max_latency_ms=latency,
                    )
                )
        except ValueError as exc:
            return _bad(str(exc))
        suite = EvalSuite.objects.create(org=org, name=name, description=str(data.get("description") or "")[:500], threshold=threshold, created_by=request.user)
        for case in clean:
            case.suite = suite
        EvalCase.objects.bulk_create(clean)
        audit(request.user, "pulse.suite_create", target=suite, request=request, org=org)
        return Response(_suite_payload(suite), status=201)


class SuiteRunView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Run a suite against a platform model (never a customer key)")
    def post(self, request, org_id, suite_id):
        from jobs.queue import enqueue
        from pulse.jobs import JOB

        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        suite = get_object_or_404(EvalSuite, pk=suite_id, org=org)
        model = str(_body(request).get("model") or "")
        if model and not MODEL.fullmatch(model):
            return _bad("model is not a model name")
        if EvalRun.objects.filter(suite=suite, status__in=["queued", "running"]).exists():
            return Response({"error": "conflict", "details": "This suite is already running"}, status=409)
        from telemetry.models import UsageEvent
        from telemetry.pricing import platform_budget_blocks

        if platform_budget_blocks(org, request.user, UsageEvent.CREDENTIAL_PLATFORM):
            return Response({"error": "budget_exceeded", "details": "The org's monthly AI budget is used up"}, status=429)
        run = EvalRun.objects.create(suite=suite, model=model, started_by=request.user)
        queued = enqueue(JOB, {"run_id": str(run.id)})
        if isinstance(queued, dict) and queued.get("ok") is False:
            run.status, run.finished_at = "failed", timezone.now()
            run.save(update_fields=["status", "finished_at"])
            return Response({"error": "not_implemented", "details": "The job queue is not running"}, status=501)
        run.refresh_from_db()
        return Response({"id": str(run.id), "status": run.status, "pass_rate": run.pass_rate}, status=202)


class RunDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Results of one evaluation run")
    def get(self, request, org_id, run_id):
        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        run = get_object_or_404(EvalRun.objects.select_related("suite"), pk=run_id, suite__org=org)
        results = EvalResult.objects.filter(run=run).select_related("case")
        return Response(
            {
                "id": str(run.id),
                "suite": run.suite.name,
                "status": run.status,
                "model": run.model,
                "pass_rate": run.pass_rate,
                "threshold": run.suite.threshold,
                "avg_latency_ms": run.avg_latency_ms,
                "results": [
                    {"case": r.case.name, "passed": r.passed, "checks": r.checks, "latency_ms": r.latency_ms, "error": r.error_code, "output": r.output[:1000]}
                    for r in results
                ],
            }
        )


def _policy_payload(p):
    return {
        "primary_model": p.primary_model,
        "fallback_models": p.fallback_models,
        "max_task_cost": str(p.max_task_cost) if p.max_task_cost is not None else None,
        "latency_threshold_ms": p.latency_threshold_ms,
        "require_approval_for_writes": p.require_approval_for_writes,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


class RoutingView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Routing and failover policy")
    def get(self, request, org_id):
        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        return Response(_policy_payload(RoutingPolicy.objects.filter(org=org).first() or RoutingPolicy(org=org)))

    @extend_schema(summary="Change the policy (pulse.view; audited)")
    def put(self, request, org_id):
        from brain.llm import direct

        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        data = _body(request)
        policy = RoutingPolicy.objects.filter(org=org).first() or RoutingPolicy(org=org)
        allowed = set(direct.allowlist())
        if "primary_model" in data:
            model = str(data["primary_model"] or "")
            if model and (not MODEL.fullmatch(model) or (allowed and model not in allowed)):
                return _bad("primary_model must be one of the allowed platform models")
            policy.primary_model = model
        if "fallback_models" in data:
            models = data["fallback_models"] or []
            if not isinstance(models, list) or len(models) > 5 or not all(isinstance(m, str) and MODEL.fullmatch(m) and (not allowed or m in allowed) for m in models):
                return _bad("fallback_models must be up to 5 allowed platform models")
            policy.fallback_models = list(dict.fromkeys(models))
        if "max_task_cost" in data:
            try:
                value = None if data["max_task_cost"] in (None, "") else Decimal(str(data["max_task_cost"]))
            except InvalidOperation:
                return _bad("max_task_cost must be an amount")
            if value is not None and (not value.is_finite() or value < 0 or value > 1000):
                return _bad("max_task_cost must be 0..1000")
            policy.max_task_cost = value
        if "latency_threshold_ms" in data:
            v = data["latency_threshold_ms"]
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 100 <= v <= 600000):
                return _bad("latency_threshold_ms must be 100..600000")
            policy.latency_threshold_ms = v
        if "require_approval_for_writes" in data:
            if data["require_approval_for_writes"] is not True:
                return _bad("AI writes always need approval in FloBrain (Decision 33)")
        policy.updated_by, policy.updated_at = request.user, timezone.now()
        policy.save()
        audit(request.user, "pulse.routing_update", payload=_policy_payload(policy), request=request, org=org)
        return Response(_policy_payload(policy))


class RoutingPreviewView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Which model a platform request would use right now, and why")
    def get(self, request, org_id):
        from brain.llm import direct
        from brain.llm.policy import check_ai

        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        if check_ai(org, "direct"):
            return Response({"model": None, "reason": "Your org is private only and no self-hosted model is set up."})
        policy = RoutingPolicy.objects.filter(org=org).first()
        candidates = ([policy.primary_model] if policy and policy.primary_model else []) + (policy.fallback_models if policy else [])
        from django.conf import settings

        candidates = candidates or [getattr(settings, "AI_DIRECT_DEFAULT_MODEL", "") or (direct.allowlist() or [""])[0]]
        health = {r["model"]: r for r in metrics.models_table(org, 1)}
        steps = []
        for model in candidates:
            h = health.get(model)
            if h and h["error_rate"] > 0.5 and h["calls"] >= 5:
                steps.append({"model": model, "skipped": f"{round(h['error_rate'] * 100)}% errors in the last day"})
                continue
            if h and policy and policy.latency_threshold_ms and (h["latency_p95_ms"] or 0) > policy.latency_threshold_ms:
                steps.append({"model": model, "skipped": f"p95 latency {h['latency_p95_ms']} ms is over the threshold"})
                continue
            steps.append({"model": model, "chosen": True})
            return Response({"model": model, "steps": steps, "note": "Requests made with a member's own key are never routed."})
        return Response({"model": None, "steps": steps, "reason": "Every candidate is unhealthy."})


class AlertListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Alert rules")
    def get(self, request, org_id):
        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        return Response(
            [
                {"id": str(a.id), "metric": a.metric, "threshold": a.threshold, "window_minutes": a.window_minutes, "is_active": a.is_active, "last_fired_at": a.last_fired_at.isoformat() if a.last_fired_at else None}
                for a in AlertRule.objects.filter(org=org).order_by("metric")
            ]
        )

    @extend_schema(summary="Add an alert (owners and admins get a notification and an email)")
    def post(self, request, org_id):
        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        data = _body(request)
        metric, threshold, window = data.get("metric"), data.get("threshold"), data.get("window_minutes", 60)
        if metric not in AlertRule.METRICS:
            return _bad("metric must be error_rate, p95_latency_ms or daily_cost")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or threshold < 0:
            return _bad("threshold must be a positive number")
        if not isinstance(window, int) or isinstance(window, bool) or not 5 <= window <= 1440:
            return _bad("window_minutes must be 5..1440")
        rule = AlertRule.objects.create(org=org, metric=metric, threshold=float(threshold), window_minutes=window, created_by=request.user)
        return Response({"id": str(rule.id)}, status=201)


class AlertDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def delete(self, request, org_id, rule_id):
        org = _org(request, org_id)
        if not _admin(request, org):
            return _denied()
        AlertRule.objects.filter(org=org, pk=rule_id).delete()
        return Response(status=204)


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
