import time

from django.utils import timezone

from jobs.queue import register
from pulse.models import EvalResult, EvalRun

JOB = "pulse.eval"


def _checks(case, text, latency_ms):
    out = []
    low = (text or "").lower()
    for needle in case.must_contain or []:
        out.append({"check": f"contains “{needle}”", "passed": str(needle).lower() in low})
    for needle in case.must_not_contain or []:
        out.append({"check": f"does not contain “{needle}”", "passed": str(needle).lower() not in low})
    if case.max_latency_ms:
        out.append({"check": f"answers within {case.max_latency_ms} ms", "passed": latency_ms is not None and latency_ms <= case.max_latency_ms})
    return out


@register(JOB)
def run_eval(payload):
    from brain.llm.policy import check_ai

    if not EvalRun.objects.filter(pk=payload.get("run_id"), status="queued").update(status="running"):
        return
    run = EvalRun.objects.select_related("suite", "suite__org", "started_by").get(pk=payload["run_id"])
    org = run.suite.org
    if check_ai(org, "direct"):
        EvalRun.objects.filter(pk=run.pk).update(status="failed", finished_at=timezone.now())
        return
    try:
        _run_cases(run, org)
    except Exception:  # noqa: BLE001 - never leave a run stuck in "running"
        EvalRun.objects.filter(pk=run.pk, status="running").update(status="failed", finished_at=timezone.now())
        raise


def _run_cases(run, org):
    from brain.llm.providers import DirectProvider
    from telemetry.models import UsageEvent
    from telemetry.pricing import platform_budget_blocks
    from telemetry.writers import record_v2_provider_event

    passed, latencies = 0, []
    cases = list(run.suite.cases.all())
    for case in cases:
        if platform_budget_blocks(org, run.started_by, UsageEvent.CREDENTIAL_PLATFORM):
            EvalRun.objects.filter(pk=run.pk).update(status="failed", finished_at=timezone.now())
            return
        started = time.monotonic()
        result = DirectProvider(org).complete([{"role": "user", "content": case.prompt}], model=run.model or None)
        latency = int((time.monotonic() - started) * 1000)
        record_v2_provider_event(run.started_by, result, surface="evaluation", org=org, latency_ms=latency)
        checks = _checks(case, result.text or "", latency) if result.ok else [{"check": "model answered", "passed": False}]
        ok = result.ok and all(c["passed"] for c in checks)
        passed += ok
        latencies.append(latency)
        EvalResult.objects.create(run=run, case=case, output=(result.text or "")[:4000], passed=ok, checks=checks, latency_ms=latency, error_code=result.error_code or "")
    EvalRun.objects.filter(pk=run.pk).update(
        status="done",
        pass_rate=round(100 * passed / len(cases), 1) if cases else None,
        avg_latency_ms=int(sum(latencies) / len(latencies)) if latencies else None,
        finished_at=timezone.now(),
    )
