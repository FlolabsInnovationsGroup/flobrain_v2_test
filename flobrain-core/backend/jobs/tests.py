import threading
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from jobs.models import Job
from jobs.queue import enqueue, register
from jobs.worker import MAX_ATTEMPTS, claim_one, requeue_stale, run_once


class JobsEagerTests(TestCase):
    def test_eager_ping(self):
        result = enqueue("ping", {"n": 1})
        self.assertEqual(result, {"ok": True, "payload": {"n": 1}})

    @override_settings(JOBS_EAGER=False, TESTING=False, DEBUG=False, JOBS_WORKER_ENABLED=False)
    def test_no_worker_reports_unavailable_and_queues_nothing(self):
        result = enqueue("ping", {"n": 1})
        self.assertEqual(result, {"ok": False, "reason": "unavailable"})
        self.assertEqual(Job.objects.count(), 0)

    @override_settings(JOBS_EAGER=False, TESTING=False, DEBUG=False, JOBS_WORKER_ENABLED=True)
    def test_with_worker_queues_the_job(self):
        result = enqueue("ping", {"n": 1})
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "queued")
        row = Job.objects.get()
        self.assertEqual(str(row.id), result["job_id"])
        self.assertEqual(row.status, Job.STATUS_QUEUED)

    def test_unknown_job_raises(self):
        with self.assertRaises(KeyError):
            enqueue("does-not-exist", {})


class JobWorkerTests(TestCase):
    def test_success_is_not_run_again(self):
        Job.objects.create(kind="ping", payload={"n": 2})
        self.assertTrue(run_once())
        self.assertFalse(run_once())
        row = Job.objects.get()
        self.assertEqual(row.status, Job.STATUS_DONE)
        self.assertEqual(row.attempts, 1)
        self.assertIsNone(row.locked_at)

    def test_failure_retries_with_backoff_then_fails(self):
        @register("boom")
        def boom(_payload):
            raise RuntimeError("nope")

        Job.objects.create(kind="boom", payload={})
        self.assertTrue(run_once())
        row = Job.objects.get()
        self.assertEqual(row.status, Job.STATUS_QUEUED)
        self.assertGreater(row.run_after, timezone.now())
        self.assertEqual(row.attempts, 1)
        self.assertIn("nope", row.last_error)
        self.assertFalse(run_once(), "a job in backoff is not due yet")

        for _ in range(MAX_ATTEMPTS - 1):
            Job.objects.filter(pk=row.pk).update(run_after=timezone.now() - timedelta(seconds=1))
            self.assertTrue(run_once())
        row.refresh_from_db()
        self.assertEqual(row.status, Job.STATUS_FAILED)
        self.assertEqual(row.attempts, MAX_ATTEMPTS)

    def test_missing_handler_is_recorded_not_raised(self):
        Job.objects.create(kind="no-such-handler", payload={})
        self.assertTrue(run_once())
        row = Job.objects.get()
        self.assertEqual(row.status, Job.STATUS_QUEUED)
        self.assertIn("No handler", row.last_error)

    def test_error_text_is_truncated(self):
        @register("long-error")
        def long_error(_payload):
            raise RuntimeError("x" * 10_000)

        Job.objects.create(kind="long-error", payload={})
        run_once()
        self.assertLessEqual(len(Job.objects.get().last_error), 2000)

    def test_stale_running_row_is_requeued(self):
        stuck = Job.objects.create(
            kind="ping",
            status=Job.STATUS_RUNNING,
            locked_at=timezone.now() - timedelta(hours=1),
        )
        fresh = Job.objects.create(kind="ping", status=Job.STATUS_RUNNING, locked_at=timezone.now())
        self.assertEqual(requeue_stale(), 1)
        stuck.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(stuck.status, Job.STATUS_QUEUED)
        self.assertEqual(fresh.status, Job.STATUS_RUNNING)

    def test_handler_runs_outside_a_transaction(self):
        seen = {}

        # TestCase wraps each test in one atomic block, so only a *nested*
        # block would mean the worker holds its own transaction around the handler.
        depth_before = len(connection.savepoint_ids)

        @register("probe-atomic")
        def probe(_payload):
            seen["depth"] = len(connection.savepoint_ids)

        Job.objects.create(kind="probe-atomic", payload={})
        run_once()
        self.assertEqual(seen["depth"], depth_before)

    def test_run_jobs_once_exits(self):
        Job.objects.create(kind="ping", payload={"n": 3})
        out = StringIO()
        call_command("run_jobs", "--once", stdout=out)
        self.assertIn("ran 1", out.getvalue())
        self.assertEqual(Job.objects.get().status, Job.STATUS_DONE)

    def test_run_jobs_exit_when_idle(self):
        out = StringIO()
        call_command("run_jobs", "--exit-when-idle", stdout=out)
        self.assertIn("idle", out.getvalue())

    def test_run_jobs_without_limits_in_tests_cannot_loop_forever(self):
        out = StringIO()
        call_command("run_jobs", stdout=out)
        self.assertIn("idle", out.getvalue())

    def test_run_jobs_max_seconds_stops_polling(self):
        out = StringIO()
        call_command("run_jobs", "--max-seconds", "0.3", "--poll-interval", "0.05", stdout=out)
        self.assertIn("idle", out.getvalue())


class SkipLockedTests(TransactionTestCase):
    """Two real connections: a row locked by one worker is skipped by the other."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("SKIP LOCKED needs PostgreSQL")

    def test_second_worker_skips_a_locked_row(self):
        now = timezone.now()
        first = Job.objects.create(kind="ping", payload={"a": 1}, run_after=now - timedelta(seconds=2))
        second = Job.objects.create(kind="ping", payload={"b": 1}, run_after=now - timedelta(seconds=1))

        holding = threading.Event()
        release = threading.Event()
        locked_by_other = {}

        def other_worker():
            try:
                with transaction.atomic(using="default"):
                    row = (
                        Job.objects.select_for_update(skip_locked=True)
                        .filter(status=Job.STATUS_QUEUED)
                        .order_by("run_after", "created_at")
                        .first()
                    )
                    locked_by_other["id"] = row.id if row else None
                    holding.set()
                    release.wait(timeout=10)
            finally:
                connections.close_all()

        t = threading.Thread(target=other_worker, daemon=True)
        t.start()
        self.assertTrue(holding.wait(timeout=10), "other worker did not lock a row")
        try:
            claimed = claim_one()
        finally:
            release.set()
            t.join(timeout=10)
        self.assertFalse(t.is_alive(), "other worker thread did not finish")
        self.assertEqual(locked_by_other["id"], first.id)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, second.id)


class RegistryTests(TestCase):
    def test_every_enqueued_job_has_a_handler_without_loading_urls(self):
        """The worker never imports URLconfs, so handlers must register from AppConfig.ready()."""
        from jobs.queue import _REGISTRY

        for name in ("exports.memory", "notifications.push", "knowledge.index"):
            self.assertIn(name, _REGISTRY)
