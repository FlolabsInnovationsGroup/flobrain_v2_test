from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from workers.models import WorkerToken


class Command(BaseCommand):
    help = "Issue (--issue NAME [--kind meeting_bot]) or revoke (--revoke ID) a worker token. The raw token is printed once."

    def add_arguments(self, parser):
        parser.add_argument("--issue", metavar="NAME")
        parser.add_argument("--kind", default="render", choices=WorkerToken.KINDS, help="render (GPU) or meeting_bot")
        parser.add_argument("--revoke", metavar="ID")

    def handle(self, *args, **options):
        if options["issue"]:
            row, raw = WorkerToken.issue(options["issue"], options["kind"])
            self.stdout.write(f"id {row.id}\ntoken {raw}\nStore it in the worker's secret store now; it is not shown again.")
            return
        if options["revoke"]:
            updated = WorkerToken.objects.filter(pk=options["revoke"], revoked_at__isnull=True).update(
                revoked_at=timezone.now()
            )
            if not updated:
                raise CommandError("No active token with that id")
            self.stdout.write("revoked")
            return
        raise CommandError("Use --issue NAME or --revoke ID")
