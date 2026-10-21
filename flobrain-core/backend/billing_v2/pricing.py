"""Price math for per-seat and per-workspace plans (M8). One implementation for the public
calculator, the plan-switch preview and sales. Mirrored in
``flobrain-website/src/components/v2/billing/pricing.ts`` (same rules, same rounding); the tests on
both sides use the same team sizes and expect the same cents.

Rules:
- A plan has a monthly price (``price_cents`` when ``interval`` is "month") and a yearly price
  (``price_yearly_cents``, or 12 x monthly when that is 0). A plan whose ``interval`` is "year" has
  only a yearly price (``price_cents``).
- Per seat: price x team size. Unavailable above ``entitlements.limits.seats``.
- Per workspace: one price for up to ``included_seats`` people. Unavailable above that cap; we never
  charge for extra people silently.
- "Per month" for a yearly price is the yearly total / 12, rounded half up to a whole cent.
- In each ``tier`` the cheaper of the available paid per-seat and per-workspace plans wins; on a tie
  the per-seat plan (no cap) wins.
"""

from django.conf import settings

INTERVALS = ("month", "year")
MAX_TEAM = 10000


def is_sample() -> bool:
    """Prices are samples until the owners confirm them (DECISIONS_NEEDED Q22): the setting, or
    the env ``BILLING_PRICES_CONFIRMED=True`` when the setting is absent."""
    import os

    confirmed = getattr(settings, "BILLING_PRICES_CONFIRMED", None)
    if confirmed is None:
        confirmed = os.environ.get("BILLING_PRICES_CONFIRMED", "False") == "True"
    return not confirmed


def unit_prices(plan) -> dict:
    """{"month": cents | None, "year": cents | None} for one seat (per seat) or the workspace."""
    if plan.interval == "year":
        return {"month": None, "year": int(plan.price_cents)}
    month = int(plan.price_cents)
    return {"month": month, "year": int(plan.price_yearly_cents or 0) or month * 12}


def per_month(year_cents: int) -> int:
    return (int(year_cents) + 6) // 12


def seat_cap(plan):
    """People the plan allows, or None for no cap."""
    if plan.per_workspace:
        return plan.included_seats
    return plan.limit("seats")


def cost(plan, team: int, interval: str) -> dict:
    prices = unit_prices(plan)
    price = prices.get(interval)
    cap = seat_cap(plan)
    row = {
        "code": plan.code,
        "name": plan.name,
        "billing_unit": plan.billing_unit,
        "tier": plan.tier or plan.code,
        "included_seats": plan.included_seats if plan.per_workspace else None,
        "seat_cap": cap,
        "unit_price_cents": price,
        "currency": plan.currency,
        "available": True,
        "reason": "",
        "per_month_cents": None,
        "per_year_cents": None,
    }
    if price is None:
        row.update(available=False, reason="interval_not_offered")
        return row
    if cap is not None and team > cap:
        row.update(available=False, reason="over_cap")
        return row
    total = price if plan.per_workspace else price * team
    if interval == "month":
        row.update(per_month_cents=total, per_year_cents=total * 12)
    else:
        row.update(per_month_cents=per_month(total), per_year_cents=total)
    return row


def calculate(plans, team: int, interval: str) -> dict:
    rows = [cost(p, team, interval) for p in plans]
    comparisons = []
    tiers = []
    for row in rows:
        if row["tier"] not in tiers:
            tiers.append(row["tier"])
    for tier in tiers:
        paid = [r for r in rows if r["tier"] == tier and (r["unit_price_cents"] or 0) > 0]
        seat = next((r for r in paid if r["billing_unit"] == "per_seat"), None)
        space = next((r for r in paid if r["billing_unit"] == "per_workspace"), None)
        if seat is None or space is None:
            continue
        options = [r for r in (seat, space) if r["available"]]
        if not options:
            cheaper, savings = None, 0
        elif len(options) == 1:
            cheaper, savings = options[0], 0
        else:
            cheaper = space if space["per_year_cents"] < seat["per_year_cents"] else seat
            other = seat if cheaper is space else space
            savings = other["per_year_cents"] - cheaper["per_year_cents"]
        comparisons.append(
            {
                "tier": tier,
                "per_seat": seat["code"],
                "per_workspace": space["code"],
                "cheaper": cheaper["code"] if cheaper else None,
                "cheaper_unit": cheaper["billing_unit"] if cheaper else None,
                "savings_per_year_cents": savings,
                "break_even": break_even(seat, space, interval),
            }
        )
    first = comparisons[0] if comparisons else None
    return {
        "sample": is_sample(),
        "team_size": team,
        "interval": interval,
        "plans": rows,
        "comparisons": comparisons,
        "cheaper": first["cheaper"] if first else None,
        "cheaper_unit": first["cheaper_unit"] if first else None,
    }


def break_even(seat_row, space_row, interval):
    """Smallest team size where the workspace plan is cheaper than per seat, or None."""
    seat_price, space_price = seat_row["unit_price_cents"], space_row["unit_price_cents"]
    if not seat_price or not space_price:
        return None
    n = space_price // seat_price + 1  # first n with n * seat_price > space_price
    cap = space_row["seat_cap"]
    if cap is not None and n > cap:
        return None
    return n
