"""Five-field cron (minute hour day-of-month month day-of-week), UTC.

Supports ``*``, numbers, lists (``1,15``), ranges (``1-5``) and steps
(``*/15``, ``0-30/10``). Day-of-week 0 or 7 is Sunday. When both day fields
are restricted, either may match (classic cron).
"""

from datetime import timedelta

FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
MIN_GAP_MINUTES = 15


class CronError(ValueError):
    pass


def _field(text, low, high):
    values = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError("bad step")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise CronError("bad range")
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
        else:
            raise CronError("bad value")
        if start < low or end > high or start > end:
            raise CronError("value out of range")
        values.update(range(start, end + 1, step))
    return values


def parse(expr):
    parts = (expr or "").split()
    if len(parts) != 5:
        raise CronError("cron needs five fields")
    sets = [_field(p, lo, hi) for p, (lo, hi) in zip(parts, FIELDS)]
    if 7 in sets[4]:
        sets[4].add(0)
    return sets, parts[2] != "*", parts[4] != "*"


def matches(spec, moment) -> bool:
    (minutes, hours, days, months, weekdays), dom_set, dow_set = spec
    if moment.minute not in minutes or moment.hour not in hours or moment.month not in months:
        return False
    dow = (moment.weekday() + 1) % 7  # Monday=1 … Sunday=0
    day_ok, week_ok = moment.day in days, dow in weekdays
    if dom_set and dow_set:
        return day_ok or week_ok
    return day_ok and week_ok


def _day_ok(spec, moment) -> bool:
    (_, _, days, months, weekdays), dom_set, dow_set = spec
    if moment.month not in months:
        return False
    dow = (moment.weekday() + 1) % 7
    day_ok, week_ok = moment.day in days, dow in weekdays
    if dom_set and dow_set:
        return day_ok or week_ok
    return day_ok and week_ok


def next_after(expr, moment, limit_days=366):
    """Next matching minute after ``moment``. Skips whole days and hours, so it is fast even for rare crons."""
    spec = parse(expr)
    minutes, hours = sorted(spec[0][0]), sorted(spec[0][1])
    t = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = t + timedelta(days=limit_days)
    while t <= end:
        if not _day_ok(spec, t):
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t.hour not in spec[0][1]:
            later = [h for h in hours if h > t.hour]
            if not later:
                t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            else:
                t = t.replace(hour=later[0], minute=0)
            continue
        later = [m for m in minutes if m >= t.minute]
        if later:
            return t.replace(minute=later[0])
        t = (t + timedelta(hours=1)).replace(minute=0)
    raise CronError("cron never fires")


def validate(expr, now):
    """Parse and refuse schedules that can fire more often than every 15 minutes.

    The check is on the times of day (with the wrap from one day to the next),
    so it holds across day boundaries whatever the day fields say.
    """
    (minutes, hours, _, _, _), _, _ = parse(expr)
    times = sorted(h * 60 + m for h in hours for m in minutes)
    gaps = [b - a for a, b in zip(times, times[1:])] + [times[0] + 1440 - times[-1]]
    if min(gaps) < MIN_GAP_MINUTES:
        raise CronError(f"runs at most every {MIN_GAP_MINUTES} minutes")
    return next_after(expr, now)
