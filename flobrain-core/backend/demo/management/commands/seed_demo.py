from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from demo import seed


class Command(BaseCommand):
    help = "Rebuild the demo org (slug 'demo') with one user per role. Requires DEMO_MODE=True."

    def handle(self, *args, **options):
        if not getattr(settings, "DEMO_MODE", False):
            raise CommandError("DEMO_MODE is off")
        org = seed.reset()
        self.stdout.write(f"demo org ready: /w/{org.slug}")
