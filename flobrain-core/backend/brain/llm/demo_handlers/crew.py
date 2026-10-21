"""Demo model answers for Flo and the specialist buddies (``DEMO_AI`` only, growth round W5).

- Flo's routing call (system prompt tagged ``[flo:router]``): the strict routing JSON, picked by
  topic from the buddies listed in the prompt (only ids that are listed, so the demo never routes
  to a buddy the person can't use).
- Specialist templates (``[crew:sales]``, ``[crew:onboarding]``, ``[crew:meeting]``,
  ``[crew:customer]``): short, believable answers built from the ``<workspace_facts>`` the turn
  carries. Drafts and tasks are offered as tool calls, so they wait in Approvals.
- The built-in Travel, Finance, Legal, Data and Space buddies get the marketing site's sample
  answers when no sources came with the turn (with sources, the rooms handler quotes them).
Everything else passes. Every answer says it is demo output.
"""

import json
import re

from brain.llm.demo_ai import _question, _result

ROUTER = "[flo:router]"
LABEL = "(Sample answer from FloBrain's demo model.)"
LINE = re.compile(r"^- id: ([0-9a-f-]{36}) \| slug: ([^|]+?) \| name: ([^|]+?) \|", re.MULTILINE)
FACTS = re.compile(r"<workspace_facts>\n(.*?)\n</workspace_facts>", re.DOTALL)

# (pattern, slugs to try in order). Order matters: the first two topics found win.
TOPICS = [
    (re.compile(r"\b(travel|trip|flights?|visa|hotel|dubai)\b|سفر|رحلة", re.I), ["travel"]),
    (re.compile(r"\b(budget|invoices?|costs?|expenses?|spend)\b|ميزانية", re.I), ["finance"]),
    (re.compile(r"\b(nda|contracts?|clauses?|legal)\b|عقد", re.I), ["legal"]),
    (re.compile(r"sign[- ]?ups?|\b(metrics?|charts?|dashboard|conversion)\b", re.I), ["data"]),
    (re.compile(r"\b(launch|blockers?|blocking|roadmap)\b|إطلاق", re.I), ["space"]),
    (re.compile(r"\b(sales|pipeline|deals?|leads?|prospects?)\b|مبيعات", re.I), ["sales"]),
    (re.compile(r"new hire|\b(onboarding|onboard|first day|30-day)\b|موظف جديد", re.I), ["onboarding-coach", "onboarding"]),
    (re.compile(r"\b(meeting|agenda|prepare me|prep)\b|اجتماع", re.I), ["meeting-prep"]),
]

BUILTIN = {
    "You help team members plan work travel": (
        "Two options fit the travel policy for Dubai. Emirates EK202 lands at 08:40, before your 10:00 meeting, "
        "and is $612 cheaper than yesterday. I can't book or pay; I can draft the request for approval."
    ),
    "You help with budgets and costs": (
        "38% of the Q4 design budget is left, about $14,200. Contractor invoices are the biggest line this month. "
        "I can't move money, but I can draft the request for Mona."
    ),
    "You give a first-pass reading of contracts and policies": (
        "Two clauses need a look: a 5-year term and a non-solicit that also covers contractors. "
        "I'm not a lawyer, so treat this as a first pass and ask counsel before signing."
    ),
    "You help plan and explain data analysis": (
        "Sign-ups are up 18% this week, almost all from the Arabic store listing. "
        "To check it: compare daily sign-ups by store language for the last 14 days."
    ),
    "You answer questions about the user's workspace": (
        "One blocker left: the Android login timeout, with a fix expected Thursday. "
        "Nobody owns the Android test device yet. Want me to suggest a task for Omar?"
    ),
}


def _candidates(system):
    return {slug.strip(): bid for bid, slug, _ in LINE.findall(system)}


def _route(system, question):
    listed = _candidates(system)
    picks, reasons = [], []
    for pattern, slugs in TOPICS:
        if len(picks) == 2:
            break
        match = pattern.search(question)
        if not match:
            continue
        slug = next((s for s in slugs if s in listed and listed[s] not in picks), None)
        if slug:
            picks.append(listed[slug])
            reasons.append(f"'{match.group(0).strip()}' is a {slug.replace('-', ' ')} question")
    if not picks:
        fallback = listed.get("space") or next(iter(listed.values()), None)
        if fallback is None:
            return _result("{}")
        picks, reasons = [fallback], ["no clear topic, so the workspace buddy takes it"]
    return _result(json.dumps({"buddy_ids": picks, "reason": "; ".join(reasons).capitalize() + "."}))


def _facts(system):
    found = FACTS.search(system or "")
    return found.group(1).splitlines() if found else []


def _section(lines, title):
    out, inside = [], False
    for line in lines:
        if not line.startswith("- "):
            inside = line.startswith(title)
            continue
        if inside:
            out.append(line[2:])
    return out


def _tool(tools, key):
    name = key.replace(".", "__")
    return name if any(t.get("function", {}).get("name") == name for t in tools or []) else None


def _sales(system, question, tools):
    leads = _section(_facts(system), "Pipeline")
    if re.search(r"draft|follow[- ]?up|email", question, re.I):
        target = leads[0].split(" (")[0] if leads else "the lead"
        body = (
            f"Hi {target},\n\nThanks for your time this week. As promised, here is a short summary of what we "
            "discussed and the next step on our side. Would Tuesday or Wednesday suit you for a 20-minute call?\n\n"
            "Best regards"
        )
        name = _tool(tools, "email.draft")
        text = f"Here is a follow-up for {target}. {LABEL}\n\n{body}"
        if name:
            call = {"name": name, "arguments": json.dumps({"subject": "Following up on our call", "body": body})}
            return _result(text + "\n\nI saved it as a draft for your approval. Nothing is sent.", [call])
        return _result(text)
    if leads:
        moving = [l for l in leads if "stage won" in l or "stage in_progress" in l or "stage meeting_1" in l]
        lines = "\n".join(f"- {l}" for l in leads[:5])
        stuck = next((l.split(" (")[0] for l in leads if "stage contacted" in l or "stage meeting_1" in l), None)
        nxt = f"\n\nNext step: book a second meeting with {stuck}." if stuck else ""
        return _result(f"Your pipeline ({len(moving)} moving):\n{lines}{nxt}\n\n{LABEL}")
    return _result(f"I can't see any leads for you yet. Add one under Leads, or connect HubSpot. {LABEL}")


def _onboarding(system, question, tools):
    paths = _section(_facts(system), "Your learning paths")
    if re.search(r"progress|how far|learning|masterclass", question, re.I):
        if not paths:
            return _result(f"You have no learning paths yet. Ask your lead to assign one. {LABEL}")
        return _result("Your learning so far:\n" + "\n".join(f"- {p}" for p in paths) + f"\n\nFinish the next step this week. {LABEL}")
    if re.search(r"policy|leave|holiday|expenses?", question, re.I):
        return _result(
            "From the handbook: 21 days of paid leave a year, booked in FloBrain at least two weeks ahead; "
            f"your lead approves it. If your contract says otherwise, the contract wins. {LABEL}"
        )
    plan = (
        "30-day plan for the new hire\n\n"
        "Days 1-10: set up laptop and accounts, read the Engineering handbook, meet Layla (lead) and Sara (design), "
        "ship one small fix.\n"
        "Days 11-20: pair on the Android login timeout, join the release review, finish the Launch basics quiz.\n"
        "Days 21-30: own one feature end to end, present it in the team room, agree goals for month two."
    )
    name = _tool(tools, "tasks.create")
    if name:
        calls = [{"name": name, "arguments": json.dumps({"title": "Read the Engineering handbook"})}]
        return _result(f"{plan}\n\nI prepared the first task for your approval. {LABEL}", calls)
    return _result(f"{plan}\n\n{LABEL}")


def _meeting(system, question, tools):
    facts = _facts(system)
    upcoming = _section(facts, "Upcoming meetings")
    actions = [l.replace("Action item: ", "") for l in facts if l.startswith("- Action item: ")]
    decisions = [l.replace("- Decision: ", "") for l in facts if l.startswith("- Decision: ")]
    tasks = _section(facts, "Your open tasks")
    if re.search(r"wrap|after|action items|attendees|minutes", question, re.I):
        name_task, name_mail = _tool(tools, "tasks.create"), _tool(tools, "email.draft")
        items = actions[:2] or ["Fix the Android login timeout", "Draft the launch blog post"]
        calls = [{"name": name_task, "arguments": json.dumps({"title": i.split(" (owner")[0][:120]})} for i in items] if name_task else []
        body = "Hi all,\n\nThanks for today. Decisions: " + ("; ".join(decisions) or "see the notes") + ".\nNext steps: " + "; ".join(items) + ".\n\nThanks"
        if name_mail:
            calls.append({"name": name_mail, "arguments": json.dumps({"subject": "Notes and next steps", "body": body})})
        text = "Decisions:\n" + "\n".join(f"- {d}" for d in decisions or ["None recorded"]) + "\n\nI prepared one task per action item and a follow-up email. They wait for your approval."
        return _result(f"{text} {LABEL}", calls[:3])
    meeting = upcoming[0] if upcoming else "your next meeting"
    brief = [f"Brief for {meeting}"]
    if decisions:
        brief.append("Last time you decided: " + "; ".join(decisions) + ".")
    if actions:
        brief.append("Still open from last time: " + "; ".join(actions[:3]) + ".")
    if tasks:
        brief.append("Your open tasks: " + "; ".join(tasks[:3]) + ".")
    brief.append("Questions to settle: who owns the Android test device, and is the release date still safe?")
    return _result("\n".join(brief) + f"\n\n{LABEL}")


def _customer(question):
    if re.search(r"person|human|agent|someone", question, re.I):
        return _result(f"Of course. A team member will reply here soon. {LABEL}")
    return _result(f"We're open Sunday to Thursday, 9:00 to 17:00 Cairo time. Anything else I can help with? {LABEL}")


def handle(system, user, messages, tools):
    system = system or ""
    if ROUTER in system:
        return _route(system, user or "")
    if "[crew:" not in system and "You are a FloBrain buddy" not in system:
        return None
    question = _question(messages) or user or ""
    if "[crew:sales]" in system:
        return _sales(system, question, tools)
    if "[crew:onboarding]" in system:
        return _onboarding(system, question, tools)
    if "[crew:meeting]" in system:
        return _meeting(system, question, tools)
    if "[crew:customer]" in system:
        return _customer(question)
    last = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), "") or ""
    if "<source" in last:
        return None  # sources came with the turn: the rooms handler quotes them
    for marker, answer in BUILTIN.items():
        if f"Buddy instructions:\n{marker}" in system:
            return _result(f"{answer}\n\n{LABEL}")
    return None
