"""BYOK rules (Phase 7k): who sees which key, where a key may be sent, and the check.

- A personal key is visible and usable only by its owner. Everyone else,
  owners and admins included, gets 404.
- An org key is visible and usable by holders of ``credential.manage``
  (owner and admin by default). Members get 403 on writes and do not see it.
- A key is sent only over HTTPS to a host in ``BYOK_ALLOWED_HOSTS``, so a
  customer cannot point the server at an internal address.
- No silent fallback: a key that is not ``active`` is refused, never swapped
  for the platform key.
"""

import http.client
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.utils import timezone

from brain.llm.http import open_customer
from integrations.models import AICredential
from organizations.permissions import can

logger = logging.getLogger(__name__)

PROVIDER_DEFAULT_BASE = {
    "openai": "https://api.openai.com",
}
PROVIDERS = ("openai", "openai_compatible")
# Demo mode only: a stand-in key served by the built-in demo model. Never reaches a network.
DEMO_PROVIDER = "demo"
DEMO_BASE_URL = "https://demo-provider.flobrain.example"


def demo_provider_enabled() -> bool:
    from brain.llm import demo_ai

    return demo_ai.enabled()


def providers() -> tuple[str, ...]:
    return PROVIDERS + ((DEMO_PROVIDER,) if demo_provider_enabled() else ())


def is_demo(credential) -> bool:
    return credential.provider == DEMO_PROVIDER


def allowed_hosts() -> set[str]:
    raw = getattr(settings, "BYOK_ALLOWED_HOSTS", "") or ""
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def normalize_base_url(provider: str, base_url: str) -> str | None:
    """Return ``https://host`` when the base is allowed, else None."""
    if provider == DEMO_PROVIDER:
        return DEMO_BASE_URL if demo_provider_enabled() else None
    base = (base_url or "").strip() or PROVIDER_DEFAULT_BASE.get(provider, "")
    if not base:
        return None
    parsed = urllib.parse.urlparse(base)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return None
    if parsed.port not in (None, 443):
        return None
    if parsed.path not in ("", "/", "/v1", "/v1/") or parsed.query or parsed.fragment:
        return None
    if host not in allowed_hosts():
        return None
    return f"https://{host}"


def can_manage_org_keys(user, org) -> bool:
    return can(user, "credential.manage", org)


def visible_credentials(user, org):
    qs = AICredential.objects.filter(org=org)
    if can_manage_org_keys(user, org):
        from django.db.models import Q

        return qs.filter(Q(owner=user) | Q(owner__isnull=True))
    return qs.filter(owner=user)


def mark_expired(credential) -> None:
    if (
        credential.expires_at
        and credential.expires_at <= timezone.now()
        and credential.status != AICredential.STATUS_EXPIRED
    ):
        credential.status = AICredential.STATUS_EXPIRED
        credential.save(update_fields=["status", "updated_at"])


def check_credential(credential) -> AICredential:
    """Minimal live check: ``GET {base}/v1/models``. Mocked in tests.

    2xx → active; 401/403 and other 4xx → rejected; 429, 5xx, timeout or network
    error → indeterminate. A failed check never marks the key active.
    """
    from integrations.crypto import CredentialCryptoError

    mark_expired(credential)
    if credential.status in (AICredential.STATUS_EXPIRED, AICredential.STATUS_DISABLED):
        return credential
    status, error = AICredential.STATUS_INDETERMINATE, "provider_unavailable"
    try:
        key = credential.api_key()
    except CredentialCryptoError:
        status, error = AICredential.STATUS_INDETERMINATE, "decrypt_failed"
        key = None
    if key is not None and is_demo(credential):
        # Demo mode only: the demo provider accepts any key and is never called over the network.
        status, error = (AICredential.STATUS_ACTIVE, "") if demo_provider_enabled() else (AICredential.STATUS_REJECTED, "provider_rejected")
        key = None
    if key is not None:
        request = urllib.request.Request(
            f"{credential.base_url.rstrip('/')}/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            method="GET",
        )
        timeout = int(getattr(settings, "BYOK_CHECK_TIMEOUT", 20) or 20)
        try:
            with open_customer(request, timeout=timeout) as response:
                json.loads(response.read().decode("utf-8") or "{}")
            status, error = AICredential.STATUS_ACTIVE, ""
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                status, error = AICredential.STATUS_REJECTED, "invalid_credential"
            elif exc.code == 429:
                status, error = AICredential.STATUS_INDETERMINATE, "rate_limited"
            elif 400 <= exc.code < 500:
                status, error = AICredential.STATUS_REJECTED, "provider_rejected"
            else:
                status, error = AICredential.STATUS_INDETERMINATE, "provider_unavailable"
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError, http.client.HTTPException, OSError):
            status, error = AICredential.STATUS_INDETERMINATE, "provider_unavailable"
    credential.status = status
    credential.last_error = error
    credential.last_checked_at = timezone.now()
    credential.save(update_fields=["status", "last_error", "last_checked_at", "updated_at"])
    logger.info("BYOK check %s: %s %s", credential.id, status, error)  # never the key
    return credential


def resolve_for_use(user, org, credential_id):
    """Return (credential, error_code). error_code is "not_found" or "credential_not_active"."""
    credential = visible_credentials(user, org).filter(pk=credential_id).first()
    if credential is None:
        return None, "not_found"
    mark_expired(credential)
    if credential.status != AICredential.STATUS_ACTIVE:
        return None, "credential_not_active"
    if normalize_base_url(credential.provider, credential.base_url) is None:
        return None, "credential_not_active"  # host was removed from the allowlist
    return credential, ""


def private_only_blocks(org, provider: str, base_url: str) -> bool:
    """True when the org's sovereign policy refuses a key for this host (Decision 50)."""
    from types import SimpleNamespace

    from brain.llm.policy import check_ai

    return bool(check_ai(org, "byok", SimpleNamespace(provider=provider, base_url=base_url)))


def payload(credential) -> dict:
    return {
        "id": str(credential.id),
        "demo": is_demo(credential),
        "scope": credential.scope,
        "provider": credential.provider,
        "base_url": credential.base_url,
        "label": credential.label,
        "last4": credential.last4,
        "status": credential.status,
        "last_error": credential.last_error,
        "last_checked_at": credential.last_checked_at.isoformat() if credential.last_checked_at else None,
        "expires_at": credential.expires_at.isoformat() if credential.expires_at else None,
        "created_at": credential.created_at.isoformat(),
    }
