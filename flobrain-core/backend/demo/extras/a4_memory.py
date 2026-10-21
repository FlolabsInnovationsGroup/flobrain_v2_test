"""Buddy memory in the demo (growth round M4).

- The org's memory rules with the defaults (memory on, ask before saving, 180 days, team memory on).
- 8 memories about Youssef (the demo member): preferences, work context, projects, people.
- 2 suggestions waiting for his yes or no on the Memory page.
- 3 team memories (2 for Engineering, 1 for Design; he is in both).
Every fact passes the same sensitivity filter as real ones (checked by the tests).
"""

from datetime import timedelta

PERSONAL = [
    # text, category, source, days ago, pinned, used days ago
    ("Prefers short answers with bullet points", "preference", "chat", 21, True, 0),
    ("Leads the Android login timeout fix for the launch", "project", "buddy", 9, False, 1),
    ("Works on the Android build of the mobile app", "work_context", "buddy", 30, False, 2),
    ("Works with Sara on the store screenshots", "people", "buddy", 12, False, 3),
    ("Prefers code examples in Kotlin", "preference", "manual", 40, False, 6),
    ("Reviews pull requests in the morning, Cairo time", "work_context", "buddy", 18, False, None),
    ("Wants a weekly summary on Sunday mornings", "preference", "chat", 5, True, 0),
    ("Owns the release checklist for version 2.0", "project", "buddy", 3, False, 1),
]
PENDING = [
    ("Prefers English for technical docs and Arabic for team updates", "preference"),
    ("Works with Omar on the Gulf customer rollout", "people"),
]
TEAM = [
    ("Engineering", "Code freeze starts two days before every release", "work_context"),
    ("Engineering", "Bugs go in Jira and code reviews happen on GitHub", "work_context"),
    ("Design", "Design reviews happen on Wednesdays at 11:00", "other"),
]


def seed(org, users, now):
    from buddies.models import Buddy
    from buddy_memory.models import MemoryItem, MemorySettings
    from buddy_memory.services import DEFAULTS, digest, expiry
    from organizations.models import Team

    member = users.get("member")
    if member is None:
        return
    row, _ = MemorySettings.objects.get_or_create(org=org, defaults=dict(DEFAULTS, updated_by=users.get("owner")))
    buddy = Buddy.objects.filter(org=org, slug="space").first() or Buddy.objects.filter(org=org).first()
    for text, category, source, days, pinned, used in PERSONAL:
        created = now - timedelta(days=days)
        MemoryItem.objects.create(
            org=org, scope=MemoryItem.SCOPE_PERSON, user=member, text=text, category=category, source=source,
            created_by_buddy=buddy if source == "buddy" else None, created_by=member if source != "buddy" else None,
            confirmed=source != "buddy" or days % 2 == 1, pinned=pinned, status=MemoryItem.STATUS_ACTIVE,
            digest=digest(org.id, text), created_at=created, expires_at=expiry(row, created),
            last_used_at=(now - timedelta(days=used)) if used is not None else None,
        )
    for i, (text, category) in enumerate(PENDING):
        created = now - timedelta(hours=3 + i * 20)
        MemoryItem.objects.create(
            org=org, scope=MemoryItem.SCOPE_PERSON, user=member, text=text, category=category, source="buddy",
            created_by_buddy=buddy, status=MemoryItem.STATUS_PENDING, digest=digest(org.id, text), created_at=created,
            expires_at=expiry(row, created, pending=True),
        )
    for team_name, text, category in TEAM:
        team = Team.objects.filter(org=org, name=team_name).first()
        if team is None:
            continue
        created = now - timedelta(days=15)
        MemoryItem.objects.create(
            org=org, scope=MemoryItem.SCOPE_TEAM, team=team, text=text, category=category, source="manual",
            created_by=users.get("lead") if team_name == "Engineering" else users.get("designer"), confirmed=True,
            digest=digest(org.id, text), created_at=created, expires_at=expiry(row, created),
        )
