"""Run an eval set through a buddy in sandbox mode and score it.

``start()`` creates the ``EvalRun`` with a copy of the buddy settings it tests (so a queued run tests
exactly what was asked, including unsaved edits checked by the gate) and either runs it now
(``sync=True``, used by the gate) or queues ``evals.run``. ``execute()`` does the work:

1. Deterministic checks on every answer (``evals.checks``).
2. The AI judge for cases with a rubric (``evals.judge``), on the org's judge model.
3. A per-run cap (``EvalPolicy.max_run_tokens`` and ``max_run_cost``) on top of the org's AI budgets:
   once it is reached, the cases left are skipped and the run ends as ``stopped``.
4. At most ``EvalPolicy.concurrency`` cases at a time, on PostgreSQL outside a transaction only;
   otherwise one by one.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from django.db import close_old_connections, connection
from django.utils import timezone

from evals import checks, judge, sandbox
from evals.models import EvalPolicy, EvalRun

logger = logging.getLogger(__name__)

JOB = "evals.run"
MAX_CASES = 50


def policy_for(org) -> EvalPolicy:
    policy = EvalPolicy.objects.filter(org=org).first()
    return policy or EvalPolicy(org=org)


def judge_model(org) -> str | None:
    """The judge model the org chose, if it is still on the platform allowlist; None = routing decides."""
    from brain.llm.direct import allowlist

    chosen = (policy_for(org).judge_model or "").strip()
    return chosen if chosen and chosen in allowlist() else None


def version_label(buddy, fp: str) -> str:
    """"v3": the third different set of buddy settings evals have seen for this buddy."""
    known = EvalRun.objects.filter(buddy=buddy, fingerprint=fp).exclude(version_label="").values_list("version_label", flat=True).first()
    if known:
        return known
    distinct = EvalRun.objects.filter(buddy=buddy).values("fingerprint").distinct().count()
    return f"v{distinct + 1}"


def start(eval_set, user, triggered_by=EvalRun.MANUAL, *, buddy=None, gate_context="", sync=False) -> EvalRun:
    buddy = buddy if buddy is not None else eval_set.buddy
    config = sandbox.snapshot(buddy)
    fp = sandbox.fingerprint(config)
    run = EvalRun.objects.create(
        org=eval_set.org,
        eval_set=eval_set,
        buddy_id=eval_set.buddy_id,
        fingerprint=fp,
        version_label=version_label(eval_set.buddy, fp),
        config=config,
        threshold=eval_set.threshold,
        triggered_by=triggered_by,
        gate_context=gate_context,
        user=user,
    )
    if sync:
        execute(run.id)
    else:
        from jobs.queue import enqueue

        result = enqueue(JOB, {"run_id": str(run.id)})
        if isinstance(result, dict) and result.get("reason") == "unavailable":
            execute(run.id)  # no worker in this install: a bounded run (at most MAX_CASES) inline
    run.refresh_from_db()
    return run


class _Budget:
    """The per-run cap. Thread-safe: cases may finish in parallel."""

    def __init__(self, policy):
        self.max_tokens = int(policy.max_run_tokens or 0)
        self.max_cost = policy.max_run_cost
        self.tokens, self.cost = 0, Decimal("0")
        self.input_tokens = self.output_tokens = 0
        self.hit = ""  # "run_budget" | an org budget code
        self._lock = threading.Lock()

    def add(self, part):
        with self._lock:
            self.tokens += part.total_tokens or 0
            self.input_tokens += part.input_tokens or 0
            self.output_tokens += part.output_tokens or 0
            self.cost += part.cost or Decimal("0")
            if (self.max_tokens and self.tokens >= self.max_tokens) or (self.max_cost is not None and self.cost >= self.max_cost):
                self.hit = self.hit or "run_budget"

    def stop(self, code):
        with self._lock:
            self.hit = self.hit or code

    @property
    def exhausted(self) -> bool:
        return bool(self.hit)


class _Part:
    def __init__(self, result, cost):
        self.input_tokens = result.input_tokens or 0
        self.output_tokens = result.output_tokens or 0
        self.total_tokens = result.total_tokens or 0
        self.cost = cost


BUDGET_CODES = {"budget_exceeded", "run_budget"}


def _docs(user, org, case):
    from docs_app.models import Document
    from rooms.services import accessible_rooms

    ids = [str(i) for i in case.context_doc_ids or []]
    if not ids:
        return [], 0
    rooms = accessible_rooms(user, org).values("pk")
    found = {str(d.id): d for d in Document.objects.filter(org=org, pk__in=ids, room__in=rooms)}
    docs = [found[i] for i in ids if i in found]
    return docs, len(ids) - len(docs)


def _judge(user, org, case, answer, calls, budget, model):
    if budget.exhausted:
        return {"valid": False, "error": "skipped_budget"}
    msgs = judge.messages(case.input, case.rubric, answer, calls)
    try:
        result, cost, error = sandbox.call_model(user, org, msgs, model=model)
    except Exception:  # noqa: BLE001
        return {"valid": False, "error": "provider_error"}
    if error:
        if error in BUDGET_CODES:
            budget.stop(error)
        return {"valid": False, "error": error}
    budget.add(_Part(result, cost))
    if not result.ok:
        return {"valid": False, "error": result.error_code or "provider_error"}
    return judge.parse(result.text)


def _case(user, org, run, case, prepared, docs, missing, budget, jmodel) -> dict:
    row = {
        "case": str(case.id),
        "name": case.name,
        "input": case.input,
        # What the case asked for when it ran (the case may be edited later).
        "expect": {
            "must_include": list(case.must_include or []),
            "must_not_include": list(case.must_not_include or []),
            "must_cite": case.must_cite,
            "expected_tool": case.expected_tool,
            "forbidden_tools": list(case.forbidden_tools or []),
            "max_words": case.max_words,
            "language": case.language,
            "rubric": case.rubric,
        },
        "answer": "",
        "calls": [],
        "checks": [],
        "judge": None,
        "passed": False,
        "score": 0.0,
        "error": "",
        "sources": [str(d.id) for d in docs],
        "missing_sources": missing,
        "tokens": 0,
        "duration_ms": 0,
    }
    if budget.exhausted:
        row["error"] = "skipped_budget"
        return row
    started = time.monotonic()
    out = sandbox.turn(user, org, run.config, prepared, case.input, docs)
    budget.add(out)
    if out.error:
        if out.error in BUDGET_CODES:
            budget.stop(out.error)
        row.update(error=out.error, duration_ms=int((time.monotonic() - started) * 1000))
        return row
    row["answer"], row["calls"] = out.text, out.calls
    row["checks"] = checks.run_checks(case, out.text, out.calls)
    if (case.rubric or "").strip():
        row["judge"] = _judge(user, org, case, out.text, out.calls, budget, jmodel)
    row["score"] = round(checks.case_score(row["checks"], row["judge"]), 4)
    row["passed"] = checks.case_passed(row["checks"], row["judge"])
    row["tokens"] = out.total_tokens
    row["model"] = out.model
    row["duration_ms"] = int((time.monotonic() - started) * 1000)
    return row


def _parallel(policy) -> int:
    workers = max(1, min(int(policy.concurrency or 1), 8))
    if workers == 1 or connection.vendor == "sqlite" or connection.in_atomic_block:
        return 1  # worker threads use their own connections: they can't see uncommitted rows
    return workers


def execute(run_id) -> EvalRun | None:
    run = EvalRun.objects.select_related("eval_set", "org", "user").filter(pk=run_id).first()
    if run is None or run.status != EvalRun.QUEUED:
        return run
    if not EvalRun.objects.filter(pk=run.pk, status=EvalRun.QUEUED).update(status=EvalRun.RUNNING, started_at=timezone.now()):
        return run  # another worker took it
    began = time.monotonic()
    org, user = run.org, run.user
    try:
        cases = list(run.eval_set.cases.all()[:MAX_CASES])
        policy = policy_for(org)
        prepared = sandbox.prepare(user, org, run.config) if user is not None else sandbox.Prepared(error="no_user")
        if prepared.error:
            _finish(run, EvalRun.ERROR, [], _Budget(policy), began, error=prepared.error)
            return run
        budget = _Budget(policy)
        jmodel = judge_model(org)
        inputs = [(case, *_docs(user, org, case)) for case in cases]

        def one(item):
            case, docs, missing = item
            return _case(user, org, run, case, prepared, docs, missing, budget, jmodel)

        workers = _parallel(policy)
        if workers == 1:
            results = [one(item) for item in inputs]
        else:
            def threaded(item):
                try:
                    return one(item)
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(threaded, inputs))
        status = EvalRun.STOPPED if budget.exhausted and any(r["error"] in BUDGET_CODES | {"skipped_budget"} for r in results) else EvalRun.DONE
        if results and all(r["error"] and r["error"] not in BUDGET_CODES | {"skipped_budget"} for r in results):
            status = EvalRun.ERROR
        error = budget.hit if status == EvalRun.STOPPED else (results[0]["error"] if status == EvalRun.ERROR else "")
        _finish(run, status, results, budget, began, error=error)
    except Exception:  # noqa: BLE001 - a run must end in a state, never stay "running"
        logger.exception("eval run %s failed", run.id)
        _finish(run, EvalRun.ERROR, [], None, began, error="internal_error")
    return run


def _finish(run, status, results, budget, began, error=""):
    run.status = status
    run.results = results
    run.cases_total = len(results)
    run.cases_passed = sum(1 for r in results if r["passed"])
    if results and status != EvalRun.ERROR:
        run.score = Decimal(str(round(100 * sum(r["score"] for r in results) / len(results), 1)))
    else:
        run.score = None
    run.passed = bool(status == EvalRun.DONE and run.score is not None and run.score >= run.threshold)
    if budget is not None:
        run.input_tokens, run.output_tokens, run.total_tokens = budget.input_tokens, budget.output_tokens, budget.tokens
        run.cost = budget.cost.quantize(Decimal("0.0001"))
    models = sorted({r.get("model") for r in results if r.get("model")})
    run.model = ", ".join(models)[:128]
    run.judge_model = judge_model(run.org) or ""
    run.error = (error or "")[:200]
    run.duration_ms = int((time.monotonic() - began) * 1000)
    run.finished_at = timezone.now()
    run.save()


def run_job(payload):
    return execute(payload.get("run_id"))
