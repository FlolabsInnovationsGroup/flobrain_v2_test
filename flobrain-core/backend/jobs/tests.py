from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from io import StringIO

from jobs.models import Job
from jobs.queue import enqueue, register
from jobs.worker import run_once


class JobsEagerTests(TestCase):
    def test_eager_ping(self):
        result = enqueue("ping", {"n": 1})
        self.assertEqual(result, {"ok": True, "payload": {"n": 1}})

    @override_settings(JOBS_EAGER=False, TESTING=False, DEBUG=False)
    def test_non_eager_reports_unavailable(self):
        result = enqueue("ping", {"n": 1})
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["reason"], "unavailable")
        self.assertEqual(Job.objects.filter(kind="ping").count(), 1)


class JobWorkerTests(TestCase):
    def test_success_is_not_run_again(self):
        Job.objects.create(kind="ping", payload={"n": 2})
        self.assertTrue(run_once())
        self.assertFalse(run_once())
        self.assertEqual(Job.objects.get().status, Job.STATUS_DONE)

    def test_failure_retries_with_backoff(self):
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

    def test_two_claims_take_different_rows(self):
        if connection.vendor != "postgresql":
            self.skipTest("SKIP LOCKED is Postgres")
        from django.db import transaction

        from jobs.worker import claim_one

        Job.objects.create(kind="ping", payload={"a": 1})
        Job.objects.create(kind="ping", payload={"b": 1})
        with transaction.atomic():
            first = claim_one()
            second = claim_one()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.id, second.id)

    def test_run_jobs_once_exits(self):
        Job.objects.create(kind="ping", payload={"n": 3})
        out = StringIO()
        call_command("run_jobs", "--once", stdout=out)
        self.assertIn("ran", out.getvalue())
        self.assertEqual(Job.objects.get().status, Job.STATUS_DONE)
        out2 = StringIO()
        call_command("run_jobs", "--max-jobs", "1", "--max-seconds", "1", stdout=out2)
        self.assertIn("idle", out2.getvalue())
