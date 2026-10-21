"""Demo data for workspace pricing (M8, flag ``workspace_pricing``):

- The sample plans Fleet (per person) and Studio (one price for up to 25 people), both "(Sample)".
- The demo org on Studio, monthly, with 8 of 25 seats used (demo people are added when the core
  seed has fewer, all on example addresses and marked demo).
- Four sample invoices (three paid, this month's draft), amounts from the plan rows, no Stripe link.

Runs after ``80_platform`` (module-name order), which created the older per-seat demo plans.
"""

from datetime import timedelta

from django.contrib.auth.hashers import make_password

TARGET_SEATS = 8
EXTRA_PEOPLE = (("Mona Fathy", "mona"), ("Rania Adel", "rania"), ("Huda Amin", "huda"), ("Tarek Nour", "tarek"), ("Ziad Hamdy", "ziad"), ("Salma Ezz", "salma"))


def seed(org, users, now):
    from billing_v2 import pricing, sample_plans
    from billing_v2.entitlements import seats_used
    from billing_v2.models import Invoice, Subscription
    from demo.seed import DEMO_DOMAIN, FLAGS

    plans = sample_plans.ensure(flags=FLAGS)
    studio, fleet = plans["studio"], plans["fleet"]
    _fill_seats(org, seats_used(org), DEMO_DOMAIN)
    sub, _ = Subscription.objects.update_or_create(
        org=org,
        defaults={
            "plan": studio,
            "status": "active",
            "seats": studio.included_seats or 1,
            "interval": "month",
            "current_period_end": now + timedelta(days=12),
            "stripe_customer_id": "",
            "stripe_subscription_id": "",
        },
    )
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    history = (
        (3, fleet, 6, "paid"),
        (2, fleet, 7, "paid"),
        (1, studio, TARGET_SEATS, "paid"),
        (0, studio, TARGET_SEATS, "draft"),
    )
    for back, plan, people, status in history:
        start = month
        for _ in range(back):
            start = (start - timedelta(days=1)).replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
        amount = pricing.cost(plan, people, "month")["per_month_cents"] or 0
        Invoice.objects.update_or_create(
            org=org,
            number=f"DEMO-{start:%Y%m}",
            defaults={
                "status": status,
                "amount_cents": amount,
                "currency": plan.currency,
                "plan_code": plan.code,
                "period_start": start,
                "period_end": end,
                "hosted_url": "",
                "demo": True,
                "created_at": start + timedelta(hours=9),
            },
        )
    return sub


def _fill_seats(org, used, domain):
    """Top the demo up to TARGET_SEATS people holding a seat (active demo members)."""
    from organizations.models import OrgMembership
    from users.models import User

    for name, key in EXTRA_PEOPLE:
        if used >= TARGET_SEATS:
            return
        email = f"{key}@{domain}"
        user = User.objects.filter(email=email).first() or User.objects.create(
            email=email, username=name, password_hash=make_password(None), provider="demo", must_change_password=False
        )
        _, made = OrgMembership.objects.get_or_create(org=org, user=user, defaults={"org_role": OrgMembership.ORG_ROLE_MEMBER, "employment_status": "active"})
        used += 1 if made else 0
