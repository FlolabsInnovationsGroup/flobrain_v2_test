"""Flo, the specialist buddies and buddy quality in the demo (growth round W5).

- Flo and the four specialist templates (Sales, Onboarding Coach, Meeting, Customer) are installed.
- About 70 short buddy exchanges over the last 30 days, a third of them routed by Flo (with
  routing logs and "Answered by" replies), so the Quality page has answers, timing and sources.
- 60 thumbs up or down from the five demo people, with "not helpful" reasons.
- Sales and Meeting buddy proposals (email drafts and tasks): some approved, one rejected, one
  still waiting in Approvals.
- Usage rows on those threads, priced with the demo model's price, for tokens and cost (small, and
  tagged so the budgets seeded earlier keep their states).
All text is labelled demo output.
"""

import random
from datetime import timedelta

LABEL = "(Sample answer from FloBrain's demo model.)"

QUESTIONS = {
    "travel": [
        ("Book me to Dubai for the partner meeting, under the travel policy.", "Two options under policy. EK202 lands before your 10:00."),
        ("Do I need a visa for Riyadh next month?", "Egyptian passport holders need an e-visa; it takes about three working days."),
    ],
    "finance": [
        ("How much of the Q4 design budget is left?", "38% is left, about $14,200. Contractor invoices are the biggest line."),
        ("Which invoices are overdue?", "Two invoices are past due: Lotus Tea (12 days) and Cairo Bikes (4 days)."),
    ],
    "legal": [
        ("Is the new NDA safe to sign?", "Two clauses need a look: a 5-year term and a broad non-solicit [1]."),
        ("Summarize the contractor agreement.", "12-month term, 30 days notice, IP assigned on payment [1]."),
    ],
    "data": [
        ("What changed in sign-ups this week?", "Sign-ups are up 18%, almost all from the Arabic store listing [1]."),
        ("Which screen loses the most users?", "The phone number step: 31% of new users stop there [1]."),
    ],
    "space": [
        ("What's still blocking the launch?", "One blocker: the Android login timeout, fix expected Thursday [1]."),
        ("Summarize my last meeting.", "Release date agreed for the end of next month; Sara owns the screenshots [1]."),
    ],
    "sales": [
        ("What moved in my pipeline this week?", "Delta Clinics is won; Cairo Bikes is stuck after the first meeting."),
        ("Draft a follow-up for Cairo Bikes.", "Here is a short follow-up asking for a 20-minute call next week."),
    ],
    "onboarding-coach": [
        ("Write a 30-day plan for our new hire.", "Days 1-10 set up and read; 11-20 pair on the login bug; 21-30 own a feature."),
        ("What is our leave policy?", "21 days a year, booked two weeks ahead, approved by your lead [1]."),
    ],
    "meeting-prep": [
        ("Prepare me for my next meeting.", "Brief: release date, the open Android bug and who owns the test device."),
        ("Wrap up my last meeting.", "Two decisions, two action items and a follow-up email for your approval."),
    ],
}
# How often each buddy is asked (weights) and how often its answers help.
WEIGHTS = {"space": 14, "data": 10, "legal": 8, "sales": 9, "meeting-prep": 9, "finance": 7, "onboarding-coach": 6, "travel": 5}
HELPFUL = {"space": 0.86, "data": 0.8, "legal": 0.78, "sales": 0.72, "meeting-prep": 0.84, "finance": 0.66, "onboarding-coach": 0.9, "travel": 0.7}
CITES = {"space", "data", "legal", "onboarding-coach"}
REASONS = ["incomplete", "wrong", "no_sources", "off_topic", "too_long", "incomplete", "wrong"]


def seed(org, users, now):
    from actions.models import ActionProposal
    from brain.models import Chat, Message
    from buddies.models import Buddy, BuddyAnswer, BuddyFeedback, BuddyRoute, BuddyRouteHop
    from buddies.seeds import seed_crew
    from telemetry.models import UsageEvent

    from organizations.models import Team

    crew = seed_crew(org)
    design = Team.objects.filter(org=org, name="Design").first()
    flo = crew["flo"]
    buddies = {b.slug: b for b in Buddy.objects.filter(org=org, slug__in=list(QUESTIONS))}
    people = [users[k] for k in ("member", "lead", "designer", "admin", "owner")]
    rng = random.Random(95)  # same numbers after every reset
    threads, flo_threads = {}, {}

    def thread(person, buddy, title=None):
        key = (person.id, buddy.id, title)
        if key not in threads:
            threads[key] = Chat.objects.create(user=person, org=org, buddy=buddy, title=title or buddy.name)
        return threads[key]

    def at(when, chat, role, text):
        message = Message.objects.create(chat=chat, role=role, text=text)
        Message.objects.filter(pk=message.pk).update(created_at=when)
        message.created_at = when
        return message

    slugs = [s for s in WEIGHTS if s in buddies]
    weights = [WEIGHTS[s] for s in slugs]
    replies, usage, facts = [], [], []
    for i in range(72):
        slug = rng.choices(slugs, weights)[0]
        buddy = buddies[slug]
        person = people[i % len(people)]
        day = min(int(rng.expovariate(1 / 7)), 29)
        when = now - timedelta(days=day, minutes=rng.randint(5, 600))
        question, answer = rng.choice(QUESTIONS[slug])
        via_flo = i % 3 == 0
        if via_flo:
            if person.id not in flo_threads:
                flo_threads[person.id] = Chat.objects.create(user=person, org=org, buddy=flo, title="Ask Flo")
            flo_chat = flo_threads[person.id]
            sub = thread(person, buddy, f"Via Flo: {flo_chat.title}")
        else:
            sub = thread(person, buddy)
        at(when, sub, Message.ROLE_USER, question)
        reply_at = when + timedelta(seconds=rng.randint(2, 9))
        reply = at(reply_at, sub, Message.ROLE_ASSISTANT, f"{answer}\n\n{LABEL}")
        latency = int(rng.lognormvariate(7.4, 0.35))  # about 1.6 s
        facts.append(BuddyAnswer(org=org, buddy=buddy, message=reply, via_flo=via_flo, latency_ms=latency,
                                 cited=slug in CITES and rng.random() < 0.85, created_at=reply_at))
        tokens_in, tokens_out = rng.randint(400, 1400), rng.randint(80, 260)
        # Tagged with the Design team (no team budget there) and kept small, so the budgets seeded
        # in 70_ai_admin keep their states; Sara's own rows use her key so her alert-only budget holds.
        own = person == users["designer"]
        usage.append(UsageEvent(org=org, user=person, chat=sub, provider="demo", model="flobrain-demo", operation="chat",
                                input_tokens=tokens_in, output_tokens=tokens_out, total_tokens=tokens_in + tokens_out,
                                credential_source=UsageEvent.CREDENTIAL_CUSTOMER if own else UsageEvent.CREDENTIAL_PLATFORM,
                                latency_ms=latency, status="ok", surface="buddy", team=design, created_at=reply_at))
        rated = reply
        if via_flo:
            at(when, flo_chat, Message.ROLE_USER, question)
            rated = at(reply_at, flo_chat, Message.ROLE_ASSISTANT, f"Answered by {buddy.name}\n\n{answer}\n\n{LABEL}")
            route = BuddyRoute.objects.create(org=org, user=person, chat=flo_chat, reply=rated, surface=BuddyRoute.SURFACE_BUDDY,
                                              method=BuddyRoute.METHOD_LLM if i % 9 else BuddyRoute.METHOD_KEYWORDS,
                                              candidates=len(buddies), latency_ms=rng.randint(240, 900))
            BuddyRoute.objects.filter(pk=route.pk).update(created_at=when)
            BuddyRouteHop.objects.create(route=route, buddy=buddy, chat=sub, position=0, status=200)
        replies.append((person, buddy, rated, reply_at))
    BuddyAnswer.objects.bulk_create(facts)
    UsageEvent.objects.bulk_create(usage)

    # 60 ratings: one per person per reply, on the reply the person saw.
    feedback = []
    for person, buddy, message, when in replies[:60]:
        up = rng.random() < HELPFUL[buddy.slug]
        feedback.append(BuddyFeedback(org=org, buddy=buddy, user=person, message=message,
                                      rating=BuddyFeedback.UP if up else BuddyFeedback.DOWN,
                                      reason="" if up else rng.choice(REASONS), created_at=when + timedelta(minutes=1)))
    BuddyFeedback.objects.bulk_create(feedback)

    _proposals(org, users, buddies, threads, now, ActionProposal)


def _proposals(org, users, buddies, threads, now, ActionProposal):
    plan = [
        # buddy, tool, arguments, summary, status, days ago
        ("sales", "email.draft", {"subject": "Following up on our call", "body": "Hi Cairo Bikes team, ... (demo draft)"},
         "Draft an email: Following up on our call", "executed", 1),
        ("sales", "email.draft", {"subject": "Proposal for Lotus Tea", "body": "Hello, attached is ... (demo draft)"},
         "Draft an email: Proposal for Lotus Tea", "rejected", 3),
        ("sales", "email.draft", {"subject": "Thanks, Delta Clinics", "body": "Thank you for choosing us ... (demo draft)"},
         "Draft an email: Thanks, Delta Clinics", "executed", 9),
        ("meeting-prep", "tasks.create", {"title": "Order the Android test device"}, "Create a task: Order the Android test device", "executed", 2),
        ("meeting-prep", "tasks.create", {"title": "Draft the launch blog post"}, "Create a task: Draft the launch blog post", "executed", 2),
        ("meeting-prep", "email.draft", {"subject": "Notes and next steps", "body": "Hi all, thanks for today ... (demo draft)"},
         "Draft an email: Notes and next steps", "proposed", 0),
        ("meeting-prep", "tasks.create", {"title": "Book the store review slot"}, "Create a task: Book the store review slot", "rejected", 12),
        ("onboarding-coach", "tasks.create", {"title": "Read the Engineering handbook"}, "Create a task: Read the Engineering handbook", "executed", 5),
    ]
    member = users["member"]
    for slug, tool, args, summary, status, days in plan:
        buddy = buddies.get(slug)
        if buddy is None:
            continue
        chat = next((c for (uid, bid, _), c in threads.items() if bid == buddy.id and uid == member.id), None)
        created = now - timedelta(days=days, hours=2)
        decided = status != "proposed"
        ActionProposal.objects.create(
            org=org, user=member, thread=chat, buddy=buddy, tool_key=tool, arguments=args, summary=summary, status=status,
            decided_by=member if decided else None, decided_at=created + timedelta(minutes=20) if decided else None,
            result={"demo": True} if status == "executed" else {}, created_at=created,
            expires_at=now + timedelta(hours=20) if not decided else created + timedelta(days=1),
        )
