"""Mirror automation notices and customer escalations to linked Slack and Teams DMs (run every minute)."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send new automation notices and customer escalations to people who linked Slack or Teams"

    def handle(self, *args, **options):
        from bridges.engine import mirror_notifications

        sent = mirror_notifications()
        if options.get("verbosity", 1) > 1:
            self.stdout.write(f"bridges: {sent} message(s) mirrored")
