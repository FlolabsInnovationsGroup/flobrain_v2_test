"""SSO endpoints (Phase 17c).

Admin (``sso.manage``): ``GET/PUT /orgs/{org}/sso``, ``POST /orgs/{org}/sso/domains``,
``POST /orgs/{org}/sso/domains/{domain}/verify`` (DNS TXT ``_flobrain-verify.<domain>``).
Public: ``GET /sso/start?email=``, ``GET /sso/callback``, ``POST /sso/exchange``; SAML:
``GET /sso/saml/{org}/metadata`` and ``POST /sso/saml/acs``. Both protocols end in the same
one-time, browser-bound code that ``/w/sso`` exchanges.
"""

import re
import secrets
import urllib.parse

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from core_v2.views import V2APIView, V2PublicAPIView
from integrations import crypto
from organizations.models import Organization
from organizations.permissions import HasPerm, IsActiveOrgMember
from organizations.services.core import audit
from platform_api import net
from sso import oidc, saml
from sso.models import SSOConnection

DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _payload(c):
    expires = saml.certificate_expiry(c.idp_cert_pem) if c.idp_cert_pem else None
    return {
        "protocol": c.protocol,
        "issuer": c.issuer,
        "client_id": c.client_id,
        "idp_entity_id": c.idp_entity_id,
        "idp_sso_url": c.idp_sso_url,
        "idp_cert_fingerprint": c.idp_cert_fingerprint,
        "idp_cert_expires_at": expires.isoformat() if expires else None,
        "email_attribute": c.email_attribute,
        "saml_complete": saml.is_complete(c),
        "sp_entity_id": saml.sp_entity_id(c.org_id),
        "acs_url": saml.acs_url(),
        "metadata_url": saml.sp_entity_id(c.org_id),
        "verified_domains": c.verified_domains,
        "pending_domains": [{"domain": d, "txt_name": f"_flobrain-verify.{d}", "txt_value": f"flobrain-verify={t}"} for d, t in c.pending_domains.items()],
        "enforced": c.enforced,
        "enabled": c.enabled,
        "redirect_uri": oidc.redirect_uri(),
    }


def _org(request, view, org_id):
    org = get_object_or_404(Organization, pk=org_id, is_active=True)
    request.org = org
    HasPerm("sso.manage").has_permission(request, view)
    return org


class SSOConnectionView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="The org's SSO connection (never the client secret)")
    def get(self, request, org_id):
        org = _org(request, self, org_id)
        c = SSOConnection.objects.filter(org=org).first()
        return Response(_payload(c) if c else None)

    @extend_schema(summary="Configure OIDC (issuer discovery is checked) or SAML 2.0 (IdP certificate is checked)")
    def put(self, request, org_id):
        org = _org(request, self, org_id)
        data = request.data if isinstance(request.data, dict) else {}
        c = SSOConnection.objects.filter(org=org).first() or SSOConnection(org=org)
        protocol = data.get("protocol", SSOConnection.PROTOCOL_OIDC if c._state.adding else c.protocol)
        if protocol not in (SSOConnection.PROTOCOL_OIDC, SSOConnection.PROTOCOL_SAML):
            return Response({"error": "invalid", "details": "protocol must be oidc or saml"}, status=400)
        if protocol == SSOConnection.PROTOCOL_OIDC and not crypto.is_configured():
            return Response({"error": "not_configured", "details": "Encryption is not configured"}, status=501)
        before = _identity(c)
        fresh = c._state.adding or protocol != c.protocol
        c.protocol = protocol
        error = _configure_oidc(c, data, fresh) if protocol == SSOConnection.PROTOCOL_OIDC else _configure_saml(c, data)
        if error is not None:
            return error
        identity_changed = not c._state.adding and _identity(c) != before
        if identity_changed:
            # A new IdP (or protocol, or signing certificate) must be switched on again on purpose.
            c.enabled, c.enforced = False, False
        if "enabled" in data and not identity_changed:
            if data["enabled"] is True and not c.verified_domains:
                return Response({"error": "invalid", "details": "verify a domain first"}, status=400)
            if data["enabled"] is True and c.protocol == SSOConnection.PROTOCOL_SAML and not saml.is_complete(c):
                return Response({"error": "invalid", "details": "add the IdP entity ID, sign-in URL and certificate first"}, status=400)
            c.enabled = data["enabled"] is True
        was_enforced = SSOConnection.objects.filter(pk=c.pk, enforced=True).exists()
        if "enforced" in data and not identity_changed:
            c.enforced = data["enforced"] is True and c.enabled
        c.save()
        cut = 0
        if c.enforced and not was_enforced:
            cut = _end_password_sessions(c)
        audit(
            request.user,
            "sso.configure",
            target=c,
            payload={
                "protocol_before": before[0],
                "protocol": c.protocol,
                "enabled": c.enabled,
                "enforced": c.enforced,
                "issuer_before": before[1],
                "issuer": c.issuer,
                "client_id_changed": before[2] != c.client_id,
                "idp_entity_id_before": before[3],
                "idp_entity_id": c.idp_entity_id,
                "idp_cert_fingerprint_before": before[5],
                "idp_cert_fingerprint": c.idp_cert_fingerprint,
                "sessions_ended": cut,
            },
            request=request,
            org=org,
        )
        return Response(_payload(c))


def _identity(c):
    """Everything that decides who the org trusts to vouch for its people."""
    return (c.protocol, c.issuer, c.client_id, c.idp_entity_id, c.idp_sso_url, c.idp_cert_fingerprint)


def _invalid(details):
    return Response({"error": "invalid", "details": details}, status=400)


def _configure_saml(c, data):
    """Fields can be saved one by one (the IdP needs our ACS URL before it gives a certificate)."""
    if "idp_entity_id" in data:
        value = str(data.get("idp_entity_id") or "").strip()
        if not value or len(value) > 300 or any(ch.isspace() for ch in value):
            return _invalid("idp_entity_id is required")
        c.idp_entity_id = value
    if "idp_sso_url" in data:
        value = str(data.get("idp_sso_url") or "").strip()
        try:
            parsed = urllib.parse.urlparse(value)
            host = parsed.hostname
        except ValueError:
            host = None
        if not host or parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment or len(value) > 500:
            return _invalid("idp_sso_url must be an https URL")
        c.idp_sso_url = value
    if "idp_certificate" in data:
        try:
            c.idp_cert_pem, c.idp_cert_fingerprint, _ = saml.parse_certificate(data.get("idp_certificate"))
        except saml.SAMLError as exc:
            return _invalid(f"idp_certificate: {exc.code}")
    if "email_attribute" in data:
        value = str(data.get("email_attribute") or "").strip()
        if len(value) > 200 or any(ch.isspace() for ch in value):
            return _invalid("email_attribute is not valid")
        c.email_attribute = value
    return None


def _configure_oidc(c, data, fresh):
    if "issuer" in data or fresh:
        issuer = str(data.get("issuer") or "").rstrip("/")
        try:
            net.check_url(issuer + "/")
            c.metadata = oidc.discover(issuer)
        except (net.UnsafeURL, oidc.OIDCError, OSError) as exc:
            return _invalid(f"issuer: {getattr(exc, 'code', exc)}")
        c.issuer = issuer
    if "client_id" in data or fresh:
        client_id = str(data.get("client_id") or "").strip()
        if not client_id or len(client_id) > 200:
            return _invalid("client_id is required")
        c.client_id = client_id
    if "client_secret" in data or fresh:
        secret = str(data.get("client_secret") or "")
        if not 8 <= len(secret) <= 500:
            return _invalid("client_secret is required")
        c.secret_ciphertext = crypto.encrypt(secret, c.id, c.org_id)
        c.key_version = crypto.current_key_version()
    return None



class SSODomainView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Add a domain to verify by DNS TXT")
    def post(self, request, org_id):
        org = _org(request, self, org_id)
        c = SSOConnection.objects.filter(org=org).first()
        if c is None:
            return Response({"error": "not_found", "details": "Configure SSO first"}, status=404)
        data = request.data if isinstance(request.data, dict) else {}
        domain = str(data.get("domain") or "").strip().lower().rstrip(".")
        if not DOMAIN_RE.match(domain):
            return Response({"error": "invalid", "details": "not a domain name"}, status=400)
        if domain in c.verified_domains:
            return Response(_payload(c))
        c.pending_domains = {**c.pending_domains, domain: secrets.token_urlsafe(24)}
        c.save(update_fields=["pending_domains", "updated_at"])
        return Response(_payload(c), status=201)


def txt_records(name):
    import dns.exception
    import dns.resolver

    try:
        answer = dns.resolver.resolve(name, "TXT", lifetime=5)
    except (dns.exception.DNSException, OSError):
        return []
    return [b"".join(r.strings).decode("utf-8", "replace") for r in answer]


class SSODomainVerifyView(V2APIView):
    permission_classes = [IsActiveOrgMember]

    @extend_schema(summary="Check the TXT record and verify the domain")
    def post(self, request, org_id, domain):
        org = _org(request, self, org_id)
        c = SSOConnection.objects.filter(org=org).first()
        token = (c.pending_domains or {}).get(domain) if c else None
        if token is None:
            return Response({"error": "not_found", "details": "Domain not pending"}, status=404)
        others = [x for x in SSOConnection.objects.exclude(pk=c.pk) if domain in (x.verified_domains or [])]
        if others:
            return Response({"error": "conflict", "details": "Another organization verified this domain"}, status=409)
        if f"flobrain-verify={token}" not in txt_records(f"_flobrain-verify.{domain}"):
            return Response({"error": "not_verified", "details": "TXT record not found yet"}, status=409)
        pending = dict(c.pending_domains)
        pending.pop(domain, None)
        c.pending_domains, c.verified_domains = pending, sorted(set(c.verified_domains) | {domain})
        c.save(update_fields=["pending_domains", "verified_domains", "updated_at"])
        audit(request.user, "sso.domain_verified", target=c, payload={"domain": domain}, request=request, org=org)
        return Response(_payload(c))


def connection_for_email(email):
    domain = (email or "").strip().lower().rsplit("@", 1)[-1]
    if not domain:
        return None
    for c in SSOConnection.objects.filter(enabled=True).select_related("org"):
        if domain in [d.lower() for d in c.verified_domains] and c.org.is_active:
            return c
    return None


class SSOStartView(V2PublicAPIView):
    @extend_schema(summary="Where to sign in for this email (OIDC authorize URL or SAML redirect)")
    def get(self, request):
        client_nonce = str(request.query_params.get("client_nonce") or "")
        if not 16 <= len(client_nonce) <= 128:
            return Response({"error": "invalid", "details": "client_nonce (16-128 characters) is required"}, status=400)
        c = connection_for_email(request.query_params.get("email"))
        if c is not None and c.protocol == SSOConnection.PROTOCOL_SAML and saml.is_complete(c):
            return Response({"authorize_url": saml.start(c, client_nonce)})
        if c is None or c.protocol != SSOConnection.PROTOCOL_OIDC or not crypto.is_configured():
            return Response({"error": "not_found", "details": "No SSO for this email"}, status=404)
        return Response({"authorize_url": oidc.start(c, client_nonce)})


class SSOCallbackView(V2PublicAPIView):
    @extend_schema(summary="OIDC callback (fixed redirect URI)")
    def get(self, request):
        frontend = (getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/")
        try:
            user, org, client = oidc.finish(request.query_params.get("state"), request.query_params.get("code") or "")
        except (oidc.OIDCError, crypto.CredentialCryptoError, net.UnsafeURL, OSError) as exc:
            return HttpResponseRedirect(f"{frontend}/w/sso?error={getattr(exc, 'code', 'sso_failed')}")
        audit(user, "sso.signin", payload={"protocol": "oidc"}, org=org)
        return HttpResponseRedirect(f"{frontend}/w/sso?code={oidc.issue_login_code(user, org, client)}")


def _see_other(url):
    response = HttpResponseRedirect(url)
    response.status_code = 303  # the browser follows a POST with a GET
    return response


class SAMLMetadataView(V2PublicAPIView):
    @extend_schema(summary="Our SAML service provider metadata for this org (give it to the IdP)")
    def get(self, request, org_id):
        c = SSOConnection.objects.filter(org_id=org_id, org__is_active=True, protocol=SSOConnection.PROTOCOL_SAML).first()
        if c is None:
            return Response({"error": "not_found", "details": "No SAML connection"}, status=404)
        return HttpResponse(saml.metadata_xml(c), content_type="application/samlmetadata+xml")


class SAMLACSView(V2PublicAPIView):
    @extend_schema(summary="SAML assertion consumer service (HTTP-POST binding)")
    def post(self, request):
        frontend = (getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/")
        form = request.data if hasattr(request.data, "get") else {}
        try:
            user, org, client = saml.finish(form.get("SAMLResponse"), str(form.get("RelayState") or ""))
        except oidc.OIDCError as exc:
            return _see_other(f"{frontend}/w/sso?error={exc.code}")
        audit(user, "sso.signin", payload={"protocol": "saml"}, org=org)
        return _see_other(f"{frontend}/w/sso?code={oidc.issue_login_code(user, org, client)}")


class SSOExchangeView(V2PublicAPIView):
    @extend_schema(summary="Exchange the one-time SSO code for tokens")
    def post(self, request):
        from users.v2.views import _tokens_for

        data = request.data if isinstance(request.data, dict) else {}
        user = oidc.redeem_login_code(str(data.get("code") or ""), str(data.get("client_nonce") or ""))
        if user is None:
            return Response({"error": "invalid_code", "details": "The code is invalid or expired"}, status=400)
        return Response(_tokens_for(user))


def password_signin_blocked(user) -> bool:
    """Enforced SSO turns off password sign-in for the org's verified domains; the owner keeps break-glass."""
    from organizations.models import OrgMembership

    c = connection_for_email(user.email)
    if c is None or not c.enforced:
        return False
    owner = OrgMembership.objects.filter(org=c.org, user=user, org_role=OrgMembership.ORG_ROLE_OWNER).exists()
    return not owner


def _end_password_sessions(connection) -> int:
    """Turning enforcement on ends existing sessions of members it covers (owner excepted).

    Uses the same cut-off as a password change: tokens issued before it stop working.
    """
    from django.utils import timezone

    from organizations.models import OrgMembership
    from users.models import User

    domains = [d.lower() for d in connection.verified_domains]
    ids = []
    for m in OrgMembership.objects.filter(org=connection.org).exclude(org_role=OrgMembership.ORG_ROLE_OWNER).select_related("user"):
        if m.user.email.lower().rsplit("@", 1)[-1] in domains:
            ids.append(m.user_id)
    return User.objects.filter(pk__in=ids).update(password_changed_at=timezone.now())
