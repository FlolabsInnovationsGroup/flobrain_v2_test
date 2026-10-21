"""OpenAI-compatible chat client. Tests mock HTTP. Production waits for a secret."""

import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from brain.llm.providers import ProviderResult


def allowlist() -> list[str]:
    raw = getattr(settings, "AI_DIRECT_MODEL_ALLOWLIST", "") or ""
    return [part.strip() for part in raw.split(",") if part.strip()]


def provider_name() -> str:
    return (getattr(settings, "AI_DIRECT_PROVIDER", "") or "").strip() or "openai_compatible"


def _base_is_allowed(base: str) -> bool:
    """HTTPS only, except a local dev server on this machine."""
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme == "https" and parsed.hostname:
        return True
    if parsed.scheme != "http" or not parsed.hostname:
        return False
    from brain.llm.policy import plaintext_hosts

    return parsed.hostname in {"127.0.0.1", "localhost", "::1"} or parsed.hostname.lower() in plaintext_hosts()


def is_configured() -> bool:
    from brain.llm import demo_ai

    if demo_ai.enabled():
        return True
    base = (getattr(settings, "AI_DIRECT_BASE_URL", "") or "").strip()
    key = (getattr(settings, "AI_DIRECT_API_KEY", "") or "").strip()
    return bool(base and key and allowlist() and _base_is_allowed(base))


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
    try:
        value = int(usage[name])
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


MODEL_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:/@")


MAX_TOOL_CALLS = 3


def chat_complete(
    messages: list[dict[str, str]], model: str | None = None, *, credential=None, tools=None
) -> ProviderResult:
    """One POST. 4xx is not retried. Missing config does not open a socket.

    ``credential`` is a customer key (BYOK, Phase 7k) with ``base_url``,
    ``api_key()`` and ``provider``. With it, the platform key and allowlist are
    not used, and nothing falls back to the platform when the call fails.
    """
    if credential is not None:
        from integrations.credentials import is_demo

        if is_demo(credential):
            # The demo provider key (demo mode only): the built-in demo model, never the network.
            from django.conf import settings as dj_settings

            from brain.llm import demo_ai

            if not getattr(dj_settings, "DEMO_MODE", False):
                return ProviderResult(text=None, model=model or "", error_code="credential_unavailable", provider=credential.provider)
            return demo_ai.reply(messages, tools)
        chosen = (model or "").strip()
        provider = credential.provider
        if not chosen or len(chosen) > 128 or not set(chosen) <= MODEL_NAME_CHARS:
            return ProviderResult(text=None, model=chosen, error_code="invalid", provider=provider)
        from integrations.crypto import CredentialCryptoError

        try:
            key = credential.api_key()
        except CredentialCryptoError:
            return ProviderResult(text=None, model=chosen, error_code="credential_unavailable", provider=provider)
        return _post_chat(credential.base_url.rstrip("/"), key, chosen, messages, provider, customer=True, tools=tools)
    from brain.llm import demo_ai

    if demo_ai.enabled():
        return demo_ai.reply(messages, tools)
    if not is_configured():
        return ProviderResult(text=None, model=model or "", error_code="not_configured", provider=provider_name())
    allowed = allowlist()
    chosen = (model or getattr(settings, "AI_DIRECT_DEFAULT_MODEL", "") or "").strip() or allowed[0]
    if chosen not in allowed:
        return ProviderResult(text=None, model=chosen, error_code="invalid", provider=provider_name())
    return _post_chat(
        settings.AI_DIRECT_BASE_URL.rstrip("/"), settings.AI_DIRECT_API_KEY, chosen, messages, provider_name(), tools=tools
    )


def _tool_calls(message: dict) -> list[dict]:
    """OpenAI-style tool calls as [{"name", "arguments"}] (arguments is the raw JSON string)."""
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return []
    out = []
    for call in calls[:MAX_TOOL_CALLS]:
        fn = call.get("function") if isinstance(call, dict) else None
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            args = fn.get("arguments")
            out.append({"name": fn["name"], "arguments": args if isinstance(args, str) else json.dumps(args or {})})
    return out


def _post_chat(
    base: str, api_key: str, chosen: str, messages, provider: str, customer: bool = False, tools=None
) -> ProviderResult:
    body = {"model": chosen, "messages": messages}
    if tools:
        body["tools"] = tools
    payload = json.dumps(body).encode()
    request = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    timeout = int(getattr(settings, "AI_DIRECT_TIMEOUT", 60) or 60)
    if customer:
        from brain.llm.http import open_customer as opener
    else:
        opener = urllib.request.urlopen
    try:
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return ProviderResult(text=None, model=chosen, error_code=_status_code(exc.code), provider=provider)
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, http.client.HTTPException, OSError):
        return ProviderResult(text=None, model=chosen, error_code="provider_unavailable", provider=provider)
    if not isinstance(data, dict):
        return ProviderResult(text=None, model=chosen, error_code="provider_error", provider=provider)

    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    text = ""
    calls = []
    if choices and isinstance(choices[0], dict) and isinstance(choices[0].get("message"), dict):
        content = choices[0]["message"].get("content")
        text = content.strip() if isinstance(content, str) else ""
        if tools:
            calls = _tool_calls(choices[0]["message"])
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    if not text and not calls:
        return ProviderResult(text=None, model=data.get("model") or chosen, error_code="provider_error", provider=provider)
    input_tokens = _token(usage, "prompt_tokens")
    output_tokens = _token(usage, "completion_tokens")
    total_tokens = _token(usage, "total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return ProviderResult(
        text=text,
        model=data.get("model") or chosen,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        provider=provider,
        tool_calls=calls,
    )
