from django.core.management.base import BaseCommand

from tasks.services import send_due_reminders


class Command(BaseCommand):
    help = "Notify assignees about tasks due tomorrow and overdue tasks. Run hourly; safe to repeat."

    def handle(self, *args, **options):
        sent = send_due_reminders()
        self.stdout.write(f"due_soon {sent['task.due_soon']} overdue {sent['task.overdue']}")
