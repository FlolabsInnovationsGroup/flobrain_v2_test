"""AI admin in the demo: keys, usage, budgets, a buddy share request and agent runs with output.

- An org key and Youssef's personal key on the built-in **demo provider** (never a real key; the
  demo model answers, nothing goes over the network). Only when credential encryption is set up.
- This month's usage across members and surfaces, some on the demo key, so Usage and Pulse Cost
  have something to group.
- Budgets at three scopes: the org (blocks at 100%, at about 40%), Engineering (switches to the
  demo model at 100%, at 85%, which sends the owners and admins a budget alert) and Sara
  (alert only, at about 30%).
- Sara asks to share her "Brand voice checker" buddy with the whole org (pending, for admins).
- The release notes helper is shared with Engineering and may propose room posts, so "Run now" on
  the Monday agent ends in Approvals. Two earlier runs show their draft in History.
"""

import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_UP

DEMO_SECRET = "demo-key-not-real-0000"  # a placeholder for the demo provider; it opens nothing


def seed(org, users, now):
    _keys(org, users, now)
    _usage(org, users, now)
    _budgets(org, users)
    _share_request(org, users, now)
    _agent_runs(org, users, now)


def _keys(org, users, now):
    from integrations import crypto
    from integrations.credentials import DEMO_BASE_URL, DEMO_PROVIDER
    from integrations.models import AICredential

    if not crypto.is_configured():
        return  # BYOK shows "not configured" without the encryption key
    for owner, label in ((None, "Demo provider (Demo org key)"), (users["member"], "My demo key (Demo)")):
        key = AICredential(
            id=uuid.uuid4(), org=org, owner=owner, provider=DEMO_PROVIDER, base_url=DEMO_BASE_URL, label=label,
            status=AICredential.STATUS_ACTIVE, last_checked_at=now, created_by=owner or users["admin"],
        )
        key.ciphertext = crypto.encrypt(DEMO_SECRET, key.id, org.id)
        key.key_version = crypto.current_key_version()
        key.last4 = DEMO_SECRET[-4:]
        key.save()


def _usage(org, users, now):
    from organizations.models import Team
    from telemetry.models import UsageEvent

    eng = Team.objects.filter(org=org, name="Engineering").first()
    design = Team.objects.filter(org=org, name="Design").first()
    rows = []
    plan = (
        # who, team, surface, operation, input, output, own key, hours ago
        ("member", eng, "buddy", "chat", 2200, 640, False, 2),
        ("member", eng, "room_ai", "chat", 1800, 420, True, 3),
        ("member", eng, "knowledge_ask", "chat", 2600, 380, False, 5),
        ("lead", eng, "scheduled_agent", "chat", 3400, 900, False, 26),
        ("lead", eng, "room_ai", "chat", 1500, 300, False, 30),
        ("lead", eng, "buddy", "summarize", 4100, 700, False, 50),
        ("designer", design, "content_studio", "summarize", 3000, 800, False, 6),
        ("designer", design, "translation", "translate", 600, 620, False, 8),
        ("admin", None, "knowledge_ask", "chat", 1200, 260, False, 4),
        ("admin", None, "room_ai", "chat", 900, 240, True, 9),
    )
    for i, (who, team, surface, operation, tokens_in, tokens_out, own, hours) in enumerate(plan):
        rows.append(UsageEvent(
            org=org, user=users[who], provider="demo", model="flobrain-demo", operation=operation,
            input_tokens=tokens_in, output_tokens=tokens_out, total_tokens=tokens_in + tokens_out,
            credential_source=UsageEvent.CREDENTIAL_CUSTOMER if own else UsageEvent.CREDENTIAL_PLATFORM,
            latency_ms=700 + i * 37, status="ok", team=team, surface=surface,
            created_at=max(now - timedelta(hours=hours), now.replace(day=1, hour=0, minute=0, second=1, microsecond=0)),
        ))
    UsageEvent.objects.bulk_create(rows)


def _cap(spent, ratio):
    """A limit that puts ``spent`` at about ``ratio`` of it (at least one cent)."""
    cap = (spent / Decimal(ratio)).quantize(Decimal("0.0001"), rounding=ROUND_UP) if spent > 0 else Decimal("0.01")
    return max(cap, Decimal("0.0001"))


def _budgets(org, users):
    from organizations.models import Team
    from telemetry.models import Budget
    from telemetry.pricing import check_alerts, scope_spend

    eng = Team.objects.filter(org=org, name="Engineering").first()
    Budget.objects.create(
        org=org, scope_type=Budget.SCOPE_ORG, cap_amount=_cap(scope_spend(org), "0.4"), on_exceed=Budget.ON_BLOCK
    )
    if eng is not None:
        # 0.85 exactly: just past the 80% alert, so the owners and admins get one budget alert.
        spent = scope_spend(org, Budget.SCOPE_TEAM, eng.id)
        Budget.objects.create(
            org=org, scope_type=Budget.SCOPE_TEAM, scope_id=eng.id, on_exceed=Budget.ON_DOWNGRADE, downgrade_model="flobrain-demo",
            cap_amount=(spent / Decimal("0.85")).quantize(Decimal("0.0001")) if spent > 0 else Decimal("0.01"),
        )
    designer = users["designer"]
    Budget.objects.create(
        org=org, scope_type=Budget.SCOPE_USER, scope_id=designer.id, on_exceed=Budget.ON_ALERT,
        cap_amount=_cap(scope_spend(org, Budget.SCOPE_USER, designer.id), "0.3"),
    )
    check_alerts(org)


def _share_request(org, users, now):
    from buddies.models import Buddy
    from notifications.services import notify

    designer = users["designer"]
    buddy = Buddy.objects.create(
        org=org, slug="brand-voice-checker-demo", name="Brand voice checker", created_by=designer,
        description="Checks copy against the Nile Labs brand voice. (Demo)",
        system_prompt="Review the text for the Nile Labs brand voice: warm, short, plain words. Suggest fixes.",
        preset_prompts=[{"label": "Check this copy", "prompt": "Check this copy against our brand voice."}],
        allowed_sources={"mode": "accessible", "source_types": ["doc"]},
        share_status=Buddy.SHARE_PENDING, share_target=Buddy.VIS_ORG,
    )
    notify(
        org, [users["owner"], users["admin"]], "buddy_share_request",
        {"text": f"{designer.username} asked to share {buddy.name} with the organization", "buddy": str(buddy.id),
         "name": buddy.name, "by": designer.username, "target": "org", "team": ""},
        link="buddies/requests",
    )


def _agent_runs(org, users, now):
    from actions.models import ActionProposal
    from agents.models import AgentRun, AgentSchedule
    from brain.models import Chat, Message
    from buddies.models import Buddy
    from organizations.models import Team
    from rooms.models import Room

    lead = users["lead"]
    eng = Team.objects.filter(org=org, name="Engineering").first()
    helper = Buddy.objects.filter(org=org, slug="release-notes-helper").first()
    schedule = AgentSchedule.objects.filter(org=org, buddy=helper).first() if helper else None
    room = Room.objects.filter(org=org, kind=Room.KIND_TEAM, team=eng).first() if eng else None
    if helper is None or schedule is None or room is None:
        return
    # Youssef built it; Layla approved sharing it with Engineering, so her agent can use it.
    helper.visibility, helper.team, helper.share_status, helper.share_decided_by = Buddy.VIS_TEAM, eng, Buddy.SHARE_APPROVED, lead
    helper.allowed_tools = list(dict.fromkeys([*(helper.allowed_tools or []), "rooms.post_message"]))
    helper.save()
    drafts = (
        (14, ["Set up CI for the mobile app", "Crash reporting groundwork"], ActionProposal.STATUS_EXECUTED),
        (7, ["Set up CI for the mobile app"], ActionProposal.STATUS_REJECTED),
    )
    for days_ago, items, outcome in drafts:
        started = now - timedelta(days=days_ago, hours=1)
        body = "Release notes for this week\n\n" + "\n".join(f"- {t}" for t in items) + "\n\n(Draft from FloBrain's demo model.)"
        chat = Chat.objects.create(user=lead, org=org, buddy=helper, title=schedule.name)
        Message.objects.create(chat=chat, role=Message.ROLE_USER, text=schedule.instructions, created_at=started)
        Message.objects.create(chat=chat, role=Message.ROLE_ASSISTANT, text=body, created_at=started + timedelta(seconds=4))
        ActionProposal.objects.create(
            org=org, user=lead, thread=chat, buddy=helper, tool_key="rooms.post_message",
            arguments={"room": str(room.id), "body": body}, summary=f"Post in {room.name}", status=outcome,
            decided_by=lead, decided_at=started + timedelta(minutes=20), created_at=started,
            expires_at=started + timedelta(days=1),
        )
        AgentRun.objects.create(
            org=org, schedule=schedule, status=AgentRun.STATUS_DONE, reason="cron", chat=chat, proposals=1,
            event_key=f"cron:demo-{days_ago}", started_at=started, finished_at=started + timedelta(seconds=5), created_at=started,
        )
    schedule.last_run_at = now - timedelta(days=7, hours=1)
    schedule.save(update_fields=["last_run_at"])
