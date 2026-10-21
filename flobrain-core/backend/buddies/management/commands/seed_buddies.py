from django.core.management.base import BaseCommand, CommandError

from buddies.seeds import seed_org
from organizations.models import Organization


class Command(BaseCommand):
    help = "Add missing built-in buddies to one org (by slug). Existing buddies are left alone."

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="Organization slug")

    def handle(self, *args, **options):
        org = Organization.objects.filter(slug=options["org"]).first()
        if org is None:
            raise CommandError("Organization not found")
        self.stdout.write(f"created {seed_org(org)}")
