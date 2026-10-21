"""Demo data for the Academy, industry packs, marketplace ratings and the AI-per-seat meter (all demo):

- Academy progress: Layla finished every lesson (badge), Youssef is halfway, Sara and Omar started.
- The Small business pack installed by Omar (workflow templates show "needs Workflows" when that
  app has no templates yet).
- An approved marketplace buddy, "Weekly report writer", installed by three people, with ratings and
  reviews, two versions and the "Verified by FloBrain" mark. The pending listing from the core seed stays pending.
- This month's AI answers for every demo person, so the meter shows a real projection.
"""

import random
from datetime import timedelta


def _academy(org, users, now):
    from growth import lessons as L
    from growth.models import AcademyBadge, LessonProgress

    plan = {"lead": len(L.KEYS), "member": 4, "designer": 1, "admin": 2}
    for role, done in plan.items():
        user = users.get(role)
        if user is None:
            continue
        for n, key in enumerate(L.KEYS):
            if n > done:
                break
            when = now - timedelta(days=12 - n)
            completed = n < done
            LessonProgress.objects.update_or_create(
                org=org,
                user=user,
                lesson=key,
                defaults={
                    "read_at": when,
                    "tried_at": when if completed else None,
                    "attempts": 1 if completed else 0,
                    "best_score": 100 if completed else 0,
                    "completed_at": when if completed else None,
                    "updated_at": when,
                },
            )
        if done == len(L.KEYS):
            AcademyBadge.objects.get_or_create(org=org, user=user, defaults={"awarded_at": now - timedelta(days=4)})


def _pack(org, users, now):
    from growth import packs as P

    admin = users.get("admin")
    if admin is None:
        return
    record, _, _, _ = P.install(org, admin, P.PACKS["smb"])
    type(record).objects.filter(pk=record.pk).update(installed_at=now - timedelta(days=6))


def _ratings(org, users, now):
    from buddies.models import Buddy
    from marketplace.models import Install, Listing, Rating

    author = users.get("lead")
    if author is None:
        return
    source = Buddy.objects.create(
        org=org, slug="weekly-report-writer", name="Weekly report writer", created_by=author,
        description="Drafts a team's weekly report from finished tasks and room updates. (Demo)",
        system_prompt="Write a short weekly report: done, next, blocked. Offer an Arabic version.",
        preset_prompts=[{"label": "This week", "prompt": "Draft this week's report for my team."}],
        allowed_sources={"mode": "accessible", "source_types": ["doc", "room_message"]},
    )
    snapshot = {
        "name": source.name, "description": source.description, "icon": "", "system_prompt": source.system_prompt,
        "preset_prompts": source.preset_prompts, "allowed_tools": [], "default_model": None, "allowed_sources": source.allowed_sources,
    }
    decider = users.get("admin") or author
    v1 = Listing.objects.create(
        org=org, kind=Listing.KIND_BUDDY, source_id=source.id, title=source.name, description=source.description,
        snapshot=dict(snapshot, system_prompt="Write a short weekly report: done, next, blocked."),
        status=Listing.SUPERSEDED, submitted_by=author, decided_by=decider, decided_at=now - timedelta(days=20),
        created_at=now - timedelta(days=21),
    )
    v2 = Listing.objects.create(
        org=org, kind=Listing.KIND_BUDDY, source_id=source.id, title=source.name, description=source.description,
        snapshot=snapshot, lineage=v1.lineage, version=2, changelog="Offers an Arabic version of the report.",
        status=Listing.APPROVED, submitted_by=author, decided_by=decider, decided_at=now - timedelta(days=8),
        created_at=now - timedelta(days=9), verified=True, verified_at=now - timedelta(days=7),
    )
    reviews = {
        "member": (5, "Saves me half an hour every Friday.", 2),
        "designer": (4, "Good structure. I edit the tone a little.", 1),
        "owner": (5, "The Arabic version is great for the board.", 2),
    }
    for role, (stars, text, version) in reviews.items():
        user = users.get(role)
        if user is None:
            continue
        listing = v2 if version == 2 else v1
        copy = Buddy.objects.create(
            org=org, slug=f"weekly-report-writer-{role}", name=source.name, created_by=user,
            description=source.description, system_prompt=listing.snapshot["system_prompt"],
            preset_prompts=source.preset_prompts, allowed_sources=source.allowed_sources,
        )
        Install.objects.create(
            org=org, listing=listing, lineage=v1.lineage, version=version, user=user, kind=Listing.KIND_BUDDY,
            target_id=copy.id, created_at=now - timedelta(days=15 if version == 1 else 6),
        )
        Rating.objects.create(
            org=org, lineage=v1.lineage, version=version, user=user, stars=stars, review=text,
            created_at=now - timedelta(days=5), updated_at=now - timedelta(days=5),
        )
    Listing.objects.filter(pk=v1.pk).update(installs=1)
    Listing.objects.filter(pk=v2.pk).update(installs=2)


# Typical buddy answers a day per person this month (the meter's projection lands around 70% of a Fleet seat allowance).
DAILY = {"member": 55, "lead": 45, "designer": 40, "admin": 30, "owner": 18}


def _budgets_before(org):
    from telemetry.models import Budget
    from telemetry.pricing import scope_spend

    return [(b, scope_spend(org, b.scope_type, b.scope_id)) for b in Budget.objects.filter(org=org)]


def _keep_budget_ratios(org, before):
    """The extra usage must not push the demo past its budgets (the org budget blocks at 100%):
    scale every cap so each budget sits at the same percentage as before."""
    from decimal import Decimal

    from telemetry.models import Budget
    from telemetry.pricing import scope_spend

    for budget, spent in before:
        now_spent = scope_spend(org, budget.scope_type, budget.scope_id)
        if now_spent <= spent:
            continue
        ratio = (budget.cap_amount / spent) if spent > 0 else Decimal(2)
        Budget.objects.filter(pk=budget.pk).update(cap_amount=(now_spent * ratio).quantize(Decimal("0.0001")))


def _usage(org, users, now):
    from telemetry.models import UsageEvent

    before = _budgets_before(org)

    rng = random.Random(96)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    events = []
    day = start
    while day < now:
        for role, base in DAILY.items():
            user = users.get(role)
            if user is None:
                continue
            for _ in range(int(base * rng.uniform(0.6, 1.2))):
                when = day + timedelta(minutes=rng.randint(0, 24 * 60 - 1))
                if when >= now:
                    continue
                tokens_in, tokens_out = rng.randint(300, 2000), rng.randint(60, 500)
                events.append(UsageEvent(
                    org=org, user=user, provider="demo", model="flobrain-demo", operation="chat",
                    input_tokens=tokens_in, output_tokens=tokens_out, total_tokens=tokens_in + tokens_out,
                    latency_ms=rng.randint(400, 2500), surface=rng.choice(["buddy", "room_ai", "knowledge_ask"]), created_at=when,
                ))
        day += timedelta(days=1)
    UsageEvent.objects.bulk_create(events, batch_size=1000)
    _keep_budget_ratios(org, before)


def seed(org, users, now):
    _academy(org, users, now)
    _pack(org, users, now)
    _ratings(org, users, now)
    _usage(org, users, now)
