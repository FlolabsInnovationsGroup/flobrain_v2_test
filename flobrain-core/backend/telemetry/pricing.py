from decimal import Decimal

from django.utils import timezone

from organizations.flags import effective_flag
from organizations.models import OrgMembership
from telemetry.models import Budget, PriceTable, UsageEvent


def estimate_tokens(text: str) -> int:
    """Tokenizer estimate when the provider returns no count. Never returns 0 for non-empty text."""
    raw = text or ""
    if not raw.strip():
        return None
    try:
        import tiktoken

        count = len(tiktoken.get_encoding("cl100k_base").encode(raw))
    except Exception:
        count = (len(raw) + 3) // 4
    return max(1, count)


def fill_missing_tokens(result, prompt_text: str, output_text: str = ""):
    """Estimate token counts the provider did not return. Returns (result, estimated).

    Input is estimated from the whole prompt (system + history + new message),
    output from the reply text. Measured counts are never overwritten.
    """
    if result.total_tokens is not None:
        return result, False
    est_in = result.input_tokens if result.input_tokens is not None else estimate_tokens(prompt_text)
    est_out = result.output_tokens if result.output_tokens is not None else estimate_tokens(output_text)
    if est_in is None and est_out is None:
        return result, False
    result.input_tokens = est_in
    result.output_tokens = est_out
    result.total_tokens = (est_in or 0) + (est_out or 0)
    return result, True


def prompt_text(messages) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages or [])


def price_for(provider: str, model: str, when=None, unit=PriceTable.UNIT_MTOK):
    when = when or timezone.now()
    return (
        PriceTable.objects.filter(provider=provider, model=model, unit=unit, valid_from__lte=when)
        .order_by("-valid_from")
        .first()
    )


class PriceBook:
    """Price lookups for many rows with one query per (provider, model, unit)."""

    def __init__(self):
        self._rows = {}

    def find(self, provider, model, when, unit=PriceTable.UNIT_MTOK):
        key = (provider or "", model or "", unit)
        if key not in self._rows:
            self._rows[key] = list(
                PriceTable.objects.filter(provider=key[0], model=key[1], unit=unit).order_by("-valid_from")
            )
        for row in self._rows[key]:
            if row.valid_from <= when:
                return row
        return None


def _amount(row, price) -> Decimal | None:
    million = Decimal("1000000")
    if row.input_tokens is not None or row.output_tokens is not None:
        amount = Decimal(row.input_tokens or 0) * price.input_price + Decimal(row.output_tokens or 0) * price.output_price
        return amount / million
    if row.total_tokens is None:
        return None
    return Decimal(row.total_tokens) * max(price.input_price, price.output_price) / million


def money_for_event(row, book: PriceBook | None = None) -> Decimal | None:
    """Platform cost of one usage row. Prices are per million tokens. None when no price applies.

    When only a total is known (no input/output split), the higher of the two
    prices is used so a budget never under-counts spend.
    """
    if row.credential_source != UsageEvent.CREDENTIAL_PLATFORM:
        return None
    if book is not None:
        price = book.find(row.provider, row.model, row.created_at)
    else:
        price = price_for(row.provider or "", row.model or "", row.created_at)
    if price is None:
        return None
    return _amount(row, price)


def money_for_render(job, book: PriceBook | None = None) -> Decimal | None:
    """GPU cost of one render (``gpu_seconds`` x the ``gpu/render`` per-second price). None when unpriced."""
    seconds = getattr(job, "gpu_seconds", None) or 0
    if seconds <= 0:
        return None
    when = job.finished_at or job.queued_at or timezone.now()
    book = book or PriceBook()
    price = book.find(PriceTable.GPU_PROVIDER, PriceTable.GPU_MODEL, when, unit=PriceTable.UNIT_GPU_SECOND)
    if price is None:
        return None
    return Decimal(str(seconds)) * price.input_price


def period_start(now=None):
    now = now or timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def period_key(now=None) -> str:
    return (now or timezone.now()).strftime("%Y-%m")


def _team_member_ids(team):
    from organizations.models import TeamMembership

    return list(TeamMembership.objects.filter(team=team).values_list("user_id", flat=True))


def scope_spend(org, scope_type="org", scope_id=None, since=None, book: PriceBook | None = None) -> Decimal:
    """Platform spend this period for the org, one team or one member, plus priced GPU renders.

    Team spend: usage rows tagged with the team, plus untagged rows of its current members.
    """
    from django.db.models import Q

    since = since or period_start()
    book = book or PriceBook()
    rows = UsageEvent.objects.filter(
        org=org, credential_source=UsageEvent.CREDENTIAL_PLATFORM, created_at__gte=since
    ).only("provider", "model", "input_tokens", "output_tokens", "total_tokens", "credential_source", "created_at")
    renders = None
    try:
        from content_studio.models import RenderJob

        renders = RenderJob.objects.filter(org=org, gpu_seconds__gt=0, queued_at__gte=since).only(
            "gpu_seconds", "finished_at", "queued_at"
        )
    except Exception:  # noqa: BLE001 - Content Studio not installed
        renders = None
    if scope_type == Budget.SCOPE_USER:
        rows = rows.filter(user_id=scope_id)
        renders = renders.filter(requested_by_id=scope_id) if renders is not None else None
    elif scope_type == Budget.SCOPE_TEAM:
        from organizations.models import Team

        team = Team.objects.filter(org=org, pk=scope_id).first()
        members = _team_member_ids(team) if team else []
        rows = rows.filter(Q(team_id=scope_id) | Q(team__isnull=True, user_id__in=members))
        renders = renders.filter(requested_by_id__in=members) if renders is not None else None
    total = Decimal("0")
    for row in rows:
        amount = money_for_event(row, book)
        if amount is not None:
            total += amount
    for job in renders if renders is not None else []:
        amount = money_for_render(job, book)
        if amount is not None:
            total += amount
    return total


def month_spend(org) -> Decimal:
    return scope_spend(org, Budget.SCOPE_ORG)


def budget_spend(budget, book: PriceBook | None = None) -> Decimal:
    return scope_spend(budget.org, budget.scope_type, budget.scope_id, book=book)


def budgets_on(org, user) -> bool:
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return effective_flag(org, membership, "budgets", default=False)


def applicable_budgets(org, user, team=None):
    """The org budget, this member's budget, and budgets of their teams (or of ``team``)."""
    from django.db.models import Q

    from organizations.models import TeamMembership

    team_ids = [team.id] if team is not None else list(
        TeamMembership.objects.filter(team__org=org, user=user).values_list("team_id", flat=True)
    )
    rule = Q(scope_type=Budget.SCOPE_ORG)
    if user is not None:
        rule |= Q(scope_type=Budget.SCOPE_USER, scope_id=user.id)
    if team_ids:
        rule |= Q(scope_type=Budget.SCOPE_TEAM, scope_id__in=team_ids)
    return list(Budget.objects.filter(org=org, period=Budget.PERIOD_MONTH).filter(rule))


SCOPE_ORDER = {Budget.SCOPE_USER: 0, Budget.SCOPE_TEAM: 1, Budget.SCOPE_ORG: 2}


class BudgetDecision:
    """``code`` is "budget_exceeded" when a blocking budget is used up. ``downgrade_model`` is set when
    a downgrade budget is used up (and no blocking one is): callers that can switch models use it."""

    def __init__(self, code="", downgrade_model="", budget=None):
        self.code, self.downgrade_model, self.budget = code, downgrade_model, budget

    def __bool__(self):
        return bool(self.code)


def state_for(budget, spent) -> str:
    limit = budget.cap_amount
    if spent >= limit:
        return "exceeded"
    if limit > 0 and spent >= limit * budget.alert_threshold:
        return "alert"
    return "ok"


def scope_label(budget) -> str:
    if budget.scope_type == Budget.SCOPE_TEAM:
        from organizations.models import Team

        team = Team.objects.filter(pk=budget.scope_id).only("name").first()
        return team.name if team else "a team"
    if budget.scope_type == Budget.SCOPE_USER:
        from users.models import User

        user = User.objects.filter(pk=budget.scope_id).only("username", "email").first()
        return (user.username or user.email) if user else "a member"
    return budget.org.name


def maybe_alert(budget, spent, now=None) -> bool:
    """Notify owners and admins once per period when spend reaches the alert threshold."""
    if budget.cap_amount <= 0 or spent < budget.cap_amount * budget.alert_threshold:
        return False
    key = period_key(now)
    if budget.alerted_period == key:
        return False
    claimed = Budget.objects.filter(pk=budget.pk).exclude(alerted_period=key).update(alerted_period=key)
    budget.alerted_period = key
    if not claimed:
        return False  # someone else sent this period's alert
    from notifications.services import notify

    admins = OrgMembership.objects.filter(
        org=budget.org, org_role__in=[OrgMembership.ORG_ROLE_OWNER, OrgMembership.ORG_ROLE_ADMIN]
    ).values_list("user_id", flat=True)
    percent = int((spent / budget.cap_amount) * 100) if budget.cap_amount else 0
    label = scope_label(budget)
    notify(
        budget.org,
        list(admins),
        "budget_alert",
        {
            "text": f"AI budget for {label} is at {percent}%",
            "budget": str(budget.id),
            "scope_type": budget.scope_type,
            "scope": label,
            "percent": percent,
            "spent": str(spent.quantize(Decimal("0.01"))),
            "limit": str(budget.cap_amount.quantize(Decimal("0.01"))),
            "currency": budget.currency,
            "period": key,
        },
        link="settings/budgets",
    )
    return True


def check_alerts(org) -> int:
    """Evaluate every budget of the org for its alert (idempotent per period). Returns alerts sent."""
    book = PriceBook()
    sent = 0
    for budget in Budget.objects.filter(org=org).select_related("org"):
        sent += maybe_alert(budget, budget_spend(budget, book))
    return sent


def budget_decision(org, user, credential_source: str, team=None) -> BudgetDecision:
    """What the budgets say about one platform call by ``user``. BYOK calls are never metered."""
    if credential_source != UsageEvent.CREDENTIAL_PLATFORM:
        return BudgetDecision()
    if not budgets_on(org, user):
        return BudgetDecision()
    budgets = applicable_budgets(org, user, team)
    if not budgets:
        return BudgetDecision()
    book = PriceBook()
    exceeded = []
    for budget in budgets:
        spent = budget_spend(budget, book)
        try:
            maybe_alert(budget, spent)
        except Exception:  # noqa: BLE001 - an alert must never break the call
            import logging

            logging.getLogger(__name__).exception("budget alert failed")
        if spent >= budget.cap_amount:
            exceeded.append(budget)
    blocking = [b for b in exceeded if b.on_exceed == Budget.ON_BLOCK]
    if blocking:
        return BudgetDecision("budget_exceeded", budget=sorted(blocking, key=lambda b: SCOPE_ORDER[b.scope_type])[0])
    downgrade = sorted(
        (b for b in exceeded if b.on_exceed == Budget.ON_DOWNGRADE and b.downgrade_model),
        key=lambda b: SCOPE_ORDER[b.scope_type],
    )
    if downgrade:
        return BudgetDecision("", downgrade[0].downgrade_model, downgrade[0])
    return BudgetDecision()


def platform_budget_blocks(org, user, credential_source: str) -> str:
    """Return an error code when a platform call would exceed a blocking budget. Empty means allowed.

    Kept for callers that cannot switch models: only ``on_exceed=block`` budgets refuse calls here.
    Callers that can switch to a cheaper model use ``budget_decision`` instead.
    """
    return budget_decision(org, user, credential_source).code
