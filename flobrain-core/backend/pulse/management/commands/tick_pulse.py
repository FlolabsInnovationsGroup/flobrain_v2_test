from django.core.management.base import BaseCommand

from pulse.alerts import evaluate


class Command(BaseCommand):
    help = "Evaluate Pulse alert rules (run every few minutes)."

    def handle(self, *args, **options):
        self.stdout.write(f"fired {evaluate()}")
