from django.core.management.base import BaseCommand

from agents.service import tick


class Command(BaseCommand):
    help = "Queue due scheduled agent runs and overdue-task events. Run every minute (dev/staging scheduler)."

    def handle(self, *args, **options):
        self.stdout.write(f"queued {tick()}")
