"""Embedder interface (Decision E31).

Memory code calls ``get_embedder()`` and never names a model. Production uses an
OpenAI-compatible ``POST {base}/v1/embeddings`` endpoint (BGE-M3 on JarvisLabs,
served by vLLM, TEI or similar). Missing config means "Not configured" and no
network call. Tests use ``FakeEmbedder``.
"""

import hashlib
import json
import math
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings

MAX_INPUTS_PER_CALL = 32
MAX_CHARS_PER_INPUT = 8000


class EmbeddingError(Exception):
    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code


@dataclass(frozen=True)
class EmbedderInfo:
    model: str
    dimension: int


class FakeEmbedder:
    """Deterministic unit vectors from a hash. Similar texts are not similar; equal texts are equal."""

    def __init__(self, model: str = "fake-embedder", dimension: int = 1024):
        self.info = EmbedderInfo(model=model, dimension=dimension)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            seed = hashlib.sha256((text or "").encode("utf-8")).digest()
            values = []
            counter = 0
            while len(values) < self.info.dimension:
                block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
                values.extend((b - 127.5) / 127.5 for b in block)
                counter += 1
            values = values[: self.info.dimension]
            norm = math.sqrt(sum(v * v for v in values)) or 1.0
            out.append([v / norm for v in values])
        return out


def _base_is_allowed(base: str) -> bool:
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme == "https" and parsed.hostname:
        return True
    if parsed.scheme != "http" or not parsed.hostname:
        return False
    from brain.llm.policy import plaintext_hosts

    return parsed.hostname in {"127.0.0.1", "localhost", "::1"} or parsed.hostname.lower() in plaintext_hosts()


class HttpEmbedder:
    """OpenAI-compatible embeddings client. One call per batch; 4xx is not retried."""

    def __init__(self, base_url: str, model: str, dimension: int, api_key: str = "", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.info = EmbedderInfo(model=model, dimension=dimension)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) > MAX_INPUTS_PER_CALL:
            raise EmbeddingError("invalid", f"at most {MAX_INPUTS_PER_CALL} inputs per call")
        inputs = [(t or "")[:MAX_CHARS_PER_INPUT] for t in texts]
        body = json.dumps({"model": self.info.model, "input": inputs}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(f"{self.base_url}/v1/embeddings", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code = "invalid_credential" if exc.code in (401, 403) else (
                "rate_limited" if exc.code == 429 else ("provider_rejected" if exc.code < 500 else "provider_unavailable")
            )
            raise EmbeddingError(code, f"embeddings HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError):
            raise EmbeddingError("provider_unavailable", "embeddings server unreachable") from None

        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) != len(inputs):
            raise EmbeddingError("provider_error", "unexpected embeddings response")
        rows = sorted(rows, key=lambda r: r.get("index", 0))
        vectors = []
        for row in rows:
            vec = row.get("embedding")
            if not isinstance(vec, list) or len(vec) != self.info.dimension:
                raise EmbeddingError(
                    "dimension_mismatch",
                    f"expected {self.info.dimension} dimensions, got {len(vec) if isinstance(vec, list) else 'none'}",
                )
            try:
                vectors.append([float(v) for v in vec])
            except (TypeError, ValueError):
                raise EmbeddingError("provider_error", "non-numeric embedding") from None
        return vectors


def get_embedder():
    """The configured embedder, or None when embeddings are not configured."""
    backend = (getattr(settings, "EMBEDDINGS_BACKEND", "") or "").strip()
    dimension = int(getattr(settings, "EMBEDDINGS_DIMENSION", 1024) or 1024)
    if backend == "fake":
        return FakeEmbedder(model=getattr(settings, "EMBEDDINGS_MODEL", "") or "fake-embedder", dimension=dimension)
    if backend != "http":
        return None
    base = (getattr(settings, "EMBEDDINGS_BASE_URL", "") or "").strip()
    model = (getattr(settings, "EMBEDDINGS_MODEL", "") or "").strip()
    if not base or not model or not _base_is_allowed(base):
        return None
    return HttpEmbedder(
        base_url=base,
        model=model,
        dimension=dimension,
        api_key=getattr(settings, "EMBEDDINGS_API_KEY", "") or "",
        timeout=int(getattr(settings, "EMBEDDINGS_TIMEOUT", 30) or 30),
    )
