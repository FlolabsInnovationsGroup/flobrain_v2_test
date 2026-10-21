"""Built-in demo model (``DEMO_AI``, only with ``DEMO_MODE``). No network, no key.

It gives short, clearly labelled replies so every AI screen works in a local demo:
chat answers, translations, Content Studio JSON, and a task proposal when the
user asks for a task and the tool is offered (still approved by a person).
"""

import json
import re

from django.conf import settings

from brain.llm.providers import ProviderResult

MODEL = "flobrain-demo"
TASK_WORDS = re.compile(r"\b(task|todo|to-do|remind)\b|مهمة|مهمه", re.IGNORECASE)


def enabled() -> bool:
    return bool(getattr(settings, "DEMO_MODE", False) and getattr(settings, "DEMO_AI", False))


def _text(messages, role):
    for message in reversed(messages):
        if message.get("role") == role and isinstance(message.get("content"), str):
            return message["content"]
    return ""


def _question(messages):
    """The person's own words: the last user message that is not a block of retrieved sources."""
    for message in reversed(messages):
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, str):
            continue
        stripped = content.strip()
        for marker in ("\n\nQuestion: ", "\n\nMessage: "):
            if marker in stripped:
                return stripped.rsplit(marker, 1)[1].strip()
        if stripped.startswith("Sources:") or stripped.startswith("<source") or stripped.startswith("<transcript"):
            continue
        return re.sub(r"<[^>]{1,200}>", "", stripped)
    return ""


def _result(text=None, calls=None):
    out = len((text or "").split()) or 1
    return ProviderResult(text=text or "", model=MODEL, input_tokens=0, output_tokens=out, total_tokens=out, provider="demo", tool_calls=calls or [])


def reply(messages, tools=None) -> ProviderResult:
    system, user = _text(messages, "system"), _text(messages, "user")
    from brain.llm.demo_handlers import dispatch

    extra = dispatch(system, user, messages, tools)
    if extra is not None:
        return extra
    if '"copy"' in system:
        line = next((l for l in user.splitlines() if l.startswith("Platforms:")), "Platforms: youtube")
        platforms = [p.strip() for p in line.split(":", 1)[1].split(",") if p.strip()]
        copy = {
            p: {"title": "Nile Labs: launch day", "description": "Our mobile app is live. (Demo copy)", "hashtags": ["NileLabs", "launch"]}
            for p in platforms
        }
        return _result(json.dumps({"copy": copy}))
    if '"questions"' in system:
        sample = [
            {"question": "When is the code freeze?", "options": ["Monday", "Friday", "Next month"], "answer": 1},
            {"question": "How long does store review take?", "options": ["1 day", "5 days", "2 weeks"], "answer": 1},
            {"question": "What is a launch risk?", "options": ["Android login timeout", "Too many testers", "Dark mode"], "answer": 0},
        ]
        return _result(json.dumps({"questions": sample}))
    if '"action_items"' in system:
        return _result(json.dumps({
            "summary": "Demo summary: the team reviewed launch readiness, agreed on the release date, and listed what is left. (Sample text from the demo model.)",
            "decisions": ["Release at the end of next month", "Sara owns the store screenshots"],
            "action_items": [{"text": "Fix the Android login timeout", "owner": "Youssef"}, {"text": "Draft the launch blog post", "owner": "Omar"}],
        }))
    if '"clips"' in system:
        return _result(json.dumps({"clips": []}))
    if "translat" in system.lower():
        return _result(f"(demo translation) {user.strip()[:2000]}")
    question = _question(messages)
    if tools and TASK_WORDS.search(question):
        name = next((t["function"]["name"] for t in tools if "tasks" in t.get("function", {}).get("name", "") and "create" in t["function"]["name"]), None)
        if name:
            title = re.sub(r"^.*?(task|مهمة|مهمه)\s*(to|:)?\s*", "", question, flags=re.IGNORECASE)[:120].strip() or "Follow up"
            return _result("I prepared a task for you to approve.", [{"name": name, "arguments": json.dumps({"title": title})}])
    asked = " ".join(question.split())[:200]
    return _result(
        "This is FloBrain's demo model, so the answer is a sample. "
        "With a real model configured, the answer would use your org's rooms and documents that you can access.\n\n"
        f"You asked: “{asked}”"
    )
