from django.utils import timezone

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


def log_activity(task, actor, verb, payload=None):
    return TaskActivity.objects.create(task=task, actor=actor, verb=verb, payload=payload or {})


def assign_task(task: Task, actor, assignee):
    if not can(actor, "task.write", {"org": task.org, "team": task.team, "project": task.project}):
        return False, "permission"
    ok, reason = assign_eligibility(actor, task.org, assignee, task)
    if not ok:
        return False, reason
    TaskAssignment.objects.get_or_create(task=task, user=assignee)
    log_activity(task, actor, "assign", {"assignee": str(assignee.id)})
    return True, None


def move_task(task: Task, actor, status: str):
    if status not in {Task.STATUS_TODO, Task.STATUS_IN_PROGRESS, Task.STATUS_DONE}:
        return False, "invalid_status"
    if not can_edit_task(actor, task):
        return False, "permission"
    task.status = status
    task.save(update_fields=["status", "updated_at"])
    log_activity(task, actor, "move", {"status": status})
    return True, None


def set_blocked(task: Task, actor, blocked: bool, reason=""):
    if not can_edit_task(actor, task):
        return False, "permission"
    task.is_blocked = blocked
    task.blocked_reason = reason if blocked else ""
    task.blocked_since = timezone.now() if blocked else None
    task.save(update_fields=["is_blocked", "blocked_reason", "blocked_since", "updated_at"])
    return True, None
