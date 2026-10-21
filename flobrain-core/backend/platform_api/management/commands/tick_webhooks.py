from django.core.management.base import BaseCommand

from platform_api.webhooks import retry_due


class Command(BaseCommand):
    help = "Retry due webhook deliveries. Run every minute next to tick_agents."

    def handle(self, *args, **options):
        self.stdout.write(f"retried {retry_due()}")
