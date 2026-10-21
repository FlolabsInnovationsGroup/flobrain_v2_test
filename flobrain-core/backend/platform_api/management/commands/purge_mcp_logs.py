from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Delete MCP call log rows older than 90 days (MCP hub). Run daily."

    def handle(self, *args, **options):
        from platform_api.mcp_hub import purge_old_logs

        self.stdout.write(f"deleted {purge_old_logs()} MCP call log rows")
