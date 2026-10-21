"""SAMPLE plan rows for workspace pricing (M8). The only place on the server where price numbers
are written down, and only to seed the demo and sandboxes. Production prices are Plan rows set by
platform admins (``POST /platform/plans``); the calculator and checkout read rows, never this file.

Prices are not decided (docs/v2/DECISIONS_NEEDED.md Q22). Override without a code change with the
Django setting ``BILLING_SAMPLE_PLANS`` (same shape). The frontend mirror lives in
``flobrain-website/src/components/v2/billing/pricing.ts``; ``test_pricing.py`` and ``pricing.test.ts``
check the same numbers.
"""

from django.conf import settings

SAMPLE_PLANS = (
    {
        "code": "fleet",
        "name": "Fleet (Sample)",
        "billing_unit": "per_seat",
        "price_cents": 1200,  # per person per month
        "price_yearly_cents": 12000,  # per person per year
        "tier": "fleet",
        "included_seats": None,
        "ai_allowance_per_workspace": None,  # per seat, see growth/allowance.py ("fleet": 1500)
        "overage_policy": "block",
    },
    {
        "code": "studio",
        "name": "Studio (Sample)",
        "billing_unit": "per_workspace",
        "price_cents": 19900,  # whole workspace per month
        "price_yearly_cents": 198000,  # whole workspace per year
        "tier": "fleet",
        "included_seats": 25,
        "ai_allowance_per_workspace": 30000,
        "overage_policy": "prompt_upgrade",
    },
)


def sample_plans():
    return tuple(getattr(settings, "BILLING_SAMPLE_PLANS", None) or SAMPLE_PLANS)


def ensure(flags=None) -> dict:
    """Create or update the sample plans (public). Returns {code: Plan}. Demo and sandboxes only."""
    from billing_v2.models import Plan

    out = {}
    for row in sample_plans():
        defaults = {k: v for k, v in row.items() if k != "code"}
        defaults.update({"is_public": True, "interval": "month", "currency": "USD"})
        defaults["entitlements"] = {"flags": list(flags) if flags is not None else [], "limits": {}}
        out[row["code"]], _ = Plan.objects.update_or_create(code=row["code"], defaults=defaults)
    return out
