"""OAuth 2.0 authorization code flow with PKCE (S256) for write-back connectors.

The redirect URI is fixed from settings: ``{PUBLIC_API_BASE_URL}/api/v2/integrations/write/oauth/callback/<provider>``.
State is single use, kept server-side as a SHA-256 hash, and expires after 10 minutes; the PKCE
verifier is stored encrypted next to it and never leaves the server.
"""

import base64
import hashlib
import secrets
import urllib.parse
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from integrations import crypto
from integrations.write.models import WriteOAuthState
from integrations.write.registry import normalize_scope
from integrations.write.transport import Client, WriteError, form, raw_request

STATE_TTL = timedelta(minutes=10)


def redirect_uri(provider_key: str) -> str:
    base = getattr(settings, "PUBLIC_API_BASE_URL", "") or "http://localhost:8000"
    return f"{base.rstrip('/')}/api/v2/integrations/write/oauth/callback/{provider_key}"


def digest(value: str) -> str:
    return hashlib.sha256((value or "").encode()).hexdigest()


def challenge_for(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def start(provider, org, user, personal: bool) -> str:
    """Create the single-use state and return the provider's authorize URL."""
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)[:96]  # RFC 7636: 43 to 128 characters
    row = WriteOAuthState(
        org=org,
        user=user,
        provider=provider.key,
        personal=personal,
        state_hash=digest(state),
        expires_at=timezone.now() + STATE_TTL,
    )
    row.verifier_ciphertext = crypto.encrypt(verifier, f"write-oauth:{row.id}", org.id)
    row.key_version = crypto.current_key_version()
    row.save()
    params = {
        "client_id": provider.client_id(),
        "response_type": "code",
        "redirect_uri": redirect_uri(provider.key),
        "scope": provider.scope_separator.join(provider.scopes()),
        "state": state,
        "code_challenge": challenge_for(verifier),
        "code_challenge_method": "S256",
        **provider.auth_params,
    }
    return f"{provider.resolve(provider.authorize_url)}?{urllib.parse.urlencode(params)}"


def consume(provider_key: str, state: str):
    """Return the open state row for ``state`` and mark it used, or None (unknown, used, expired or raced)."""
    row = WriteOAuthState.objects.filter(state_hash=digest(state), provider=provider_key).select_related("org").first()
    if row is None or row.used_at is not None or row.expires_at <= timezone.now() or not state:
        return None
    if not WriteOAuthState.objects.filter(pk=row.pk, used_at__isnull=True).update(used_at=timezone.now()):
        return None
    return row


def verifier_of(row) -> str:
    return crypto.decrypt(row.verifier_ciphertext, f"write-oauth:{row.id}", row.org_id, row.key_version)


def exchange(provider, code: str, verifier: str) -> dict:
    """Swap the code for tokens and identify the account. Raises WriteError."""
    body, headers = form(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(provider.key),
            "client_id": provider.client_id(),
            "client_secret": provider.client_secret(),
            "code_verifier": verifier,
        }
    )
    status, token = raw_request(provider, "POST", provider.resolve(provider.token_url), body=body, headers=headers)
    access = token.get("access_token") if isinstance(token, dict) else None
    if status != 200 or not isinstance(access, str) or not access:
        raise WriteError("exchange_failed", f"{provider.name} did not accept the sign-in")
    granted = token.get("scope")
    if isinstance(granted, str) and granted.strip():
        scopes = [s for s in granted.replace(",", " ").split() if s]
    else:
        scopes = provider.scopes()
    label, config = ("", {})
    if provider.identify is not None:
        try:
            label, config = provider.identify(Client(provider, token=access), token)
        except ValueError as exc:
            raise WriteError("exchange_failed", str(exc)[:120]) from exc
    return {
        "access_token": access,
        "refresh_token": token.get("refresh_token") if isinstance(token.get("refresh_token"), str) else "",
        "expires_in": token.get("expires_in"),
        "scopes": scopes[:40],
        "label": str(label or provider.name)[:160],
        "config": config if isinstance(config, dict) else {},
    }


def missing_scopes(action, granted) -> list[str]:
    have = {normalize_scope(s) for s in granted or []}
    return [s for s in action.scopes if normalize_scope(s) not in have]
