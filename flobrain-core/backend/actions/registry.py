"""The tools a buddy or room AI may propose (Decision 33, spec 8.6).

One namespace with permission keys, MCP tool names and token scopes. A tool
is only ever *proposed* by a model; FloBrain executes it after a person
approves. ``perm_key`` is checked with ``can()`` at propose and at approve,
and each executor re-checks its own target (room, task, team).

Provider function names cannot contain dots, so ``tasks.create`` is offered
as ``tasks__create``.
"""

READ, WRITE, EXTERNAL = "read", "write", "external"

UUID = {"type": "string", "format": "uuid"}

TOOLS = {
    "tasks.create": {
        "perm_key": "task.write",
        "risk": WRITE,
        "label": "Create a task",
        "description": "Create a task in this workspace. The user must approve before it is created.",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "description": {"type": "string", "maxLength": 4000},
                "team": UUID,
                "project": UUID,
                "due_on": {"type": "string", "format": "date"},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    "tasks.assign": {
        "perm_key": "task.write",
        "risk": WRITE,
        "label": "Assign a task",
        "description": "Assign an existing task to a member. Needs approval.",
        "schema": {
            "type": "object",
            "properties": {"task": UUID, "user": UUID},
            "required": ["task", "user"],
            "additionalProperties": False,
        },
    },
    "tasks.update_status": {
        "perm_key": "task.write",
        "risk": WRITE,
        "label": "Change a task's status",
        "description": "Move a task to to_do, in_progress or done. Needs approval.",
        "schema": {
            "type": "object",
            "properties": {"task": UUID, "status": {"type": "string", "enum": ["to_do", "in_progress", "done"]}},
            "required": ["task", "status"],
            "additionalProperties": False,
        },
    },
    "rooms.post_message": {
        "perm_key": "chat.use",
        "risk": WRITE,
        "label": "Post a room message",
        "description": "Post a message in a room as the user. Needs approval.",
        "schema": {
            "type": "object",
            "properties": {"room": UUID, "body": {"type": "string", "minLength": 1, "maxLength": 8000}},
            "required": ["room", "body"],
            "additionalProperties": False,
        },
    },
    "meetings.create": {
        "perm_key": "meeting.manage",
        "risk": WRITE,
        "label": "Schedule a meeting",
        "description": "Create a meeting in a room. Needs approval.",
        "schema": {
            "type": "object",
            "properties": {
                "room": UUID,
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "starts_at": {"type": "string", "format": "date-time"},
            },
            "required": ["room", "title"],
            "additionalProperties": False,
        },
    },
    "email.draft": {
        "perm_key": "ai.use",
        "risk": WRITE,
        "label": "Draft an email (not sent)",
        "description": "Save an email draft for the user. Nothing is sent.",
        "schema": {
            "type": "object",
            "properties": {
                "to": {"type": "array", "items": {"type": "string", "format": "email"}, "maxItems": 20},
                "subject": {"type": "string", "maxLength": 200},
                "body": {"type": "string", "minLength": 1, "maxLength": 20000},
            },
            "required": ["body"],
            "additionalProperties": False,
        },
    },
    "content.publish": {
        "perm_key": "content.use",
        "risk": "external",
        "label": "Submit a social post for approval",
        "description": "Submit a finished render as a social post. It waits for a separate approval; it never publishes.",
        "schema": {
            "type": "object",
            "properties": {
                "project": UUID,
                "render": UUID,
                "social_account": UUID,
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "description": {"type": "string", "maxLength": 5000},
                "hashtags": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 60}, "maxItems": 30},
                "scheduled_at": {"type": "string", "format": "date-time"},
            },
            "required": ["project", "render", "social_account", "title"],
            "additionalProperties": False,
        },
    },
    "reports.generate": {
        "perm_key": "report.generate",
        "risk": WRITE,
        "label": "Generate a team report",
        "description": "Draft a daily standup or weekly report for a team the user leads. Needs approval.",
        "schema": {
            "type": "object",
            "properties": {"team": UUID, "kind": {"type": "string", "enum": ["daily_standup", "weekly_report"]}},
            "required": ["team", "kind"],
            "additionalProperties": False,
        },
    },
}


def tool_keys() -> list[str]:
    return list(TOOLS)


def perm_for(tool_key: str) -> str | None:
    tool = TOOLS.get(tool_key)
    return tool["perm_key"] if tool else None


def function_name(tool_key: str) -> str:
    return tool_key.replace(".", "__")


def tool_key_for(function: str) -> str | None:
    key = (function or "").replace("__", ".")
    return key if key in TOOLS else None


def provider_tools(keys) -> list[dict]:
    """OpenAI-style ``tools`` for the given keys."""
    return [
        {
            "type": "function",
            "function": {
                "name": function_name(key),
                "description": TOOLS[key]["description"],
                "parameters": TOOLS[key]["schema"],
            },
        }
        for key in keys
        if key in TOOLS
    ]
