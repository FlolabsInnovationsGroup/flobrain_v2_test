"""Switching between per-seat and per-workspace plans (M8): validation and the "what changes"
summary the owner confirms. Money moves at Stripe (proration there); nothing here charges."""

from billing_v2 import pricing
from billing_v2.entitlements import seats_used
from billing_v2.models import Plan


class SwitchError(Exception):
    def __init__(self, status: int, code: str, details: str, **extra):
        super().__init__(details)
        self.status, self.code, self.details, self.extra = status, code, details, extra

    def body(self):
        return {"error": self.code, "details": self.details, **self.extra}


def ai_included(plan, seats: int) -> dict:
    """AI buddy answers included per month: per workspace for workspace plans, else per seat x seats
    (growth.allowance numbers)."""
    if plan.per_workspace and plan.ai_allowance_per_workspace is not None:
        return {"basis": "per_workspace", "per_seat": None, "total": int(plan.ai_allowance_per_workspace)}
    from growth.allowance import config

    cfg = config()
    per_seat = cfg["per_seat"].get(plan.code, cfg["per_seat"].get(cfg["default_plan"], 0))
    return {"basis": "per_seat", "per_seat": per_seat, "total": per_seat * max(seats, 1)}


def describe(plan, interval: str, seats: int) -> dict:
    """One side of the comparison: what the org would have and pay."""
    team = plan.included_seats if plan.per_workspace and plan.included_seats else seats
    row = pricing.cost(plan, 1 if plan.per_workspace else seats, interval)  # one price for the workspace
    return {
        "plan": plan.code,
        "name": plan.name,
        "billing_unit": plan.billing_unit,
        "interval": interval,
        "seats": team,
        "seat_cap": pricing.seat_cap(plan),
        "per_month_cents": row["per_month_cents"],
        "per_year_cents": row["per_year_cents"],
        "charge_cents": row["per_month_cents"] if interval == "month" else row["per_year_cents"],
        "currency": plan.currency,
        "ai": ai_included(plan, team or seats),
        "overage_policy": plan.overage_policy if plan.per_workspace else Plan.OVERAGE_BLOCK,
    }


def plan_change(org, sub, target, interval, seats_value) -> dict:
    """Validate a switch and return {"from", "to", "changes", "proration"}. Raises SwitchError."""
    if interval not in pricing.INTERVALS:
        raise SwitchError(400, "invalid", "interval must be month or year")
    if pricing.unit_prices(target).get(interval) is None:
        raise SwitchError(400, "invalid", f"{target.name} is not sold {'monthly' if interval == 'month' else 'yearly'}")
    used = seats_used(org)
    if target.per_workspace:
        cap = target.included_seats
        if cap is not None and used > cap:
            raise SwitchError(
                409, "seat_limit", f"{target.name} includes up to {cap} people and you have {used}. Remove people first or keep a per-person plan.", seats=cap, used=used
            )
        seats = cap or max(used, 1)
    else:
        try:
            seats = int(seats_value) if seats_value not in (None, "", 0, "0") else max(used, 1)
        except (TypeError, ValueError):
            raise SwitchError(400, "invalid", "seats must be a whole number") from None
        if seats < 1 or seats > pricing.MAX_TEAM:
            raise SwitchError(400, "invalid", "seats must be 1..10000")
        if seats < used:
            raise SwitchError(400, "invalid", f"You have {used} people. Choose at least {used} seats.", used=used)
        cap = target.limit("seats")
        if cap is not None and seats > cap:
            raise SwitchError(400, "invalid", f"{target.name} allows up to {cap} seats.")
    before = None
    if sub is not None and sub.status != "canceled":
        before = describe(sub.plan, sub.interval if sub.interval in pricing.INTERVALS else "month", sub.seats)
        if sub.plan_id == target.pk and before["interval"] == interval and (target.per_workspace or sub.seats == seats):
            raise SwitchError(400, "no_change", "That is already your plan.")
    after = describe(target, interval, seats)
    return {"from": before, "to": after, "changes": changes(before, after), "proration": "stripe" if before else "none", "sample": pricing.is_sample()}


def changes(before, after) -> list[dict]:
    """Plain list of what differs, for the confirmation. Keys are stable; the page words them."""
    if before is None:
        return [{"key": "plan", "from": None, "to": after["name"]}]
    out = []
    for key in ("name", "billing_unit", "interval", "seats", "charge_cents"):
        if before[key] != after[key] or (key == "charge_cents" and before["interval"] != after["interval"]):
            out.append({"key": "plan" if key == "name" else key, "from": before[key], "to": after[key]})
    if before["ai"] != after["ai"]:
        out.append({"key": "ai", "from": before["ai"], "to": after["ai"]})
    if before["overage_policy"] != after["overage_policy"] or before["seat_cap"] != after["seat_cap"]:
        out.append({"key": "seat_cap", "from": before["seat_cap"], "to": after["seat_cap"]})
    return out
