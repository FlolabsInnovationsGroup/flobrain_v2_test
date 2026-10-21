"""One gate before every model call (Decision 50, Phase 17a).

``check_ai(org, target)`` returns "" when the call may go ahead, or an error
code. In ``private_only`` only self-hosted hosts (``AI_SELF_HOSTED_HOSTS``) may
receive org content: the legacy multimodal host, external provider APIs,
external customer keys and external agents are refused.

Targets:
- ``("direct", None)``: the platform ``direct`` provider (its base URL host is checked)
- ``("byok", credential)``: a customer key (its base URL host is checked)
- ``("legacy", None)``: the multimodal service
- ``("embeddings", None)``: the embeddings endpoint
- ``("external_agent", url)``
"""

import urllib.parse

from django.conf import settings

PRIVATE_ONLY = "private_only"


def self_hosted_hosts() -> set[str]:
    raw = getattr(settings, "AI_SELF_HOSTED_HOSTS", "") or ""
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def plaintext_hosts() -> set[str]:
    """In-cluster model hosts that may be called over plain http (sovereign installs, Phase 17f).

    Empty by default: every model call is https unless the operator lists a host here.
    """
    raw = getattr(settings, "AI_ALLOW_PLAINTEXT_HOSTS", "") or ""
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def forced_private() -> bool:
    return bool(getattr(settings, "AI_FORCE_PRIVATE_ONLY", False))


def _host(url) -> str:
    return (urllib.parse.urlparse(url or "").hostname or "").lower()


def inference_scope(org) -> str:
    if forced_private():
        return PRIVATE_ONLY
    if org is None:
        return "external_allowed"
    from organizations.models import OrgPolicy

    policy = OrgPolicy.objects.filter(org=org).only("inference_scope").first()
    return policy.inference_scope if policy else "external_allowed"


def check_ai(org, kind, target=None) -> str:
    try:  # a pinned data region refuses AI services outside it (market round, einvoice.residency)
        from einvoice.residency import check_ai_residency

        blocked = check_ai_residency(org, kind, target)
    except ImportError:
        blocked = ""
    if blocked:
        return blocked  # "data_region"
    if inference_scope(org) != PRIVATE_ONLY:
        return ""
    private = self_hosted_hosts()
    if kind == "legacy":
        return "private_only"
    if kind == "direct":
        return "" if _host(getattr(settings, "AI_DIRECT_BASE_URL", "")) in private else "private_only"
    if kind == "embeddings":
        return "" if _host(getattr(settings, "EMBEDDINGS_BASE_URL", "")) in private or getattr(settings, "EMBEDDINGS_BACKEND", "") == "fake" else "private_only"
    if kind == "byok":
        return "" if target is not None and _host(target.base_url) in private else "private_only"
    if kind == "external_agent":
        return "private_only"
    return "private_only"
