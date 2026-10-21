"""The quality gate: a buddy must pass its eval sets before it is offered or changed.

``check(buddy, user, context=...)`` runs every set of the buddy that guards this context
(``gate_marketplace`` for a marketplace submit or new version, ``gate_saves`` for a buddy edit) and
returns a ``GateResult``. A set blocks when its score is under the set's pass mark, when it is more
than ``max_drop`` points under the last accepted run (the previous version), or when it could not
finish. A run of the same buddy settings from the last 7 days is reused instead of running again.

Someone with ``evals.manage`` can override a block with a reason; the override is audited and the
run becomes the new accepted baseline, like a pass. Everything is a no-op (allowed) while the
``buddy_evals`` flag is off for that person or the buddy has no gating set with cases.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from evals import runner, sandbox
from evals.models import EvalGateEvent, EvalRun, EvalSet

FLAG = "buddy_evals"
REUSE_DAYS = 7
MIN_REASON = 10


@dataclass
class GateResult:
    allowed: bool
    outcome: str  # "skipped" | "passed" | "blocked" | "overridden"
    sets: list = field(default_factory=list)
    message: str = ""
    event: str | None = None
    override_error: str = ""

    def payload(self) -> dict:
        return {
            "allowed": self.allowed,
            "outcome": self.outcome,
            "message": self.message,
            "sets": self.sets,
            "event": self.event,
            "override_error": self.override_error,
        }


def enabled_for(org, user) -> bool:
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership

    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return bool(effective_flag(org, membership, FLAG, default=False))


def _gating_sets(buddy, context):
    sets = EvalSet.objects.filter(org_id=buddy.org_id, buddy_id=buddy.id)
    if context == EvalGateEvent.SAVE:
        sets = sets.filter(gate_saves=True)
    elif context == EvalGateEvent.MARKETPLACE:
        sets = sets.filter(gate_marketplace=True)
    # A preview ("check") looks at every set that guards something.
    else:
        sets = sets.filter(Q(gate_saves=True) | Q(gate_marketplace=True))
    return [s for s in sets.order_by("name") if s.cases.exists()]


def previous_run(eval_set, fingerprint):
    """The last accepted run, or else the newest finished run of different settings."""
    if eval_set.baseline_run_id and eval_set.baseline_run and eval_set.baseline_run.fingerprint != fingerprint:
        return eval_set.baseline_run
    return (
        EvalRun.objects.filter(eval_set=eval_set, status=EvalRun.DONE, score__isnull=False)
        .exclude(fingerprint=fingerprint)
        .order_by("-created_at")
        .first()
    )


def _run_for(eval_set, buddy, user, context, reuse):
    fp = sandbox.fingerprint(sandbox.snapshot(buddy))
    if reuse:
        since = timezone.now() - timedelta(days=REUSE_DAYS)
        cached = (
            EvalRun.objects.filter(
                eval_set=eval_set, fingerprint=fp, status=EvalRun.DONE, created_at__gte=since, finished_at__gte=eval_set.updated_at
            )
            .order_by("-created_at")
            .first()
        )
        if cached is not None:
            return cached, True
    return runner.start(eval_set, user, EvalRun.GATE, buddy=buddy, gate_context=context, sync=True), False


def _verdict(eval_set, run, reused):
    previous = previous_run(eval_set, run.fingerprint)
    prev_score = float(previous.score) if previous is not None and previous.score is not None else None
    score = float(run.score) if run.score is not None else None
    row = {
        "set": str(eval_set.id),
        "name": eval_set.name,
        "run": str(run.id),
        "reused": reused,
        "status": run.status,
        "score": score,
        "threshold": eval_set.threshold,
        "previous": prev_score,
        "previous_run": str(previous.id) if previous is not None else None,
        "max_drop": eval_set.max_drop,
        "cases_passed": run.cases_passed,
        "cases_total": run.cases_total,
        "failed_cases": [r.get("name") or r.get("input", "")[:60] for r in run.results or [] if not r.get("passed")][:10],
        "passed": False,
        "reason": "",
    }
    if run.status != EvalRun.DONE or score is None:
        row["reason"] = f"The checks could not finish ({run.error or run.status})."
    elif score < eval_set.threshold:
        row["reason"] = f"Score {score:g}% is below the pass mark of {eval_set.threshold}%."
    elif prev_score is not None and prev_score - score > eval_set.max_drop:
        row["reason"] = f"Score {score:g}% is {prev_score - score:.1f} points below the previous version ({prev_score:g}%)."
    else:
        row["passed"] = True
    return row


def check(buddy, user, *, context=EvalGateEvent.MARKETPLACE, override_reason=None, request=None, reuse=True, record=True) -> GateResult:
    """Run the gate for ``buddy`` as it is in memory (unsaved edits included)."""
    from organizations.permissions import can
    from organizations.services.core import audit

    org = buddy.org
    if not enabled_for(org, user):
        return GateResult(True, "skipped", message="Evals are off.")
    sets = _gating_sets(buddy, context)
    if not sets:
        return GateResult(True, "skipped", message="No eval set guards this buddy.")
    rows, runs = [], {}
    for eval_set in sets:
        run, reused = _run_for(eval_set, buddy, user, context, reuse)
        runs[eval_set.id] = (eval_set, run)
        rows.append(_verdict(eval_set, run, reused))
    blocked = [r for r in rows if not r["passed"]]
    if not blocked:
        result = GateResult(True, "passed", rows, "All eval sets passed.")
    else:
        names = "; ".join(f"{r['name']}: {r['reason']}" for r in blocked)
        result = GateResult(False, "blocked", rows, f"Blocked by evals. {names}")
        reason = str(override_reason or "").strip()
        if reason:
            if not can(user, "evals.manage", org):
                result.override_error = "Only someone who manages evals can override."
            elif len(reason) < MIN_REASON:
                result.override_error = f"Say why in at least {MIN_REASON} characters."
            else:
                result = GateResult(True, "overridden", rows, f"Override accepted. {names}")
    if not record or context == EvalGateEvent.CHECK:
        return result
    if result.allowed:
        for eval_set, run in runs.values():
            if run.status == EvalRun.DONE:
                EvalSet.objects.filter(pk=eval_set.pk).update(baseline_run=run)
    event = EvalGateEvent.objects.create(
        org=org,
        buddy_id=buddy.id,
        context=context,
        outcome=result.outcome,
        details=rows,
        override_reason=(str(override_reason or "").strip()[:500] if result.outcome == "overridden" else ""),
        user=user,
    )
    result.event = str(event.id)
    audit(
        user,
        f"evals.gate.{result.outcome}",
        target=event,
        payload={
            "buddy": str(buddy.id),
            "context": context,
            "sets": [{"set": r["set"], "score": r["score"], "previous": r["previous"], "passed": r["passed"]} for r in rows],
            **({"reason": event.override_reason} if result.outcome == "overridden" else {}),
        },
        request=request,
        org=org,
    )
    return result


def blocked_response(result: GateResult):
    from rest_framework.response import Response

    return Response(
        {"error": "eval_gate_failed", "details": result.message + (f" {result.override_error}" if result.override_error else ""), "gate": result.payload()},
        status=409,
    )


def marketplace_block(request, org, buddy):
    """For ``marketplace.views``: None when the submit may go ahead, else the 409 to return.
    An ``evals.manage`` holder overrides with ``{"eval_override_reason": "..."}`` in the body."""
    data = request.data if isinstance(request.data, dict) else {}
    result = check(buddy, request.user, context=EvalGateEvent.MARKETPLACE, override_reason=data.get("eval_override_reason"), request=request)
    return None if result.allowed else blocked_response(result)


def buddy_save_block(request, org, buddy, fields):
    """For the buddy edit (``buddies.views.BuddyDetailView.patch``), called after the new values are
    set on ``buddy`` and before ``buddy.save()``. Only edits to behaviour are checked."""
    if not set(fields) & set(sandbox.BEHAVIOUR_FIELDS):
        return None
    data = request.data if isinstance(request.data, dict) else {}
    result = check(buddy, request.user, context=EvalGateEvent.SAVE, override_reason=data.get("eval_override_reason"), request=request)
    return None if result.allowed else blocked_response(result)
