from datetime import timedelta

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.response import Response

from core_v2.pagination import V2PageNumberPagination
from core_v2.views import V2APIView
from organizations.models import Organization, Project, Team, TeamMembership
from organizations.permissions import HasPerm, IsActiveOrgMember, get_scoped_or_404
from organizations.permissions.engine import can, is_org_owner_or_admin
from organizations.services import audit
from tasks.models import Task
from tasks.selectors import calendar_items
from tasks.services import can_use_project, display_name, resolve_room
from timetracking.models import Tag, TimeEntry
from timetracking.reports import dashboard_me, parse_week, readable_links, report_me, report_team, week_bounds

MAX_MANUAL = timedelta(hours=24)


def _org(org_id):
    return get_object_or_404(Organization, pk=org_id, is_active=True)


def _uuid(value):
    import uuid

    try:
        return uuid.UUID(str(value))
    except ValueError:
        return uuid.UUID(int=0)


def _bad(details):
    return Response({"error": "validation_error", "details": details}, status=400)


def _not_found(details):
    return Response({"error": "not_found", "details": details}, status=404)


def _entry_payload(entry: TimeEntry, hide_description: bool = False, viewer=None, readable=None):
    """``readable`` = (room ids, task check) for someone else's entries: names the viewer can't open
    are left out. With the person's sharing off, only times and the category remain."""
    others = viewer is not None and entry.user_id != viewer.id
    show_room = not hide_description and (not others or readable is None or entry.room_id in readable[0])
    show_task = not hide_description and (not others or readable is None or readable[1](entry.task))
    data = {
        "id": str(entry.id),
        "user": str(entry.user_id),
        "description": "" if hide_description else entry.description,
        "description_hidden": hide_description,
        "started_at": entry.started_at.isoformat(),
        "ended_at": entry.ended_at.isoformat() if entry.ended_at else None,
        "seconds": entry.seconds,
        "category": entry.category,
        "source": entry.source,
        "task": str(entry.task_id) if entry.task_id and show_task else None,
        "task_title": entry.task.title if entry.task_id and show_task else "",
        "project": str(entry.project_id) if entry.project_id and not hide_description else None,
        "project_name": entry.project.name if entry.project_id and not hide_description else "",
        "room": str(entry.room_id) if entry.room_id and show_room else None,
        "room_name": entry.room.name if entry.room_id and show_room else "",
        "tags": [] if hide_description else [t.name for t in entry.tags.all()],
        "approval_status": entry.approval_status,
        "approval_note": entry.approval_note,
        "approved_by": str(entry.approved_by_id) if entry.approved_by_id else None,
        "approved_at": entry.approved_at.isoformat() if entry.approved_at else None,
    }
    if viewer is not None:
        data["can_edit"] = entry.user_id == viewer.id and entry.approval_status != TimeEntry.APPROVAL_APPROVED
    return data


def _entries_qs():
    return TimeEntry.objects.select_related("task", "project", "room").prefetch_related("tags")


def _hidden_for(org, viewer, entries):
    """Privacy: people who turned off sharing time details show totals without descriptions."""
    from privacy.models import PrivacySettings

    others = {e.user_id for e in entries if e.user_id != viewer.id}
    if not others:
        return set()
    return set(
        PrivacySettings.objects.filter(org=org, user_id__in=others, share_time_details_with_org=False).values_list(
            "user_id", flat=True
        )
    )


def _links(request, org, data, entry=None):
    """Validate task, project, room, category and tags from ``data``. Returns (fields, error_response)."""
    fields = {}
    if "task" in data or "task_id" in data:
        raw = data.get("task", data.get("task_id"))
        if raw:
            task = Task.objects.filter(pk=_uuid(raw), org=org).first()
            if task is None or not can(request.user, "task.view", {"org": org, "team": task.team, "project": task.project}):
                return None, _not_found("Task not found")
            fields["task"] = task
            if "project" not in data and task.project_id and (entry is None or not entry.project_id):
                fields["project"] = task.project
        else:
            fields["task"] = None
    if "project" in data or "project_id" in data:
        raw = data.get("project", data.get("project_id"))
        if raw:
            project = Project.objects.filter(pk=_uuid(raw), org=org).first()
            if project is None or not can_use_project(request.user, project):
                return None, _not_found("Project not found")
            fields["project"] = project
        else:
            fields["project"] = None
    if "room" in data or "room_id" in data:
        raw = data.get("room", data.get("room_id"))
        if raw:
            room = resolve_room(request.user, org, _uuid(raw))
            if room is None:
                return None, _not_found("Room not found")
            fields["room"] = room
        else:
            fields["room"] = None
    if "category" in data:
        if data["category"] not in TimeEntry.CATEGORIES:
            return None, _bad("Category must be onboarding, masterclass or projects.")
        fields["category"] = data["category"]
    if "description" in data:
        if not isinstance(data["description"], str):
            return None, _bad("description must be text")
        fields["description"] = data["description"][:2000]
    if "tags" in data:
        tags = data["tags"]
        if not isinstance(tags, list) or len(tags) > 10 or not all(isinstance(t, str) and 0 < len(t.strip()) <= 80 for t in tags):
            return None, _bad("tags must be a list of up to 10 short names")
        fields["tags"] = sorted({t.strip() for t in tags})
    return fields, None


def _apply(entry, fields):
    tags = fields.pop("tags", None)
    for key, value in fields.items():
        setattr(entry, key, value)
    entry.save()
    if tags is not None:
        entry.tags.set([Tag.objects.get_or_create(org=entry.org, name=name)[0] for name in tags])


def _times(data, entry=None):
    """Parse started_at/ended_at for a manual entry. Returns (start, end, error_response)."""
    start = entry.started_at if entry else None
    end = entry.ended_at if entry else None
    for key in ("started_at", "ended_at"):
        if key in data:
            value = data[key]
            parsed = parse_datetime(value) if isinstance(value, str) else None
            if parsed is None:
                return None, None, _bad(f"{key} must be a date and time")
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            if key == "started_at":
                start = parsed
            else:
                end = parsed
    if start is None or end is None:
        return None, None, _bad("A manual entry needs a start and an end.")
    if end <= start:
        return None, None, _bad("The end must be after the start.")
    if end > timezone.now() + timedelta(minutes=5):
        return None, None, _bad("You can't log time in the future.")
    if end - start > MAX_MANUAL:
        return None, None, _bad("One entry can be at most 24 hours.")
    return start, end, None


def _running_payload(org, user):
    entry = _entries_qs().filter(org=org, user=user, ended_at__isnull=True).first()
    return _entry_payload(entry, viewer=user) if entry else None


class TimerView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        return Response({"running": _running_payload(org, request.user), "server_time": timezone.now().isoformat()})

    def patch(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.write").has_permission(request, self)
        open_entry = TimeEntry.objects.filter(org=org, user=request.user, ended_at__isnull=True).first()
        if not open_entry:
            return Response({"error": "not_running", "details": "No open timer"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        fields, error = _links(request, org, data, entry=open_entry)
        if error:
            return error
        _apply(open_entry, fields)
        return Response(_running_payload(org, request.user))


class TimerStartView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.write").has_permission(request, self)
        running = _running_payload(org, request.user)
        if running:
            return Response({"error": "timer_already_running", "details": running}, status=409)
        data = request.data if isinstance(request.data, dict) else {}
        fields, error = _links(request, org, data)
        if error:
            return error
        try:
            with transaction.atomic():
                entry = TimeEntry.objects.create(org=org, user=request.user, source=TimeEntry.SOURCE_TIMER)
                _apply(entry, fields)
        except IntegrityError:
            return Response({"error": "timer_already_running", "details": _running_payload(org, request.user)}, status=409)
        return Response(_entry_payload(_entries_qs().get(pk=entry.pk), viewer=request.user), status=201)


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
        return Response(_entry_payload(_entries_qs().get(pk=entry.pk), viewer=request.user))


class TimeEntryListCreateView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        qs = _entries_qs().filter(org=org, user=request.user)
        team_id = request.query_params.get("team")
        if team_id:
            team = get_object_or_404(Team, pk=_uuid(team_id), org=org)
            get_scoped_or_404(request.user, "time.view", team)
            user_ids = team.memberships.values_list("user_id", flat=True)
            qs = _entries_qs().filter(org=org, user_id__in=user_ids)
        week = request.query_params.get("week")
        if week:
            monday = parse_week(week)
            if monday is None:
                return _bad("week must look like 2026-W43 or a date")
            start, end = week_bounds(monday)
            qs = qs.filter(started_at__gte=start, started_at__lt=end)
        status = request.query_params.get("status")
        if status:
            if status not in dict(TimeEntry.APPROVAL_CHOICES):
                return _bad("Unknown status")
            qs = qs.filter(approval_status=status)
        qs = qs.order_by("-started_at")
        paginator = V2PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        hidden = _hidden_for(org, request.user, page)
        readable = readable_links(request.user, org)
        return paginator.get_paginated_response([_entry_payload(e, e.user_id in hidden, request.user, readable) for e in page])

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.write").has_permission(request, self)
        data = request.data if isinstance(request.data, dict) else None
        if data is None:
            return _bad("Send a JSON object")
        start, end, error = _times(data)
        if error:
            return error
        fields, error = _links(request, org, data)
        if error:
            return error
        entry = TimeEntry.objects.create(
            org=org, user=request.user, started_at=start, ended_at=end, source=TimeEntry.SOURCE_MANUAL
        )
        _apply(entry, fields)
        return Response(_entry_payload(_entries_qs().get(pk=entry.pk), viewer=request.user), status=201)


class TimeEntryDetailView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def patch(self, request, org_id, entry_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.write").has_permission(request, self)
        entry = get_object_or_404(TimeEntry, pk=entry_id, org=org, user=request.user)
        if entry.approval_status == TimeEntry.APPROVAL_APPROVED:
            return Response({"error": "entry_locked", "details": "Approved time can't be changed."}, status=409)
        data = request.data if isinstance(request.data, dict) else None
        if data is None:
            return _bad("Send a JSON object")
        if "started_at" in data or "ended_at" in data:
            if entry.ended_at is None:
                return _bad("Stop the timer before changing its times.")
            start, end, error = _times(data, entry)
            if error:
                return error
            entry.started_at, entry.ended_at = start, end
        fields, error = _links(request, org, data, entry=entry)
        if error:
            return error
        if entry.approval_status in {TimeEntry.APPROVAL_SUBMITTED, TimeEntry.APPROVAL_REJECTED}:
            # A changed entry goes back to draft; the person submits it again.
            fields.update(approval_status=TimeEntry.APPROVAL_DRAFT, submitted_at=None, approval_note="")
        _apply(entry, fields)
        return Response(_entry_payload(_entries_qs().get(pk=entry.pk), viewer=request.user))

    def delete(self, request, org_id, entry_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.write").has_permission(request, self)
        entry = get_object_or_404(TimeEntry, pk=entry_id, org=org, user=request.user)
        if entry.approval_status == TimeEntry.APPROVAL_APPROVED:
            return Response({"error": "entry_locked", "details": "Approved time can't be deleted."}, status=409)
        entry.delete()
        return Response(status=204)


class TimeEntrySubmitView(V2APIView):
    """Send your closed draft (or rejected) entries to your lead: by ``ids`` or by ``week``."""

    permission_classes = [IsActiveOrgMember]

    def post(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.write").has_permission(request, self)
        data = request.data if isinstance(request.data, dict) else {}
        qs = TimeEntry.objects.filter(
            org=org,
            user=request.user,
            ended_at__isnull=False,
            approval_status__in=[TimeEntry.APPROVAL_DRAFT, TimeEntry.APPROVAL_REJECTED],
        )
        if isinstance(data.get("ids"), list) and data["ids"]:
            qs = qs.filter(pk__in=[_uuid(i) for i in data["ids"][:500]])
        elif data.get("week"):
            monday = parse_week(data["week"])
            if monday is None:
                return _bad("week must look like 2026-W43 or a date")
            start, end = week_bounds(monday)
            qs = qs.filter(started_at__gte=start, started_at__lt=end)
        else:
            return _bad("Send ids or a week")
        count = qs.update(
            approval_status=TimeEntry.APPROVAL_SUBMITTED, submitted_at=timezone.now(), approval_note="", updated_at=timezone.now()
        )
        return Response({"submitted": count})


def _review_scope(actor, entry):
    """'ok' for an admin or a lead of one of the person's teams, 'forbidden' for a teammate,
    'hidden' for anyone else. Nobody reviews their own time."""
    if entry.user_id == actor.id:
        return "forbidden"
    if is_org_owner_or_admin(actor, entry.org):
        return "ok"
    their_teams = TeamMembership.objects.filter(user_id=entry.user_id, team__org=entry.org).values_list("team_id", flat=True)
    mine = TeamMembership.objects.filter(user=actor, team_id__in=list(their_teams))
    if mine.filter(team_role=TeamMembership.ROLE_LEAD).exists():
        return "ok"
    return "forbidden" if mine.exists() else "hidden"


class TimeEntryReviewView(V2APIView):
    permission_classes = [IsActiveOrgMember]
    decision = None

    def post(self, request, org_id, entry_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        entry = get_object_or_404(TimeEntry, pk=entry_id, org=org)
        scope = _review_scope(request.user, entry)
        if scope == "hidden":
            return _not_found("Time entry not found")
        if scope == "forbidden":
            return Response({"error": "permission_denied", "details": "Only a lead of this person's team or an admin can review their time."}, status=403)
        if entry.approval_status != TimeEntry.APPROVAL_SUBMITTED:
            return Response({"error": "not_submitted", "details": "This entry is not waiting for review."}, status=409)
        note = request.data.get("note") if isinstance(request.data, dict) else ""
        if note is not None and not isinstance(note, str):
            return _bad("note must be text")
        note = (note or "").strip()[:300]
        if self.decision == TimeEntry.APPROVAL_REJECTED and not note:
            return _bad("Say why you are sending it back.")
        entry.approval_status = self.decision
        entry.approval_note = note
        entry.approved_by = request.user
        entry.approved_at = timezone.now()
        entry.save(update_fields=["approval_status", "approval_note", "approved_by", "approved_at", "updated_at"])
        audit(request.user, f"time_entry.{self.decision}", target=entry, payload={"user": str(entry.user_id)}, org=org, request=request)
        return Response(
            _entry_payload(_entries_qs().get(pk=entry.pk), entry.user_id in _hidden_for(org, request.user, [entry]), request.user, readable_links(request.user, org))
        )


class TimeApprovalQueueView(V2APIView):
    """Submitted entries waiting for this lead (teams they lead) or admin (everyone)."""

    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        qs = _entries_qs().select_related("user").filter(org=org, approval_status=TimeEntry.APPROVAL_SUBMITTED).exclude(user=request.user)
        if not is_org_owner_or_admin(request.user, org):
            led = TeamMembership.objects.filter(user=request.user, team__org=org, team_role=TeamMembership.ROLE_LEAD).values_list("team_id", flat=True)
            people = TeamMembership.objects.filter(team_id__in=list(led)).values_list("user_id", flat=True)
            qs = qs.filter(user_id__in=list(people))
        rows = list(qs.order_by("submitted_at", "started_at")[:200])
        hidden = _hidden_for(org, request.user, rows)
        readable = readable_links(request.user, org)
        return Response(
            [{**_entry_payload(e, e.user_id in hidden, request.user, readable), "user_name": display_name(e.user)} for e in rows]
        )


def _week_param(request):
    value = request.query_params.get("week")
    if not value:
        return None, None
    monday = parse_week(value)
    if monday is None:
        return None, _bad("week must look like 2026-W43 or a date")
    return monday, None


class TimeReportMeView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        monday, error = _week_param(request)
        if error:
            return error
        return Response(report_me(org, request.user, period=request.query_params.get("period"), week=monday))


class TimeReportTeamView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    def get(self, request, org_id, team_id):
        org = _org(org_id)
        request.org = org
        HasPerm("time.view").has_permission(request, self)
        team = get_object_or_404(Team, pk=team_id, org=org)
        get_scoped_or_404(request.user, "time.view", team)
        lead = TeamMembership.objects.filter(team=team, user=request.user, team_role=TeamMembership.ROLE_LEAD).exists()
        if not (lead or is_org_owner_or_admin(request.user, org)):
            return Response({"error": "permission_denied", "details": "The team report is for the team lead and admins."}, status=403)
        monday, error = _week_param(request)
        if error:
            return error
        return Response(report_team(org, team, week=monday, viewer=request.user))


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
        room = None
        if request.query_params.get("room"):
            room = resolve_room(request.user, org, _uuid(request.query_params["room"]))
            if room is None:
                return _not_found("Room not found")
        bounds = {}
        for key in ("from", "to"):
            raw = request.query_params.get(key)
            if raw:
                try:
                    value = parse_date(raw[:10])
                except ValueError:
                    value = None
                if value is None:
                    return _bad(f"{key} must be a date (YYYY-MM-DD)")
                bounds[key] = value
        return Response(calendar_items(org, request.user, room=room, start=bounds.get("from"), end=bounds.get("to")))

