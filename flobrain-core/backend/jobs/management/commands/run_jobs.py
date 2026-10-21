import time

from django.conf import settings
from django.core.management.base import BaseCommand

from jobs.worker import run_once


class Command(BaseCommand):
    help = "Claim and run queued jobs. Production runs this in its own process."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run at most one job and exit")
        parser.add_argument("--max-jobs", type=int, default=None, help="Stop after this many claimed jobs")
        parser.add_argument("--max-seconds", type=float, default=None, help="Stop after this many seconds")

    def handle(self, *args, **options):
        once = options["once"]
        max_jobs = options["max_jobs"]
        max_seconds = options["max_seconds"]
        if getattr(settings, "TESTING", False) and not once and max_jobs is None and max_seconds is None:
            max_jobs = 1
            max_seconds = 5
        started = time.monotonic()
        claimed = 0
        while True:
            if once and claimed >= 1:
                break
            if max_jobs is not None and claimed >= max_jobs:
                break
            if max_seconds is not None and (time.monotonic() - started) >= max_seconds:
                break
            if not run_once():
                break
            claimed += 1
        self.stdout.write("ran" if claimed else "idle")
