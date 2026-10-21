from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from jobs.models import Job
from jobs.queue import _REGISTRY

MAX_ATTEMPTS = 5


def claim_one():
    now = timezone.now()
    qs = Job.objects.filter(status=Job.STATUS_QUEUED, run_after__lte=now).order_by("created_at")
    if connection.vendor == "postgresql":
        qs = qs.select_for_update(skip_locked=True)
    row = qs.first()
    if row is None:
        return None
    row.status = Job.STATUS_RUNNING
    row.locked_at = now
    row.attempts = row.attempts + 1
    row.save(update_fields=["status", "locked_at", "attempts"])
    return row


def finish(row, ok: bool, error: str = ""):
    if ok:
        row.status = Job.STATUS_DONE
        row.last_error = ""
        row.locked_at = None
        row.save(update_fields=["status", "last_error", "locked_at"])
        return
    if row.attempts >= MAX_ATTEMPTS:
        row.status = Job.STATUS_FAILED
        row.last_error = error
        row.locked_at = None
        row.save(update_fields=["status", "last_error", "locked_at"])
        return
    row.status = Job.STATUS_QUEUED
    row.last_error = error
    row.locked_at = None
    row.run_after = timezone.now() + timedelta(seconds=2 ** row.attempts)
    row.save(update_fields=["status", "last_error", "locked_at", "run_after"])


def _execute(row) -> bool:
    handler = _REGISTRY.get(row.kind)
    try:
        if handler is None:
            raise KeyError(row.kind)
        handler(row.payload or {})
    except Exception as exc:
        finish(row, False, str(exc))
        return True
    finish(row, True)
    return True


def run_once() -> bool:
    # SQLite has no SKIP LOCKED and a nested lock can wait forever. Claim without FOR UPDATE.
    if connection.vendor != "postgresql":
        row = claim_one()
        if row is None:
            return False
        return _execute(row)
    with transaction.atomic():
        row = claim_one()
        if row is None:
            return False
        return _execute(row)
