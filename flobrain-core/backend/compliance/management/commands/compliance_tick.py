"""Daily compliance housekeeping: remind reviewers of open access reviews that are due within 3 days or
overdue (at most once a day per review), and delete evidence packages older than 7 days.

    python manage.py compliance_tick
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from compliance import evidence, reviews
from compliance.models import AccessReview
from organizations.flags import effective_flag


class Command(BaseCommand):
    help = "Remind access reviewers and delete expired evidence packages"

    def handle(self, *args, **options):
        now = timezone.now()
        reminded = 0
        due = AccessReview.objects.select_related("org").filter(status=AccessReview.OPEN, due_at__lte=now + timedelta(days=3))
        for review in due:
            if not review.org.is_active or not effective_flag(review.org, None, "compliance", default=False):
                continue
            if review.last_reminded_at and review.last_reminded_at > now - timedelta(hours=23):
                continue
            reviews.notify_reviewers(review)
            review.last_reminded_at = now
            review.save(update_fields=["last_reminded_at"])
            reminded += 1
        expired = evidence.expire(now)
        self.stdout.write(f"reminded={reminded} expired_packages={expired}")
