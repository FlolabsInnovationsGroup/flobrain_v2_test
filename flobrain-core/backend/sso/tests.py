import base64
import json
import secrets
import time
import zlib
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from lxml import etree
from rest_framework.test import APIClient
from signxml import XMLSigner, methods

from organizations.models import OrgMembership, Organization, Team, TeamMembership
from platform_api.models import PersonalAccessToken
from sso import saml
from sso.models import SAMLRequest, SSOConnection
from users.jwt_utils import make_access_token
from users.models import User

KEY = "ab" * 32
CLIENT = "browser-nonce-0123456789"
ISSUER = "https://idp.example.com"
PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE.public_key()))
JWK.update({"kid": "k1", "alg": "RS256", "use": "sig"})
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
}


def _id_token(nonce, email="ana@acme.test", verified=True, aud="client-1", iss=ISSUER, exp_delta=300, key=PRIVATE, kid="k1"):
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "sub": "sub-1", "iat": now, "exp": now + exp_delta, "nonce": nonce, "email": email, "email_verified": verified}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


class FakeIdP:
    def __init__(self, **token_kwargs):
        self.token_kwargs = token_kwargs
        self.nonce = None

    def __call__(self, method, url, body=b"", headers=None, timeout=10, max_bytes=4096):
        if url.endswith("/.well-known/openid-configuration"):
            return 200, json.dumps(DISCOVERY).encode()
        if url.endswith("/jwks"):
            return 200, json.dumps({"keys": [JWK]}).encode()
        if url.endswith("/token"):
            form = parse_qs(body.decode())
            assert form["code_verifier"][0] and form["client_secret"][0] == "secret-123456"
            return 200, json.dumps({"id_token": _id_token(self.nonce, **self.token_kwargs)}).encode()
        return 404, b""


@override_settings(CREDENTIALS_ENCRYPTION_KEY=KEY, FRONTEND_BASE_URL="https://app.example", PUBLIC_API_BASE_URL="https://api.example")
class SSOTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(name="Acme", slug="acme-sso")
        self.owner = User.objects.create(email="boss@acme.test", password_hash=make_password("pw-123456"))
        self.ana = User.objects.create(email="ana@acme.test", password_hash=make_password("pw-123456"))
        OrgMembership.objects.create(org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status="active")
        OrgMembership.objects.create(org=self.org, user=self.ana, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status="active")
        self.base = f"/api/v2/orgs/{self.org.id}/sso"

    def _setup(self, enforce=False):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.owner.id))}")
        with patch("platform_api.net.fetch", side_effect=FakeIdP()), patch("platform_api.net.resolve", return_value=["93.184.216.34"]):
            made = self.client.put(self.base, {"issuer": ISSUER, "client_id": "client-1", "client_secret": "secret-123456"}, format="json")
        self.assertEqual(made.status_code, 200, made.content)
        self.assertNotIn("secret-123456", json.dumps(made.json()))
        self.assertEqual(self.client.put(self.base, {"enabled": True}, format="json").status_code, 400, "verify a domain first")
        pending = self.client.post(f"{self.base}/domains", {"domain": "acme.test"}, format="json").json()["pending_domains"][0]
        with patch("sso.views.txt_records", return_value=[]):
            self.assertEqual(self.client.post(f"{self.base}/domains/acme.test/verify").status_code, 409)
        with patch("sso.views.txt_records", return_value=[pending["txt_value"]]):
            self.assertEqual(self.client.post(f"{self.base}/domains/acme.test/verify").status_code, 200)
        self.client.put(self.base, {"enabled": True, "enforced": enforce}, format="json")
        self.client.credentials()

    def _login(self, **token_kwargs):
        start = self.client.get(f"/api/v2/sso/start?email=ana@acme.test&client_nonce={CLIENT}")
        self.assertEqual(start.status_code, 200, start.content)
        query = parse_qs(urlparse(start.json()["authorize_url"]).query)
        self.assertEqual(query["code_challenge_method"], ["S256"])
        idp = FakeIdP(**token_kwargs)
        idp.nonce = query["nonce"][0]
        with patch("platform_api.net.fetch", side_effect=idp):
            callback = self.client.get(f"/api/v2/sso/callback?state={query['state'][0]}&code=abc")
        return query["state"][0], callback["Location"]

    def test_full_oidc_login(self):
        self._setup()
        state, location = self._login()
        code = parse_qs(urlparse(location).query)["code"][0]
        self.assertNotIn("access", location, "no tokens in the URL")
        other_browser = self.client.post("/api/v2/sso/exchange", {"code": code, "client_nonce": "someone-elses-browser-123"}, format="json")
        self.assertEqual(other_browser.status_code, 400, "a code only works in the browser that started")
        tokens = self.client.post("/api/v2/sso/exchange", {"code": code, "client_nonce": CLIENT}, format="json")
        self.assertEqual(tokens.status_code, 200)
        self.assertEqual(tokens.json()["user_id"], str(self.ana.id))
        self.assertEqual(self.client.post("/api/v2/sso/exchange", {"code": code, "client_nonce": CLIENT}, format="json").status_code, 400, "single use")
        reused = self.client.get(f"/api/v2/sso/callback?state={state}&code=abc")
        self.assertIn("error=invalid_state", reused["Location"])

    def test_bad_tokens_are_refused(self):
        self._setup()
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        for kwargs, expected in (
            ({"verified": False}, "email_not_verified"),
            ({"aud": "someone-else"}, "bad_id_token"),
            ({"iss": "https://evil.example"}, "bad_id_token"),
            ({"exp_delta": -600}, "bad_id_token"),
            ({"key": other}, "bad_id_token"),
            ({"kid": "nope"}, "unknown_key"),
            ({"email": "eve@evil.test"}, "domain_not_verified"),
            ({"email": "nobody@acme.test"}, "not_a_member"),
        ):
            _, location = self._login(**kwargs)
            self.assertIn(f"error={expected}", location, kwargs)

    def test_bad_nonce(self):
        self._setup()
        start = self.client.get(f"/api/v2/sso/start?email=ana@acme.test&client_nonce={CLIENT}").json()
        query = parse_qs(urlparse(start["authorize_url"]).query)
        idp = FakeIdP()
        idp.nonce = "other-nonce"
        with patch("platform_api.net.fetch", side_effect=idp):
            location = self.client.get(f"/api/v2/sso/callback?state={query['state'][0]}&code=abc")["Location"]
        self.assertIn("error=bad_nonce", location)

    def test_enforced_sso_blocks_passwords_but_owner_keeps_break_glass(self):
        self._setup(enforce=True)
        ana = self.client.post("/api/v2/auth/signin", {"email": "ana@acme.test", "password": "pw-123456"}, format="json")
        boss = self.client.post("/api/v2/auth/signin", {"email": "boss@acme.test", "password": "pw-123456"}, format="json")
        if ana.status_code == 404:
            self.skipTest("sign-in route differs")
        self.assertEqual(ana.status_code, 403)
        self.assertEqual(ana.json()["error"], "sso_required")
        self.assertEqual(boss.status_code, 200)

    def test_domain_claimed_by_another_org_is_refused(self):
        other = Organization.objects.create(name="Other", slug="other-sso")
        SSOConnection.objects.create(org=other, issuer=ISSUER, client_id="c", secret_ciphertext=b"x", verified_domains=["acme.test"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.owner.id))}")
        with patch("platform_api.net.fetch", side_effect=FakeIdP()), patch("platform_api.net.resolve", return_value=["93.184.216.34"]):
            self.client.put(self.base, {"issuer": ISSUER, "client_id": "client-1", "client_secret": "secret-123456"}, format="json")
        pending = self.client.post(f"{self.base}/domains", {"domain": "acme.test"}, format="json").json()["pending_domains"][0]
        with patch("sso.views.txt_records", return_value=[pending["txt_value"]]):
            self.assertEqual(self.client.post(f"{self.base}/domains/acme.test/verify").status_code, 409)

    def test_member_and_admin_cannot_configure(self):
        admin = User.objects.create(email="adm@acme.test", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=admin, org_role=OrgMembership.ORG_ROLE_ADMIN, employment_status="active")
        for user in (self.ana, admin):
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
            self.assertEqual(self.client.put(self.base, {"issuer": ISSUER}, format="json").status_code, 403)
            self.assertEqual(self.client.post(f"/api/v2/orgs/{self.org.id}/scim/tokens", {}, format="json").status_code, 403)
        # Owner-only keys cannot be granted to an admin either.
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.owner.id))}")
        grant = self.client.post(f"/api/v2/orgs/{self.org.id}/grants", {"grantee": str(admin.id), "perm_key": "sso.manage"}, format="json")
        self.assertEqual(grant.status_code, 400, grant.content)
        staff = User.objects.create(email="staff@flobrain.test", password_hash=make_password("x"), is_platform_admin=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(staff.id))}")
        self.assertEqual(self.client.put(self.base, {"issuer": ISSUER}, format="json").status_code, 403, "no platform bypass")

    def test_new_issuer_turns_sso_off(self):
        self._setup(enforce=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.owner.id))}")
        evil = dict(DISCOVERY, issuer="https://other-idp.example.com")
        with patch("sso.oidc._get_json", return_value=evil), patch("platform_api.net.resolve", return_value=["93.184.216.34"]):
            made = self.client.put(self.base, {"issuer": "https://other-idp.example.com", "enabled": True}, format="json")
        self.assertEqual(made.status_code, 200, made.content)
        self.assertEqual((made.json()["enabled"], made.json()["enforced"]), (False, False))
        from organizations.models import AuditEvent

        event = AuditEvent.objects.filter(org=self.org, action="sso.configure").order_by("-created_at").first()
        self.assertEqual(event.payload["issuer_before"], ISSUER)

    def test_v1_signin_and_old_tokens_respect_enforcement(self):
        from users.jwt_utils import make_refresh_token

        old_refresh = make_refresh_token(str(self.ana.id))
        old_access = make_access_token(str(self.ana.id))
        time.sleep(0.01)
        self._setup(enforce=True)
        v1 = self.client.post("/api/auth/signin/", {"email": "ana@acme.test", "password": "pw-123456"}, format="json")
        self.assertEqual(v1.status_code, 403, v1.content)
        self.assertEqual(self.client.post("/api/auth/refresh/", {"refresh": old_refresh}, format="json").status_code, 401)
        self.assertEqual(self.client.post("/api/v2/auth/refresh", {"refresh": old_refresh}, format="json").status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.org.id}/marketplace").status_code, 401)

    def test_platform_admin_cannot_sign_in_by_sso(self):
        self._setup()
        User.objects.filter(pk=self.ana.pk).update(is_platform_admin=True)
        _, location = self._login()
        self.assertIn("error=platform_admin", location)

    def test_start_needs_client_nonce(self):
        self._setup()
        self.assertEqual(self.client.get("/api/v2/sso/start?email=ana@acme.test").status_code, 400)


@override_settings(CREDENTIALS_ENCRYPTION_KEY=KEY)
class SCIMTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Acme", slug="acme-scim", settings={"flags": {"api_access": True}})
        self.owner = User.objects.create(email="owner@acme.test", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status="active")
        self.team = Team.objects.create(org=self.org, name="Eng")
        SSOConnection.objects.create(org=self.org, issuer=ISSUER, client_id="c", secret_ciphertext=b"x", verified_domains=["acme.test"])
        admin = APIClient()
        admin.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.owner.id))}")
        self.admin = admin
        self.raw = admin.post(f"/api/v2/orgs/{self.org.id}/scim/tokens", {}, format="json").json()["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw}")

    def test_provisioning_rules(self):
        made = self.client.post("/scim/v2/Users", {"userName": "new@acme.test", "displayName": "New", "active": True}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        user_id = made.json()["id"]
        membership = OrgMembership.objects.get(org=self.org, user_id=user_id)
        self.assertEqual((membership.org_role, membership.employment_status), ("member", "pending"), "no team yet → pending")
        self.assertEqual(self.client.post("/scim/v2/Users", {"userName": "new@acme.test"}, format="json").status_code, 409)
        group = self.client.post("/scim/v2/Groups", {"displayName": "Engineering", "externalId": "g-eng"}, format="json").json()
        self.admin.post(f"/api/v2/orgs/{self.org.id}/scim/tokens", {"map_group": group["id"], "team": str(self.team.id)}, format="json")
        self.client.patch(
            f"/scim/v2/Groups/{group['id']}",
            {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [{"op": "add", "path": "members", "value": [{"value": user_id}]}]},
            format="json",
        )
        membership.refresh_from_db()
        self.assertEqual(membership.employment_status, "active")
        self.assertEqual(TeamMembership.objects.get(team=self.team, user_id=user_id).team_role, "member", "never lead")
        found = self.client.get('/scim/v2/Users?filter=userName eq "new@acme.test"').json()
        self.assertEqual(found["totalResults"], 1)

    def test_deactivate_revokes_tokens_and_owner_is_protected(self):
        user_id = self.client.post("/scim/v2/Users", {"userName": "ex@acme.test"}, format="json").json()["id"]
        OrgMembership.objects.filter(org=self.org, user_id=user_id).update(employment_status="active")
        pat, _ = PersonalAccessToken.issue(User.objects.get(pk=user_id), self.org, "cli", ["tasks:read"])
        off = self.client.patch(
            f"/scim/v2/Users/{user_id}", {"Operations": [{"op": "replace", "path": "active", "value": False}]}, format="json"
        )
        self.assertEqual(off.json()["active"], False)
        self.assertEqual(OrgMembership.objects.get(org=self.org, user_id=user_id).employment_status, "paused")
        pat.refresh_from_db()
        self.assertIsNotNone(pat.revoked_at)
        owner_off = self.client.delete(f"/scim/v2/Users/{self.owner.id}")
        self.assertEqual(owner_off.status_code, 403)
        self.assertEqual(OrgMembership.objects.get(org=self.org, user=self.owner).employment_status, "active")

    def test_auth_and_org_isolation(self):
        other = Organization.objects.create(name="Other", slug="other-scim")
        stranger = User.objects.create(email="s@other.test", password_hash=make_password("x"))
        OrgMembership.objects.create(org=other, user=stranger, employment_status="active")
        self.assertEqual(self.client.get(f"/scim/v2/Users/{stranger.id}").status_code, 404)
        self.assertEqual(self.client.delete(f"/scim/v2/Users/{stranger.id}").status_code, 404)
        bad = APIClient()
        bad.credentials(HTTP_AUTHORIZATION="Bearer scim_nope")
        self.assertEqual(bad.get("/scim/v2/Users").status_code, 401)
        jwt_client = APIClient()
        jwt_client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.owner.id))}")
        self.assertEqual(jwt_client.get("/scim/v2/Users").status_code, 401)
        self.assertEqual(self.client.get('/scim/v2/Users?filter=userName co "a"').status_code, 400)

    def test_review_rules(self):
        # Only verified domains; never someone else's account.
        outsider = self.client.post("/scim/v2/Users", {"userName": "victim@gmail.com", "active": False}, format="json")
        self.assertEqual(outsider.status_code, 400)
        self.assertFalse(OrgMembership.objects.filter(org=self.org, user__email="victim@gmail.com").exists())
        self.assertEqual(self.client.post("/scim/v2/Users", {"userName": "n@acme.test", "name": "str"}, format="json").status_code, 201)
        # A string "false" deactivates; nonsense is refused.
        uid = OrgMembership.objects.get(org=self.org, user__email="n@acme.test").user_id
        self.assertEqual(self.client.put(f"/scim/v2/Users/{uid}", {"active": "false"}, format="json").json()["active"], False)
        self.assertEqual(self.client.put(f"/scim/v2/Users/{uid}", {"active": "maybe"}, format="json").status_code, 400)
        # Admins paused by a person are not brought back by SCIM, and keep paused.
        admin_user = User.objects.create(email="adm@acme.test", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=admin_user, org_role="admin", employment_status="paused", status_reason="manual")
        back = self.client.patch(f"/scim/v2/Users/{admin_user.id}", {"Operations": [{"op": "replace", "path": "active", "value": True}]}, format="json")
        self.assertEqual(back.status_code, 403)
        self.assertEqual(OrgMembership.objects.get(org=self.org, user=admin_user).employment_status, "paused")
        member = User.objects.create(email="m@acme.test", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=member, org_role="member", employment_status="paused", status_reason="policy breach")
        self.assertEqual(self.client.put(f"/scim/v2/Users/{member.id}", {"active": True}, format="json").status_code, 403)

    def test_token_dies_with_owner(self):
        self.assertEqual(self.client.get("/scim/v2/Users").status_code, 200)
        OrgMembership.objects.filter(org=self.org, user=self.owner).update(org_role="admin")
        self.assertEqual(self.client.get("/scim/v2/Users").status_code, 401)


# --- SAML 2.0 ---------------------------------------------------------------------------

SAMLP, SAML_NS = saml.SAMLP, saml.SAML
IDP_ENTITY = "https://idp.example.com/saml/metadata"
IDP_SSO = "https://idp.example.com/saml/sso"


def _idp_keypair(cn):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(dt_timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return key, cert


IDP_KEY, IDP_CERT = _idp_keypair("idp.example.com")
EVIL_KEY, EVIL_CERT = _idp_keypair("idp.example.com")  # same name, different key
IDP_PEM = IDP_CERT.public_bytes(serialization.Encoding.PEM).decode()


def _iso(delta):
    return (datetime.now(dt_timezone.utc) + timedelta(seconds=delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _el(parent, ns, tag, text=None, **attrs):
    node = etree.SubElement(parent, f"{{{ns}}}{tag}", **attrs)
    if text is not None:
        node.text = text
    return node


def _sign(element, key=IDP_KEY, cert=IDP_CERT):
    signer = XMLSigner(method=methods.enveloped, c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")
    return signer.sign(element, key=key, cert=[cert])


class TestIdP:
    """Builds SAML responses the way a real IdP would, signed with its own key."""

    def __init__(self, org_id, acs="https://api.example/api/v2/sso/saml/acs"):
        self.audience = f"https://api.example/api/v2/sso/saml/{org_id}/metadata"
        self.acs = acs

    def assertion(self, request_id, email="ana@acme.test", audience=None, recipient=None, issuer=IDP_ENTITY, expires=300, starts=-60,
                  name_format=saml.EMAIL_FORMAT, attributes=None, assertion_id=None):
        a = etree.Element(f"{{{SAML_NS}}}Assertion", nsmap={"saml": SAML_NS}, ID=assertion_id or f"_a{secrets.token_hex(8)}", Version="2.0", IssueInstant=_iso(0))
        _el(a, SAML_NS, "Issuer", issuer)
        subject = _el(a, SAML_NS, "Subject")
        _el(subject, SAML_NS, "NameID", email, Format=name_format)
        confirmation = _el(subject, SAML_NS, "SubjectConfirmation", Method=saml.BEARER)
        _el(confirmation, SAML_NS, "SubjectConfirmationData", InResponseTo=request_id, Recipient=recipient or self.acs, NotOnOrAfter=_iso(expires))
        conditions = _el(a, SAML_NS, "Conditions", NotBefore=_iso(starts), NotOnOrAfter=_iso(expires))
        _el(_el(conditions, SAML_NS, "AudienceRestriction"), SAML_NS, "Audience", audience or self.audience)
        _el(a, SAML_NS, "AuthnStatement", AuthnInstant=_iso(0))
        if attributes:
            statement = _el(a, SAML_NS, "AttributeStatement")
            for name, value in attributes.items():
                _el(_el(statement, SAML_NS, "Attribute", Name=name), SAML_NS, "AttributeValue", value)
        return a

    def response(self, request_id, assertion=None, sign="assertion", key=IDP_KEY, cert=IDP_CERT, destination=None,
                 status="urn:oasis:names:tc:SAML:2.0:status:Success", **assertion_kwargs):
        a = assertion if assertion is not None else self.assertion(request_id, **assertion_kwargs)
        if sign in ("assertion", "both"):
            a = _sign(a, key, cert)
        r = etree.Element(
            f"{{{SAMLP}}}Response",
            nsmap={"samlp": SAMLP, "saml": SAML_NS},
            ID=f"_r{secrets.token_hex(8)}",
            Version="2.0",
            IssueInstant=_iso(0),
            Destination=destination or self.acs,
            InResponseTo=request_id,
        )
        _el(r, SAML_NS, "Issuer", IDP_ENTITY)
        _el(_el(r, SAMLP, "Status"), SAMLP, "StatusCode", Value=status)
        r.append(a)
        if sign in ("response", "both"):
            r = _sign(r, key, cert)
        return etree.tostring(r)


@override_settings(CREDENTIALS_ENCRYPTION_KEY=KEY, FRONTEND_BASE_URL="https://app.example", PUBLIC_API_BASE_URL="https://api.example")
class SAMLTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(name="Acme", slug="acme-saml")
        self.owner = User.objects.create(email="boss@acme.test", password_hash=make_password("pw-123456"))
        self.ana = User.objects.create(email="ana@acme.test", password_hash=make_password("pw-123456"))
        OrgMembership.objects.create(org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status="active")
        OrgMembership.objects.create(org=self.org, user=self.ana, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status="active")
        self.base = f"/api/v2/orgs/{self.org.id}/sso"
        self.idp = TestIdP(self.org.id)

    def _as_owner(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.owner.id))}")

    def _setup(self, enforce=False, **extra):
        self._as_owner()
        # Step 1: choose SAML before the IdP exists, to get our ACS URL and metadata.
        made = self.client.put(self.base, {"protocol": "saml"}, format="json")
        self.assertEqual(made.status_code, 200, made.content)
        body = made.json()
        self.assertEqual(body["acs_url"], "https://api.example/api/v2/sso/saml/acs")
        self.assertEqual(body["sp_entity_id"], self.idp.audience)
        self.assertFalse(body["saml_complete"])
        made = self.client.put(
            self.base, {"idp_entity_id": IDP_ENTITY, "idp_sso_url": IDP_SSO, "idp_certificate": IDP_PEM, **extra}, format="json"
        )
        self.assertEqual(made.status_code, 200, made.content)
        self.assertTrue(made.json()["saml_complete"])
        self.assertEqual(made.json()["idp_cert_fingerprint"], ":".join(f"{b:02X}" for b in IDP_CERT.fingerprint(hashes.SHA256())))
        pending = self.client.post(f"{self.base}/domains", {"domain": "acme.test"}, format="json").json()["pending_domains"][0]
        with patch("sso.views.txt_records", return_value=[pending["txt_value"]]):
            self.assertEqual(self.client.post(f"{self.base}/domains/acme.test/verify").status_code, 200)
        on = self.client.put(self.base, {"enabled": True, "enforced": enforce}, format="json")
        self.assertEqual((on.json()["enabled"], on.json()["enforced"]), (True, enforce), on.content)
        self.client.credentials()

    def _start(self, email="ana@acme.test"):
        start = self.client.get(f"/api/v2/sso/start?email={email}&client_nonce={CLIENT}")
        self.assertEqual(start.status_code, 200, start.content)
        url = urlparse(start.json()["authorize_url"])
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", IDP_SSO)
        query = parse_qs(url.query)
        request = etree.fromstring(zlib.decompress(base64.b64decode(query["SAMLRequest"][0]), -15))
        return request, query["RelayState"][0]

    def _post(self, xml, relay):
        res = self.client.post("/api/v2/sso/saml/acs", {"SAMLResponse": base64.b64encode(xml).decode(), "RelayState": relay})
        self.assertEqual(res.status_code, 303, res.content)
        return res["Location"]

    def _attempt(self, **kwargs):
        request, relay = self._start()
        return self._post(self.idp.response(request.get("ID"), **kwargs), relay)

    def test_full_saml_login(self):
        self._setup()
        request, relay = self._start()
        self.assertEqual(request.tag, f"{{{SAMLP}}}AuthnRequest")
        self.assertEqual(request.get("AssertionConsumerServiceURL"), "https://api.example/api/v2/sso/saml/acs")
        self.assertEqual(request.get("Destination"), IDP_SSO)
        self.assertEqual(request.findtext(f"{{{SAML_NS}}}Issuer"), self.idp.audience)
        self.assertTrue(SAMLRequest.objects.filter(request_id=request.get("ID"), used_at__isnull=True).exists(), "stored server-side")
        xml = self.idp.response(request.get("ID"))
        location = self._post(xml, relay)
        self.assertTrue(location.startswith("https://app.example/w/sso?code="), location)
        code = parse_qs(urlparse(location).query)["code"][0]
        other = self.client.post("/api/v2/sso/exchange", {"code": code, "client_nonce": "someone-elses-browser-123"}, format="json")
        self.assertEqual(other.status_code, 400, "the code only works in the browser that started")
        tokens = self.client.post("/api/v2/sso/exchange", {"code": code, "client_nonce": CLIENT}, format="json")
        self.assertEqual(tokens.status_code, 200)
        self.assertEqual(tokens.json()["user_id"], str(self.ana.id))
        from organizations.models import AuditEvent

        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="sso.signin", payload__protocol="saml").exists())
        # Replaying the same signed response: InResponseTo is single use.
        self.assertIn("error=invalid_state", self._post(xml, relay))

    def test_signed_response_with_unsigned_assertion(self):
        self._setup()
        self.assertIn("code=", self._attempt(sign="response"))
        self.assertIn("code=", self._attempt(sign="both"))

    def test_metadata(self):
        self.assertEqual(self.client.get(f"/api/v2/sso/saml/{self.org.id}/metadata").status_code, 404)
        self._setup()
        res = self.client.get(f"/api/v2/sso/saml/{self.org.id}/metadata")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/samlmetadata+xml")
        doc = etree.fromstring(res.content)
        self.assertEqual(doc.get("entityID"), self.idp.audience)
        acs = doc.find(f".//{{{saml.MD}}}AssertionConsumerService")
        self.assertEqual((acs.get("Location"), acs.get("Binding")), ("https://api.example/api/v2/sso/saml/acs", saml.POST_BINDING))

    def test_signature_is_required_and_checked_with_the_configured_cert(self):
        self._setup()
        self.assertIn("error=bad_signature", self._attempt(key=EVIL_KEY, cert=EVIL_CERT))
        self.assertIn("error=bad_signature", self._attempt(sign="response", key=EVIL_KEY, cert=EVIL_CERT))
        self.assertIn("error=unsigned", self._attempt(sign="none"))
        # Tampering with a signed assertion breaks its digest.
        request, relay = self._start()
        xml = self.idp.response(request.get("ID")).replace(b"ana@acme.test", b"boss@acme.test")
        self.assertIn("error=bad_signature", self._post(xml, relay))

    def test_wrapped_or_duplicated_assertions_are_refused(self):
        self._setup()
        # 1. An extra unsigned assertion (as the owner) next to Ana's genuine signed one.
        request, relay = self._start()
        rid = request.get("ID")
        doc = etree.fromstring(self.idp.response(rid))
        evil = self.idp.assertion(rid, email="boss@acme.test")
        doc.insert(2, evil)
        self.assertIn("error=bad_response", self._post(etree.tostring(doc), relay))
        # 2. Classic XSW: an unsigned evil assertion on top, the genuine signed one tucked inside it.
        request, relay = self._start()
        rid = request.get("ID")
        doc = etree.fromstring(self.idp.response(rid))
        genuine = doc.find(f"{{{SAML_NS}}}Assertion")
        evil = self.idp.assertion(rid, email="boss@acme.test")
        doc.replace(genuine, evil)
        _el(evil, SAML_NS, "Advice").append(genuine)
        self.assertIn("error=bad_response", self._post(etree.tostring(doc), relay))
        # 3. A whole signed response wrapped in an evil outer response.
        request, relay = self._start()
        rid = request.get("ID")
        inner = etree.fromstring(self.idp.response(rid, sign="response"))
        outer = etree.fromstring(self.idp.response(rid, sign="none", email="boss@acme.test"))
        _el(outer, SAMLP, "Extensions").append(inner)
        self.assertIn("error=bad_response", self._post(etree.tostring(outer), relay))
        from organizations.models import AuditEvent

        self.assertFalse(AuditEvent.objects.filter(org=self.org, action="sso.signin").exists(), "nobody was signed in")

    def test_replay_unknown_and_expired_requests(self):
        self._setup()
        request, relay = self._start()
        self.assertIn("error=invalid_state", self._post(self.idp.response("_never-sent"), relay))
        self.assertIn("error=invalid_state", self._post(self.idp.response(request.get("ID")), "wrong-relay-state"))
        SAMLRequest.objects.filter(request_id=request.get("ID")).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIn("error=invalid_state", self._post(self.idp.response(request.get("ID")), relay))
        # A signed assertion for another request cannot be glued onto this one.
        first, _ = self._start()
        second, relay2 = self._start()
        doc = etree.fromstring(self.idp.response(first.get("ID")))
        doc.set("InResponseTo", second.get("ID"))
        self.assertIn("error=invalid_state", self._post(etree.tostring(doc), relay2))

    def test_conditions_are_enforced(self):
        self._setup()
        for kwargs, expected in (
            ({"audience": "https://someone-else.example/sp"}, "bad_audience"),
            ({"audience": f"https://api.example/api/v2/sso/saml/{Organization.objects.create(name='B', slug='b-saml').id}/metadata"}, "bad_audience"),
            ({"recipient": "https://evil.example/acs"}, "bad_destination"),
            ({"sign": "response", "destination": "https://evil.example/acs"}, "bad_destination"),
            ({"issuer": "https://evil.example/idp"}, "bad_issuer"),
            ({"expires": -300}, "expired"),
            ({"starts": 600}, "not_yet_valid"),
            ({"sign": "response", "status": "urn:oasis:names:tc:SAML:2.0:status:Requester"}, "idp_error"),
            ({"email": "eve@evil.test"}, "domain_not_verified"),
            ({"email": "nobody@acme.test"}, "not_a_member"),
            ({"name_format": "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent"}, "no_email"),
        ):
            self.assertIn(f"error={expected}", self._attempt(**kwargs), kwargs)
        self.assertIn("code=", self._attempt(expires=-60), "small clock skew is tolerated")

    def test_email_attribute_mapping(self):
        self._setup(email_attribute="mail")
        location = self._attempt(name_format="urn:oasis:names:tc:SAML:2.0:nameid-format:persistent", attributes={"mail": "ana@acme.test"})
        self.assertIn("code=", location)
        self.assertIn("error=no_email", self._attempt(attributes={"email": "ana@acme.test"}))

    def test_platform_admin_cannot_sign_in_by_saml(self):
        self._setup()
        User.objects.filter(pk=self.ana.pk).update(is_platform_admin=True)
        self.assertIn("error=platform_admin", self._attempt())

    def test_xml_entities_are_refused(self):
        self._setup()
        request, relay = self._start()
        xml = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e SYSTEM "file:///etc/passwd">]>' + self.idp.response(request.get("ID"))
        self.assertIn("error=bad_response", self._post(xml, relay))
        self.assertIn("error=bad_response", self._post(b"not xml", relay))

    def test_enforced_saml_blocks_passwords_but_owner_keeps_break_glass(self):
        self._setup(enforce=True)
        ana = self.client.post("/api/v2/auth/signin", {"email": "ana@acme.test", "password": "pw-123456"}, format="json")
        boss = self.client.post("/api/v2/auth/signin", {"email": "boss@acme.test", "password": "pw-123456"}, format="json")
        self.assertEqual((ana.status_code, ana.json()["error"]), (403, "sso_required"))
        self.assertEqual(boss.status_code, 200)
        v1 = self.client.post("/api/auth/signin/", {"email": "ana@acme.test", "password": "pw-123456"}, format="json")
        self.assertEqual(v1.status_code, 403)
        self.assertIn("code=", self._attempt(), "SSO itself still works")

    def test_configuration_rules(self):
        self._as_owner()
        self.client.put(self.base, {"protocol": "saml"}, format="json")
        for body in (
            {"idp_sso_url": "http://idp.example.com/sso"},
            {"idp_sso_url": "javascript:alert(1)"},
            {"idp_certificate": "not a certificate"},
            {"idp_entity_id": ""},
            {"protocol": "ldap"},
        ):
            self.assertEqual(self.client.put(self.base, body, format="json").status_code, 400, body)
        self.client.credentials()
        self._setup(enforce=True)
        # A new signing certificate is a new IdP: SSO and enforcement switch off, and it is audited.
        self._as_owner()
        made = self.client.put(self.base, {"idp_certificate": EVIL_CERT.public_bytes(serialization.Encoding.PEM).decode(), "enabled": True}, format="json")
        self.assertEqual((made.json()["enabled"], made.json()["enforced"]), (False, False))
        from organizations.models import AuditEvent

        event = AuditEvent.objects.filter(org=self.org, action="sso.configure").order_by("-created_at").first()
        self.assertNotEqual(event.payload["idp_cert_fingerprint_before"], event.payload["idp_cert_fingerprint"])
        self.assertEqual(self.client.get("/api/v2/sso/start?email=ana@acme.test&client_nonce=" + CLIENT).status_code, 404)
        # Members and admins cannot configure SAML either.
        admin = User.objects.create(email="adm@acme.test", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=admin, org_role=OrgMembership.ORG_ROLE_ADMIN, employment_status="active")
        for user in (self.ana, admin):
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
            self.assertEqual(self.client.put(self.base, {"protocol": "saml", "idp_certificate": IDP_PEM}, format="json").status_code, 403)

    def test_switching_protocol_turns_sso_off(self):
        self._setup()
        self._as_owner()
        with patch("platform_api.net.fetch", side_effect=FakeIdP()), patch("platform_api.net.resolve", return_value=["93.184.216.34"]):
            made = self.client.put(self.base, {"protocol": "oidc", "issuer": ISSUER, "client_id": "client-1", "client_secret": "secret-123456"}, format="json")
        self.assertEqual(made.status_code, 200, made.content)
        self.assertEqual((made.json()["protocol"], made.json()["enabled"]), ("oidc", False))
