"""Daily standup and weekly report drafts for team leads (Phase 8d, spec 8.6).

The draft is built from rows, not from a model, so every line cites the task
or time entry it came from and nothing outside the team is read. A lead
reviews it; posting it to the team room is a separate step.
"""

from datetime import timedelta

from django.utils import timezone

from actions.models import AutoReport
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Team, TeamMembership

FLAG = "auto_reports"


def _is_admin(user, org):
    m = OrgMembership.objects.filter(org=org, user=user).first()
    return bool(m and m.is_active_member and m.org_role in {OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN})


def can_report(user, team) -> bool:
    return _is_admin(user, team.org) or TeamMembership.objects.filter(
        team=team, user=user, team_role=TeamMembership.ROLE_LEAD
    ).exists()


def check_report_access(user, org, team_id):
    """The team, if ``user`` leads it (or is an admin) and the flag is on. Raises ActionDenied otherwise."""
    from actions.service import ActionDenied

    team = Team.objects.filter(pk=team_id, org=org).first()
    if team is None:
        raise ActionDenied("not_found", "team not found")
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if not effective_flag(org, membership, FLAG, default=False):
        raise ActionDenied("not_available", "reports are not enabled")
    if not can_report(user, team):
        visible = _is_admin(user, org) or TeamMembership.objects.filter(team=team, user=user).exists()
        raise ActionDenied("permission" if visible else "not_found", "lead or admin only")
    return team


def _period(kind, now):
    return now - (timedelta(days=1) if kind == AutoReport.KIND_DAILY else timedelta(days=7)), now


def generate_report(user, org, team_id, kind) -> AutoReport:
    from rooms.models import Room, RoomMessage
    from tasks.models import Task
    from timetracking.models import TimeEntry

    team = check_report_access(user, org, team_id)
    start, end = _period(kind, timezone.now())
    member_ids = list(TeamMembership.objects.filter(team=team).values_list("user_id", flat=True))
    tasks = Task.objects.filter(org=org, team=team)
    done = list(tasks.filter(status=Task.STATUS_DONE, updated_at__gte=start, updated_at__lte=end).order_by("title"))
    moving = list(tasks.filter(status=Task.STATUS_IN_PROGRESS).order_by("title"))
    blocked = list(tasks.filter(is_blocked=True).exclude(status=Task.STATUS_DONE).order_by("blocked_since"))
    overdue = list(
        tasks.exclude(status=Task.STATUS_DONE).filter(due_on__lt=end.date()).order_by("due_on")
    )
    # Only time on this team's tasks: a member's hours on another team's work stay out.
    entries = list(
        TimeEntry.objects.filter(
            org=org,
            user_id__in=member_ids,
            task__team=team,
            started_at__gte=start,
            started_at__lte=end,
            ended_at__isnull=False,
        ).select_related("user", "task")
    )
    seconds_by_user = {}
    for entry in entries:
        seconds_by_user[entry.user] = seconds_by_user.get(entry.user, 0) + int((entry.ended_at - entry.started_at).total_seconds())
    room = Room.objects.filter(team=team, kind=Room.KIND_TEAM).first()
    messages = (
        RoomMessage.objects.filter(room=room, created_at__gte=start, created_at__lte=end, deleted_at__isnull=True).count()
        if room
        else 0
    )

    title = "Daily standup" if kind == AutoReport.KIND_DAILY else "Weekly report"
    lines = [f"# {title}: {team.name}", f"Period: {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC", ""]

    def section(name, rows, fmt):
        lines.append(f"## {name} ({len(rows)})")
        if rows:
            lines.extend(fmt(row) for row in rows[:50])
        else:
            lines.append("- none")
        lines.append("")

    section("Done", done, lambda t: f"- {t.title} [task:{t.id}]")
    section("In progress", moving, lambda t: f"- {t.title} [task:{t.id}]")
    section("Blocked", blocked, lambda t: f"- {t.title}: {t.blocked_reason or 'no reason given'} [task:{t.id}]")
    section("Overdue", overdue, lambda t: f"- {t.title} (due {t.due_on}) [task:{t.id}]")
    lines.append(f"## Time logged ({len(entries)} entries)")
    if seconds_by_user:
        for member, seconds in sorted(seconds_by_user.items(), key=lambda kv: -kv[1]):
            # Names, never emails: the report may be posted to the whole team room.
            lines.append(f"- {member.username or 'member ' + str(member.id)[:8]}: {seconds / 3600:.1f} h")
    else:
        lines.append("- none")
    lines.extend(["", f"Team room messages in the period: {messages}"])

    report = AutoReport.objects.create(
        org=org,
        team=team,
        kind=kind,
        period_start=start,
        period_end=end,
        content="\n".join(lines),
        sources={
            "tasks": sorted({str(t.id) for t in done + moving + blocked + overdue}),
            "time_entries": [str(e.id) for e in entries],
            "room_messages": messages,
        },
        generated_by=user,
    )
    from organizations.services.core import audit

    audit(user, "report.generate", target=report, payload={"team": str(team.id), "kind": kind}, org=org)
    return report


def payload(report) -> dict:
    return {
        "id": str(report.id),
        "team": str(report.team_id),
        "kind": report.kind,
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "content": report.content,
        "sources": report.sources,
        "generated_at": report.generated_at.isoformat(),
        "posted_room": str(report.posted_room_id) if report.posted_room_id else None,
        "posted_at": report.posted_at.isoformat() if report.posted_at else None,
    }
