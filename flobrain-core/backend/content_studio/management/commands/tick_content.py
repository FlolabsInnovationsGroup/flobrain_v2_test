from django.core.management.base import BaseCommand

from content_studio.publishing import publish_due


class Command(BaseCommand):
    help = "Publish approved posts whose time has come (and retries). Run every minute next to tick_agents."

    def handle(self, *args, **options):
        self.stdout.write(f"published {publish_due()}")
