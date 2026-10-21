from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView
from organizations.models import Organization, Team
from organizations.permissions import HasPerm, IsActiveOrgMember, get_scoped_or_404
from tasks.models import Task
from tasks.selectors import visible_tasks
from timetracking.models import TimeEntry
from timetracking.reports import dashboard_me, report_me, report_team


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _entry_payload(entry: TimeEntry):
    return {
        "id": str(entry.id),
        "description": entry.description,
        "started_at": entry.started_at.isoformat(),
        "ended_at": entry.ended_at.isoformat() if entry.ended_at else None,
        "seconds": entry.seconds,
        "task": str(entry.task_id) if entry.task_id else None,
    }


class TimerView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        open_entry = TimeEntry.objects.filter(org=org, user=request.user, ended_at__isnull=True).first()
        return Response({"running": _entry_payload(open_entry) if open_entry else None})

    def patch(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.write").has_permission(request, self)
        open_entry = TimeEntry.objects.filter(org=org, user=request.user, ended_at__isnull=True).first()
        if not open_entry:
            return Response({"error": "not_running", "details": "No open timer"}, status=404)
        if "description" in request.data:
            open_entry.description = request.data["description"]
            open_entry.save(update_fields=["description", "updated_at"])
        return Response(_entry_payload(open_entry))


class TimerStartView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.write").has_permission(request, self)
        if TimeEntry.objects.filter(org=org, user=request.user, ended_at__isnull=True).exists():
            return Response({"error": "already_running", "details": "Stop the current timer first"}, status=409)
        task = None
        if request.data.get("task"):
            task = get_object_or_404(Task, pk=request.data["task"], org=org)
        entry = TimeEntry.objects.create(
            org=org,
            user=request.user,
            task=task,
            description=request.data.get("description") or "",
        )
        return Response(_entry_payload(entry), status=201)


class TimerStopView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.write").has_permission(request, self)
        entry = TimeEntry.objects.filter(org=org, user=request.user, ended_at__isnull=True).first()
        if not entry:
            return Response({"error": "not_running", "details": "No open timer"}, status=404)
        entry.ended_at = timezone.now()
        entry.save(update_fields=["ended_at", "updated_at"])
        return Response(_entry_payload(entry))


class TimeEntryListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        qs = TimeEntry.objects.filter(org=org, user=request.user).order_by("-started_at")
        team_id = request.query_params.get("team")
        if team_id:
            team = get_object_or_404(Team, pk=team_id, org=org)
            get_scoped_or_404(request.user, "time.view", team)
            user_ids = team.memberships.values_list("user_id", flat=True)
            qs = TimeEntry.objects.filter(org=org, user_id__in=user_ids).order_by("-started_at")
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([_entry_payload(e) for e in page])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.write").has_permission(request, self)
        started = request.data.get("started_at") or timezone.now()
        ended = request.data.get("ended_at")
        entry = TimeEntry.objects.create(
            org=org,
            user=request.user,
            description=request.data.get("description") or "",
            started_at=started,
            ended_at=ended,
        )
        return Response(_entry_payload(entry), status=201)


class TimeEntryDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def patch(self, request, org_id, entry_id):
        org = _org(org_id)
        request.org = org
        entry = get_object_or_404(TimeEntry, pk=entry_id, org=org, user=request.user)
        if "description" in request.data:
            entry.description = request.data["description"]
        entry.save()
        return Response(_entry_payload(entry))

    def delete(self, request, org_id, entry_id):
        org = _org(org_id)
        request.org = org
        entry = get_object_or_404(TimeEntry, pk=entry_id, org=org, user=request.user)
        entry.delete()
        return Response(status=204)


class TimeReportMeView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        return Response(report_me(org, request.user, period=request.query_params.get("period")))


class TimeReportTeamView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, team_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        team = get_object_or_404(Team, pk=team_id, org=org)
        get_scoped_or_404(request.user, "time.view", team)
        return Response(report_team(org, team))


class DashboardMeView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        return Response(dashboard_me(org, request.user))


class CalendarView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("task.view").has_permission(request, self)
        tasks = visible_tasks(
            Task.objects.filter(org=org, due_on__isnull=False).order_by("due_on"),
            request.user,
            org,
        )
        return Response(
            [{"id": str(t.id), "title": t.title, "due_on": t.due_on.isoformat(), "kind": "task"} for t in tasks]
        )
