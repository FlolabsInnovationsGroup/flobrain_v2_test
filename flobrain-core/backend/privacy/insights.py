"""Personal insights (yours only) and team insights (leads), 2026-10-21.

Personal insights are visible to the person alone. Team insights show one row per member (tasks done,
hours, meetings; never message or AI counts) to the people who can generate that team's reports, except members who chose "keep my insights
personal" (``analytics_personal_only``): they are left out of the rows and the totals, and the
response only says how many chose that.
"""

from collections import Counter
from datetime import date, timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core_v2.views import V2APIView
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from organizations.permissions.engine import can
from privacy.models import PrivacySettings


def _days(request):
    try:
        days = int(request.query_params.get("days") or 30)
    except ValueError:
        return None
    return days if 7 <= days <= 180 else None


def _stats(org, user_ids, since, until):
    """Counts per user id for one period: tasks done, hours, messages, meetings spoken in, AI requests."""
    from meetings.models import Recording
    from rooms.models import RoomMessage
    from tasks.models import Task, TaskAssignment
    from telemetry.models import UsageEvent
    from timetracking.models import TimeEntry

    ids = list(user_ids)
    out = {uid: Counter() for uid in ids}
    done = TaskAssignment.objects.filter(
        task__org=org, user_id__in=ids, task__status=Task.STATUS_DONE, task__completed_at__gte=since, task__completed_at__lt=until
    ).values_list("user_id", flat=True)
    for uid in done:
        out[uid]["tasks_done"] += 1
    for entry in TimeEntry.objects.filter(org=org, user_id__in=ids, started_at__gte=since, started_at__lt=until, ended_at__isnull=False).only("user_id", "started_at", "ended_at"):
        out[entry.user_id]["seconds"] += entry.seconds
    for uid in RoomMessage.objects.filter(room__org=org, author_id__in=ids, created_at__gte=since, created_at__lt=until, deleted_at__isnull=True).values_list("author_id", flat=True):
        out[uid]["messages"] += 1
    for uid, _ in Recording.objects.filter(org=org, speaker_id__in=ids, recorded_at__gte=since, recorded_at__lt=until).values_list("speaker_id", "meeting_id").distinct():
        out[uid]["meetings"] += 1
    for uid in UsageEvent.objects.filter(org=org, user_id__in=ids, created_at__gte=since, created_at__lt=until).values_list("user_id", flat=True):
        out[uid]["ai_requests"] += 1
    return out


FIELDS = ("tasks_done", "seconds", "messages", "meetings", "ai_requests")
TEAM_FIELDS = ("tasks_done", "seconds", "meetings")  # leads never see message or AI counts per person


def _row(counter, fields=FIELDS):
    return {k: int(counter.get(k, 0)) for k in fields}


class MyInsightsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Your own work over the last N days (only you see this)")
    def get(self, request, org_id):
        from tasks.models import Task
        from timetracking.models import TimeEntry

        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        if not OrgMembership.objects.filter(org=org, user=request.user, employment_status="active").exists():
            return Response({"error": "not_found"}, status=404)
        days = _days(request)
        if days is None:
            return Response({"error": "invalid", "details": "days must be between 7 and 180"}, status=400)
        now = timezone.now()
        since, before = now - timedelta(days=days), now - timedelta(days=2 * days)
        uid = request.user.id
        current = _row(_stats(org, [uid], since, now)[uid])
        previous = _row(_stats(org, [uid], before, since)[uid])
        today = timezone.localdate()
        mine = Task.objects.filter(org=org, assignments__user=request.user).exclude(status=Task.STATUS_DONE)
        by_day = Counter()
        by_category = Counter()
        for entry in TimeEntry.objects.filter(org=org, user=request.user, started_at__gte=since, ended_at__isnull=False).only("started_at", "ended_at", "category"):
            by_day[timezone.localtime(entry.started_at).date().isoformat()] += entry.seconds
            by_category[entry.category] += entry.seconds
        weekday = Counter()
        for day, secs in by_day.items():
            weekday[date.fromisoformat(day).strftime("%A")] += secs
        settings_row = PrivacySettings.objects.filter(org=org, user=request.user).first()
        return Response(
            {
                "days": days,
                "current": current,
                "previous": previous,
                "open_tasks": mine.count(),
                "overdue_tasks": mine.filter(due_on__lt=today).count(),
                "hours_by_day": [{"day": d, "seconds": by_day[d]} for d in sorted(by_day)],
                "hours_by_category": [{"category": c, "seconds": s} for c, s in by_category.most_common()],
                "busiest_weekday": weekday.most_common(1)[0][0] if weekday else None,
                "personal_only": bool(settings_row and settings_row.analytics_personal_only),
            }
        )


class TeamInsightsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Team insights for the team's leads (or report.generate); people who keep their insights personal are left out")
    def get(self, request, org_id, team_id):
        org = get_object_or_404(Organization, pk=org_id, is_active=True)
        team = Team.objects.filter(org=org, pk=team_id).first()
        if team is None or not OrgMembership.objects.filter(org=org, user=request.user, employment_status="active").exists():
            return Response({"error": "not_found"}, status=404)
        is_lead = TeamMembership.objects.filter(team=team, user=request.user, team_role=TeamMembership.ROLE_LEAD).exists()
        if not is_lead and not can(request.user, "report.generate", team):
            return Response({"error": "permission_denied", "details": "Missing permission: report.generate"}, status=403)
        days = _days(request)
        if days is None:
            return Response({"error": "invalid", "details": "days must be between 7 and 180"}, status=400)
        members = list(
            TeamMembership.objects.filter(team=team, user__org_memberships__org=org, user__org_memberships__employment_status="active")
            .select_related("user")
            .distinct()
        )
        private = set(PrivacySettings.objects.filter(org=org, analytics_personal_only=True, user_id__in=[m.user_id for m in members]).values_list("user_id", flat=True))
        shown = [m for m in members if m.user_id not in private]
        now = timezone.now()
        stats = _stats(org, [m.user_id for m in shown], now - timedelta(days=days), now)
        rows = [{"user_id": str(m.user_id), "name": m.user.username or m.user.email.split("@")[0], **_row(stats[m.user_id], TEAM_FIELDS)} for m in shown]
        totals = {k: sum(r[k] for r in rows) for k in TEAM_FIELDS}
        return Response({"days": days, "team": {"id": str(team.id), "name": team.name}, "members": rows, "totals": totals, "private_count": len(private)})
