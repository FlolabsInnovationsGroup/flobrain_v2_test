"""One buddy turn in sandbox mode, for evals.

It builds the same request as ``buddies.chat.run_buddy_turn``: the same base prompt and buddy
instructions, the tools that buddy would be offered for this person (``actions.service.offered_tools``
and external agents), the same model choice (buddy default inside the platform allowlist, budget
downgrade), the same AI policy and budget checks, and the same provider with the org's routing.

What it never does: write a chat message, create an ``ActionProposal`` or an external agent call,
run a tool, send a notification, write memory or answer facts. Tool calls the model makes are
captured as data on the result (``calls``) and checked against the tool's schema, nothing more.
The only row written is the ``UsageEvent`` (surface ``eval``), so evals count against the org's
AI budgets like any other call.

Two deliberate differences, so runs are repeatable and nobody's private context leaks into results
that other admins read: there is no workspace search (a case names the documents it gives the
buddy, and only those the person running it can open are used), and specialists don't get the
runner's personal facts (``templates_extra.context_for``).
"""

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal

from buddies.chat import BUDDY_BASE

BEHAVIOUR_FIELDS = ("system_prompt", "allowed_tools", "default_model", "allowed_sources")


def snapshot(buddy) -> dict:
    """The settings a run uses. ``allowed_sources`` keeps the mode only (room ids are not needed)."""
    return {
        "buddy": str(buddy.id),
        "slug": buddy.slug,
        "name": buddy.name,
        "builtin": bool(buddy.is_builtin),
        "system_prompt": buddy.system_prompt or "",
        "allowed_tools": list(buddy.allowed_tools or []),
        "default_model": buddy.default_model or "",
        "sources": (buddy.allowed_sources or {}).get("mode") or "none",
    }


def fingerprint(config: dict) -> str:
    body = {
        "base": BUDDY_BASE,
        "prompt": config.get("system_prompt", ""),
        "tools": sorted(config.get("allowed_tools") or []),
        "model": config.get("default_model", ""),
        "sources": config.get("sources", "none"),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def as_buddy(config: dict, org):
    """An unsaved Buddy carrying the run's settings (``offered_tools`` reads ``allowed_tools``)."""
    from buddies.models import Buddy

    return Buddy(
        id=config.get("buddy"),
        org=org,
        slug=config.get("slug", ""),
        name=config.get("name", ""),
        is_builtin=bool(config.get("builtin")),
        system_prompt=config.get("system_prompt", ""),
        allowed_tools=list(config.get("allowed_tools") or []),
        default_model=config.get("default_model") or None,
        allowed_sources={"mode": config.get("sources", "none")},
    )


def system_prompt(config: dict) -> str:
    system = BUDDY_BASE
    if (config.get("system_prompt") or "").strip():
        system += "\n\nBuddy instructions:\n" + config["system_prompt"].strip()
    return system


def sources_block(docs) -> str:
    from knowledge.prompting import quote, quote_attr

    parts = [
        f'<source id="{n}" type="document" title="{quote_attr(doc.title)}">\n{quote(doc.content_text[:4000])}\n</source>'
        for n, doc in enumerate(docs, start=1)
    ]
    return "Sources:\n" + "\n\n".join(parts)


def build_messages(config: dict, text: str, docs) -> list:
    messages = [{"role": "system", "content": system_prompt(config)}]
    if docs:
        messages.append({"role": "user", "content": f"{sources_block(docs)}\n\nMessage: {text}"})
    else:
        messages.append({"role": "user", "content": text})
    return messages


@dataclass
class Prepared:
    """What is decided once per run: the tools offered and the model asked for."""

    offered: list = field(default_factory=list)
    tools: list | None = None
    model: str | None = None
    error: str = ""


def prepare(user, org, config: dict) -> Prepared:
    from brain.llm import direct
    from brain.llm.policy import check_ai
    from organizations.flags import effective_flag
    from organizations.models import OrgMembership
    from platform_api import external_agents

    if not direct.is_configured():
        return Prepared(error="not_configured")
    if check_ai(org, "direct"):
        return Prepared(error="private_only")
    buddy = as_buddy(config, org)
    model = (config.get("default_model") or "").strip() or None
    if model and model not in direct.allowlist():
        model = None
    offered = []
    membership = OrgMembership.objects.filter(org=org, user=user).first()
    if buddy.allowed_tools and effective_flag(org, membership, "ai_actions", default=False):
        from actions.service import offered_tools

        offered = offered_tools(user, org, buddy)
    tools = None
    if offered:
        from actions.registry import provider_tools

        tools = provider_tools(offered)
    external = external_agents.offered_tools(user, org)
    if external:
        tools = (tools or []) + external
    return Prepared(offered=offered, tools=tools, model=model)


@dataclass
class Turn:
    text: str = ""
    calls: list = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: Decimal = Decimal("0")
    error: str = ""


def _cost(result) -> Decimal:
    from brain.llm.direct import provider_name
    from telemetry.pricing import price_for

    price = price_for(result.provider or provider_name(), result.model) if result.model else None
    if price is None:
        return Decimal("0")
    return (
        Decimal(result.input_tokens or 0) * price.input_price + Decimal(result.output_tokens or 0) * price.output_price
    ) / Decimal(1_000_000)


def capture(calls, offered) -> list:
    """Model tool calls as data: which tool, validated arguments, and whether it was offered."""
    from actions.registry import TOOLS, tool_key_for
    from actions.schema import SchemaError, validate

    out = []
    for call in calls or []:
        name = str(call.get("name") or "")[:120]
        if name.startswith("ext__"):
            out.append({"tool": name, "external": True, "offered": True, "valid": True})
            continue
        key = tool_key_for(name)
        row = {"tool": key or name, "offered": bool(key and key in offered), "valid": False}
        if key in TOOLS:
            try:
                row["args"] = validate(TOOLS[key]["schema"], json.loads(call.get("arguments") or "{}"))
                row["valid"] = True
            except (ValueError, SchemaError) as exc:
                row["error"] = str(exc)[:200]
        out.append(row)
    return out


def call_model(user, org, messages, *, model=None, tools=None, demo_answer=None) -> tuple:
    """One platform call with the budget check and usage accounting. Returns (result, cost, error)."""
    from brain.llm import demo_ai
    from brain.llm.providers import DirectProvider
    from telemetry.models import UsageEvent
    from telemetry.pricing import budget_decision, fill_missing_tokens, prompt_text
    from telemetry.writers import record_v2_provider_event

    decision = budget_decision(org, user, UsageEvent.CREDENTIAL_PLATFORM)
    if decision.code:
        return None, Decimal("0"), decision.code
    if decision.downgrade_model:
        model = decision.downgrade_model
    result = None
    if demo_answer is not None and demo_ai.enabled():
        result = demo_answer()
    if result is None:
        result = DirectProvider(org).complete(messages, model=model, tools=tools)
    result, estimated = fill_missing_tokens(result, prompt_text(messages), result.text or "")
    record_v2_provider_event(
        user, result, surface="eval", org=org, estimated=estimated, credential_source=UsageEvent.CREDENTIAL_PLATFORM
    )
    return result, _cost(result), ""


def turn(user, org, config: dict, prepared: Prepared, text: str, docs) -> Turn:
    """The buddy's answer to one case. Never persists anything but the usage row."""
    if prepared.error:
        return Turn(error=prepared.error)
    messages = build_messages(config, text, docs)

    def demo_answer():
        from brain.llm.demo_handlers import evals as demo

        return demo.sandbox_answer(config, text, prepared.tools)

    try:
        result, cost, error = call_model(user, org, messages, model=prepared.model, tools=prepared.tools, demo_answer=demo_answer)
    except Exception:  # noqa: BLE001 - one broken call fails one case, not the run
        return Turn(error="provider_error")
    if error:
        return Turn(error=error)
    out = Turn(
        model=result.model or "",
        input_tokens=result.input_tokens or 0,
        output_tokens=result.output_tokens or 0,
        total_tokens=result.total_tokens or 0,
        cost=cost,
    )
    calls = (result.tool_calls or []) if result.ok else []
    out.calls = capture(calls, prepared.offered)
    text_out = result.text or ""
    if calls and not text_out:
        text_out = f"I prepared {len(calls)} action(s) for your approval."
    if not result.ok or not text_out:
        out.error = result.error_code or "provider_error"
        return out
    out.text = text_out[:8000]
    return out
