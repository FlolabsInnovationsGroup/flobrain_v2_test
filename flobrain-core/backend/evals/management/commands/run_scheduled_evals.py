"""Run eval sets that are due on their schedule (cron, e.g. hourly). Each due set runs once as the
person who created it, only while that person is still an active member with ``evals.manage`` and the
``buddy_evals`` flag is on for them. Runs are sandboxed and capped like manual runs."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from evals import gate, runner
from evals.models import EvalRun, EvalSet

PERIOD = {EvalSet.SCHEDULE_DAILY: timedelta(days=1), EvalSet.SCHEDULE_WEEKLY: timedelta(days=7)}


def due_sets(now=None):
    now = now or timezone.now()
    for eval_set in EvalSet.objects.exclude(schedule=EvalSet.SCHEDULE_OFF).select_related("org", "created_by", "buddy"):
        period = PERIOD.get(eval_set.schedule)
        if period is None or (eval_set.last_scheduled_at and now - eval_set.last_scheduled_at < period):
            continue
        yield eval_set


def run_due(now=None) -> int:
    from organizations.models import OrgMembership
    from organizations.permissions import can

    now = now or timezone.now()
    started = 0
    for eval_set in due_sets(now):
        user = eval_set.created_by
        EvalSet.objects.filter(pk=eval_set.pk).update(last_scheduled_at=now)
        member = user and OrgMembership.objects.filter(org=eval_set.org, user=user).first()
        if not (member and member.is_active_member and can(user, "evals.manage", eval_set.org) and gate.enabled_for(eval_set.org, user)):
            continue
        if not eval_set.org.is_active or not eval_set.cases.exists():
            continue
        if eval_set.runs.filter(status__in=[EvalRun.QUEUED, EvalRun.RUNNING]).exists():
            continue
        runner.start(eval_set, user, EvalRun.SCHEDULE)
        started += 1
    return started


class Command(BaseCommand):
    help = "Run eval sets that are due on their daily or weekly schedule."

    def handle(self, *args, **options):
        self.stdout.write(f"started {run_due()} eval run(s)")
