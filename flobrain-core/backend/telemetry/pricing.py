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


def fill_missing_tokens(result, text: str):
    if result.total_tokens is not None:
        return result, False
    estimated = estimate_tokens(text)
    if estimated is None:
        return result, False
    result.total_tokens = estimated
    if result.input_tokens is None:
        result.input_tokens = estimated
    return result, True


def price_for(provider: str, model: str, when=None):
    when = when or timezone.now()
    return (
        PriceTable.objects.filter(provider=provider, model=model, valid_from__lte=when)
        .order_by("-valid_from")
        .first()
    )


def money_for_event(row) -> Decimal | None:
    if row.credential_source != UsageEvent.CREDENTIAL_PLATFORM:
        return None
    price = price_for(row.provider or "platform", row.model or "", row.created_at)
    if price is None or row.total_tokens is None:
        return None
    per_million = price.input_price
    return (Decimal(row.total_tokens) / Decimal("1000000")) * per_million


def month_spend(org) -> Decimal:
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = Decimal("0")
    rows = UsageEvent.objects.filter(
        org=org,
        credential_source=UsageEvent.CREDENTIAL_PLATFORM,
        created_at__gte=start,
    )
    for row in rows:
        amount = money_for_event(row)
        if amount is not None:
            total += amount
    return total


def budgets_on(org, user) -> bool:
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    return effective_flag(org, membership, "budgets", default=False)


def platform_budget_blocks(org, user, credential_source: str) -> str:
    """Return an error code when a platform call would exceed the cap. Empty means allowed."""
    if credential_source != UsageEvent.CREDENTIAL_PLATFORM:
        return ""
    if not budgets_on(org, user):
        return ""
    budget = Budget.objects.filter(org=org, period=Budget.PERIOD_MONTH).first()
    if budget is None:
        return ""
    if month_spend(org) >= budget.cap_amount:
        return "budget_exceeded"
    return ""
