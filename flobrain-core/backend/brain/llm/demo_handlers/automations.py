"""Demo model answers for automations (``DEMO_AI`` only).

- The workflow builder (system prompt has ``[flo:automation-builder]``): a believable workflow
  JSON from simple word matching, e.g. "every Monday at 9 summarise last week's blocked tasks in
  Launch room" or "when a task is blocked notify the lead". Room ids come from the room list the
  builder put in the system prompt. FloBrain validates it like any other draft.
- An ``ai_prompt`` step (``[flo:automation-step]``): a short labelled summary of the data lines.
Everything else passes on.
"""

import json
import re

from brain.llm.demo_ai import _result

BUILDER_MARK = "[flo:automation-builder]"
STEP_MARK = "[flo:automation-step]"
LABEL = "(Demo summary from FloBrain's demo model.)"
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
ROOM_LINE = re.compile(r"^room: ([0-9a-f-]{36}) (.+)$", re.MULTILINE)
STOP = {"room", "team", "the", "and", "app", "with", "chat"}


def _request(user):
    match = re.search(r"<request>\s*(.*?)\s*</request>", user or "", re.DOTALL)
    return (match.group(1) if match else user or "").strip()


def _time(text):
    match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text) or re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
    if not match:
        return "09:00"
    hour, minute, half = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if half == "pm" and hour < 12:
        hour += 12
    if half == "am" and hour == 12:
        hour = 0
    return f"{min(hour, 23):02d}:{min(minute, 59):02d}"


def _room(text, system):
    rooms = ROOM_LINE.findall(system or "")
    for rid, name in rooms:
        if name.lower() in text:
            return rid, name
    for rid, name in rooms:
        words = [w for w in re.findall(r"[a-z]{4,}", name.lower()) if w not in STOP]
        if any(re.search(rf"\b{re.escape(w)}\b", text) for w in words):
            return rid, name
    return None, None


def _trigger(text):
    if re.search(r"\b(blocked|stuck)\b", text) and re.search(r"\bwhen(ever)?\b", text):
        return {"type": "task_blocked"}, "When a task is blocked"
    if re.search(r"\bwhen(ever)?\b.*\btask\b.*\b(created|added|new)\b|\bnew task\b", text):
        return {"type": "task_created"}, "When a task is created"
    if re.search(r"\bwhen(ever)?\b.*\bmeeting\b.*\b(ends|ended|over|finishes)\b", text):
        return {"type": "meeting_ended"}, "After each meeting"
    if re.search(r"\bwhen(ever)?\b.*\bcustomer\b", text):
        return {"type": "customer_conversation"}, "New customer conversation"
    if "webhook" in text:
        return {"type": "webhook"}, "From a webhook"
    for i, day in enumerate(DAYS):
        if re.search(rf"\b(every|each|on)\s+{day}s?\b", text):
            return {"type": "schedule", "every": "week", "weekday": i, "at": _time(text)}, f"Every {day.title()}"
    match = re.search(r"\bevery\s+(\d{1,2})\s+hours?\b", text)
    if match:
        return {"type": "schedule", "every": "hours", "hours": max(1, min(24, int(match.group(1))))}, f"Every {match.group(1)} hours"
    if re.search(r"\b(monthly|every month|each month)\b", text):
        return {"type": "schedule", "every": "month", "day": 1, "at": _time(text)}, "Monthly"
    if re.search(r"\b(daily|every day|each day|every morning|each morning)\b", text):
        return {"type": "schedule", "every": "day", "at": _time(text)}, "Daily"
    return {"type": "manual"}, "On demand"


def _context(text):
    if "blocked" in text:
        return "blocked_tasks", "blocked tasks"
    if "overdue" in text or "late" in text:
        return "overdue_tasks", "overdue tasks"
    if "today" in text or "due" in text:
        return "tasks_due_today", "tasks due today"
    return "recent_tasks", "recent work"


def build(request, system):
    text = request.lower()
    trigger, when = _trigger(text)
    room_id, room_name = _room(text, system)
    steps = []
    name = when
    if re.search(r"\b(summar|digest|report|recap|overview)", text):
        context, what = _context(text)
        step = {"type": "ai_prompt", "label": f"Summarise {what}", "context": context,
                "prompt": f"Summarise the {what}: what each one is, who owns it, and what would move it forward. Short bullet points."}
        if room_id:
            step["room"] = room_id
        steps.append(step)
        name = f"{when}: {what} summary"
        if room_id:
            steps.append({"type": "post_to_room", "room": room_id, "text": f"{what.capitalize()}\n\n{{{{steps.1.output}}}}"})
    if re.search(r"\b(notify|tell|alert|ping|let .* know)\b", text):
        roles = ["team_leads"] if re.search(r"\blead", text) else ["admins"] if "admin" in text else ["task_assignees"] if "assignee" in text or "owner" in text else ["owner"]
        body = "{{steps.1.output}}" if steps else ("“{{trigger.title}}” is blocked: {{trigger.reason}}" if trigger["type"] == "task_blocked" else "{{trigger.title}}")
        steps.append({"type": "notify", "roles": roles, "text": body})
        name = name if steps[:-1] else f"{when}: notify {'the lead' if roles == ['team_leads'] else roles[0].replace('_', ' ')}"
    if re.search(r"\b(email|mail)\b", text):
        to = EMAIL.findall(request) or ["team@example.com"]
        steps.append({"type": "send_email", "to": to[:5], "subject": name[:80], "body": "{{steps.1.output}}" if steps else "Update from FloBrain"})
    if re.search(r"\b(create|make|open)\b.*\btask\b", text) and not any(s["type"] == "create_task" for s in steps):
        step = {"type": "create_task", "title": "{{trigger.title}}" if trigger["type"] not in ("schedule", "manual") else "Follow up", "due_in_days": 3}
        if room_id:
            step["room"] = room_id
        steps.append(step)
    if re.search(r"\b(post|share)\b", text) and room_id and not any(s["type"] == "post_to_room" for s in steps):
        steps.append({"type": "post_to_room", "room": room_id, "text": "{{steps.1.output}}" if steps else "{{trigger.title}}"})
    if not steps:
        steps.append({"type": "ai_prompt", "context": "recent_tasks", "prompt": request[:500] or "Summarise recent work."})
        name = f"{when}: {request[:40]}" if request else when
    return {
        "name": name[:120],
        "description": f"Drafted from: “{request[:200]}”" + (f" Posts in {room_name}." if room_id and any(s["type"] == "post_to_room" for s in steps) else ""),
        "trigger": trigger,
        "steps": steps[:12],
    }


def _summary(user):
    lines = [line[2:].split(" (", 1)[0] for line in (user or "").splitlines() if line.startswith("- ")]
    if not lines:
        return f"Nothing to report: no matching items. {LABEL}"
    shown = "\n".join(f"- {line}" for line in lines[:5])
    more = f"\n…and {len(lines) - 5} more." if len(lines) > 5 else ""
    return f"{len(lines)} item(s) need attention:\n{shown}{more}\n\n{LABEL}"


def handle(system, user, messages, tools):
    system = system or ""
    if BUILDER_MARK in system:
        return _result(json.dumps(build(_request(user), system)))
    if STEP_MARK in system:
        return _result(_summary(user))
    return None
