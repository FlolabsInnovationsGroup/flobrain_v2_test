"""Data for steps: task context for ``ai_prompt``, who to notify, the proactive daily brief,
overdue nudges and the budget check.

Every brief and nudge is built from the recipient's own tasks, meetings and approvals and is sent
only to that person. People can opt out (``BriefOptOut``).
"""

import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from automations.engine import StepFailed, StopRun
from automations.models import BriefOptOut
from automations.schema import tz_name

MAX_LINES = 50


def org_today(org):
    return timezone.now().astimezone(ZoneInfo(tz_name({}, org))).date()


def _name(user) -> str:
    return ((getattr(user, "username", "") or "").strip() or "Member") if user else "Nobody"


def _task_lines(tasks, today, show_blocked=False):
    lines = []
    for task in tasks[:MAX_LINES]:
        who = ", ".join(_name(a.user) for a in task.assignments.all()) or "unassigned"
        parts = [f"- {task.title} ({task.status.replace('_', ' ')}; {who})"]
        if task.due_on:
            parts.append(f"due {task.due_on.isoformat()}")
        if show_blocked and task.is_blocked:
            days = (timezone.now() - task.blocked_since).days if task.blocked_since else 0
            parts.append(f"blocked {days} day(s): {(task.blocked_reason or 'no reason given')[:200]}")
        lines.append("; ".join(parts))
    return "\n".join(lines) or "(no matching tasks)"


def context_text(org, owner, kind, run, room_id=None) -> str:
    """The data an ``ai_prompt`` step sees, limited to what ``owner`` can see."""
    if kind == "none":
        return ""
    if kind == "trigger":
        return json.dumps(run.trigger_payload or {}, ensure_ascii=False)[:4000]
    from tasks.models import Task
    from tasks.selectors import room_q, visible_tasks

    qs = visible_tasks(Task.objects.filter(org=org), owner, org).exclude(status=Task.STATUS_DONE)
    if room_id:
        from automations.engine import _room

        qs = qs.filter(room_q(_room(org, owner, room_id, run)))
    today = org_today(org)
    if kind == "blocked_tasks":
        qs = qs.filter(is_blocked=True)
    elif kind == "overdue_tasks":
        qs = qs.filter(due_on__lt=today)
    elif kind == "tasks_due_today":
        qs = qs.filter(due_on=today)
    elif kind == "recent_tasks":
        qs = visible_tasks(Task.objects.filter(org=org), owner, org).filter(updated_at__gte=timezone.now() - timedelta(days=7))
        if room_id:
            from automations.engine import _room

            qs = qs.filter(room_q(_room(org, owner, room_id, run)))
    else:
        raise StepFailed("Unknown context.")
    qs = qs.prefetch_related("assignments__user").order_by("due_on", "title")
    return f"Today is {today.isoformat()}.\n" + _task_lines(list(qs[:MAX_LINES]), today, show_blocked=True)


def recipients(org, owner, people, roles, payload) -> set:
    from organizations.models import OrgMembership, TeamMembership
    from rooms.models import Room, RoomMember
    from rooms.services import user_can_access_room
    from tasks.models import Task, TaskAssignment

    ids = {str(p) for p in people}
    task = Task.objects.filter(pk=payload.get("task"), org=org).first() if payload.get("task") else None
    for role in roles:
        if role == "owner" and owner is not None:
            ids.add(str(owner.id))
        elif role == "admins":
            ids |= {
                str(u)
                for u in OrgMembership.objects.filter(
                    org=org, org_role__in=[OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN], employment_status="active"
                ).values_list("user_id", flat=True)
            }
        elif role == "team_leads":
            team_id = payload.get("team") or (task.team_id if task else None)
            if team_id:
                ids |= {
                    str(u)
                    for u in TeamMembership.objects.filter(
                        team_id=team_id, team__org=org, team_role=TeamMembership.ROLE_LEAD
                    ).values_list("user_id", flat=True)
                }
        elif role == "task_assignees" and task is not None:
            ids |= {str(u) for u in TaskAssignment.objects.filter(task=task).values_list("user_id", flat=True)}
        elif role == "room_members" and payload.get("room"):
            room = Room.objects.filter(pk=payload["room"], org=org).first()
            if room is not None and owner is not None and user_can_access_room(owner, room):
                ids |= {str(u) for u in RoomMember.objects.filter(room=room).values_list("user_id", flat=True)}
    active = OrgMembership.objects.filter(org=org, user_id__in=list(ids), employment_status="active")
    return {str(u) for u in active.values_list("user_id", flat=True)}


def opted_out(org, kind) -> set:
    return {str(u) for u in BriefOptOut.objects.filter(org=org, kind=kind).values_list("user_id", flat=True)}


def _day_bounds(org, day):
    tz = ZoneInfo(tz_name({}, org))
    start = datetime.combine(day, time(0, 0), tzinfo=tz)
    return start, start + timedelta(days=1)


def brief_for(org, user, today=None) -> str:
    """One person's day: their tasks due today and overdue, today's meetings in rooms they can
    read, and approvals waiting for them. Empty when there is nothing to say."""
    from actions.models import ActionProposal
    from meetings.models import Meeting
    from rooms.services import accessible_rooms
    from tasks.models import Task
    from tasks.selectors import my_tasks

    today = today or org_today(org)
    mine = my_tasks(org, user).exclude(status=Task.STATUS_DONE)
    due = list(mine.filter(due_on=today).values_list("title", flat=True)[:20])
    overdue = mine.filter(due_on__lt=today).count()
    start, end = _day_bounds(org, today)
    meetings = list(
        Meeting.objects.filter(org=org, started_at__gte=start, started_at__lt=end, room__in=accessible_rooms(user, org))
        .order_by("started_at")
        .values_list("title", flat=True)[:10]
    )
    approvals = ActionProposal.objects.filter(
        org=org, user=user, status=ActionProposal.STATUS_PROPOSED, expires_at__gt=timezone.now()
    ).count()
    if not (due or overdue or meetings or approvals):
        return ""
    parts = []
    if due:
        parts.append(f"{len(due)} task(s) due today: {', '.join(t[:60] for t in due[:3])}" + ("…" if len(due) > 3 else ""))
    if overdue:
        parts.append(f"{overdue} overdue task(s)")
    if meetings:
        parts.append(f"{len(meetings)} meeting(s): {', '.join(m[:60] for m in meetings[:3])}")
    if approvals:
        parts.append(f"{approvals} approval(s) waiting for you")
    return "Your day: " + "; ".join(parts) + "."


def send_daily_briefs(org) -> int:
    from notifications.services import notify
    from organizations.models import OrgMembership

    skip = opted_out(org, BriefOptOut.DAILY_BRIEF)
    today = org_today(org)
    sent = 0
    members = OrgMembership.objects.filter(org=org, employment_status="active").select_related("user")
    for membership in members[:2000]:
        if str(membership.user_id) in skip:
            continue
        text = brief_for(org, membership.user, today)
        if text:
            sent += notify(org, [membership.user_id], "automation.daily_brief", {"text": text, "title": "Your daily brief"}, link="tasks")
    return sent


def send_nudges(org, owner, min_days=1) -> int:
    from notifications.services import notify
    from tasks.models import Task
    from tasks.selectors import visible_tasks

    skip = opted_out(org, BriefOptOut.NUDGES)
    cutoff = org_today(org) - timedelta(days=min_days)
    tasks = (
        visible_tasks(Task.objects.filter(org=org), owner, org)
        .exclude(status=Task.STATUS_DONE)
        .filter(due_on__isnull=False, due_on__lte=cutoff)
        .prefetch_related("assignments")
    )
    by_person = {}
    for task in tasks[:1000]:
        for assignment in task.assignments.all():
            by_person.setdefault(str(assignment.user_id), []).append(task.title)
    sent = 0
    for user_id, titles in by_person.items():
        if user_id in skip:
            continue
        text = f"You have {len(titles)} overdue task(s): {', '.join(t[:60] for t in titles[:3])}" + ("…" if len(titles) > 3 else ".")
        sent += notify(org, [user_id], "automation.nudge", {"text": text, "title": "Overdue tasks"}, link="tasks")
    return sent


def budget_status(org, threshold) -> str:
    from telemetry.models import Budget
    from telemetry.pricing import budget_spend

    budget = Budget.objects.filter(org=org, scope_type=Budget.SCOPE_ORG).first()
    if budget is None or not budget.cap_amount:
        raise StopRun("No monthly AI budget is set, so there is nothing to check.")
    spent = budget_spend(budget)
    pct = float(spent) / float(budget.cap_amount) * 100
    if pct < threshold:
        raise StopRun(f"AI spend is at {pct:.0f}% of the monthly budget, below {threshold}%. Nothing to do.")
    return f"AI spend is at {pct:.0f}% of the monthly budget ({spent:.2f} of {budget.cap_amount:.2f} {budget.currency})."
