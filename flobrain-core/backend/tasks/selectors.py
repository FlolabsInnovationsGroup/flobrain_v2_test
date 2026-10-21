from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from organizations.models import OrgMembership, TeamMembership
from organizations.permissions import visible_team_ids
from tasks.models import Task
from timetracking.models import TimeEntry
from timetracking.reports import _duration_seconds  # noqa: F401  (kept for importers)


def visible_tasks(qs, user, org):
    team_ids = visible_team_ids(user, org)
    if team_ids is None:
        return qs
    return qs.filter(Q(team_id__in=team_ids) | Q(team__isnull=True)).distinct()


def room_q(room) -> Q:
    """Tasks on a room's board: tasks filed in the room, plus its team's or project's tasks."""
    q = Q(room=room)
    if room.team_id:
        q |= Q(team_id=room.team_id)
    if room.project_id:
        q |= Q(project_id=room.project_id)
    return q


def deadline_priority(due_on) -> str:
    """Urgency derived from the due date (not the task's own priority)."""
    if due_on is None:
        return "none"
    days = (due_on - date.today()).days
    if days < 0:
        return "overdue"
    if days <= 2:
        return "high"
    if days <= 7:
        return "medium"
    return "low"


def blocker_duration_seconds(task) -> int:
    if not task.blocked_since:
        return 0
    return max(int((timezone.now() - task.blocked_since).total_seconds()), 0)


def filter_tasks(qs, user, params):
    """Apply list filters (Decision 4 plus team, project, status, due and blocked). Returns
    (queryset, error). Unknown values are a 400, never a 500."""
    import uuid

    from django.utils.dateparse import parse_date

    def _uuid(value):
        try:
            return uuid.UUID(str(value))
        except ValueError:
            return None

    mode = params.get("filter") or ("mine" if params.get("mine") == "1" else "all")
    if mode == "mine":
        qs = qs.filter(assignments__user=user)
    elif mode == "assigned_by_me":
        from tasks.models import TaskAssignment

        given = TaskAssignment.objects.filter(assigned_by=user).exclude(user=user).values("task_id")
        qs = qs.filter(pk__in=given)
    elif mode == "completed":
        qs = qs.filter(status=Task.STATUS_DONE)
    elif mode != "all":
        return None, "filter"
    for key, field in (("assignee", "assignments__user_id"), ("assigned_by", "assignments__assigned_by_id"), ("team", "team_id"), ("project", "project_id")):
        if params.get(key):
            value = _uuid(params[key])
            if value is None:
                return None, key
            qs = qs.filter(**{field: value})
    if params.get("status"):
        if params["status"] not in Task.STATUSES:
            return None, "status"
        qs = qs.filter(status=params["status"])
    if params.get("priority"):
        if params["priority"] not in Task.PRIORITIES:
            return None, "priority"
        qs = qs.filter(priority=params["priority"])
    if params.get("blocked") in {"1", "true"}:
        qs = qs.filter(is_blocked=True)
    elif params.get("blocked") in {"0", "false"}:
        qs = qs.filter(is_blocked=False)
    due = params.get("due")
    today = timezone.localdate()
    if due:
        open_qs = qs.exclude(status=Task.STATUS_DONE)
        if due == "overdue":
            qs = open_qs.filter(due_on__lt=today)
        elif due == "today":
            qs = open_qs.filter(due_on=today)
        elif due == "week":
            qs = open_qs.filter(due_on__gte=today, due_on__lte=today + timedelta(days=7))
        elif due == "none":
            qs = qs.filter(due_on__isnull=True)
        else:
            return None, "due"
    if params.get("due_before"):
        try:
            before = parse_date(params["due_before"])
        except ValueError:
            before = None
        if before is None:
            return None, "due_before"
        qs = qs.filter(due_on__lte=before)
    return qs.distinct(), None


def _names(user_ids):
    from tasks.services import display_name
    from users.models import User

    return {u.id: display_name(u) for u in User.objects.filter(pk__in=[i for i in user_ids if i])}


def mission_control(org, user, team=None):
    scoped = visible_tasks(
        Task.objects.filter(org=org).prefetch_related("assignments__user").select_related("team"), user, org
    )
    if team is not None:
        scoped = scoped.filter(team=team)
    mine = scoped.filter(assignments__user=user).distinct()
    now = timezone.now()
    week_ago = now - timedelta(days=7)
    accomplishments = list(
        scoped.filter(status=Task.STATUS_DONE)
        .filter(Q(completed_at__gte=week_ago) | Q(completed_at__isnull=True, updated_at__gte=week_ago))
        .order_by("-completed_at", "-updated_at")[:10]
    )
    blockers = list(scoped.filter(is_blocked=True).order_by("blocked_since")[:20])
    deadlines = list(
        scoped.filter(due_on__isnull=False).exclude(status=Task.STATUS_DONE).order_by("due_on")[:20]
    )

    member_ids = set(scoped.values_list("assignments__user_id", flat=True))
    member_ids.discard(None)
    if team is not None:
        member_ids.update(team.memberships.values_list("user_id", flat=True))
    else:
        member_ids.update(
            OrgMembership.objects.filter(org=org, employment_status=OrgMembership.STATUS_ACTIVE).values_list(
                "user_id", flat=True
            )
        )
    week_entries = TimeEntry.objects.filter(org=org, user_id__in=member_ids, started_at__gte=week_ago)
    hours_by_user = {}
    for entry in week_entries:
        hours_by_user[entry.user_id] = hours_by_user.get(entry.user_id, 0) + entry.seconds
    target_rows = TeamMembership.objects.filter(user_id__in=member_ids, team__org=org)
    if team is not None:
        target_rows = target_rows.filter(team=team)
    targets = {}
    for row in target_rows:
        if row.weekly_target_hours is not None:
            targets[row.user_id] = targets.get(row.user_id, 0) + row.weekly_target_hours
    names = _names(member_ids | {a.user_id for t in accomplishments + blockers + deadlines for a in t.assignments.all()})

    def people(task):
        return [{"id": str(a.user_id), "name": names.get(a.user_id, "")} for a in task.assignments.all()]

    assigned_by_user = {}
    for task in scoped.filter(assignments__user_id__in=member_ids).distinct():
        for a in task.assignments.all():
            if a.user_id in member_ids:
                assigned_by_user.setdefault(a.user_id, []).append(task)
    workload = []
    for user_id in sorted(member_ids, key=lambda uid: (names.get(uid, "").lower(), str(uid))):
        assigned = sorted(assigned_by_user.get(user_id, []), key=lambda t: (t.status == Task.STATUS_DONE, t.due_on or date.max))
        target = targets.get(user_id)
        seconds = hours_by_user.get(user_id, 0)
        workload.append(
            {
                "user_id": str(user_id),
                "name": names.get(user_id, ""),
                "open_tasks": sum(1 for task in assigned if task.status != Task.STATUS_DONE),
                "done_tasks": sum(1 for task in assigned if task.status == Task.STATUS_DONE),
                "blocked_tasks": sum(1 for task in assigned if task.is_blocked and task.status != Task.STATUS_DONE),
                "seconds_7d": seconds,
                "weekly_target_hours": str(target) if target is not None else None,
                # Decision 17: capacity only when a target is set.
                "capacity_seconds": int(float(target) * 3600) - seconds if target is not None else None,
                "task_ids": [str(task.id) for task in assigned],
                "tasks": [
                    {
                        "id": str(task.id),
                        "title": task.title,
                        "status": task.status,
                        "priority": task.priority,
                        "due_on": task.due_on.isoformat() if task.due_on else None,
                        "is_blocked": task.is_blocked,
                    }
                    for task in assigned
                ],
            }
        )

    return {
        "assigned_open": mine.exclude(status=Task.STATUS_DONE).count(),
        "assigned_done": mine.filter(status=Task.STATUS_DONE).count(),
        "blocked": scoped.filter(is_blocked=True).exclude(status=Task.STATUS_DONE).count(),
        "by_status": list(scoped.values("status").annotate(count=Count("id", distinct=True)).order_by("status")),
        "total": scoped.count(),
        "done": scoped.filter(status=Task.STATUS_DONE).count(),
        "overdue": scoped.filter(due_on__isnull=False)
        .exclude(status=Task.STATUS_DONE)
        .filter(due_on__lt=date.today())
        .count(),
        "accomplishments": [
            {
                "id": str(task.id),
                "title": task.title,
                "done_at": (task.completed_at or task.updated_at).isoformat(),
                "assignees": [str(row.user_id) for row in task.assignments.all()],
                "people": people(task),
            }
            for task in accomplishments
        ],
        "blockers": [
            {
                "id": str(task.id),
                "title": task.title,
                "reason": task.blocked_reason,
                "blocked_seconds": blocker_duration_seconds(task),
                "assignees": [str(row.user_id) for row in task.assignments.all()],
                "people": people(task),
            }
            for task in blockers
        ],
        "deadlines": [
            {
                "id": str(task.id),
                "title": task.title,
                "due_on": task.due_on.isoformat(),
                "priority": task.priority,
                "urgency": deadline_priority(task.due_on),
                "is_blocked": task.is_blocked,
                "assignees": [str(row.user_id) for row in task.assignments.all()],
                "people": people(task),
            }
            for task in deadlines
        ],
        "workload": workload,
    }


def my_tasks(org, user):
    return (
        Task.objects.filter(org=org)
        .filter(Q(assignments__user=user) | Q(created_by=user))
        .distinct()
        .order_by("due_on", "-created_at")
    )


def calendar_items(org, user, *, room=None, start=None, end=None):
    """Task deadlines the user can see and meetings in rooms they can open, between two dates."""
    from meetings.models import Meeting
    from rooms.services import user_can_access_room

    tasks = visible_tasks(Task.objects.filter(org=org, due_on__isnull=False), user, org)
    if room is not None:
        tasks = tasks.filter(room_q(room))
    if start:
        tasks = tasks.filter(due_on__gte=start)
    if end:
        tasks = tasks.filter(due_on__lte=end)
    tasks = tasks.prefetch_related("assignments").order_by("due_on", "position")[:500]
    task_rows = list(tasks)
    names = _names({a.user_id for t in task_rows for a in t.assignments.all()})
    items = [
        {
            "id": str(t.id),
            "kind": "task",
            "title": t.title,
            "due_on": t.due_on.isoformat(),
            "date": t.due_on.isoformat(),
            "status": t.status,
            "priority": t.priority,
            "is_blocked": t.is_blocked,
            "overdue": t.status != Task.STATUS_DONE and t.due_on < timezone.localdate(),
            "people": [{"id": str(a.user_id), "name": names.get(a.user_id, "")} for a in t.assignments.all()],
        }
        for t in task_rows
    ]
    meetings = Meeting.objects.filter(org=org).select_related("room")
    if room is not None:
        meetings = meetings.filter(room=room)
    if start:
        meetings = meetings.filter(started_at__date__gte=start)
    if end:
        meetings = meetings.filter(started_at__date__lte=end)
    allowed = {}
    for meeting in meetings.order_by("started_at")[:300]:
        if meeting.room_id not in allowed:
            allowed[meeting.room_id] = user_can_access_room(user, meeting.room)
        if not allowed[meeting.room_id]:
            continue
        day = timezone.localtime(meeting.started_at).date().isoformat()
        items.append(
            {
                "id": str(meeting.id),
                "kind": "meeting",
                "title": meeting.title,
                "due_on": day,
                "date": day,
                "starts_at": meeting.started_at.isoformat(),
                "room": str(meeting.room_id),
                "room_name": meeting.room.name,
            }
        )
    items.sort(key=lambda item: (item["date"], item["kind"] != "meeting", item.get("starts_at") or ""))
    return items
