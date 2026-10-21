"""Buddy evals in the demo (market round M5).

- Four short demo documents (an NDA, a contractor agreement, a sign-ups report and a funnel) in the
  "Mobile app launch" room, used as case sources.
- One eval set each for the Legal, Data and Sales buddies (7 to 8 cases), with the org eval settings.
- Five past runs per set over three weeks. Sales run 4 tested a "more proactive" prompt for a new
  marketplace version: it scored far below the previous version, so the gate blocked it (a gate event
  with the report); run 5 is the fixed version that passed and is the current buddy.
Results are computed with the real checks from the scripted demo answers in ``evals.demo_data``.
"""

import hashlib
from datetime import timedelta
from decimal import Decimal


def _room(org):
    from rooms.models import Room

    return Room.objects.filter(org=org, name="Mobile app launch").first() or Room.objects.filter(org=org).exclude(kind="direct").first()


def _docs(org, admin):
    from docs_app.models import Document, DocumentRevision

    from evals.demo_data import DOCS

    room = _room(org)
    out = {}
    if room is None:
        return out
    for key, (title, text) in DOCS.items():
        doc = Document.objects.create(org=org, room=room, title=title, content_text=text, created_by=admin)
        DocumentRevision.objects.create(document=doc, version=1, content_text=text, created_by=admin)
        out[key] = doc
    return out


class _Case:
    """Enough of an EvalCase for ``evals.checks``."""

    def __init__(self, spec):
        self.must_include = spec.get("must_include", [])
        self.must_not_include = spec.get("must_not_include", [])
        self.must_cite = spec.get("must_cite", False)
        self.expected_tool = spec.get("expected_tool", "")
        self.forbidden_tools = spec.get("forbidden_tools", [])
        self.max_words = spec.get("max_words")
        self.language = spec.get("language", "any")


def _results(cases, specs, weak, docs):
    from evals import checks

    rows = []
    for n, (case, spec) in enumerate(zip(cases, specs)):
        text, calls, verdict = spec["weak" if n in weak else "good"]
        found = checks.run_checks(_Case(spec), text, calls)
        judge = {"valid": True, **verdict} if spec.get("rubric") else None
        tokens = 300 + len(text.split()) * 2
        rows.append({
            "case": str(case.id),
            "name": case.name,
            "input": case.input,
            "expect": {
                "must_include": case.must_include, "must_not_include": case.must_not_include, "must_cite": case.must_cite,
                "expected_tool": case.expected_tool, "forbidden_tools": case.forbidden_tools, "max_words": case.max_words,
                "language": case.language, "rubric": case.rubric,
            },
            "answer": text,
            "calls": [{"tool": c["tool"], "args": c["args"], "offered": True, "valid": True} for c in calls],
            "checks": found,
            "judge": judge,
            "passed": checks.case_passed(found, judge),
            "score": round(checks.case_score(found, judge), 4),
            "error": "",
            "sources": [str(docs[k].id) for k in spec.get("docs", []) if k in docs],
            "missing_sources": 0,
            "tokens": tokens,
            "duration_ms": 900 + 37 * len(text.split()),
            "model": "flobrain-demo",
        })
    return rows


def seed(org, users, now):
    from buddies.models import Buddy
    from organizations.services.core import audit

    from evals import sandbox
    from evals.demo_data import SETS
    from evals.models import EvalCase, EvalGateEvent, EvalPolicy, EvalRun, EvalSet

    admin = users["admin"]
    EvalPolicy.objects.update_or_create(org=org, defaults={"max_run_tokens": 60000, "max_run_cost": Decimal("1.0000"), "concurrency": 3, "updated_by": admin})
    docs = _docs(org, admin)
    for slug, spec in SETS.items():
        buddy = Buddy.objects.filter(org=org, slug=slug).first()
        if buddy is None:
            continue
        first_at = now - timedelta(days=spec["history"][0][2] + 1)
        eval_set = EvalSet.objects.create(
            org=org, buddy=buddy, name=spec["name"], description=spec["description"], threshold=spec["threshold"],
            max_drop=spec.get("max_drop", 5), gate_marketplace=True, gate_saves=spec.get("gate_saves", False),
            schedule=EvalSet.SCHEDULE_WEEKLY, last_scheduled_at=now - timedelta(days=2), created_by=admin, created_at=first_at,
        )
        cases = []
        for n, c in enumerate(spec["cases"]):
            cases.append(EvalCase.objects.create(
                eval_set=eval_set, position=n, name=c["name"], input=c["input"],
                context_doc_ids=[str(docs[k].id) for k in c.get("docs", []) if k in docs],
                must_include=c.get("must_include", []), must_not_include=c.get("must_not_include", []),
                must_cite=c.get("must_cite", False), expected_tool=c.get("expected_tool", ""),
                forbidden_tools=c.get("forbidden_tools", []), max_words=c.get("max_words"),
                language=c.get("language", "any"), rubric=c.get("rubric", ""), created_by=admin, created_at=first_at,
            ))
        config = sandbox.snapshot(buddy)
        current_fp = sandbox.fingerprint(config)
        current_version = spec["history"][-1][1]
        runs, baseline = [], None
        for index, (weak, version, days_ago) in enumerate(spec["history"]):
            at = now - timedelta(days=days_ago, hours=3)
            fp = current_fp if version == current_version else hashlib.sha256(f"demo:{slug}:{version}".encode()).hexdigest()
            rows = _results(cases, spec["cases"], weak, docs)
            score = Decimal(str(round(100 * sum(r["score"] for r in rows) / len(rows), 1)))
            tokens = sum(r["tokens"] for r in rows) * 2  # buddy answers plus the judge
            gate_run = index == spec.get("regression_run")
            run = EvalRun.objects.create(
                org=org, eval_set=eval_set, buddy=buddy, fingerprint=fp, version_label=version, config=config,
                model="flobrain-demo", status=EvalRun.DONE, passed=score >= spec["threshold"], score=score,
                threshold=spec["threshold"], cases_total=len(rows), cases_passed=sum(1 for r in rows if r["passed"]),
                results=rows, input_tokens=int(tokens * 0.8), output_tokens=tokens - int(tokens * 0.8), total_tokens=tokens,
                cost=(Decimal(tokens) * Decimal("0.8") / Decimal(1_000_000)).quantize(Decimal("0.0001")),
                duration_ms=sum(r["duration_ms"] for r in rows) // 3,
                triggered_by=EvalRun.GATE if gate_run else (EvalRun.SCHEDULE if index % 2 else EvalRun.MANUAL),
                gate_context=EvalGateEvent.MARKETPLACE if gate_run else "",
                user=admin, created_at=at, started_at=at, finished_at=at + timedelta(seconds=40),
            )
            if gate_run:
                previous = baseline
                drop = float(previous.score - score) if previous else 0.0
                details = [{
                    "set": str(eval_set.id), "name": eval_set.name, "run": str(run.id), "reused": False, "status": run.status,
                    "score": float(score), "threshold": eval_set.threshold, "previous": float(previous.score) if previous else None,
                    "previous_run": str(previous.id) if previous else None, "max_drop": eval_set.max_drop,
                    "cases_passed": run.cases_passed, "cases_total": run.cases_total,
                    "failed_cases": [r["name"] for r in rows if not r["passed"]], "passed": False,
                    "reason": f"Score {float(score):g}% is below the pass mark of {eval_set.threshold}%." if score < eval_set.threshold
                    else f"Score {float(score):g}% is {drop:.1f} points below the previous version ({float(previous.score):g}%).",
                }]
                event = EvalGateEvent.objects.create(
                    org=org, buddy=buddy, context=EvalGateEvent.MARKETPLACE, outcome=EvalGateEvent.BLOCKED,
                    details=details, user=admin, created_at=at + timedelta(seconds=41),
                )
                audit(admin, "evals.gate.blocked", target=event, payload={"buddy": str(buddy.id), "context": "marketplace", "demo": True}, org=org)
            elif run.passed:
                baseline = run
            runs.append(run)
        if baseline is not None:
            EvalSet.objects.filter(pk=eval_set.pk).update(baseline_run=baseline)
        last = runs[-1]
        EvalGateEvent.objects.create(
            org=org, buddy=buddy, context=EvalGateEvent.MARKETPLACE if slug == "sales" else EvalGateEvent.SAVE,
            outcome=EvalGateEvent.PASSED,
            details=[{"set": str(eval_set.id), "name": eval_set.name, "run": str(last.id), "reused": True, "status": last.status,
                      "score": float(last.score), "threshold": eval_set.threshold, "previous": None, "previous_run": None,
                      "max_drop": eval_set.max_drop, "cases_passed": last.cases_passed, "cases_total": last.cases_total,
                      "failed_cases": [], "passed": True, "reason": ""}],
            user=admin, created_at=last.finished_at + timedelta(minutes=2),
        )
