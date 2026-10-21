"""Strict shapes for triggers and steps, and the checks that tie them to the org.

``clean_workflow(org, editor, data)`` returns cleaned ``(trigger, steps)`` or raises
``WorkflowError`` with a list of problems. Unknown fields, unknown step types and more than
``MAX_STEPS`` steps are refused. Rooms, teams and people must be in the org and usable by the
editor (who becomes the workflow's ``run_as``).
"""

import re
import urllib.parse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from actions.schema import SchemaError, validate

MAX_STEPS = 12
UUID = {"type": "string", "format": "uuid"}
ROOM_REF = {"type": "string", "minLength": 1, "maxLength": 40}  # a room id, or "trigger"
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

TRIGGERS = {
    "manual": {"type": "object", "properties": {"type": {"type": "string"}}, "additionalProperties": False},
    "schedule": {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "every": {"type": "string", "enum": ["day", "week", "month", "hours"]},
            "at": {"type": "string", "minLength": 5, "maxLength": 5},
            "weekday": {"type": "integer", "minimum": 0, "maximum": 6},  # 0 = Monday
            "day": {"type": "integer", "minimum": 1, "maximum": 28},
            "hours": {"type": "integer", "minimum": 1, "maximum": 24},
            "timezone": {"type": "string", "maxLength": 64},
        },
        "required": ["every"],
        "additionalProperties": False,
    },
    "room_message": {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "room": UUID,
            "keyword": {"type": "string", "minLength": 2, "maxLength": 60},
        },
        "required": ["room", "keyword"],
        "additionalProperties": False,
    },
    "task_created": {
        "type": "object",
        "properties": {"type": {"type": "string"}, "team": UUID},
        "additionalProperties": False,
    },
    "task_blocked": {
        "type": "object",
        "properties": {"type": {"type": "string"}, "team": UUID},
        "additionalProperties": False,
    },
    "meeting_ended": {
        "type": "object",
        "properties": {"type": {"type": "string"}, "room": UUID},
        "additionalProperties": False,
    },
    "customer_conversation": {"type": "object", "properties": {"type": {"type": "string"}}, "additionalProperties": False},
    "webhook": {"type": "object", "properties": {"type": {"type": "string"}}, "additionalProperties": False},
}

# Triggers whose payload carries a room ("trigger" may be used as a room) or a task.
ROOM_TRIGGERS = {"room_message", "meeting_ended"}
TASK_TRIGGERS = {"task_created", "task_blocked"}

CONTEXTS = ["none", "blocked_tasks", "overdue_tasks", "tasks_due_today", "recent_tasks", "trigger"]
ROLES = ["owner", "admins", "team_leads", "task_assignees", "room_members"]


def _step(props, required=()):
    return {
        "type": "object",
        "properties": {"type": {"type": "string"}, "label": {"type": "string", "maxLength": 80}, **props},
        "required": list(required),
        "additionalProperties": False,
    }


STEPS = {
    "ai_prompt": _step(
        {
            "prompt": {"type": "string", "minLength": 1, "maxLength": 4000},
            "context": {"type": "string", "enum": CONTEXTS},
            "room": UUID,
        },
        ["prompt"],
    ),
    "post_to_room": _step({"room": ROOM_REF, "text": {"type": "string", "minLength": 1, "maxLength": 8000}}, ["room", "text"]),
    "create_task": _step(
        {
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "description": {"type": "string", "maxLength": 4000},
            "room": ROOM_REF,
            "due_in_days": {"type": "integer", "minimum": 0, "maximum": 365},
        },
        ["title"],
    ),
    "notify": _step(
        {
            "text": {"type": "string", "minLength": 1, "maxLength": 1000},
            "people": {"type": "array", "items": UUID, "maxItems": 50},
            "roles": {"type": "array", "items": {"type": "string", "enum": ROLES}, "maxItems": 5},
        },
        ["text"],
    ),
    "send_email": _step(
        {
            "to": {"type": "array", "items": {"type": "string", "format": "email", "maxLength": 254}, "maxItems": 20},
            "subject": {"type": "string", "minLength": 1, "maxLength": 200},
            "body": {"type": "string", "minLength": 1, "maxLength": 20000},
        },
        ["to", "subject", "body"],
    ),
    "call_webhook": _step(
        {
            "url": {"type": "string", "minLength": 9, "maxLength": 500},
            "method": {"type": "string", "enum": ["POST", "PUT"]},
            "body": {"type": "string", "maxLength": 20000},
        },
        ["url"],
    ),
    "wait_for_approval": _step({"message": {"type": "string", "minLength": 1, "maxLength": 300}}, ["message"]),
    "daily_brief": _step({}),
    "nudge_overdue": _step({"min_days_overdue": {"type": "integer", "minimum": 0, "maximum": 30}}),
    "check_budget": _step({"threshold_pct": {"type": "integer", "minimum": 1, "maximum": 100}}),
}

# Steps that leave FloBrain: always an approval (call_webhook skips it only for trusted hosts).
EXTERNAL_STEPS = {"send_email", "call_webhook"}
TEMPLATED = {
    "ai_prompt": ("prompt",),
    "post_to_room": ("text",),
    "create_task": ("title", "description"),
    "notify": ("text",),
    "send_email": ("subject", "body"),
    "call_webhook": ("body",),
    "wait_for_approval": ("message",),
}


class WorkflowError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def tz_name(trigger, org) -> str:
    name = (trigger or {}).get("timezone") or ((org.settings or {}).get("timezone") if org is not None else "") or "UTC"
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"
    return name


def clean_trigger(raw) -> dict:
    if not isinstance(raw, dict):
        raise WorkflowError(["trigger must be an object"])
    kind = raw.get("type")
    schema = TRIGGERS.get(kind)
    if schema is None:
        raise WorkflowError([f"trigger.type must be one of {', '.join(TRIGGERS)}"])
    try:
        trigger = validate(schema, raw, "trigger")
    except SchemaError as exc:
        raise WorkflowError([str(exc)]) from exc
    trigger["type"] = kind
    if kind == "schedule":
        every = trigger["every"]
        if every in ("day", "week", "month"):
            if not HHMM.match(trigger.get("at") or ""):
                raise WorkflowError(["trigger.at must be a time like 09:00"])
        else:
            trigger.pop("at", None)
            trigger.setdefault("hours", 1)
        if every == "week" and "weekday" not in trigger:
            raise WorkflowError(["trigger.weekday is required for a weekly schedule"])
        if every == "month" and "day" not in trigger:
            raise WorkflowError(["trigger.day is required for a monthly schedule"])
        for unused, keep in (("weekday", "week"), ("day", "month")):
            if every != keep:
                trigger.pop(unused, None)
        if every != "hours":
            trigger.pop("hours", None)
        if "timezone" in trigger:
            try:
                ZoneInfo(trigger["timezone"])
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise WorkflowError(["trigger.timezone is not a known time zone"]) from exc
    if kind == "room_message":
        trigger["keyword"] = trigger["keyword"].strip()
    return trigger


def clean_steps(raw, trigger_type) -> list:
    if not isinstance(raw, list) or not raw:
        raise WorkflowError(["steps must be a list with at least one step"])
    if len(raw) > MAX_STEPS:
        raise WorkflowError([f"a workflow has at most {MAX_STEPS} steps"])
    out, problems = [], []
    for i, step in enumerate(raw, start=1):
        path = f"steps[{i}]"
        if not isinstance(step, dict) or step.get("type") not in STEPS:
            problems.append(f"{path}.type must be one of {', '.join(STEPS)}")
            continue
        try:
            cleaned = validate(STEPS[step["type"]], step, path)
        except SchemaError as exc:
            problems.append(str(exc))
            continue
        cleaned["type"] = step["type"]
        problems.extend(_step_rules(cleaned, path, trigger_type, i))
        out.append(cleaned)
    if problems:
        raise WorkflowError(problems)
    return out


STEP_REF = re.compile(r"\{\{\s*steps\.(\d+)\.output\s*\}\}")


def _step_rules(step, path, trigger_type, index):
    problems = []
    kind = step["type"]
    for field in ("room",):
        value = step.get(field)
        if value == "trigger":
            if trigger_type not in ROOM_TRIGGERS:
                problems.append(f"{path}.room can be \"trigger\" only when the trigger is a room message or a meeting")
        elif value is not None and kind != "ai_prompt":
            try:
                validate(UUID, value, f"{path}.room")
            except SchemaError as exc:
                problems.append(str(exc))
    if kind == "send_email" and not step.get("to"):
        problems.append(f"{path}.to needs at least one address")
    if kind == "notify" and not (step.get("people") or step.get("roles")):
        problems.append(f"{path} needs people or roles to notify")
    if kind == "call_webhook":
        parsed = urllib.parse.urlparse(step["url"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            problems.append(f"{path}.url must be an https address without credentials")
    for field in TEMPLATED.get(kind, ()):
        for ref in STEP_REF.findall(step.get(field) or ""):
            if not 1 <= int(ref) < index:
                problems.append(f"{path}.{field} can only use the output of an earlier step")
    return problems


def check_references(org, editor, trigger, steps, settings_row=None):
    """Rooms, teams and people must exist in ``org`` and be usable by ``editor``."""
    from organizations.models import OrgMembership, Team
    from organizations.permissions import can
    from rooms.models import Room
    from rooms.services import user_can_access_room

    problems = []

    def room_ok(room_id, path):
        room = Room.objects.filter(pk=room_id, org=org, is_active=True).first()
        if room is None or not user_can_access_room(editor, room):
            problems.append(f"{path}: room not found")

    if trigger.get("room"):
        room_ok(trigger["room"], "trigger.room")
    if trigger.get("team"):
        team = Team.objects.filter(pk=trigger["team"], org=org).first()
        if team is None or not can(editor, "team.view", team):
            problems.append("trigger.team: team not found")
    hosts = set((settings_row.webhook_hosts if settings_row else []) or [])
    for i, step in enumerate(steps, start=1):
        path = f"steps[{i}]"
        room = step.get("room")
        if room and room != "trigger":
            room_ok(room, f"{path}.room")
        if step.get("people"):
            active = set(
                str(u)
                for u in OrgMembership.objects.filter(
                    org=org, user_id__in=step["people"], employment_status="active"
                ).values_list("user_id", flat=True)
            )
            if set(step["people"]) - active:
                problems.append(f"{path}.people: someone is not an active member")
        if step["type"] == "create_task" and not can(editor, "task.write", org):
            problems.append(f"{path}: you can't create tasks")
        if step["type"] == "call_webhook":
            host = (urllib.parse.urlparse(step["url"]).hostname or "").lower()
            if host not in hosts:
                problems.append(f"{path}.url: {host or 'this host'} is not on the allowed list in automation settings")
    if problems:
        raise WorkflowError(problems)


def clean_workflow(org, editor, data, settings_row=None):
    trigger = clean_trigger(data.get("trigger"))
    steps = clean_steps(data.get("steps"), trigger["type"])
    check_references(org, editor, trigger, steps, settings_row)
    return trigger, steps


def clean_hosts(raw) -> list:
    if not isinstance(raw, list) or len(raw) > 50:
        raise WorkflowError(["hosts must be a list of at most 50 host names"])
    out = []
    for value in raw:
        host = str(value or "").strip().lower().rstrip(".")
        if not re.match(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", host):
            raise WorkflowError([f"{str(value)[:80]} is not a host name"])
        if host not in out:
            out.append(host)
    return out
