"""Simple schedules: daily or weekly at HH:MM, monthly on a day, or every N hours. No free cron.

Times are in the trigger's time zone (else the org's ``settings.timezone``, else UTC); the
result is an aware UTC datetime strictly after ``now``.
"""

from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from automations.schema import tz_name


def _at(trigger):
    hour, minute = (int(x) for x in (trigger.get("at") or "09:00").split(":"))
    return time(hour, minute)


def next_run(trigger, org, now, last=None):
    every = trigger.get("every")
    if every == "hours":
        step = timedelta(hours=int(trigger.get("hours") or 1))
        base = last or now
        nxt = base + step
        while nxt <= now:
            nxt += step
        return nxt
    tz = ZoneInfo(tz_name(trigger, org))
    local_now = now.astimezone(tz)
    at = _at(trigger)
    day = local_now.date()
    for offset in range(0, 400):
        candidate_day = day + timedelta(days=offset)
        if every == "week" and candidate_day.weekday() != int(trigger.get("weekday", 0)):
            continue
        if every == "month" and candidate_day.day != int(trigger.get("day", 1)):
            continue
        candidate = datetime.combine(candidate_day, at, tzinfo=tz)
        if candidate > local_now:
            return candidate.astimezone(dt_timezone.utc)
    return None


def describe(trigger) -> str:
    every = trigger.get("every")
    if every == "hours":
        return f"every {trigger.get('hours', 1)} hours"
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if every == "week":
        return f"every {days[int(trigger.get('weekday', 0))]} at {trigger.get('at')}"
    if every == "month":
        return f"on day {trigger.get('day')} of each month at {trigger.get('at')}"
    return f"every day at {trigger.get('at')}"
