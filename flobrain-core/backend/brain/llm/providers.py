"""V2 provider selection. V1 keeps calling MultimodalLLMAdapter.generate()."""

from dataclasses import dataclass

from django.conf import settings

from brain.llm.multimodal_adapter import MultimodalLLMAdapter

ECHO_PREFIX = "Perception system temporarily unavailable. Echoing input"
LEGACY_PROVIDER = "multimodal_legacy"


@dataclass
class ProviderResult:
    text: str | None
    model: str
    error_code: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    file_type: str = "text"
    provider: str = ""
    tool_calls: list | None = None  # proposals only; FloBrain never executes these directly
    failed_attempts: list | None = None  # Pulse routing: earlier platform models that failed over

    @property
    def ok(self) -> bool:
        return not self.error_code


class LegacyMultimodalProvider:
    """Wrap today's V1 call. The echo body is an error, and omitted tokens are unknown."""

    def complete(self, messages: list[dict[str, str]], model: str | None = None) -> ProviderResult:
        result = MultimodalLLMAdapter().generate(messages, model=model)
        body = result.generated_response or ""
        if body.startswith(ECHO_PREFIX):
            return ProviderResult(
                text=None,
                model=result.model,
                error_code="provider_error",
                file_type=result.file_type,
                provider=LEGACY_PROVIDER,
            )
        return ProviderResult(
            text=body,
            model=result.model,
            total_tokens=result.total_tokens if result.tokens_known else None,
            file_type=result.file_type,
            provider=LEGACY_PROVIDER,
        )


class DirectProvider:
    """OpenAI-compatible client. Missing config returns not_configured and does not open a socket.

    With ``org`` set, platform calls that don't name a model follow the org's Pulse routing policy
    (``brain.llm.routing``). Customer keys and explicit models are never routed."""

    def __init__(self, org=None):
        self.org = org

    def complete(
        self, messages: list[dict[str, str]], model: str | None = None, credential=None, tools=None
    ) -> ProviderResult:
        from brain.llm.direct import chat_complete

        if credential is not None or model or self.org is None:
            return chat_complete(messages, model=model, credential=credential, tools=tools)
        from brain.llm import routing

        return routing.complete(lambda m, name, t: chat_complete(m, model=name, tools=t), self.org, messages, tools=tools)


def get_provider():
    backend = getattr(settings, "AI_PROVIDER_BACKEND", "") or "multimodal_legacy"
    if backend == "direct":
        return DirectProvider()
    return LegacyMultimodalProvider()
