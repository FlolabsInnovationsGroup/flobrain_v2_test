from django.core.management.base import BaseCommand

from privacy.jobs import run_retention


class Command(BaseCommand):
    help = "Delete data older than each org's retention policy, with its search vectors (run daily)."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="", help="Only this org id")

    def handle(self, *args, **opts):
        result = run_retention({"org_id": opts["org"]} if opts["org"] else {})
        for org_id, removed in result.items():
            self.stdout.write(f"{org_id}: {removed}")
