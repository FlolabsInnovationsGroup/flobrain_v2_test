"""Demo organisation (local demos only, ``DEMO_MODE=True``).

``reset()`` deletes the demo org and the demo users, then builds a complete, believable
workspace: one user per role, teams, a project, tasks, time, rooms, documents, a meeting,
buddies, a pending AI action, a scheduled agent, Content Studio, marketplace and skills.
Every demo user has an unusable password; they sign in only through demo sign-in.
"""

from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

DEMO_SLUG = "demo"
DEMO_DOMAIN = "demo.flobrain.example"
FLAGS = [
    "ai_actions", "api_access", "assign_suggestions", "auto_reports", "budgets", "buddies", "byok",
    "content_studio", "live_translation", "memory_search", "realtime", "room_ai", "scheduled_agents",
    "social_publishing", "voice_video", "webhooks", "learning", "commissions", "pulse", "privacy_center",
    "integrations", "meeting_bot", "cockpit", "status_page", "external_agents", "public_portfolio",
]

# key → (name, org role, description shown on the role picker)
ROLES = {
    "owner": ("Nadia Hassan", "owner", "Owns the org: billing, policy, SSO, export, everything."),
    "admin": ("Omar Khaled", "admin", "Runs the org day to day: members, access, approvals."),
    "lead": ("Layla Mansour", "member", "Leads the Engineering team: team reports, assigning, approvals for her team."),
    "member": ("Youssef Adel", "member", "Engineer on the team: tasks, time, rooms, buddies."),
}
EXTRA = {"designer": ("Sara Nabil", "member")}


def email_for(key):
    return f"{key}@{DEMO_DOMAIN}"


def _user(key, name):
    from users.models import User

    return User.objects.create(
        email=email_for(key), username=name, password_hash=make_password(None), provider="demo", must_change_password=False
    )


class DemoSlugTaken(Exception):
    """A real org already uses the demo slug; demo mode never touches it."""


def wipe():
    """Delete only what the demo created: the org marked ``demo`` and users with provider ``demo``."""
    from demo.models import DemoAccount
    from organizations.models import Organization
    from users.models import User

    org = Organization.objects.filter(slug=DEMO_SLUG).first()
    if org is not None:
        if (org.settings or {}).get("demo") is not True:
            raise DemoSlugTaken(DEMO_SLUG)
        _delete_org(org)
    ids = set(DemoAccount.objects.values_list("user_id", flat=True))
    ids |= set(User.objects.filter(provider="demo").values_list("id", flat=True))
    User.objects.filter(pk__in=ids, provider="demo").delete()
    DemoAccount.objects.all().delete()


def _delete_org(org):
    """Audit rows are append-only by design; demo data is the one place they are removed (raw delete)."""
    from organizations.models import AuditEvent

    from commissions.models import Commission

    AuditEvent.objects.filter(org=org)._raw_delete(AuditEvent.objects.db)
    Commission.objects.filter(org=org).delete()  # leads are protected while they have commissions
    org.delete()


@transaction.atomic
def reset():
    from actions.models import ActionProposal
    from agents import cron
    from agents.models import AgentSchedule
    from buddies.models import Buddy
    from buddies.seeds import seed_org
    from content_studio.models import BrandKit, ContentProject
    from content_studio.seeds import ensure_builtin_templates
    from demo.models import DemoAccount
    from docs_app.models import Document, DocumentRevision
    from integrations.models import ExternalTool
    from marketplace.models import Listing
    from meetings.models import Meeting, MeetingSummary
    from notifications.models import Notification
    from organizations.models import (
        MemberSkill,
        OrgMembership,
        Organization,
        Project,
        ProjectMembership,
        SkillTag,
        Team,
        TeamMembership,
    )
    from rooms.models import Announcement, Room, RoomMember, RoomMessage
    from rooms.services import ensure_project_room, ensure_team_room, pair_key_for
    from tasks.models import Task, TaskAssignment
    from timetracking.models import TimeEntry

    wipe()
    now = timezone.now()
    org = Organization.objects.create(
        name="Nile Labs (Demo)", slug=DEMO_SLUG, settings={"flags": {flag: True for flag in FLAGS}, "demo": True}
    )
    users = {}
    for key, (name, role, _) in ROLES.items():
        users[key] = _user(key, name)
        DemoAccount.objects.create(user=users[key], role=key)
        OrgMembership.objects.create(org=org, user=users[key], org_role=role, employment_status="active")
    for key, (name, role) in EXTRA.items():
        users[key] = _user(key, name)
        OrgMembership.objects.create(org=org, user=users[key], org_role=role, employment_status="active")
    owner, admin, lead, member, designer = (users[k] for k in ("owner", "admin", "lead", "member", "designer"))

    eng = Team.objects.create(org=org, name="Engineering", description="Builds the product")
    design = Team.objects.create(org=org, name="Design", description="Product and brand design")
    TeamMembership.objects.create(team=eng, user=lead, team_role=TeamMembership.ROLE_LEAD, weekly_target_hours=30)
    TeamMembership.objects.create(team=eng, user=member, weekly_target_hours=30)
    TeamMembership.objects.create(team=design, user=designer, team_role=TeamMembership.ROLE_LEAD, weekly_target_hours=25)
    TeamMembership.objects.create(team=design, user=member)
    project = Project.objects.create(
        org=org, name="Mobile app launch", description="Ship the first mobile release", lead=lead,
        starts_on=(now - timedelta(days=14)).date(), due_on=(now + timedelta(days=30)).date(),
    )
    project.teams.add(eng, design)
    ProjectMembership.objects.create(project=project, user=admin)
    eng_room, design_room, project_room = ensure_team_room(eng), ensure_team_room(design), ensure_project_room(project)

    tasks = [
        ("Set up CI for the mobile app", "done", member, eng, None),
        ("Design the onboarding screens", "in_progress", designer, design, project),
        ("Push notifications API", "in_progress", member, eng, project),
        ("Write the launch blog post", "to_do", admin, None, project),
        ("App store screenshots", "to_do", designer, design, project),
        ("Crash reporting", "to_do", member, eng, project),
        ("Security review of sign-in", "to_do", lead, eng, project),
        ("Fix login timeout on Android", "in_progress", member, eng, project),
    ]
    for i, (title, status, who, team, proj) in enumerate(tasks):
        task = Task.objects.create(
            org=org, title=title, status=status, team=team, project=proj, created_by=lead,
            due_on=(now + timedelta(days=3 + i * 2)).date(),
            is_blocked=title.startswith("Fix login"), blocked_reason="Waiting for the Android test device" if title.startswith("Fix login") else "",
            blocked_since=now - timedelta(days=2) if title.startswith("Fix login") else None,
        )
        TaskAssignment.objects.create(task=task, user=who)
    for days_ago in range(1, 8):
        for who, hours in ((member, 6), (lead, 5), (designer, 4)):
            start = (now - timedelta(days=days_ago)).replace(hour=9, minute=0, second=0, microsecond=0)
            TimeEntry.objects.create(org=org, user=who, description="Focused work", started_at=start, ended_at=start + timedelta(hours=hours))

    def say(room, who, body, minutes_ago):
        RoomMessage.objects.create(room=room, author=who, body=body, created_at=now - timedelta(minutes=minutes_ago))

    say(eng_room, lead, "Morning team. Today: push notifications and the Android login bug.", 300)
    say(eng_room, member, "I'm on the login timeout. I need the Android test device to reproduce it.", 290)
    say(eng_room, lead, "Omar is ordering one. Mark the task blocked until it arrives.", 280)
    say(design_room, designer, "Onboarding screens v2 are in Figma. Feedback welcome before Thursday.", 200)
    say(project_room, admin, "Launch date is confirmed for the end of next month.", 120)
    say(project_room, designer, "Screenshots need the final copy. Who owns the blog post?", 100)
    say(project_room, admin, "I do. Draft by Monday.", 90)
    say(project_room, member, "مرحبا! I'll share the release notes in Arabic too.", 60)
    Announcement.objects.create(org=org, room=project_room, body="Release candidate freeze: Friday 18:00.", created_by=lead)
    dm = Room.objects.create(org=org, name="Layla / Youssef", kind=Room.KIND_DIRECT, pair_key=pair_key_for(lead, member))
    for who in (lead, member):
        RoomMember.objects.create(room=dm, user=who)
    say(dm, lead, "Can you pair with Sara on the onboarding API tomorrow?", 30)
    say(dm, member, "Sure, 11:00 works.", 25)

    plan = Document.objects.create(
        org=org, room=project_room, title="Launch plan", created_by=admin,
        content_text="# Launch plan\n\n1. Code freeze Friday.\n2. Store review: 5 days.\n3. Blog post and social posts on launch day.\n\nRisks: Android login timeout, store review delays.",
    )
    DocumentRevision.objects.create(document=plan, version=1, content_text=plan.content_text, created_by=admin)
    guide = Document.objects.create(
        org=org, room=eng_room, title="Engineering onboarding", created_by=lead,
        content_text="Clone the repo, run the tests, ask in the Engineering room. Code review within one working day.",
    )
    DocumentRevision.objects.create(document=guide, version=1, content_text=guide.content_text, created_by=lead)

    meeting = Meeting.objects.create(
        org=org, room=project_room, title="Weekly launch sync", created_by=admin,
        started_at=now - timedelta(days=1, hours=2), ended_at=now - timedelta(days=1, hours=1, minutes=30),
    )
    MeetingSummary.objects.create(
        meeting=meeting,
        text="The team agreed on the launch date and the store screenshot owner.",
        decisions=["Launch at the end of next month", "Sara owns the store screenshots"],
        action_items=[{"id": "a1", "text": "Order an Android test device", "owner": "Omar"}, {"id": "a2", "text": "Blog post draft", "owner": "Omar"}],
    )

    for who, kind, payload in (
        (member, "task.assigned", {"title": "Crash reporting"}),
        (member, "mention", {"room": str(project_room.id), "by": "Layla Mansour"}),
        (lead, "task.blocked", {"title": "Fix login timeout on Android"}),
        (owner, "billing.notice", {"text": "Demo org: every feature is switched on"}),
    ):
        Notification.objects.create(org=org, user=who, kind=kind, payload=payload)

    for name in ("Python", "Django", "Figma", "Arabic copywriting"):
        SkillTag.objects.create(org=org, name=name)
    for who, skill in ((member, "Python"), (member, "Django"), (designer, "Figma"), (admin, "Arabic copywriting")):
        MemberSkill.objects.create(org=org, user=who, skill=SkillTag.objects.get(org=org, name=skill), confirmed_by=lead)

    ExternalTool.objects.create(org=org, name="Figma", url="https://www.figma.com", sort_order=1)
    ExternalTool.objects.create(org=org, name="GitHub", url="https://github.com", sort_order=2)

    seed_org(org)
    helper = Buddy.objects.create(
        org=org, slug="release-notes-helper", name="Release notes helper", created_by=member,
        description="Turns merged work into short release notes in English and Arabic.",
        system_prompt="Write short, friendly release notes. Offer an Arabic version.",
        preset_prompts=[{"label": "This week", "prompt": "Write release notes for this week's finished tasks."}],
        allowed_sources={"mode": "accessible", "source_types": ["doc", "room_message"]},
        allowed_tools=["tasks.create"],
    )
    Listing.objects.create(
        org=org, kind=Listing.KIND_BUDDY, source_id=helper.id, title=helper.name, description=helper.description,
        snapshot={
            "name": helper.name, "description": helper.description, "icon": "", "system_prompt": helper.system_prompt,
            "preset_prompts": helper.preset_prompts, "allowed_tools": helper.allowed_tools, "default_model": None,
            "allowed_sources": helper.allowed_sources,
        },
        submitted_by=member,
    )
    ActionProposal.objects.create(
        org=org, user=member, buddy=helper, tool_key="tasks.create",
        arguments={"title": "Add Arabic release notes to the store listing"},
        summary="Create a task: Add Arabic release notes to the store listing",
        expires_at=now + timedelta(days=1),
    )
    AgentSchedule.objects.create(
        org=org, buddy=helper, created_by=lead, name="Monday release notes", trigger_type=AgentSchedule.TRIGGER_CRON,
        cron="0 9 * * 1", instructions="Draft release notes for last week's finished tasks and post them in Engineering.",
        next_run_at=cron.next_after("0 9 * * 1", now),
    )

    ensure_builtin_templates(org)
    kit = BrandKit.objects.create(
        org=org, name="Nile Labs", colors={"primary": "#0E7C66", "accent": "#F2B134"}, fonts={"heading": "Cairo"}, created_by=admin
    )
    ContentProject.objects.create(org=org, owner=admin, title="Launch teaser (30 s)", brand_kit=kit, target_platforms=["youtube", "linkedin"])

    _seed_learning(org, users, guide, now)
    _seed_commissions(org, users)
    _seed_pulse(org, users, eng, now)
    _seed_integrations(org, users, eng_room)
    _seed_privacy(org, users)
    from demo.extras import run_all

    run_all(org, users, now)

    from organizations.services.core import sync_user_type

    for user in users.values():
        sync_user_type(user)

    return org


def _seed_learning(org, users, guide, now):
    """Phase 11: a path, a published quiz, a mentorship with a note, a cohort, a portfolio item and,
    when signing is configured, a certificate."""
    from learning import certs
    from learning.models import Certificate, Cohort, LearningPath, Mentorship, MentorNote, PortfolioItem, Quiz

    quiz = Quiz.objects.create(
        org=org, title="Launch basics", status=Quiz.PUBLISHED, created_by=users["admin"],
        questions=[
            {"question": "When is the code freeze?", "options": ["Monday", "Friday", "Next month"], "answer": 1},
            {"question": "Who owns the store screenshots?", "options": ["Sara", "Omar", "Youssef"], "answer": 0},
        ],
    )
    LearningPath.objects.create(
        org=org, name="Engineering onboarding", description="Your first week at Nile Labs.", created_by=users["lead"],
        steps=[
            {"kind": "doc", "title": "Read the onboarding guide", "ref": str(guide.id)},
            {"kind": "link", "title": "Set up your laptop", "ref": "https://example.com/setup"},
            {"kind": "quiz", "title": "Launch basics quiz", "ref": str(quiz.id)},
        ],
    )
    pair = Mentorship.objects.create(org=org, mentor=users["lead"], mentee=users["member"], cadence="weekly")
    MentorNote.objects.create(org=org, mentorship=pair, author=users["lead"], body="Week 1: get CI green, pair with Sara on onboarding.")
    cohort = Cohort.objects.create(org=org, name="Autumn interns")
    cohort.members.set([users["member"], users["designer"]])
    cohort.instructors.set([users["lead"]])
    PortfolioItem.objects.create(org=org, user=users["member"], kind="project", title="Mobile app CI pipeline", summary="Set up CI for the Nile Labs mobile app.", is_public=True)
    users["member"].portfolio_slug = "youssef-demo"
    users["member"].save(update_fields=["portfolio_slug"])
    try:
        data = certs.build_data(org, users["designer"], "internship_completion")
        data["issued_at"] = now.date().isoformat()
        Certificate.objects.create(
            org=org, user=users["designer"], kind="internship_completion", data=data, signature=certs.sign(data), key_id=certs.key_id(),
            issued_by=users["admin"], public_slug="demo-sara-internship",
        )
    except certs.NotConfigured:
        pass


def _seed_commissions(org, users):
    """Phase 12: Youssef's small pipeline, with one won lead and an approved commission."""
    from decimal import Decimal

    from commissions.models import Commission, Lead

    won = Lead.objects.create(org=org, owner_user=users["member"], project_or_product="Mobile app", contact_name="Delta Clinics", stage="won", estimated_value=Decimal("12000"))
    Lead.objects.create(org=org, owner_user=users["member"], project_or_product="Mobile app", contact_name="Cairo Bikes", stage="meeting_1")
    Lead.objects.create(org=org, owner_user=users["designer"], project_or_product="Brand refresh", contact_name="Lotus Tea", stage="in_progress")
    Commission.objects.create(org=org, lead=won, user=users["member"], amount=Decimal("600"), currency="USD", status="approved", recorded_by=users["admin"])


def _seed_pulse(org, users, team, now):
    """Phase 13: a week of AI usage and traces so Pulse has real records to show (demo workspace only)."""
    import random
    from decimal import Decimal

    from pulse.models import AlertRule, EvalCase, EvalSuite
    from telemetry.models import AITrace, PriceTable, UsageEvent

    PriceTable.objects.get_or_create(
        provider="demo", model="flobrain-demo",
        defaults={"input_price": Decimal("0.5"), "output_price": Decimal("1.5"), "valid_from": now - timedelta(days=60)},
    )
    rng = random.Random(7)  # same numbers after every reset
    surfaces = ["knowledge_ask", "buddy", "room_ai", "translation", "scheduled_agent"]
    people = [users["member"], users["lead"], users["designer"], users["admin"]]
    events, traces = [], []
    for day in range(7):
        for _ in range(rng.randint(12, 30)):
            when = now - timedelta(days=day, minutes=rng.randint(0, 600))
            ok = rng.random() > 0.06
            latency = int(rng.lognormvariate(6.6, 0.45))
            person = rng.choice(people)
            events.append(UsageEvent(
                org=org, user=person, provider="demo", model="flobrain-demo", operation="chat",
                input_tokens=rng.randint(300, 2400), output_tokens=rng.randint(80, 600), total_tokens=None,
                latency_ms=latency, status="ok" if ok else "error", error_code="" if ok else "provider_unavailable",
                team=team if person in (users["member"], users["lead"]) else None, created_at=when,
            ))
            traces.append(AITrace(
                org=org, user=person, request_id=f"demo-{len(traces)}", surface=rng.choice(surfaces), model="flobrain-demo",
                latency_ms=latency, outcome="completed" if ok else "error", created_at=when,
                context_sources=[{"type": "doc", "id": "demo"}] if rng.random() > 0.5 else [],
            ))
    for e in events:
        e.total_tokens = (e.input_tokens or 0) + (e.output_tokens or 0)
    UsageEvent.objects.bulk_create(events)
    AITrace.objects.bulk_create(traces)
    suite = EvalSuite.objects.create(org=org, name="Answers cite sources", threshold=80, created_by=users["admin"])
    EvalCase.objects.create(suite=suite, name="Launch date", prompt="When is the launch?", must_contain=["demo model"])
    EvalCase.objects.create(suite=suite, name="No invented numbers", prompt="What was revenue last year?", must_not_contain=["$"])
    AlertRule.objects.create(org=org, metric="error_rate", threshold=0.2, window_minutes=60, created_by=users["admin"])


def _seed_integrations(org, users, room):
    """Phase 15: a GitHub repo already brought into the Engineering room (no real token: sync is disabled)."""
    from connectors.models import Connection, ExternalItem

    conn = Connection.objects.create(
        org=org, connector="github", label="GitHub (demo)", room=room, config={"repo": "nile-labs/mobile-app"},
        created_by=users["admin"], status=Connection.ACTIVE, last_error="Demo data: syncing is off",
    )
    for number, title, kind, state in (
        (41, "Login times out on Android 14", "issue", "open"),
        (42, "Add crash reporting", "pull_request", "open"),
        (38, "Set up CI for the mobile app", "pull_request", "merged"),
    ):
        ExternalItem.objects.create(org=org, connection=conn, kind=kind, external_id=str(number), title=title, state=state,
                                    url=f"https://github.com/nile-labs/mobile-app/{'pull' if kind == 'pull_request' else 'issues'}/{number}")


def _seed_privacy(org, users):
    """Youssef keeps his time descriptions private; Sara has asked for deletion; recordings expire after a year."""
    from privacy.models import DeletionRequest, PrivacySettings, RetentionPolicy

    PrivacySettings.objects.create(user=users["member"], org=org, share_time_details_with_org=False)
    DeletionRequest.objects.create(org=org, user=users["designer"], reason="My internship ends this month.")
    RetentionPolicy.objects.create(org=org, recordings_days=365, transcripts_days=365, updated_by=users["owner"])
