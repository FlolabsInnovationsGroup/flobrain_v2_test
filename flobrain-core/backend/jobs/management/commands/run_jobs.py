import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection

from jobs.worker import requeue_stale, run_once


class Command(BaseCommand):
    help = (
        "Run queued jobs. In production this runs in its own process and keeps polling "
        "until it receives SIGTERM/SIGINT. --once, --max-jobs and --max-seconds stop it earlier."
    )

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run at most one job and exit")
        parser.add_argument("--max-jobs", type=int, default=None, help="Stop after this many jobs")
        parser.add_argument("--max-seconds", type=float, default=None, help="Stop after this many seconds")
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=float(getattr(settings, "JOBS_POLL_SECONDS", 2.0)),
            help="Seconds to sleep when the queue is empty",
        )
        parser.add_argument(
            "--exit-when-idle",
            action="store_true",
            help="Exit as soon as the queue is empty instead of polling",
        )

    def handle(self, *args, **options):
        once = options["once"]
        max_jobs = options["max_jobs"]
        max_seconds = options["max_seconds"]
        poll = max(0.05, options["poll_interval"])
        exit_when_idle = options["exit_when_idle"]

        # A test that forgets the limits must never loop forever.
        if getattr(settings, "TESTING", False) and not once and max_jobs is None and max_seconds is None:
            max_jobs, max_seconds, exit_when_idle = 1, 5, True

        self._stop = False

        def _request_stop(signum, frame):
            self._stop = True

        installed = []
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                installed.append((sig, signal.signal(sig, _request_stop)))
            except (ValueError, OSError):
                pass  # not the main thread (tests) or unsupported on this platform

        started = time.monotonic()
        last_stale_check = 0.0
        ran = 0
        try:
            while not self._stop:
                if once and ran >= 1:
                    break
                if max_jobs is not None and ran >= max_jobs:
                    break
                if max_seconds is not None and (time.monotonic() - started) >= max_seconds:
                    break
                if time.monotonic() - last_stale_check >= 60:
                    requeue_stale()
                    last_stale_check = time.monotonic()
                if not connection.in_atomic_block:
                    # Drop broken or expired connections between jobs (long-running worker).
                    close_old_connections()
                if run_once():
                    ran += 1
                    continue
                if once or exit_when_idle:
                    break
                time.sleep(poll)
        finally:
            for sig, previous in installed:
                signal.signal(sig, previous)
        self.stdout.write(f"ran {ran}" if ran else "idle")
