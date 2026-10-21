"""V2 provider selection. V1 keeps calling MultimodalLLMAdapter.generate()."""

from dataclasses import dataclass

from django.conf import settings

from brain.llm.multimodal_adapter import MultimodalLLMAdapter

ECHO_PREFIX = "Perception system temporarily unavailable. Echoing input"


@dataclass
class ProviderResult:
    text: str | None
    model: str
    error_code: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    file_type: str = "text"

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
            )
        return ProviderResult(
            text=body,
            model=result.model,
            total_tokens=result.total_tokens if result.tokens_known else None,
            file_type=result.file_type,
        )


class DirectProvider:
    """OpenAI-compatible client. Missing config returns not_configured and does not open a socket."""

    def complete(self, messages: list[dict[str, str]], model: str | None = None) -> ProviderResult:
        from brain.llm.direct import chat_complete

        return chat_complete(messages, model=model)


def get_provider():
    backend = getattr(settings, "AI_PROVIDER_BACKEND", "") or "multimodal_legacy"
    if backend == "direct":
        return DirectProvider()
    return LegacyMultimodalProvider()
