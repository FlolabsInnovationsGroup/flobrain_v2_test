from django.core.management.base import BaseCommand

from automations.triggers import tick


class Command(BaseCommand):
    help = "Fire due workflow schedules, run queued workflow runs and follow up on approvals. Run every minute; safe to repeat."

    def handle(self, *args, **options):
        result = tick()
        self.stdout.write(f"fired {result['fired']} processed {result['processed']} reconciled {result['reconciled']}")
