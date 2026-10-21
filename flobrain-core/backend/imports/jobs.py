"""Worker jobs for imports. Each takes ``{"run_id"}`` and never raises for expected failures
(the run records them); unexpected errors mark the run failed so it can be resumed."""

import logging

from django.utils import timezone

from imports import services
from imports.models import ImportRun
from jobs.queue import jobs_eager, register

logger = logging.getLogger(__name__)

ANALYZE_JOB = "imports.analyze"
RUN_JOB = services.RUN_JOB
UNDO_JOB = "imports.undo"


def _guard(run_id, fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - recorded on the run, never the content
        logger.exception("import %s: unexpected error", run_id)
        ImportRun.objects.filter(pk=run_id).exclude(status__in=(ImportRun.DONE, ImportRun.UNDONE)).update(
            status=ImportRun.FAILED, error="internal_error: Something went wrong. Try resuming", lease_until=None, finished_at=timezone.now()
        )
        return {"ok": False, "reason": "internal_error"}


@register(ANALYZE_JOB)
def analyze_job(payload):
    run = ImportRun.objects.select_related("org").filter(pk=payload.get("run_id"), status=ImportRun.ANALYZING).first()
    if run is None:
        return {"ok": False}
    _guard(run.pk, lambda: services.analyze(run))
    return {"ok": True}


@register(RUN_JOB)
def run_job(payload):
    run_id = payload.get("run_id")
    # Eager mode (tests, local demo) runs the whole import inline; a worker runs it in slices.
    budget = None if jobs_eager() else services.job_seconds()
    status = _guard(run_id, lambda: services.execute(run_id, budget))
    return {"ok": True, "status": status}


@register(UNDO_JOB)
def undo_job(payload):
    run_id = payload.get("run_id")
    return _guard(run_id, lambda: services.undo(run_id, payload.get("user_id")))
