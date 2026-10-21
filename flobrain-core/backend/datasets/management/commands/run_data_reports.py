from django.core.management.base import BaseCommand

from datasets.services import refresh_due_sheets, run_due_reports


class Command(BaseCommand):
    help = "Refresh Google Sheets that are due and send data reports that are due. Run hourly; safe to repeat."

    def add_arguments(self, parser):
        parser.add_argument("--skip-refresh", action="store_true", help="Only send reports; do not fetch sheets")

    def handle(self, *args, **options):
        refreshed = 0 if options["skip_refresh"] else refresh_due_sheets()
        sent = run_due_reports()
        self.stdout.write(f"sheets_refreshed {refreshed} reports_sent {sent}")
