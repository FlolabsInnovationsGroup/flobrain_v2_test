"""Buddy evals API (market round M5). Flags ``buddies`` and ``buddy_evals`` (501 when off),
permission ``evals.manage`` (403). A buddy is only reachable here when the person may use or edit it.

- ``GET  /orgs/{org}/evals/overview``: buddies you can evaluate with their latest score; actions and judge models
- ``GET|POST /orgs/{org}/evals/sets`` (``?buddy=``); ``GET|PATCH|DELETE /orgs/{org}/evals/sets/{set}``
- ``POST /orgs/{org}/evals/sets/{set}/cases`` (one case, or ``{"cases": [...]}``); ``PATCH|DELETE /orgs/{org}/evals/cases/{case}``
- ``POST /orgs/{org}/evals/sets/{set}/suggest``: AI-drafted cases, not saved
- ``GET|POST /orgs/{org}/evals/sets/{set}/runs``: history, or run now; ``GET /orgs/{org}/evals/runs/{run}``: per-case results
- ``POST /orgs/{org}/evals/gate-check`` ``{buddy, changes?}``: what the gate would say (nothing is saved or accepted)
- ``GET  /orgs/{org}/evals/gate-events?buddy=``: gate history
- ``GET|PUT /orgs/{org}/evals/settings``: judge model, per-run budget, concurrency
- ``GET  /orgs/{org}/evals/documents?q=``: documents you can open, for a case's sources
"""

import uuid

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from brain.throttles import AISendThrottle
from core_v2.throttles import V2UserThrottle
from core_v2.views import V2APIView
from evals import gate, runner, sandbox, suggest
from evals.models import EvalCase, EvalGateEvent, EvalPolicy, EvalRun, EvalSet
from evals.validation import CaseInvalid, clean_case, clean_policy, clean_set
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from organizations.permissions import HasPerm, IsActiveOrgMember, can
from organizations.services.core import audit

PERM = "evals.manage"
MAX_CASES_PER_SET = runner.MAX_CASES


def _gate(request, view, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    membership = OrgMembership.objects.filter(org=org, user=request.user).first()
    for flag, label in (("buddies", "Buddies are not enabled"), (gate.FLAG, "Buddy evals are not enabled")):
        if not effective_flag(org, membership, flag, default=False):
            return org, Response({"error": "not_implemented", "details": label}, status=501)
    HasPerm(PERM).has_permission(request, view)
    return org, None


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _invalid(details):
    return Response({"error": "invalid", "details": str(details)}, status=400)


def _not_found(what="Not found"):
    return Response({"error": "not_found", "details": what}, status=404)


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def evaluable(user, org):
    """Buddies this person may evaluate: ones they can use or edit (never Flo, which only routes)."""
    from buddies.models import Buddy
    from buddies.services import visible_buddies

    buddies = Buddy.objects.filter(org=org).exclude(is_builtin=True, slug="flo")
    if can(user, "buddy.manage", org):
        return buddies
    return buddies.filter(Q(pk__in=visible_buddies(user, org).values("pk")) | Q(created_by=user))


def _set_for(request, org, set_id):
    eval_set = EvalSet.objects.filter(org=org, pk=set_id).select_related("buddy", "baseline_run").first()
    if eval_set is None or not evaluable(request.user, org).filter(pk=eval_set.buddy_id).exists():
        return None
    return eval_set


def _person(user):
    return {"id": str(user.id), "name": user.username or user.email} if user else None


def run_summary(run) -> dict:
    return {
        "id": str(run.id),
        "set": str(run.eval_set_id),
        "buddy": str(run.buddy_id),
        "status": run.status,
        "passed": run.passed,
        "score": float(run.score) if run.score is not None else None,
        "threshold": run.threshold,
        "cases_total": run.cases_total,
        "cases_passed": run.cases_passed,
        "version": run.version_label,
        "fingerprint": run.fingerprint[:12],
        "tools": list((run.config or {}).get("allowed_tools") or []),
        "model": run.model,
        "judge_model": run.judge_model,
        "tokens": run.total_tokens,
        "cost": str(run.cost),
        "duration_ms": run.duration_ms,
        "triggered_by": run.triggered_by,
        "gate_context": run.gate_context,
        "error": run.error,
        "by": _person(run.user),
        "created_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _readable_docs(user, org, ids):
    from docs_app.models import Document
    from rooms.services import accessible_rooms

    if not ids:
        return {}
    rooms = accessible_rooms(user, org).values("pk")
    return {str(d.id): d.title for d in Document.objects.filter(org=org, pk__in=list(ids), room__in=rooms).only("id", "title")}


def run_detail(run, user) -> dict:
    """Per-case results. An answer built from a document the viewer can't open is hidden."""
    data = run_summary(run)
    ids = {s for r in run.results or [] for s in r.get("sources") or []}
    readable = _readable_docs(user, run.org, ids)
    rows = []
    for r in run.results or []:
        row = dict(r)
        row.pop("model", None)
        if any(s not in readable for s in r.get("sources") or []):
            row.update(answer="", calls=[], hidden=True)
            if row.get("judge"):
                row["judge"] = {**row["judge"], "reason": ""}
        row["sources"] = [{"id": s, "title": readable.get(s, "")} for s in r.get("sources") or []]
        rows.append(row)
    data["results"] = rows
    previous = gate.previous_run(run.eval_set, run.fingerprint)
    data["previous"] = run_summary(previous) if previous is not None and previous.created_at < run.created_at else None
    if data["previous"]:
        data["previous_results"] = {r["case"]: {"passed": r.get("passed"), "score": r.get("score")} for r in previous.results or []}
    return data


def case_payload(case, titles=None) -> dict:
    return {
        "id": str(case.id),
        "set": str(case.eval_set_id),
        "position": case.position,
        "name": case.name,
        "input": case.input,
        "context_doc_ids": case.context_doc_ids or [],
        "context_docs": [{"id": d, "title": (titles or {}).get(d, "")} for d in case.context_doc_ids or []],
        "must_include": case.must_include or [],
        "must_not_include": case.must_not_include or [],
        "must_cite": case.must_cite,
        "expected_tool": case.expected_tool,
        "forbidden_tools": case.forbidden_tools or [],
        "max_words": case.max_words,
        "language": case.language,
        "rubric": case.rubric,
        "updated_at": case.updated_at.isoformat(),
    }


def set_payload(eval_set, full=False, user=None) -> dict:
    latest = eval_set.runs.exclude(status__in=[EvalRun.QUEUED, EvalRun.RUNNING]).order_by("-created_at").first()
    baseline = eval_set.baseline_run
    data = {
        "id": str(eval_set.id),
        "buddy": {"id": str(eval_set.buddy_id), "name": eval_set.buddy.name, "icon": eval_set.buddy.icon},
        "name": eval_set.name,
        "description": eval_set.description,
        "threshold": eval_set.threshold,
        "max_drop": eval_set.max_drop,
        "gate_marketplace": eval_set.gate_marketplace,
        "gate_saves": eval_set.gate_saves,
        "schedule": eval_set.schedule,
        "cases_count": eval_set.cases.count(),
        "latest_run": run_summary(latest) if latest else None,
        "baseline": {"run": str(baseline.id), "score": float(baseline.score) if baseline.score is not None else None, "version": baseline.version_label} if baseline else None,
        "current_fingerprint": sandbox.fingerprint(sandbox.snapshot(eval_set.buddy))[:12],
        "created_at": eval_set.created_at.isoformat(),
    }
    if full:
        cases = list(eval_set.cases.all())
        titles = _readable_docs(user, eval_set.org, {d for c in cases for d in c.context_doc_ids or []}) if user else {}
        data["cases"] = [case_payload(c, titles) for c in cases]
        data["trend"] = [
            {"run": str(r.id), "at": r.created_at.isoformat(), "score": float(r.score), "passed": r.passed,
             "version": r.version_label, "triggered_by": r.triggered_by}
            for r in reversed(list(eval_set.runs.filter(score__isnull=False).order_by("-created_at")[:30]))
        ]
    return data


def _touch(eval_set):
    """Case edits make earlier runs stale for the gate's reuse."""
    EvalSet.objects.filter(pk=eval_set.pk).update(updated_at=timezone.now())


class OverviewView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Buddies you can evaluate, their sets and latest scores")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        from actions.registry import TOOLS
        from brain.llm.direct import allowlist

        buddies = list(evaluable(request.user, org).order_by("position", "name"))
        sets = EvalSet.objects.filter(org=org, buddy__in=buddies)
        counts, latest = {}, {}
        for s in sets:
            counts[s.buddy_id] = counts.get(s.buddy_id, 0) + 1
        for run in EvalRun.objects.filter(org=org, buddy__in=buddies, score__isnull=False).order_by("-created_at")[:500]:
            latest.setdefault(run.buddy_id, run)
        return Response({
            "buddies": [
                {
                    "id": str(b.id),
                    "name": b.name,
                    "icon": b.icon,
                    "builtin": b.is_builtin,
                    "sets": counts.get(b.id, 0),
                    "latest": {"score": float(latest[b.id].score), "passed": latest[b.id].passed, "at": latest[b.id].created_at.isoformat()} if b.id in latest else None,
                }
                for b in buddies
            ],
            "tools": [{"key": k, "label": t.get("label", k)} for k, t in sorted(TOOLS.items())],
            "judge_models": allowlist(),
        })


class SetListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Eval sets (filter with ?buddy=)")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        sets = EvalSet.objects.filter(org=org, buddy__in=evaluable(request.user, org)).select_related("buddy", "baseline_run")
        buddy = request.query_params.get("buddy")
        if buddy:
            if _uuid(buddy) is None:
                return _invalid("buddy must be an id")
            sets = sets.filter(buddy_id=buddy)
        return Response([set_payload(s) for s in sets[:200]])

    @extend_schema(summary="Create an eval set for a buddy")
    def post(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        data = _body(request)
        buddy_id = _uuid(data.get("buddy"))
        buddy = evaluable(request.user, org).filter(pk=buddy_id).first() if buddy_id else None
        if buddy is None:
            return _not_found("Buddy not found")
        try:
            fields = clean_set(data)
        except CaseInvalid as exc:
            return _invalid(exc)
        eval_set = EvalSet.objects.create(org=org, buddy=buddy, created_by=request.user, **fields)
        audit(request.user, "evals.set.create", target=eval_set, payload={"buddy": str(buddy.id)}, request=request, org=org)
        return Response(set_payload(eval_set, full=True, user=request.user), status=201)


class SetDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="An eval set with its cases and score trend")
    def get(self, request, org_id, set_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        eval_set = _set_for(request, org, set_id)
        if eval_set is None:
            return _not_found()
        return Response(set_payload(eval_set, full=True, user=request.user))

    @extend_schema(summary="Change an eval set's name, pass mark or gate settings")
    def patch(self, request, org_id, set_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        eval_set = _set_for(request, org, set_id)
        if eval_set is None:
            return _not_found()
        try:
            fields = clean_set(_body(request), partial=True)
        except CaseInvalid as exc:
            return _invalid(exc)
        for key, value in fields.items():
            setattr(eval_set, key, value)
        eval_set.save()
        audit(request.user, "evals.set.update", target=eval_set, payload={"fields": sorted(fields)}, request=request, org=org)
        return Response(set_payload(eval_set, full=True, user=request.user))

    @extend_schema(summary="Delete an eval set, its cases and runs")
    def delete(self, request, org_id, set_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        eval_set = _set_for(request, org, set_id)
        if eval_set is None:
            return _not_found()
        audit(request.user, "evals.set.delete", target=eval_set, payload={"name": eval_set.name}, request=request, org=org)
        eval_set.delete()
        return Response(status=204)


class CaseListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Add one case, or several reviewed suggestions with {cases: [...]}")
    def post(self, request, org_id, set_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        eval_set = _set_for(request, org, set_id)
        if eval_set is None:
            return _not_found()
        data = _body(request)
        items = data.get("cases") if "cases" in data else [data]
        if not isinstance(items, list) or not items:
            return _invalid("cases must be a non-empty list")
        existing = eval_set.cases.count()
        if existing + len(items) > MAX_CASES_PER_SET:
            return _invalid(f"a set has at most {MAX_CASES_PER_SET} cases")
        try:
            cleaned = [clean_case(item, request.user, org) for item in items]
        except CaseInvalid as exc:
            return _invalid(exc)
        with transaction.atomic():
            made = []
            for n, fields in enumerate(cleaned):
                fields.setdefault("position", existing + n)
                made.append(EvalCase.objects.create(eval_set=eval_set, created_by=request.user, **fields))
        _touch(eval_set)
        audit(request.user, "evals.case.create", target=eval_set, payload={"count": len(made)}, request=request, org=org)
        titles = _readable_docs(request.user, org, {d for c in made for d in c.context_doc_ids or []})
        body = [case_payload(c, titles) for c in made]
        return Response(body if "cases" in data else body[0], status=201)


class CaseDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def _case(self, request, org, case_id):
        case = EvalCase.objects.filter(pk=case_id, eval_set__org=org).select_related("eval_set").first()
        if case is None or _set_for(request, org, case.eval_set_id) is None:
            return None
        return case

    @extend_schema(summary="Edit a case")
    def patch(self, request, org_id, case_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        case = self._case(request, org, case_id)
        if case is None:
            return _not_found()
        data = _body(request)
        try:
            fields = clean_case(data, request.user, org, partial=True)
            # Expected and forbidden are checked together, against the case as it will be.
            merged = {"expected_tool": fields.get("expected_tool", case.expected_tool), "forbidden_tools": fields.get("forbidden_tools", case.forbidden_tools)}
            clean_case({"input": "x", **merged}, request.user, org, check_docs=False)
        except CaseInvalid as exc:
            return _invalid(exc)
        for key, value in fields.items():
            setattr(case, key, value)
        case.save()
        _touch(case.eval_set)
        audit(request.user, "evals.case.update", target=case, payload={"fields": sorted(fields)}, request=request, org=org)
        titles = _readable_docs(request.user, org, set(case.context_doc_ids or []))
        return Response(case_payload(case, titles))

    @extend_schema(summary="Delete a case")
    def delete(self, request, org_id, case_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        case = self._case(request, org, case_id)
        if case is None:
            return _not_found()
        eval_set = case.eval_set
        audit(request.user, "evals.case.delete", target=eval_set, payload={"case": str(case.id)}, request=request, org=org)
        case.delete()
        _touch(eval_set)
        return Response(status=204)


class SuggestView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    throttle_classes = [V2UserThrottle, AISendThrottle]

    @extend_schema(summary="AI-drafted cases from the buddy's description, starter prompts and not-helpful reasons (not saved)")
    def post(self, request, org_id, set_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        eval_set = _set_for(request, org, set_id)
        if eval_set is None:
            return _not_found()
        from brain.llm import direct
        from brain.llm.policy import check_ai

        if not direct.is_configured():
            return Response({"error": "not_configured", "details": "No AI provider is set up"}, status=501)
        if check_ai(org, "direct"):
            return Response({"error": "private_only", "details": "This organization only allows self-hosted models"}, status=409)
        buddy = eval_set.buddy
        reasons = suggest.not_helpful_reasons(buddy)
        result, _, code = sandbox.call_model(request.user, org, suggest.messages(buddy, reasons), model=runner.judge_model(org))
        if code:
            return Response({"error": code, "details": "Your AI budget is used up"}, status=429)
        if not result.ok:
            return Response({"error": result.error_code or "provider_error", "details": "The AI did not answer"}, status=502)
        cases = suggest.parse(result.text)
        if not cases:
            return Response({"error": "bad_model_output", "details": "The AI did not suggest usable cases. Try again."}, status=502)
        return Response({"cases": cases, "reasons": reasons})


class RunListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get_throttles(self):
        if self.request.method == "POST":
            return [V2UserThrottle(), AISendThrottle()]
        return [V2UserThrottle()]

    @extend_schema(summary="Run history of a set")
    def get(self, request, org_id, set_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        eval_set = _set_for(request, org, set_id)
        if eval_set is None:
            return _not_found()
        return Response([run_summary(r) for r in eval_set.runs.select_related("user")[:100]])

    @extend_schema(summary="Run the set now in sandbox mode (nothing is executed or saved outside the run)")
    def post(self, request, org_id, set_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        eval_set = _set_for(request, org, set_id)
        if eval_set is None:
            return _not_found()
        if not eval_set.cases.exists():
            return _invalid("add at least one case first")
        if eval_set.runs.filter(status__in=[EvalRun.QUEUED, EvalRun.RUNNING]).exists():
            return Response({"error": "conflict", "details": "A run of this set is already going"}, status=409)
        run = runner.start(eval_set, request.user, EvalRun.MANUAL)
        audit(request.user, "evals.run", target=run, payload={"set": str(eval_set.id), "status": run.status}, request=request, org=org)
        return Response(run_summary(run), status=201)


class RunDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="One run with expected vs got for each case")
    def get(self, request, org_id, run_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        run = EvalRun.objects.filter(org=org, pk=run_id).select_related("eval_set", "user", "org").first()
        if run is None or _set_for(request, org, run.eval_set_id) is None:
            return _not_found()
        return Response(run_detail(run, request.user))


class GateCheckView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    throttle_classes = [V2UserThrottle, AISendThrottle]

    @extend_schema(summary="What the gate would say for a buddy, optionally with unsaved changes (nothing is saved)")
    def post(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        data = _body(request)
        buddy_id = _uuid(data.get("buddy"))
        buddy = evaluable(request.user, org).filter(pk=buddy_id).first() if buddy_id else None
        if buddy is None:
            return _not_found("Buddy not found")
        changes = data.get("changes") or {}
        if not isinstance(changes, dict):
            return _invalid("changes must be an object")
        if changes:
            from buddies.services import BuddyInvalid, clean_definition

            allowed = {k: v for k, v in changes.items() if k in sandbox.BEHAVIOUR_FIELDS}
            try:
                fields = clean_definition(request.user, org, allowed, partial=True)
            except BuddyInvalid as exc:
                return _invalid(exc)
            for key, value in fields.items():
                setattr(buddy, key, value)  # in memory only, never saved
        result = gate.check(buddy, request.user, context=EvalGateEvent.CHECK, record=False)
        return Response(result.payload())


class GateEventListView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Gate history: passes, blocks and overrides")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        events = EvalGateEvent.objects.filter(org=org, buddy__in=evaluable(request.user, org)).select_related("user", "buddy")
        buddy = request.query_params.get("buddy")
        if buddy:
            if _uuid(buddy) is None:
                return _invalid("buddy must be an id")
            events = events.filter(buddy_id=buddy)
        return Response([
            {
                "id": str(e.id),
                "buddy": {"id": str(e.buddy_id), "name": e.buddy.name},
                "context": e.context,
                "outcome": e.outcome,
                "details": e.details,
                "override_reason": e.override_reason,
                "by": _person(e.user),
                "created_at": e.created_at.isoformat(),
            }
            for e in events[:100]
        ])


def policy_payload(policy) -> dict:
    return {
        "judge_model": policy.judge_model,
        "max_run_tokens": policy.max_run_tokens,
        "max_run_cost": str(policy.max_run_cost) if policy.max_run_cost is not None else None,
        "concurrency": policy.concurrency,
    }


class SettingsView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Org eval settings")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        return Response(policy_payload(runner.policy_for(org)))

    @extend_schema(summary="Change the judge model, per-run budget or concurrency")
    def put(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        try:
            fields = clean_policy(_body(request))
        except CaseInvalid as exc:
            return _invalid(exc)
        policy, _ = EvalPolicy.objects.get_or_create(org=org)
        for key, value in fields.items():
            setattr(policy, key, value)
        policy.updated_by = request.user
        policy.save()
        audit(request.user, "evals.settings", target=org, payload={"fields": sorted(fields)}, request=request, org=org)
        return Response(policy_payload(policy))


class DocumentPickView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Documents you can open, to give a case as sources")
    def get(self, request, org_id):
        org, error = _gate(request, self, org_id)
        if error:
            return error
        from docs_app.models import Document
        from rooms.services import accessible_rooms

        docs = Document.objects.filter(org=org, room__in=accessible_rooms(request.user, org).values("pk"))
        q = str(request.query_params.get("q") or "").strip()[:100]
        if q:
            docs = docs.filter(title__icontains=q)
        return Response([{"id": str(d.id), "title": d.title} for d in docs.order_by("-updated_at").only("id", "title")[:20]])
