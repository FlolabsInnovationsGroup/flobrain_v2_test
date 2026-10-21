"""Built-in workflow templates. Installing one validates it like any workflow and saves a copy
(disabled unless ``enabled`` is sent). ``needs`` lists what the installer must provide:
``room`` (a room id) and ``emails`` (a list of addresses)."""

import copy

TEMPLATES = [
    {
        "key": "weekly_blocked_digest",
        "name": "Weekly blocked-tasks digest",
        "description": "Every Monday at 09:00, summarise the blocked tasks of a room and post the summary there.",
        "category": "Reports",
        "needs": ["room"],
        "proactive": False,
        "trigger": {"type": "schedule", "every": "week", "weekday": 0, "at": "09:00"},
        "steps": [
            {"type": "ai_prompt", "label": "Summarise blocked tasks", "context": "blocked_tasks", "room": "{room}",
             "prompt": "Summarise the blocked tasks: what is blocked, for how long, and who can unblock each one. Short bullet points."},
            {"type": "post_to_room", "room": "{room}", "text": "Blocked tasks this week\n\n{{steps.1.output}}"},
        ],
    },
    {
        "key": "daily_brief",
        "name": "Daily brief for everyone",
        "description": "Each morning at 08:00, every member gets a notification with their tasks due today, meetings and approvals waiting.",
        "category": "Proactive",
        "needs": [],
        "proactive": True,
        "trigger": {"type": "schedule", "every": "day", "at": "08:00"},
        "steps": [{"type": "daily_brief", "label": "Send each person their day"}],
    },
    {
        "key": "overdue_nudges",
        "name": "Nudge owners of overdue tasks",
        "description": "Every day at 10:00, remind people about their tasks that are at least one day overdue.",
        "category": "Proactive",
        "needs": [],
        "proactive": True,
        "trigger": {"type": "schedule", "every": "day", "at": "10:00"},
        "steps": [{"type": "nudge_overdue", "label": "Remind owners", "min_days_overdue": 1}],
    },
    {
        "key": "blocked_task_alert",
        "name": "Tell the lead when a task is blocked",
        "description": "When a task is marked blocked, notify the lead of its team.",
        "category": "Tasks",
        "needs": [],
        "proactive": False,
        "trigger": {"type": "task_blocked"},
        "steps": [{"type": "notify", "roles": ["team_leads"], "text": "“{{trigger.title}}” is blocked: {{trigger.reason}}"}],
    },
    {
        "key": "customer_conversation_to_room",
        "name": "New customer conversation to a room",
        "description": "When a customer starts a conversation on the website chat or WhatsApp, post it in a room.",
        "category": "Customers",
        "needs": ["room"],
        "proactive": False,
        "trigger": {"type": "customer_conversation"},
        "steps": [{"type": "post_to_room", "room": "{room}", "text": "New customer conversation: {{trigger.title}}"}],
    },
    {
        "key": "meeting_followup",
        "name": "Meeting follow-up reminder",
        "description": "When a meeting ends, remind the room to write down decisions and owners.",
        "category": "Meetings",
        "needs": [],
        "proactive": False,
        "trigger": {"type": "meeting_ended"},
        "steps": [
            {"type": "post_to_room", "room": "trigger",
             "text": "“{{trigger.title}}” just ended. Please add decisions and who owns each next step within 24 hours."},
        ],
    },
    {
        "key": "webhook_to_task",
        "name": "Incoming webhook to a task",
        "description": "When another system calls this workflow's webhook, create a task in a room.",
        "category": "Integrations",
        "needs": ["room"],
        "proactive": False,
        "trigger": {"type": "webhook"},
        "steps": [
            {"type": "create_task", "room": "{room}", "title": "{{trigger.title}}", "description": "{{trigger.description}}", "due_in_days": 3},
        ],
    },
    {
        "key": "monthly_report_email",
        "name": "Monthly report by email",
        "description": "On the 1st of each month, write a short report of last month's work and email it after you approve.",
        "category": "Reports",
        "needs": ["emails"],
        "proactive": False,
        "trigger": {"type": "schedule", "every": "month", "day": 1, "at": "09:00"},
        "steps": [
            {"type": "ai_prompt", "label": "Write the report", "context": "recent_tasks",
             "prompt": "Write a short monthly report: what was finished, what is in progress, and the main risks."},
            {"type": "send_email", "to": "{emails}", "subject": "Monthly report", "body": "{{steps.1.output}}"},
        ],
    },
    {
        "key": "budget_alert",
        "name": "AI budget alert",
        "description": "Every day at 09:00, tell the admins when AI spend passes 80% of the monthly budget.",
        "category": "Admin",
        "needs": [],
        "proactive": False,
        "trigger": {"type": "schedule", "every": "day", "at": "09:00"},
        "steps": [
            {"type": "check_budget", "threshold_pct": 80},
            {"type": "notify", "roles": ["admins"], "text": "{{steps.1.output}}"},
        ],
    },
]

BY_KEY = {t["key"]: t for t in TEMPLATES}


class TemplateError(ValueError):
    pass


def public(template) -> dict:
    return {k: copy.deepcopy(v) for k, v in template.items()}


def build(key, room=None, emails=None) -> dict:
    """The template's workflow data with ``{room}`` and ``{emails}`` filled in."""
    template = BY_KEY.get(key)
    if template is None:
        raise TemplateError("unknown template")
    if "room" in template["needs"] and not room:
        raise TemplateError("pick a room for this template")
    if "emails" in template["needs"] and not (isinstance(emails, list) and emails):
        raise TemplateError("add at least one email address")

    def fill(value):
        if value == "{room}":
            return str(room)
        if value == "{emails}":
            return list(emails)
        return value

    steps = [{k: fill(v) for k, v in step.items()} for step in copy.deepcopy(template["steps"])]
    return {
        "name": template["name"],
        "description": template["description"],
        "trigger": copy.deepcopy(template["trigger"]),
        "steps": steps,
        "template_key": key,
    }
