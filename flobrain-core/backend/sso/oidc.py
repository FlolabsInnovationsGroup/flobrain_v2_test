"""OIDC authorization-code flow with PKCE, state and nonce (Phase 17c).

All IdP traffic uses the SSRF-safe pinned client. The ID token is verified:
signature against the issuer's JWKS (RS256/ES256 only), ``iss``, ``aud``,
``exp``/``iat``, ``nonce``, and ``email_verified``.
"""

import base64
import hashlib
import hmac
import json
import secrets
import urllib.parse
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

from integrations import crypto
from platform_api import net
from sso.models import SSOLoginCode, SSOState

ALGORITHMS = ["RS256", "ES256"]


class OIDCError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _get_json(url):
    status, body = net.fetch("GET", url, headers={"Accept": "application/json"}, max_bytes=512 * 1024)
    if status != 200:
        raise OIDCError("idp_error")
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise OIDCError("idp_bad_json") from exc
    if not isinstance(data, dict):
        raise OIDCError("idp_bad_json")
    return data


def discover(issuer) -> dict:
    """Fetch and check the discovery document. The issuer must match exactly."""
    issuer = issuer.rstrip("/")
    doc = _get_json(f"{issuer}/.well-known/openid-configuration")
    if (doc.get("issuer") or "").rstrip("/") != issuer:
        raise OIDCError("issuer_mismatch")
    out = {}
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = doc.get(key)
        if not isinstance(value, str) or not value.startswith("https://"):
            raise OIDCError("discovery_incomplete")
        out[key] = value
    return out


def redirect_uri() -> str:
    base = (getattr(settings, "PUBLIC_API_BASE_URL", "") or "http://localhost:8000").rstrip("/")
    return f"{base}/api/v2/sso/callback"


def client_hash(client_nonce) -> str:
    return hashlib.sha256(("sso-client:" + (client_nonce or "")).encode()).hexdigest()


def start(connection, client_nonce) -> str:
    """``client_nonce`` is a random value the starting browser keeps (sessionStorage); the
    one-time code is only redeemable with it, so a link from someone else cannot sign you in."""
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    row = SSOState(
        connection=connection,
        state_hash=hashlib.sha256(state.encode()).hexdigest(),
        nonce=nonce,
        client_hash=client_hash(client_nonce),
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    row.verifier_ciphertext = crypto.encrypt(verifier, row.id, connection.org_id)
    row.key_version = crypto.current_key_version()
    row.save()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": connection.client_id,
            "redirect_uri": redirect_uri(),
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{connection.metadata['authorization_endpoint']}?{query}"


def _claim_state(state):
    digest = hashlib.sha256((state or "").encode()).hexdigest()
    row = SSOState.objects.select_related("connection", "connection__org").filter(state_hash=digest, used_at__isnull=True).first()
    if row is None or row.expires_at <= timezone.now():
        raise OIDCError("invalid_state")
    if not SSOState.objects.filter(pk=row.pk, used_at__isnull=True).update(used_at=timezone.now()):
        raise OIDCError("invalid_state")
    return row


def _verify_id_token(connection, id_token, nonce):
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise OIDCError("bad_id_token") from exc
    if header.get("alg") not in ALGORITHMS:
        raise OIDCError("bad_alg")
    jwks = _get_json(connection.metadata["jwks_uri"]).get("keys") or []
    key = next((k for k in jwks if isinstance(k, dict) and k.get("kid") == header.get("kid")), None)
    if key is None:
        raise OIDCError("unknown_key")
    try:
        signing_key = jwt.PyJWK(key).key
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=ALGORITHMS,
            audience=connection.client_id,
            issuer=connection.issuer.rstrip("/"),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=60,
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise OIDCError("bad_id_token") from exc
    if claims.get("nonce") != nonce:
        raise OIDCError("bad_nonce")
    if claims.get("email_verified") is not True or not isinstance(claims.get("email"), str):
        raise OIDCError("email_not_verified")
    return claims


def finish(state, code):
    """Return (user, org, client_hash) for a valid callback, or raise OIDCError."""
    row = _claim_state(state)
    connection = row.connection
    if not connection.enabled or connection.protocol != connection.PROTOCOL_OIDC:
        raise OIDCError("disabled")
    verifier = crypto.decrypt(row.verifier_ciphertext, row.id, connection.org_id, row.key_version)
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
            "client_id": connection.client_id,
            "client_secret": connection.client_secret(),
            "code_verifier": verifier,
        }
    ).encode()
    status, raw = net.fetch(
        "POST",
        connection.metadata["token_endpoint"],
        body,
        {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        max_bytes=256 * 1024,
    )
    if status != 200:
        raise OIDCError("token_exchange_failed")
    try:
        tokens = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise OIDCError("token_exchange_failed") from exc
    if not isinstance(tokens, dict) or not isinstance(tokens.get("id_token"), str):
        raise OIDCError("no_id_token")
    claims = _verify_id_token(connection, tokens["id_token"], row.nonce)
    return member_for(connection, claims["email"]), connection.org, row.client_hash


def member_for(connection, email):
    """The rules every SSO protocol shares once the IdP has vouched for ``email``."""
    from organizations.models import OrgMembership
    from users.models import User

    email = email.strip().lower()
    domain = email.rsplit("@", 1)[-1]
    if domain not in [d.lower() for d in connection.verified_domains]:
        raise OIDCError("domain_not_verified")  # this IdP can only sign in this org's verified domains
    user = User.objects.filter(email__iexact=email).first()
    membership = OrgMembership.objects.filter(org=connection.org, user=user).first() if user else None
    if membership is None or not membership.is_active_member:
        raise OIDCError("not_a_member")  # SSO never creates accounts; SCIM does
    if user.is_platform_admin:
        raise OIDCError("platform_admin")  # an org's IdP must never mint platform-wide access
    return user


def issue_login_code(user, org, client) -> str:
    code = secrets.token_urlsafe(32)
    SSOLoginCode.objects.create(
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        user=user,
        org=org,
        client_hash=client,
        expires_at=timezone.now() + timedelta(minutes=2),
    )
    return code


def redeem_login_code(code, client_nonce):
    digest = hashlib.sha256((code or "").encode()).hexdigest()
    row = SSOLoginCode.objects.select_related("user").filter(code_hash=digest, used_at__isnull=True).first()
    if row is None or row.expires_at <= timezone.now():
        return None
    if not row.client_hash or not hmac.compare_digest(row.client_hash, client_hash(client_nonce)):
        return None
    if not SSOLoginCode.objects.filter(pk=row.pk, used_at__isnull=True).update(used_at=timezone.now()):
        return None
    return row.user
