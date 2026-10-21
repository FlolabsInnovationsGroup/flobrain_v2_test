"""OpenAI-compatible chat client. Tests mock HTTP. Production waits for a secret."""

import json
import socket
import urllib.error
import urllib.request

from django.conf import settings

from brain.llm.providers import ProviderResult


def allowlist() -> list[str]:
    raw = getattr(settings, "AI_DIRECT_MODEL_ALLOWLIST", "") or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def is_configured() -> bool:
    base = (getattr(settings, "AI_DIRECT_BASE_URL", "") or "").strip()
    key = (getattr(settings, "AI_DIRECT_API_KEY", "") or "").strip()
    return bool(base and key and allowlist())


def _status_code(code: int) -> str:
    if code == 400:
        return "invalid"
    if code in (401, 403):
        return "invalid_credential"
    if code == 429:
        return "rate_limited"
    if 400 <= code < 500:
        return "provider_rejected"
    return "provider_unavailable"


def _token(usage: dict, name: str):
    if name not in usage or usage.get(name) is None:
        return None
    return int(usage[name])


def chat_complete(messages: list[dict[str, str]], model: str | None = None) -> ProviderResult:
    """One POST. 4xx is not retried. Missing config does not open a socket."""
    if not is_configured():
        return ProviderResult(text=None, model=model or "", error_code="not_configured")
    allowed = allowlist()
    chosen = (model or getattr(settings, "AI_DIRECT_DEFAULT_MODEL", "") or "").strip() or allowed[0]
    if chosen not in allowed:
        return ProviderResult(text=None, model=chosen, error_code="invalid")

    base = settings.AI_DIRECT_BASE_URL.rstrip("/")
    payload = json.dumps({"model": chosen, "messages": messages}).encode()
    request = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.AI_DIRECT_API_KEY}",
        },
        method="POST",
    )
    timeout = int(getattr(settings, "AI_DIRECT_TIMEOUT", 60) or 60)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return ProviderResult(text=None, model=chosen, error_code=_status_code(exc.code))
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        return ProviderResult(text=None, model=chosen, error_code="provider_unavailable")

    choices = data.get("choices") or []
    text = ""
    if choices:
        text = ((choices[0].get("message") or {}).get("content") or "").strip()
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    if not text:
        return ProviderResult(text=None, model=data.get("model") or chosen, error_code="provider_error")
    return ProviderResult(
        text=text,
        model=data.get("model") or chosen,
        input_tokens=_token(usage, "prompt_tokens"),
        output_tokens=_token(usage, "completion_tokens"),
        total_tokens=_token(usage, "total_tokens"),
    )
