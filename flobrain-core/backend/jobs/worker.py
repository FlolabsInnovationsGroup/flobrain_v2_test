"""PostgreSQL-backed job worker (Decision E17).

Claim and run are separate steps:

1. ``claim_one`` marks one due row ``running`` in a short transaction and
   commits. On Postgres the claim uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so
   two workers never take the same row.
2. The handler runs **outside** any transaction, so a slow job never holds a
   row lock or a database transaction open.
3. ``finish`` records the result (done, retry with backoff, or failed).

A worker that dies mid-job leaves a row in ``running``. ``requeue_stale`` puts
rows back in the queue once their lock is older than ``JOBS_STALE_SECONDS``.
"""

from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from jobs.models import Job
from jobs.queue import _REGISTRY

MAX_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 15 * 60
MAX_ERROR_CHARS = 2000


def _stale_after() -> timedelta:
    return timedelta(seconds=int(getattr(settings, "JOBS_STALE_SECONDS", 15 * 60)))


def requeue_stale(now=None) -> int:
    """Return rows stuck in ``running`` past the stale window to the queue."""
    now = now or timezone.now()
    return Job.objects.filter(
        status=Job.STATUS_RUNNING,
        locked_at__lt=now - _stale_after(),
    ).update(status=Job.STATUS_QUEUED, locked_at=None, run_after=now)


def claim_one():
    """Claim one due job and commit the claim. Returns the row or None."""
    now = timezone.now()
    with transaction.atomic():
        qs = Job.objects.filter(status=Job.STATUS_QUEUED, run_after__lte=now).order_by("run_after", "created_at")
        if connection.vendor == "postgresql":
            qs = qs.select_for_update(skip_locked=True)
        row = qs.first()
        if row is None:
            return None
        # Conditional update: on SQLite (no row locks) a second worker that read
        # the same row loses here instead of running it twice.
        updated = Job.objects.filter(pk=row.pk, status=Job.STATUS_QUEUED).update(
            status=Job.STATUS_RUNNING,
            locked_at=now,
            attempts=row.attempts + 1,
        )
        if not updated:
            return None
    row.refresh_from_db()
    return row


def finish(row, ok: bool, error: str = ""):
    if ok:
        row.status = Job.STATUS_DONE
        row.last_error = ""
        row.locked_at = None
        row.save(update_fields=["status", "last_error", "locked_at"])
        return
    row.last_error = (error or "")[:MAX_ERROR_CHARS]
    row.locked_at = None
    if row.attempts >= MAX_ATTEMPTS:
        row.status = Job.STATUS_FAILED
        row.save(update_fields=["status", "last_error", "locked_at"])
        return
    row.status = Job.STATUS_QUEUED
    delay = min(2 ** row.attempts, MAX_BACKOFF_SECONDS)
    row.run_after = timezone.now() + timedelta(seconds=delay)
    row.save(update_fields=["status", "last_error", "locked_at", "run_after"])


def _execute(row) -> None:
    handler = _REGISTRY.get(row.kind)
    try:
        if handler is None:
            raise KeyError(f"No handler registered for job kind {row.kind!r}")
        handler(row.payload or {})
    except Exception as exc:  # noqa: BLE001 - every failure is recorded on the row
        finish(row, False, f"{type(exc).__name__}: {exc}")
        return
    finish(row, True)


def run_once() -> bool:
    """Claim and run at most one job. Returns True if a job was claimed."""
    row = claim_one()
    if row is None:
        return False
    _execute(row)
    return True
