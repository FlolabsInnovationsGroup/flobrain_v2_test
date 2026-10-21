from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from organizations.models import OrgMembership, TeamMembership
from organizations.permissions.engine import can
from tasks.models import Task, TaskActivity, TaskAssignment


def _is_lead_or_admin(user, org, team=None) -> bool:
    if getattr(user, "is_platform_admin", False):
        return True
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if membership and membership.org_role in {
        OrgMembership.ORG_ROLE_OWNER,
        OrgMembership.ORG_ROLE_ADMIN,
    }:
        return True
    if team and TeamMembership.objects.filter(team=team, user=user, team_role=TeamMembership.ROLE_LEAD).exists():
        return True
    return False


def display_name(user) -> str:
    if user is None:
        return ""
    return user.username or (user.email or "").split("@")[0] or str(user.id)[:8]


def can_assign(actor, org, assignee, task: Task) -> bool:
    ok, _reason = assign_eligibility(actor, org, assignee, task)
    return ok


def assign_eligibility(actor, org, assignee, task: Task):
    membership = OrgMembership.objects.filter(org=org, user=assignee).first()
    if membership is None or not membership.is_active_member:
        return False, "inactive"
    actor_membership = OrgMembership.objects.filter(org=org, user=actor).first()
    is_org_admin = getattr(actor, "is_platform_admin", False) or (
        actor_membership
        and actor_membership.org_role
        in {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN}
    )
    if is_org_admin:
        return True, None
    is_lead = bool(
        task.team
        and TeamMembership.objects.filter(
            team=task.team, user=actor, team_role=TeamMembership.ROLE_LEAD
        ).exists()
    )
    if is_lead:
        if TeamMembership.objects.filter(team=task.team, user=assignee).exists():
            return True, None
        return False, "out_of_team"
    if str(assignee.id) == str(actor.id):
        return True, None
    return False, "assign_others"


def can_edit_task(actor, task: Task) -> bool:
    if _is_lead_or_admin(actor, task.org, team=task.team):
        return True
    if task.created_by_id == actor.id:
        return True
    return TaskAssignment.objects.filter(task=task, user=actor).exists()


def can_delete_task(actor, task: Task) -> bool:
    """The creator, the team's lead, or an org admin. Assignees can move a task but not delete it."""
    return task.created_by_id == actor.id or _is_lead_or_admin(actor, task.org, team=task.team)


def can_set_due_date(actor, task: Task) -> bool:
    """Decision 2: due dates on other people's tasks are for the team lead and admins."""
    if _is_lead_or_admin(actor, task.org, team=task.team):
        return True
    others = TaskAssignment.objects.filter(task=task).exclude(user=actor).exists()
    return not others and can_edit_task(actor, task)


class EditContext:
    """Answers can_edit for many tasks with a fixed number of queries (list payloads)."""

    def __init__(self, actor, org):
        self.actor = actor
        self.admin = _is_lead_or_admin(actor, org)
        self.lead_teams = set(
            TeamMembership.objects.filter(user=actor, team__org=org, team_role=TeamMembership.ROLE_LEAD).values_list(
                "team_id", flat=True
            )
        )

    def can_edit(self, task: Task) -> bool:
        if self.admin or (task.team_id and task.team_id in self.lead_teams):
            return True
        if task.created_by_id == self.actor.id:
            return True
        return any(a.user_id == self.actor.id for a in task.assignments.all())

    def can_delete(self, task: Task) -> bool:
        return self.admin or (task.team_id and task.team_id in self.lead_teams) or task.created_by_id == self.actor.id


def log_activity(task, actor, verb, payload=None):
    return TaskActivity.objects.create(task=task, actor=actor, verb=verb, payload=payload or {})


# Notification preference types (settings page) for each notification kind.
PREF_TYPE = {
    "task.assigned": "task_assigned",
    "task.due_soon": "task_deadline_reached",
    "task.overdue": "task_deadline_reached",
}


def notify_task(task: Task, users, kind: str, payload: dict | None = None, push: bool = False) -> int:
    """``notifications.services.notify`` for a task, honouring the per-type switches on the
    notification settings page (stored under their underscore names)."""
    from notifications.models import NotificationPreference
    from notifications.services import notify

    ids = {getattr(u, "id", u) for u in users if u is not None}
    if not ids:
        return 0
    pref = PREF_TYPE.get(kind)
    prefs = {row.user_id: row for row in NotificationPreference.objects.filter(user_id__in=ids, type=pref)} if pref else {}
    ids = {uid for uid in ids if uid not in prefs or prefs[uid].enabled}
    data = {"title": task.title, "task": str(task.id), **(payload or {})}
    push_ids = {uid for uid in ids if push and (uid not in prefs or prefs[uid].push)}
    sent = 0
    if push_ids:
        sent += notify(task.org, push_ids, kind, data, link="tasks", push=True, push_title=data.get("text", ""))
    if ids - push_ids:
        sent += notify(task.org, ids - push_ids, kind, data, link="tasks")
    return sent


def assign_task(task: Task, actor, assignee, *, notify_assignee: bool = True):
    if not can(actor, "task.write", {"org": task.org, "team": task.team, "project": task.project}):
        return False, "permission"
    ok, reason = assign_eligibility(actor, task.org, assignee, task)
    if not ok:
        return False, reason
    _row, created = TaskAssignment.objects.get_or_create(task=task, user=assignee, defaults={"assigned_by": actor})
    if created:
        log_activity(task, actor, "assign", {"assignee": str(assignee.id)})
        if notify_assignee and assignee.id != actor.id:
            notify_task(
                task,
                [assignee],
                "task.assigned",
                {"by": display_name(actor), "text": f"You were assigned “{task.title}”"},
                push=True,
            )
    return True, None


def unassign_task(task: Task, actor, assignee):
    """Leads and admins remove anyone they could assign; everyone else only themselves."""
    if str(assignee.id) != str(actor.id) and not _is_lead_or_admin(actor, task.org, team=task.team):
        return False, "permission"
    deleted, _ = TaskAssignment.objects.filter(task=task, user=assignee).delete()
    if not deleted:
        return False, "not_assigned"
    log_activity(task, actor, "unassign", {"assignee": str(assignee.id)})
    return True, None


def _column(org, status, exclude_id=None):
    qs = Task.objects.filter(org=org, status=status).order_by("position", "created_at", "id")
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return list(qs.only("id", "position"))


def move_task(task: Task, actor, status: str, *, before=None, position=None):
    """Move to ``status`` and place it before the task ``before`` (an id in the same column), at
    index ``position`` of the column, or at the end. Renumbers the column 0..n."""
    if status not in Task.STATUSES:
        return False, "invalid_status"
    if not can_edit_task(actor, task):
        return False, "permission"
    if position is not None and (isinstance(position, bool) or not isinstance(position, int) or position < 0):
        return False, "invalid_position"
    with transaction.atomic():
        column = _column(task.org, status, exclude_id=task.pk)
        index = len(column)
        if before:
            ids = [str(row.id) for row in column]
            if str(before) not in ids:
                return False, "invalid_before"
            index = ids.index(str(before))
        elif position is not None:
            index = min(position, len(column))
        column.insert(index, task)
        changed = []
        for i, row in enumerate(column):
            if row.pk != task.pk and row.position != i:
                row.position = i
                changed.append(row)
        if changed:
            Task.objects.bulk_update(changed, ["position"])
        previous = task.status
        task.status = status
        task.position = index
        if status == Task.STATUS_DONE and previous != Task.STATUS_DONE:
            task.completed_at = timezone.now()
        elif status != Task.STATUS_DONE:
            task.completed_at = None
        task.save(update_fields=["status", "position", "completed_at", "updated_at"])
        if previous != status:
            log_activity(task, actor, "move", {"status": status, "from": previous})
        else:
            log_activity(task, actor, "reorder", {"position": index})
    return True, None


def set_blocked(task: Task, actor, blocked: bool, reason=""):
    if not can_edit_task(actor, task):
        return False, "permission"
    was = task.is_blocked
    task.is_blocked = blocked
    task.blocked_reason = (reason or "")[:1000] if blocked else ""
    if blocked and not was:
        task.blocked_since = timezone.now()
    elif not blocked:
        task.blocked_since = None
    task.save(update_fields=["is_blocked", "blocked_reason", "blocked_since", "updated_at"])
    if blocked != was:
        log_activity(task, actor, "blocked" if blocked else "unblocked", {"reason": task.blocked_reason})
    return True, None


def can_use_project(actor, project) -> bool:
    """Admins, the project lead, direct members, and members of the project's teams.

    The org-level check only confirms an active membership: ``can(..., project)`` alone is
    False for members of the project's teams (no ProjectMembership row), which this function
    is meant to allow."""
    if not can(actor, "project.view", project.org):
        return False
    if _is_lead_or_admin(actor, project.org) or project.lead_id == actor.id:
        return True
    from organizations.models import ProjectMembership

    if ProjectMembership.objects.filter(project=project, user=actor).exists():
        return True
    return TeamMembership.objects.filter(team__in=project.teams.all(), user=actor).exists()


def parse_due(value):
    """``None``/"" clear it; a date or ISO string sets it; anything else is ``False`` (invalid)."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return False
    try:
        parsed = parse_date(value)
    except ValueError:
        return False
    return parsed or False


def resolve_room(actor, org, room_id):
    """A room in ``org`` the actor can open, or None."""
    from rooms.models import Room
    from rooms.services import user_can_access_room

    room = Room.objects.filter(pk=room_id, org=org, is_active=True).first()
    if room is None or not user_can_access_room(actor, room):
        return None
    return room


class _Rollback(Exception):
    def __init__(self, reason):
        self.reason = reason


def create_task(
    actor,
    org,
    title,
    *,
    description="",
    team_id=None,
    project_id=None,
    due_on=None,
    room_id=None,
    priority=None,
    assignee_ids=None,
):
    """Create a task for ``actor``. Returns (task, error). Team, project and room must be in ``org``
    and usable by the actor (a foreign or hidden id is "not_found"). With ``assignee_ids`` the task
    goes to those people (each checked like the assign endpoint); without, to the actor."""
    from organizations.models import Project, Team
    from users.models import User

    title = title.strip() if isinstance(title, str) else ""
    if not title:
        return None, "invalid"
    if not isinstance(description, str):
        return None, "invalid"
    if priority is None:
        priority = Task.PRIORITY_NORMAL
    if priority not in Task.PRIORITIES:
        return None, "invalid_priority"
    if not can(actor, "task.write", org):
        return None, "permission"
    team = project = room = None
    if room_id:
        room = resolve_room(actor, org, room_id)
        if room is None:
            return None, "not_found"
        team_id = team_id or room.team_id
        project_id = project_id or room.project_id
    if team_id:
        team = Team.objects.filter(pk=team_id, org=org).first()
        if team is None or not can(actor, "task.write", team):
            return None, "not_found"
    if project_id:
        project = Project.objects.filter(pk=project_id, org=org).first()
        if project is None or not can_use_project(actor, project):
            return None, "not_found"
    assignees = []
    if assignee_ids:
        found = {str(u.id): u for u in User.objects.filter(pk__in=list(assignee_ids))}
        for uid in assignee_ids:
            if str(uid) not in found:
                return None, "inactive"
            assignees.append(found[str(uid)])
        if any(u.id != actor.id for u in assignees) and due_on is None:
            return None, "due_required"
    try:
        with transaction.atomic():
            column_end = Task.objects.filter(org=org, status=Task.STATUS_TODO).count()
            task = Task.objects.create(
                org=org,
                title=title[:200],
                description=(description or "")[:4000],
                created_by=actor,
                project=project,
                team=team,
                room=room,
                due_on=due_on,
                priority=priority,
                position=column_end,
            )
            log_activity(task, actor, "create", {})
            if not assignees:
                TaskAssignment.objects.get_or_create(task=task, user=actor, defaults={"assigned_by": actor})
            for person in assignees:
                ok, reason = assign_task(task, actor, person, notify_assignee=False)
                if not ok:
                    raise _Rollback(reason)
    except _Rollback as exc:
        return None, exc.reason
    others = [u for u in assignees if u.id != actor.id]
    if others:
        notify_task(
            task,
            others,
            "task.assigned",
            {"by": display_name(actor), "text": f"You were assigned “{task.title}”"},
            push=True,
        )
    return task, None


def send_due_reminders(today=None, org=None) -> dict:
    """Due tomorrow and overdue notifications to assignees. Idempotent: a ``TaskReminder`` row per
    task, kind and due date is written in the same transaction as the notification."""
    from django.db import IntegrityError

    from tasks.models import TaskReminder

    today = today or timezone.localdate()
    sent = {"task.due_soon": 0, "task.overdue": 0}
    base = (
        Task.objects.filter(org__is_active=True, due_on__isnull=False)
        .exclude(status=Task.STATUS_DONE)
        .select_related("org")
        .prefetch_related("assignments")
    )
    if org is not None:
        base = base.filter(org=org)
    plans = (
        (TaskReminder.KIND_DUE_SOON, base.filter(due_on=today + timedelta(days=1))),
        (TaskReminder.KIND_OVERDUE, base.filter(due_on__lt=today)),
    )
    for kind, qs in plans:
        already = set(
            TaskReminder.objects.filter(kind=kind, task__in=qs).values_list("task_id", "due_on")
        )
        for task in qs.order_by("due_on", "id")[:2000]:
            if (task.id, task.due_on) in already:
                continue
            people = [a.user_id for a in task.assignments.all()]
            try:
                with transaction.atomic():
                    TaskReminder.objects.create(task=task, kind=kind, due_on=task.due_on)
                    text = (
                        f"“{task.title}” is due tomorrow"
                        if kind == TaskReminder.KIND_DUE_SOON
                        else f"“{task.title}” is overdue"
                    )
                    notify_task(task, people, kind, {"due_on": task.due_on.isoformat(), "text": text}, push=True)
            except IntegrityError:
                continue  # another ticker got there first
            sent[kind] += 1
    return sent
