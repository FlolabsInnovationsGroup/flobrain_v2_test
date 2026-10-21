"""Pulse routing applied to platform calls (Phase 13 TECH_DEBT, Decision 20).

Only platform-key calls with no model chosen by the caller are routed. A customer key (BYOK) or
an explicit model is used exactly as given. Candidates are the org's primary model then its
fallbacks, each re-checked against the platform allowlist at call time. The next candidate is
tried only when the provider itself failed (unavailable, 5xx, timeout), never on a refusal or bad
input, so a fallback can't hide a policy decision. Private-only orgs are refused before this runs.

Before calling, candidates are also screened like the Pulse preview: a model with more than half
its calls failing over the last day (at least 5 calls) or a p95 latency above the policy's
threshold is skipped while another candidate is healthy, and a model whose estimated cost for
this request exceeds ``max_task_cost`` is never used. Health is cached for a minute per org.
"""

from decimal import Decimal

from django.core.cache import cache

from brain.llm.providers import ProviderResult

FAILOVER_CODES = {"provider_unavailable", "provider_error"}
MAX_ATTEMPTS = 3


def candidates(org) -> list[str]:
    from brain.llm.direct import allowlist

    if org is None:
        return []
    try:
        policy = org.routing_policy
    except Exception:  # noqa: BLE001 - no policy row
        return []
    allowed = set(allowlist())
    names = ([policy.primary_model] if policy.primary_model else []) + list(policy.fallback_models or [])
    out = []
    for name in names:
        if isinstance(name, str) and name in allowed and name not in out:
            out.append(name)
    return out[:MAX_ATTEMPTS]


EXPECTED_OUTPUT_TOKENS = 800


def _health(org) -> dict:
    key = f"pulse:health:{org.pk}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    from pulse import metrics

    table = {r["model"]: {"error_rate": r["error_rate"] or 0, "calls": r["calls"], "p95": r["latency_p95_ms"]} for r in metrics.models_table(org, 1)}
    cache.set(key, table, 60)
    return table


def estimated_cost(model: str, messages) -> Decimal | None:
    from brain.llm.direct import provider_name
    from telemetry.pricing import estimate_tokens, price_for, prompt_text

    price = price_for(provider_name(), model)
    if price is None:
        return None
    tokens_in = estimate_tokens(prompt_text(messages))
    return (Decimal(tokens_in) * price.input_price + Decimal(EXPECTED_OUTPUT_TOKENS) * price.output_price) / Decimal(1_000_000)


def screen(org, order: list[str], messages) -> tuple[list[str], str]:
    """Drop candidates that are over the cost cap, and prefer healthy ones. Returns (order, error)."""
    policy = getattr(org, "routing_policy", None)
    cap = getattr(policy, "max_task_cost", None)
    if cap is not None:
        affordable = []
        for model in order:
            cost = estimated_cost(model, messages)
            if cost is None or cost <= cap:  # unpriced models can't be judged; they stay
                affordable.append(model)
        if not affordable:
            return [], "cost_limit"
        order = affordable
    health = _health(org)
    threshold = getattr(policy, "latency_threshold_ms", None)

    def unhealthy(model):
        h = health.get(model)
        if not h:
            return False
        if h["calls"] >= 5 and h["error_rate"] > 0.5:
            return True
        return bool(threshold and h["p95"] and h["p95"] > threshold)

    healthy = [m for m in order if not unhealthy(m)]
    return (healthy or order), ""  # all unhealthy: still try them in order rather than fail outright


def complete(call, org, messages, tools=None) -> ProviderResult:
    """``call(messages, model)`` is the single platform call. Returns the last result with
    ``failed_attempts`` set to the results that were skipped over."""
    order = candidates(org)
    if not order:
        return call(messages, None, tools)
    order, error = screen(org, order, messages)
    if error:
        return ProviderResult(text=None, model="", error_code=error, provider="")
    failed = []
    result = None
    for model in order:
        result = call(messages, model, tools)
        if result.ok or result.error_code not in FAILOVER_CODES:
            break
        failed.append(result)
    if result is not None:
        result.failed_attempts = [f for f in failed if f is not result]
    return result
