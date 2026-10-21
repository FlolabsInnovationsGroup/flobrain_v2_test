from datetime import timedelta

from django.utils import timezone

from timetracking.models import TimeEntry


def _duration_seconds(qs):
    total = 0
    for entry in qs:
        total += entry.seconds
    return total


def report_me(org, user, period=None):
    qs = TimeEntry.objects.filter(org=org, user=user)
    if period == "week":
        qs = qs.filter(started_at__gte=timezone.now() - timedelta(days=7))
    return {"seconds": _duration_seconds(qs), "entries": qs.count(), "period": period or "all"}


def report_team(org, team):
    user_ids = team.memberships.values_list("user_id", flat=True)
    qs = TimeEntry.objects.filter(org=org, user_id__in=user_ids)
    return {"seconds": _duration_seconds(qs), "entries": qs.count(), "team": str(team.id)}


def dashboard_me(org, user):
    week_ago = timezone.now() - timedelta(days=7)
    qs = TimeEntry.objects.filter(org=org, user=user, started_at__gte=week_ago)
    return {"seconds_7d": _duration_seconds(qs), "impact_score": None}
