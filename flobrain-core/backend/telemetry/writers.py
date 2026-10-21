import logging
import uuid

from telemetry.models import AITrace, UsageEvent

logger = logging.getLogger(__name__)


def record_v1_chat(user, chat, llm_result, latency_ms=None):
    """Write UsageEvent + AITrace for a V1 send. Callers must treat failures as best-effort."""
    UsageEvent.objects.create(
        org=None,
        user=user,
        chat=chat,
        provider="",
        model=getattr(llm_result, "model", "") or "",
        operation="chat",
        total_tokens=int(getattr(llm_result, "total_tokens", 0) or 0),
        estimated=False,
        status="ok",
        latency_ms=latency_ms,
    )
    AITrace.objects.create(
        org=None,
        user=user,
        request_id=uuid.uuid4().hex,
        surface="v1_chat",
        model=getattr(llm_result, "model", "") or "",
        latency_ms=latency_ms,
        outcome="completed",
    )


def record_v1_chat_best_effort(user, chat, llm_result, latency_ms=None):
    try:
        record_v1_chat(user, chat, llm_result, latency_ms=latency_ms)
    except Exception:
        logger.exception("Best-effort V1 telemetry write failed")


def record_v2_provider_event(
    user,
    result,
    *,
    surface="room_ai",
    org=None,
    chat=None,
    latency_ms=None,
    estimated=False,
    credential_source=None,
    operation="chat",
    team=None,
):
    """V2 writer. A missing token count is stored as NULL, not 0, unless a later estimate filled it.
    Models that failed over under Pulse routing are recorded as their own error calls.
    ``team`` (for team budgets) defaults to the team of the thread's room."""
    if team is None and chat is not None and getattr(chat, "room_id", None):
        room = getattr(chat, "room", None)
        team = getattr(room, "team", None) if room is not None else None
    for failed in getattr(result, "failed_attempts", None) or []:
        UsageEvent.objects.create(
            org=org,
            user=user,
            chat=chat,
            provider=getattr(failed, "provider", "") or "",
            model=failed.model or "",
            operation=operation,
            credential_source=UsageEvent.CREDENTIAL_PLATFORM,
            status="error",
            error_code=failed.error_code or "",
            surface=surface or "",
            team=team,
        )
    UsageEvent.objects.create(
        org=org,
        user=user,
        chat=chat,
        provider=getattr(result, "provider", "") or "",
        model=result.model or "",
        operation=operation,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        estimated=estimated,
        credential_source=credential_source or UsageEvent.CREDENTIAL_PLATFORM,
        status="ok" if result.ok else "error",
        error_code=result.error_code or "",
        latency_ms=latency_ms,
        surface=surface or "",
        team=team,
    )
    AITrace.objects.create(
        org=org,
        user=user,
        request_id=uuid.uuid4().hex,
        surface=surface,
        model=result.model or "",
        latency_ms=latency_ms,
        outcome=("fallback" if getattr(result, "failed_attempts", None) else "completed") if result.ok else "error",
    )
