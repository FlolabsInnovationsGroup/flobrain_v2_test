"""Demo model answers for buddy turns and scheduled agents (``DEMO_AI`` only).

- "Draft release notes ... and post them in Engineering": a labelled draft built from the finished
  tasks of that room's team, plus a ``rooms.post_message`` proposal for the same text. The post
  still waits in Approvals; nothing is posted by the model.
- Anything that asks for a task or tasks ("follow up on overdue tasks"): a ``tasks.create``
  proposal. The built-in matcher only knows the singular "task".
Only buddy turns with tools are handled; everything else passes on.
"""

import json
import re

from brain.llm.demo_ai import _question, _result

BUDDY_MARK = "You are a FloBrain buddy"
POST = re.compile(r"\b(post|share|publish)\b", re.IGNORECASE)
NOTES = re.compile(r"release[- ]notes?|changelog|weekly (update|report)|summary", re.IGNORECASE)
TASKS = re.compile(r"\b(tasks?|todos?|to-dos?|remind(?:er)?s?|follow[- ]ups?)\b|مهمة|مهمه|مهام", re.IGNORECASE)
LABEL = "(Draft from FloBrain's demo model. A real model would write it from your workspace.)"


def _names(tools):
    return {t.get("function", {}).get("name", "") for t in tools or []}


def _demo_room(text):
    """A team or project room of the demo org whose name appears in the instructions."""
    from organizations.models import Organization
    from rooms.models import Room

    org = Organization.objects.filter(slug="demo").first()
    if org is None or (org.settings or {}).get("demo") is not True:
        return None
    lowered = text.lower()
    for room in Room.objects.filter(org=org, kind__in=[Room.KIND_TEAM, Room.KIND_PROJECT]).select_related("team"):
        if room.name and room.name.lower() in lowered:
            return room
    return None


def _draft(room):
    from tasks.models import Task

    done = Task.objects.filter(org=room.org, status=Task.STATUS_DONE)
    if room.team_id:
        done = done.filter(team_id=room.team_id)
    titles = list(done.order_by("-updated_at").values_list("title", flat=True)[:8])
    lines = [f"- {t}" for t in titles] or ["- No finished tasks this week."]
    return "Release notes for this week\n\n" + "\n".join(lines) + f"\n\n{LABEL}"


def handle(system, user, messages, tools):
    if not tools or BUDDY_MARK not in (system or ""):
        return None
    names = _names(tools)
    question = _question(messages) or user or ""
    if "rooms__post_message" in names and POST.search(question) and NOTES.search(question):
        room = _demo_room(question)
        if room is not None:
            body = _draft(room)
            call = {"name": "rooms__post_message", "arguments": json.dumps({"room": str(room.id), "body": body})}
            return _result(f"{body}\n\nI prepared a post for {room.name}. It waits for your approval.", [call])
    create = next((n for n in names if n == "tasks__create"), None)
    if create and TASKS.search(question):
        title = re.sub(r"^.*?\b(tasks?|مهمة|مهمه|مهام)\b\s*(to|:|for)?\s*", "", question, flags=re.IGNORECASE)
        title = (title.split("\n")[0].strip(" .") or "Follow up")[:120]
        return _result("I prepared a task for you to approve.", [{"name": create, "arguments": json.dumps({"title": title})}])
    return None
