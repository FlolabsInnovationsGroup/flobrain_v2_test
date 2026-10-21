"""FloBrain as an OAuth 2.1 authorization server for its remote MCP endpoint (growth round M1).

Follows the MCP authorization spec (2025-06-18, https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization):

- ``/.well-known/oauth-protected-resource[/api/mcp]``: RFC 9728 metadata for the MCP resource. A
  401 from ``/api/mcp`` carries ``WWW-Authenticate: Bearer resource_metadata="…"``.
- ``/.well-known/oauth-authorization-server``: RFC 8414 metadata. The issuer is the API origin.
- ``POST /oauth/register``: dynamic client registration (RFC 7591), rate limited per IP and per
  day. Redirect URIs must be https, or http on a loopback host (localhost, 127.0.0.1, [::1]).
- ``GET /oauth/authorize``: authorization code flow, PKCE S256 only, ``resource`` (RFC 8707)
  must be this MCP endpoint. Sends the person to the consent page in the web app with a signed,
  15-minute request. The consent page calls ``/api/v2/mcp/consent`` (signed-in, JWT).
- ``POST /oauth/token``: code exchange (single use, 5 minutes, exact redirect URI, verifier
  checked) and refresh (rotating; a reused refresh token revokes the whole grant).
- ``POST /oauth/revoke``: RFC 7009.

Access tokens last 1 hour and work only on the resource they were issued for (audience check).
Every secret is stored as a SHA-256 hash. Personal access tokens keep working on ``/api/mcp``.
"""

import base64
import hashlib
import hmac
import ipaddress
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.utils import timezone
from rest_framework import authentication, exceptions
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from core_v2.views import V2APIView
from platform_api.authentication import PATAuthentication
from platform_api.models import (
    OAUTH_ACCESS_PREFIX,
    OAUTH_CLIENT_PREFIX,
    OAUTH_CODE_PREFIX,
    OAUTH_REFRESH_PREFIX,
    OAUTH_SECRET_PREFIX,
    SCOPES,
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthGrant,
    OAuthRefreshToken,
    hash_token,
)

MCP_PATH = "/api/mcp"
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=5)
REQUEST_MAX_AGE = 15 * 60
SIGN_SALT = "flobrain.mcp.oauth.authorize"
MAX_REDIRECT_URIS = 5
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
CHALLENGE_RE = re.compile(r"^[A-Za-z0-9\-_]{43,128}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
# What a person sees on the consent screen for each scope (the web app translates these).
SCOPE_LABELS = {
    "mcp": "Connect to FloBrain's MCP server",
    "tasks:read": "See tasks you can see",
    "tasks:write": "Suggest new tasks (you approve each one)",
    "rooms:read": "See the names of rooms you are in",
    "rooms:write": "Suggest room messages (you approve each one)",
    "time:read": "See your own logged hours",
    "knowledge:read": "Search documents and messages you can read",
    "buddies:read": "Ask your buddies questions (answers only, no actions)",
    "data:read": "Ask questions about datasets you can see",
    "approvals:read": "See what is waiting for your approval",
    "meetings:read": "See summaries of recent meetings you can open",
    "automations:write": "Suggest running a workflow (you approve each run)",
}
DEFAULT_SCOPES = ["mcp"] + [s for s in SCOPES if s.endswith(":read")]


# --- URLs ------------------------------------------------------------------------------


def base_url(request) -> str:
    configured = (getattr(settings, "PUBLIC_API_BASE_URL", "") or "").rstrip("/")
    if configured:
        return configured
    return f"{request.scheme}://{request.get_host()}"


def resource_url(request) -> str:
    return base_url(request) + MCP_PATH


def metadata_url(request) -> str:
    return base_url(request) + "/.well-known/oauth-protected-resource" + MCP_PATH


def canonical(url: str) -> str:
    """RFC 8707 / MCP canonical server URI: lower-case scheme and host, no default port, no
    fragment, no trailing slash."""
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    if not scheme or not host:
        return ""
    port = parts.port
    netloc = host if ":" not in host else f"[{host}]"
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc += f":{port}"
    path = parts.path.rstrip("/") if parts.path not in ("", "/") else ""
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def frontend_consent_url(**params) -> str:
    base = (getattr(settings, "FRONTEND_BASE_URL", "") or "http://localhost:3000").rstrip("/")
    return f"{base}/w/oauth/consent?{urlencode(params)}"


# --- helpers ---------------------------------------------------------------------------


def _client_ip(request) -> str:
    from organizations.flags import client_ip

    return client_ip(request) or ""


def _no_store(response):
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def oauth_error(error, description="", status=400):
    body = {"error": error}
    if description:
        body["error_description"] = description
    return _no_store(JsonResponse(body, status=status))


def valid_redirect_uri(uri) -> bool:
    if not isinstance(uri, str) or not uri or len(uri) > 500 or CONTROL_RE.search(uri):
        return False
    try:
        parts = urlsplit(uri)
        parts.port  # noqa: B018  (raises on a bad port)
    except ValueError:
        return False
    if parts.fragment or not parts.hostname or parts.username or parts.password:
        return False
    if parts.scheme == "https":
        return True
    if parts.scheme == "http":
        host = parts.hostname.lower()
        if host in LOOPBACK:
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False
    return False


def pkce_ok(verifier, challenge) -> bool:
    if not isinstance(verifier, str) or not VERIFIER_RE.match(verifier):
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(digest, challenge or "")


def parse_scopes(raw) -> list[str]:
    wanted = [s for s in str(raw or "").split() if s in SCOPES]
    if not wanted:
        return list(DEFAULT_SCOPES)
    if "mcp" not in wanted:
        wanted.insert(0, "mcp")
    return list(dict.fromkeys(wanted))


def _active_membership(org, user):
    from organizations.models import OrgMembership

    m = OrgMembership.objects.filter(org=org, user=user).first()
    return m if m and m.is_active_member and org.is_active else None


def hub_on(org, membership) -> bool:
    from organizations.flags import effective_flag

    return effective_flag(org, membership, "mcp_hub", default=False)


def revoke_grant(grant, reason):
    now = timezone.now()
    OAuthGrant.objects.filter(pk=grant.pk, revoked_at__isnull=True).update(revoked_at=now, revoked_reason=reason[:40])
    OAuthAccessToken.objects.filter(grant=grant, revoked_at__isnull=True).update(revoked_at=now)
    OAuthRefreshToken.objects.filter(grant=grant, revoked_at__isnull=True).update(revoked_at=now)
    grant.revoked_at = grant.revoked_at or now


def issue_tokens(grant, scopes=None) -> dict:
    scopes = list(scopes or grant.scopes)
    now = timezone.now()
    access = OAUTH_ACCESS_PREFIX + secrets.token_urlsafe(32)
    refresh = OAUTH_REFRESH_PREFIX + secrets.token_urlsafe(32)
    OAuthAccessToken.objects.create(
        token_hash=hash_token(access), grant=grant, user_id=grant.user_id, org_id=grant.org_id, scopes=scopes,
        resource=grant.resource, expires_at=now + ACCESS_TTL,
    )
    OAuthRefreshToken.objects.create(token_hash=hash_token(refresh), grant=grant, expires_at=now + REFRESH_TTL)
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
        "refresh_token": refresh,
        "scope": " ".join(scopes),
    }


# --- throttles -------------------------------------------------------------------------


class _IPThrottle(SimpleRateThrottle):
    setting = ""
    default = "60/min"

    def get_rate(self):
        return getattr(settings, self.setting, self.default)

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class RegisterThrottle(_IPThrottle):
    scope, setting, default = "mcp_oauth_register", "MCP_OAUTH_REGISTER_RATE", "10/hour"


class TokenThrottle(_IPThrottle):
    scope, setting, default = "mcp_oauth_token", "MCP_OAUTH_TOKEN_RATE", "60/min"


class AuthorizeThrottle(_IPThrottle):
    scope, setting, default = "mcp_oauth_authorize", "MCP_OAUTH_AUTHORIZE_RATE", "60/min"


class MetadataThrottle(_IPThrottle):
    scope, setting, default = "mcp_oauth_metadata", "MCP_OAUTH_METADATA_RATE", "120/min"


class _OAuthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [FormParser, JSONParser, MultiPartParser]


# --- metadata --------------------------------------------------------------------------


class ProtectedResourceMetadataView(_OAuthView):
    throttle_classes = [MetadataThrottle]

    def get(self, request):
        return JsonResponse(
            {
                "resource": resource_url(request),
                "authorization_servers": [base_url(request)],
                "scopes_supported": list(SCOPES),
                "bearer_methods_supported": ["header"],
                "resource_name": "FloBrain",
                "resource_documentation": "https://flobrain.ai/docs/mcp",
            }
        )


class AuthorizationServerMetadataView(_OAuthView):
    throttle_classes = [MetadataThrottle]

    def get(self, request):
        base = base_url(request)
        return JsonResponse(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/oauth/authorize",
                "token_endpoint": f"{base}/oauth/token",
                "registration_endpoint": f"{base}/oauth/register",
                "revocation_endpoint": f"{base}/oauth/revoke",
                "scopes_supported": list(SCOPES),
                "response_types_supported": ["code"],
                "response_modes_supported": ["query"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                "revocation_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                "authorization_response_iss_parameter_supported": True,
                "service_documentation": "https://flobrain.ai/docs/mcp",
            }
        )


# --- dynamic client registration (RFC 7591) ----------------------------------------------


def _daily_cap() -> int:
    return int(getattr(settings, "MCP_OAUTH_MAX_CLIENTS_PER_DAY", 500))


class RegisterView(_OAuthView):
    throttle_classes = [RegisterThrottle]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else None
        if data is None:
            return oauth_error("invalid_client_metadata", "send the client metadata as a JSON object")
        uris = data.get("redirect_uris")
        if not isinstance(uris, list) or not uris or len(uris) > MAX_REDIRECT_URIS:
            return oauth_error("invalid_redirect_uri", f"redirect_uris must list 1 to {MAX_REDIRECT_URIS} addresses")
        if not all(valid_redirect_uri(u) for u in uris):
            return oauth_error("invalid_redirect_uri", "redirect URIs must use https, or http on localhost, with no fragment")
        method = data.get("token_endpoint_auth_method") or OAuthClient.AUTH_NONE
        if method not in (OAuthClient.AUTH_NONE, OAuthClient.AUTH_POST, OAuthClient.AUTH_BASIC):
            return oauth_error("invalid_client_metadata", "token_endpoint_auth_method must be none, client_secret_post or client_secret_basic")
        grants = data.get("grant_types") or ["authorization_code", "refresh_token"]
        if not isinstance(grants, list) or not set(grants) <= {"authorization_code", "refresh_token"} or "authorization_code" not in grants:
            return oauth_error("invalid_client_metadata", "grant_types must be authorization_code and optionally refresh_token")
        responses = data.get("response_types") or ["code"]
        if responses != ["code"]:
            return oauth_error("invalid_client_metadata", "response_types must be [\"code\"]")
        name = data.get("client_name") or "Unnamed app"
        client_uri = data.get("client_uri") or ""
        scope = data.get("scope") or ""
        for value in (name, client_uri, scope, data.get("software_id") or ""):
            if not isinstance(value, str):
                return oauth_error("invalid_client_metadata", "client_name, client_uri, scope and software_id must be text")
        name = CONTROL_RE.sub("", name).strip()[:80] or "Unnamed app"
        if client_uri and (len(client_uri) > 300 or urlsplit(client_uri).scheme != "https"):
            return oauth_error("invalid_client_metadata", "client_uri must be an https address")
        since = timezone.now() - timedelta(days=1)
        if OAuthClient.objects.filter(created_at__gte=since, is_demo=False).count() >= _daily_cap():
            return oauth_error("temporarily_unavailable", "Too many apps registered today. Try again tomorrow.", status=429)
        secret = OAUTH_SECRET_PREFIX + secrets.token_urlsafe(32) if method != OAuthClient.AUTH_NONE else ""
        client = OAuthClient.objects.create(
            client_id=OAUTH_CLIENT_PREFIX + secrets.token_urlsafe(18), secret_hash=hash_token(secret) if secret else "",
            name=name, client_uri=client_uri, redirect_uris=list(dict.fromkeys(uris)), token_endpoint_auth_method=method,
            scope=" ".join(s for s in scope.split() if s in SCOPES)[:400], software_id=str(data.get("software_id") or "")[:120],
            registered_ip=hash_token(_client_ip(request))[:16],
        )
        body = {
            "client_id": client.client_id,
            "client_id_issued_at": int(client.created_at.timestamp()),
            "client_name": client.name,
            "redirect_uris": client.redirect_uris,
            "grant_types": list(dict.fromkeys(grants)),
            "response_types": ["code"],
            "token_endpoint_auth_method": method,
        }
        if client.client_uri:
            body["client_uri"] = client.client_uri
        if client.scope:
            body["scope"] = client.scope
        if secret:
            body["client_secret"] = secret
            body["client_secret_expires_at"] = 0
        return _no_store(JsonResponse(body, status=201))


# --- authorize -------------------------------------------------------------------------


def _redirect_with(uri, params):
    sep = "&" if urlsplit(uri).query else "?"
    return HttpResponseRedirect(uri + sep + urlencode({k: v for k, v in params.items() if v not in (None, "")}))


class AuthorizeView(_OAuthView):
    throttle_classes = [AuthorizeThrottle]

    def get(self, request):
        q = request.query_params
        client = OAuthClient.objects.filter(client_id=str(q.get("client_id") or "")[:64]).first()
        redirect_uri = str(q.get("redirect_uri") or "")
        # Until the client and its exact redirect URI check out, never redirect to the app.
        if client is None:
            return HttpResponseRedirect(frontend_consent_url(error="invalid_client"))
        if not redirect_uri or redirect_uri not in (client.redirect_uris or []):
            return HttpResponseRedirect(frontend_consent_url(error="invalid_redirect_uri"))
        state = str(q.get("state") or "")[:500]
        iss = base_url(request)

        def fail(error, description):
            return _redirect_with(redirect_uri, {"error": error, "error_description": description, "state": state, "iss": iss})

        if q.get("response_type") != "code":
            return fail("unsupported_response_type", "only response_type=code is supported")
        challenge = str(q.get("code_challenge") or "")
        if q.get("code_challenge_method") != "S256" or not CHALLENGE_RE.match(challenge):
            return fail("invalid_request", "PKCE with code_challenge_method=S256 is required")
        resource = q.get("resource")
        if resource is not None and canonical(resource) != canonical(resource_url(request)):
            return fail("invalid_target", "resource must be this server's MCP endpoint")
        signed = signing.dumps(
            {
                "c": client.client_id,
                "r": redirect_uri,
                "s": state,
                "ch": challenge,
                "sc": parse_scopes(q.get("scope") or client.scope),
                "rs": canonical(resource_url(request)),
                "iss": iss,
            },
            salt=SIGN_SALT,
            compress=True,
        )
        return HttpResponseRedirect(frontend_consent_url(request=signed))


# --- consent (the signed-in person, from the web app) -----------------------------------


def _load_request(raw):
    try:
        data = signing.loads(str(raw or ""), salt=SIGN_SALT, max_age=REQUEST_MAX_AGE)
    except signing.SignatureExpired:
        return None, "expired"
    except signing.BadSignature:
        return None, "invalid"
    client = OAuthClient.objects.filter(client_id=data.get("c")).first()
    if client is None or data.get("r") not in (client.redirect_uris or []):
        return None, "invalid"
    return (data, client), None


def _org_choices(user):
    from organizations.models import OrgMembership

    out = []
    rows = OrgMembership.objects.filter(user=user).select_related("org").order_by("org__name")
    for m in rows:
        if not m.is_active_member or not m.org.is_active:
            continue
        out.append({"id": str(m.org.id), "name": m.org.name, "slug": m.org.slug, "available": hub_on(m.org, m)})
    return out


class ConsentView(V2APIView):
    """``GET`` what the app asks for; ``POST`` the person's answer. Returns where to send the browser."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        loaded, error = _load_request(request.query_params.get("request"))
        if error:
            return Response({"error": error, "details": "This sign-in link expired or is not valid. Start again from the app."}, status=400)
        data, client = loaded
        host = urlsplit(data["r"]).hostname or ""
        return Response(
            {
                "client": {
                    "name": client.name,
                    "client_uri": client.client_uri,
                    "redirect_host": host,
                    "verified": client.is_demo,
                    "registered_at": client.created_at.isoformat(),
                },
                "scopes": [{"key": s, "label": SCOPE_LABELS.get(s, s)} for s in data["sc"]],
                "resource": data["rs"],
                "orgs": _org_choices(request.user),
                "expires_in": REQUEST_MAX_AGE,
            }
        )

    def post(self, request):
        from organizations.models import Organization
        from organizations.services.core import audit

        body = request.data if isinstance(request.data, dict) else {}
        loaded, error = _load_request(body.get("request"))
        if error:
            return Response({"error": error, "details": "This sign-in link expired or is not valid. Start again from the app."}, status=400)
        data, client = loaded
        if body.get("decision") == "deny":
            return Response({"redirect": _redirect_with(data["r"], {"error": "access_denied", "error_description": "The person declined.", "state": data["s"], "iss": data["iss"]}).url})
        if body.get("decision") != "approve":
            return Response({"error": "invalid", "details": "decision must be approve or deny"}, status=400)
        org = Organization.objects.filter(pk=_uuid_or_none(body.get("org")), is_active=True).first()
        membership = _active_membership(org, request.user) if org else None
        if membership is None:
            return Response({"error": "not_found", "details": "Organization not found"}, status=404)
        if not hub_on(org, membership):
            return Response({"error": "not_implemented", "details": "Connecting apps is not enabled in this organization"}, status=501)
        scopes = body.get("scopes", data["sc"])
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes) or not set(scopes) <= set(data["sc"]):
            return Response({"error": "invalid", "details": "pick scopes from the ones the app asked for"}, status=400)
        scopes = list(dict.fromkeys(["mcp"] + [s for s in data["sc"] if s in scopes]))
        with transaction.atomic():
            grant = OAuthGrant.objects.filter(client=client, user=request.user, org=org, resource=data["rs"], revoked_at__isnull=True).first()
            if grant is None:
                grant = OAuthGrant.objects.create(client=client, user=request.user, org=org, scopes=scopes, resource=data["rs"])
            elif grant.scopes != scopes:
                grant.scopes = scopes
                grant.save(update_fields=["scopes"])
            code = OAUTH_CODE_PREFIX + secrets.token_urlsafe(32)
            OAuthAuthorizationCode.objects.create(
                code_hash=hash_token(code), grant=grant, client=client, redirect_uri=data["r"], code_challenge=data["ch"],
                scopes=scopes, resource=data["rs"], expires_at=timezone.now() + CODE_TTL,
            )
        audit(request.user, "mcp.oauth.authorize", target=grant, payload={"client": client.name, "scopes": scopes}, request=request, org=org)
        return Response({"redirect": _redirect_with(data["r"], {"code": code, "state": data["s"], "iss": data["iss"]}).url})


def _uuid_or_none(value):
    import uuid

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


# --- token -----------------------------------------------------------------------------


def _authenticate_client(request, data):
    """Returns (client, error_response)."""
    client_id, secret = data.get("client_id"), data.get("client_secret")
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
            from urllib.parse import unquote

            basic_id, _, basic_secret = decoded.partition(":")
            client_id, secret = unquote(basic_id), unquote(basic_secret)
        except (ValueError, UnicodeDecodeError):
            return None, oauth_error("invalid_client", "bad client credentials", 401)
    if not isinstance(client_id, str) or not client_id:
        return None, oauth_error("invalid_client", "client_id is required", 401)
    client = OAuthClient.objects.filter(client_id=client_id[:64]).first()
    if client is None:
        return None, oauth_error("invalid_client", "unknown client", 401)
    if client.token_endpoint_auth_method != OAuthClient.AUTH_NONE:
        if not isinstance(secret, str) or not secret or not hmac.compare_digest(hash_token(secret), client.secret_hash):
            return None, oauth_error("invalid_client", "bad client credentials", 401)
    return client, None


def _grant_usable(grant) -> bool:
    if grant.revoked_at is not None:
        return False
    user = grant.user
    if user.password_changed_at and grant.created_at < user.password_changed_at:
        revoke_grant(grant, "password_changed")
        return False
    membership = _active_membership(grant.org, user)
    if membership is None:
        revoke_grant(grant, "membership_ended")
        return False
    return hub_on(grant.org, membership)


class TokenView(_OAuthView):
    throttle_classes = [TokenThrottle]

    def post(self, request):
        data = request.data if hasattr(request.data, "get") else {}
        client, error = _authenticate_client(request, data)
        if error:
            return error
        grant_type = data.get("grant_type")
        if grant_type == "authorization_code":
            return self._code(request, client, data)
        if grant_type == "refresh_token":
            return self._refresh(request, client, data)
        return oauth_error("unsupported_grant_type", "use authorization_code or refresh_token")

    def _code(self, request, client, data):
        raw = str(data.get("code") or "")
        code = OAuthAuthorizationCode.objects.select_related("grant__user", "grant__org").filter(code_hash=hash_token(raw)).first() if raw else None
        if code is None or code.client_id != client.id:
            return oauth_error("invalid_grant", "unknown code")
        if code.used_at is not None:
            # A second use of a code: someone may have stolen it. Stop everything issued from it.
            revoke_grant(code.grant, "code_reused")
            return oauth_error("invalid_grant", "this code was already used")
        if code.expires_at <= timezone.now():
            return oauth_error("invalid_grant", "this code expired")
        if str(data.get("redirect_uri") or "") != code.redirect_uri:
            return oauth_error("invalid_grant", "redirect_uri does not match")
        if not pkce_ok(data.get("code_verifier"), code.code_challenge):
            return oauth_error("invalid_grant", "code_verifier does not match")
        resource = data.get("resource")
        if resource is not None and canonical(resource) != canonical(code.resource):
            return oauth_error("invalid_target", "resource does not match the authorization")
        if OAuthAuthorizationCode.objects.filter(pk=code.pk, used_at__isnull=True).update(used_at=timezone.now()) != 1:
            revoke_grant(code.grant, "code_reused")
            return oauth_error("invalid_grant", "this code was already used")
        if not _grant_usable(code.grant):
            return oauth_error("invalid_grant", "this authorization is no longer valid")
        OAuthClient.objects.filter(pk=client.pk).update(last_used_at=timezone.now())
        return _no_store(JsonResponse(issue_tokens(code.grant, code.scopes)))

    def _refresh(self, request, client, data):
        raw = str(data.get("refresh_token") or "")
        token = OAuthRefreshToken.objects.select_related("grant__user", "grant__org", "grant__client").filter(token_hash=hash_token(raw)).first() if raw else None
        if token is None or token.grant.client_id != client.id:
            return oauth_error("invalid_grant", "unknown refresh token")
        grant = token.grant
        if token.rotated_at is not None:
            revoke_grant(grant, "refresh_reused")
            _audit_reuse(grant)
            return oauth_error("invalid_grant", "this refresh token was already used; the connection was stopped")
        if token.revoked_at is not None or grant.revoked_at is not None or token.expires_at <= timezone.now():
            return oauth_error("invalid_grant", "this refresh token is no longer valid")
        resource = data.get("resource")
        if resource is not None and canonical(resource) != canonical(grant.resource):
            return oauth_error("invalid_target", "resource does not match the authorization")
        scopes = grant.scopes
        if data.get("scope"):
            wanted = str(data["scope"]).split()
            if not set(wanted) <= set(grant.scopes):
                return oauth_error("invalid_scope", "a refresh cannot add scopes")
            scopes = list(dict.fromkeys(["mcp"] + wanted))
        if OAuthRefreshToken.objects.filter(pk=token.pk, rotated_at__isnull=True).update(rotated_at=timezone.now()) != 1:
            revoke_grant(grant, "refresh_reused")
            return oauth_error("invalid_grant", "this refresh token was already used; the connection was stopped")
        if not _grant_usable(grant):
            return oauth_error("invalid_grant", "this authorization is no longer valid")
        return _no_store(JsonResponse(issue_tokens(grant, scopes)))


def _audit_reuse(grant):
    from organizations.services.core import audit

    audit(grant.user, "mcp.oauth.refresh_reused", target=grant, payload={"client": grant.client.name}, org=grant.org)


class RevokeView(_OAuthView):
    throttle_classes = [TokenThrottle]

    def post(self, request):
        data = request.data if hasattr(request.data, "get") else {}
        client, error = _authenticate_client(request, data)
        if error:
            return error
        raw = str(data.get("token") or "")
        digest = hash_token(raw) if raw else ""
        if raw.startswith(OAUTH_REFRESH_PREFIX):
            row = OAuthRefreshToken.objects.select_related("grant").filter(token_hash=digest, grant__client=client).first()
            if row is not None:
                revoke_grant(row.grant, "revoked_by_app")
        elif raw.startswith(OAUTH_ACCESS_PREFIX):
            OAuthAccessToken.objects.filter(token_hash=digest, grant__client=client, revoked_at__isnull=True).update(revoked_at=timezone.now())
        return _no_store(JsonResponse({}, status=200))


# --- the MCP endpoint's authentication ------------------------------------------------------


class NotEnabled(exceptions.APIException):
    status_code = 501
    default_detail = "mcp_hub is not enabled"
    default_code = "not_implemented"


class MCPAuthentication(authentication.BaseAuthentication):
    """``Bearer fba_…`` (OAuth, bound to this MCP endpoint) or ``Bearer fbp_…`` (PAT, as before)."""

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer "):
            return None
        raw = header[7:].strip()
        if not raw.startswith(OAUTH_ACCESS_PREFIX):
            return PATAuthentication().authenticate(request)
        digest = hash_token(raw)
        token = OAuthAccessToken.objects.select_related("grant__client", "user", "org").filter(token_hash=digest).first()
        if token is None or not hmac.compare_digest(token.token_hash, digest) or token.revoked_at is not None:
            raise exceptions.AuthenticationFailed("invalid_token")
        now = timezone.now()
        if token.expires_at <= now:
            raise exceptions.AuthenticationFailed("invalid_token: expired")
        if canonical(token.resource) != canonical(resource_url(request)):
            raise exceptions.AuthenticationFailed("invalid_token: issued for another resource")
        grant = token.grant
        if grant.revoked_at is not None:
            raise exceptions.AuthenticationFailed("invalid_token: the connection was revoked")
        user = token.user
        if user.password_changed_at and grant.created_at < user.password_changed_at:
            revoke_grant(grant, "password_changed")
            raise exceptions.AuthenticationFailed("invalid_token: issued before the last password change")
        membership = _active_membership(token.org, user)
        if membership is None:
            revoke_grant(grant, "membership_ended")
            raise exceptions.AuthenticationFailed("invalid_token: membership is not active")
        if not hub_on(token.org, membership):
            raise NotEnabled()
        if grant.last_used_at is None or now - grant.last_used_at > timedelta(seconds=60):
            OAuthGrant.objects.filter(pk=grant.pk).update(last_used_at=now)
            OAuthClient.objects.filter(pk=grant.client_id).update(last_used_at=now)
        return user, token

    def authenticate_header(self, request):
        return f'Bearer resource_metadata="{metadata_url(request)}"'
