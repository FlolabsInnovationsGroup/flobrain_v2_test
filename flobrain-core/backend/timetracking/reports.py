import re
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from timetracking.models import TimeEntry

WEEK = re.compile(r"^(\d{4})-W(\d{1,2})$")


def _duration_seconds(qs):
    total = 0
    for entry in qs:
        total += entry.seconds
    return total


def parse_week(value):
    """``2026-W43`` or any date in the week (``2026-10-21``) → the Monday, or None if invalid.
    An empty value means the current week."""
    if not value:
        today = timezone.localdate()
        return today - timedelta(days=today.weekday())
    if not isinstance(value, str):
        return None
    match = WEEK.match(value.strip())
    try:
        if match:
            return date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
        day = date.fromisoformat(value.strip())
    except ValueError:
        return None
    return day - timedelta(days=day.weekday())


def week_bounds(monday):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(monday, time.min), tz)
    return start, start + timedelta(days=7)


def week_label(monday) -> str:
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}"


def readable_links(viewer, org):
    """(room ids, task check) for what ``viewer`` may name: other people's private rooms and
    tasks the viewer can't open show as "private" in time lists and reports."""
    from organizations.permissions import visible_team_ids
    from rooms.services import accessible_rooms

    rooms = set(accessible_rooms(viewer, org).values_list("pk", flat=True))
    teams = visible_team_ids(viewer, org)

    def task_ok(task):
        return task is not None and (teams is None or task.team_id is None or task.team_id in teams)

    return rooms, task_ok


def breakdown(entries, viewer=None, org=None):
    """Seconds by category, project, task, room and day for already-loaded entries."""
    out = {"by_category": {}, "by_project": {}, "by_task": {}, "by_room": {}, "by_day": {}}
    rooms, task_ok = readable_links(viewer, org) if viewer is not None else (None, None)
    for entry in entries:
        seconds = entry.seconds
        cat = out["by_category"].setdefault(entry.category, {"key": entry.category, "seconds": 0, "entries": 0})
        cat["seconds"] += seconds
        cat["entries"] += 1
        for field, bucket, label in (
            ("project", "by_project", lambda e: e.project.name),
            ("task", "by_task", lambda e: e.task.title),
            ("room", "by_room", lambda e: e.room.name),
        ):
            key = getattr(entry, f"{field}_id")
            if key and viewer is not None and entry.user_id != viewer.id and (
                (field == "room" and key not in rooms) or (field == "task" and not task_ok(entry.task))
            ):
                row = out[bucket].setdefault("private", {"id": None, "name": "", "private": True, "seconds": 0, "entries": 0})
                row["seconds"] += seconds
                row["entries"] += 1
                continue
            row = out[bucket].setdefault(
                str(key) if key else None,
                {"id": str(key) if key else None, "name": label(entry) if key else "", "seconds": 0, "entries": 0},
            )
            row["seconds"] += seconds
            row["entries"] += 1
        day = timezone.localtime(entry.started_at).date().isoformat()
        row = out["by_day"].setdefault(day, {"date": day, "seconds": 0})
        row["seconds"] += seconds
    result = {}
    for key, rows in out.items():
        values = list(rows.values())
        if key == "by_day":
            values.sort(key=lambda r: r["date"])
        else:
            values.sort(key=lambda r: (-r["seconds"], str(r.get("name") or r.get("key") or "")))
        result[key] = values
    for name in ("onboarding", "masterclass", "projects"):
        if not any(r["key"] == name for r in result["by_category"]):
            result["by_category"].append({"key": name, "seconds": 0, "entries": 0})
    return result


def _with_links(qs):
    return qs.select_related("task", "project", "room")


def report_me(org, user, period=None, week=None):
    qs = TimeEntry.objects.filter(org=org, user=user)
    data = {"period": period or "all"}
    if week is not None:
        start, end = week_bounds(week)
        qs = qs.filter(started_at__gte=start, started_at__lt=end)
        data.update(period="week", week=week_label(week), week_start=week.isoformat(), week_end=(week + timedelta(days=6)).isoformat())
    elif period == "week":
        qs = qs.filter(started_at__gte=timezone.now() - timedelta(days=7))
    entries = list(_with_links(qs))
    data.update(seconds=sum(e.seconds for e in entries), entries=len(entries), **breakdown(entries))
    return data


def report_team(org, team, week=None, viewer=None):
    from organizations.models import TeamMembership
    from tasks.services import display_name

    members = list(TeamMembership.objects.filter(team=team).select_related("user"))
    user_ids = [m.user_id for m in members]
    qs = TimeEntry.objects.filter(org=org, user_id__in=user_ids)
    data = {"team": str(team.id), "team_name": team.name}
    if week is not None:
        start, end = week_bounds(week)
        qs = qs.filter(started_at__gte=start, started_at__lt=end)
        data.update(week=week_label(week), week_start=week.isoformat(), week_end=(week + timedelta(days=6)).isoformat())
    entries = list(_with_links(qs))
    per_user = {}
    for entry in entries:
        row = per_user.setdefault(entry.user_id, {"seconds": 0, "entries": 0, "submitted": 0, "approved": 0})
        row["seconds"] += entry.seconds
        row["entries"] += 1
        if entry.approval_status == TimeEntry.APPROVAL_SUBMITTED:
            row["submitted"] += 1
        elif entry.approval_status == TimeEntry.APPROVAL_APPROVED:
            row["approved"] += 1
    by_member = []
    for m in members:
        row = per_user.get(m.user_id, {"seconds": 0, "entries": 0, "submitted": 0, "approved": 0})
        target = m.weekly_target_hours
        by_member.append(
            {
                "user_id": str(m.user_id),
                "name": display_name(m.user),
                "team_role": m.team_role,
                **row,
                "weekly_target_hours": str(target) if target is not None else None,
                "capacity_seconds": int(float(target) * 3600) - row["seconds"] if target is not None and week is not None else None,
            }
        )
    by_member.sort(key=lambda r: (-r["seconds"], r["name"].lower()))
    data.update(seconds=sum(e.seconds for e in entries), entries=len(entries), by_member=by_member, **breakdown(entries, viewer, org))
    return data


def dashboard_me(org, user):
    week_ago = timezone.now() - timedelta(days=7)
    entries = list(TimeEntry.objects.filter(org=org, user=user, started_at__gte=week_ago))
    return {
        "seconds_7d": sum(e.seconds for e in entries),
        "by_category": breakdown(entries)["by_category"],
        "impact_score": None,
    }
