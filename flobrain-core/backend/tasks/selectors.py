from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from organizations.models import OrgMembership, TeamMembership
from organizations.permissions import visible_team_ids
from tasks.models import Task
from timetracking.models import TimeEntry
from timetracking.reports import _duration_seconds


def visible_tasks(qs, user, org):
    team_ids = visible_team_ids(user, org)
    if team_ids is None:
        return qs
    return qs.filter(Q(team_id__in=team_ids) | Q(team__isnull=True)).distinct()


def deadline_priority(due_on) -> str:
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


def mission_control(org, user, team=None):
    scoped = visible_tasks(Task.objects.filter(org=org).prefetch_related("assignments__user"), user, org)
    if team is not None:
        scoped = scoped.filter(team=team)
    mine = scoped.filter(assignments__user=user).distinct()
    week_ago = timezone.now() - timedelta(days=7)
    accomplishments = list(
        scoped.filter(status=Task.STATUS_DONE, updated_at__gte=week_ago).order_by("-updated_at")[:10]
    )
    blockers = list(scoped.filter(is_blocked=True).order_by("-blocked_since")[:20])
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
    targets = {
        row.user_id: row.weekly_target_hours
        for row in TeamMembership.objects.filter(user_id__in=member_ids, team__org=org)
    }
    workload = []
    for user_id in sorted(member_ids, key=str):
        assigned = list(scoped.filter(assignments__user_id=user_id).distinct())
        workload.append(
            {
                "user_id": str(user_id),
                "open_tasks": sum(1 for task in assigned if task.status != Task.STATUS_DONE),
                "done_tasks": sum(1 for task in assigned if task.status == Task.STATUS_DONE),
                "seconds_7d": hours_by_user.get(user_id, 0),
                "weekly_target_hours": str(targets.get(user_id)) if targets.get(user_id) is not None else None,
                "task_ids": [str(task.id) for task in assigned],
            }
        )

    return {
        "assigned_open": mine.exclude(status=Task.STATUS_DONE).count(),
        "assigned_done": mine.filter(status=Task.STATUS_DONE).count(),
        "blocked": scoped.filter(is_blocked=True).count(),
        "by_status": list(scoped.values("status").annotate(count=Count("id")).order_by("status")),
        "overdue": scoped.filter(due_on__isnull=False)
        .exclude(status=Task.STATUS_DONE)
        .filter(due_on__lt=date.today())
        .count(),
        "accomplishments": [
            {
                "id": str(task.id),
                "title": task.title,
                "done_at": task.updated_at.isoformat(),
                "assignees": [str(row.user_id) for row in task.assignments.all()],
            }
            for task in accomplishments
        ],
        "blockers": [
            {
                "id": str(task.id),
                "title": task.title,
                "blocked_seconds": blocker_duration_seconds(task),
                "assignees": [str(row.user_id) for row in task.assignments.all()],
            }
            for task in blockers
        ],
        "deadlines": [
            {
                "id": str(task.id),
                "title": task.title,
                "due_on": task.due_on.isoformat(),
                "priority": deadline_priority(task.due_on),
                "assignees": [str(row.user_id) for row in task.assignments.all()],
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
