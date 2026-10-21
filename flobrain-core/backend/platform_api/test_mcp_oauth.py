"""MCP authorization (growth round M1): metadata, dynamic client registration, authorization code
with PKCE, consent, resource binding, rotating refresh tokens with reuse detection, revocation."""

import base64
import hashlib
import json
import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization
from platform_api.models import OAuthAccessToken, OAuthAuthorizationCode, OAuthClient, OAuthGrant, OAuthRefreshToken
from users.jwt_utils import make_access_token
from users.models import User

RESOURCE = "http://testserver/api/mcp"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def _user(email):
    return User.objects.create(email=email, username=email.split("@")[0], password_hash=make_password("x"))


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


@override_settings(FRONTEND_BASE_URL="https://app.example.com", PUBLIC_API_BASE_URL="")
class OAuthBase(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="Hub", slug="hub-org", settings={"flags": {"mcp_hub": True, "api_access": True}})
        self.off = Organization.objects.create(name="Off", slug="off-org", settings={"flags": {}})
        self.member = _user("hub-m@example.com")
        self.stranger = _user("hub-s@example.com")
        for org in (self.org, self.off):
            OrgMembership.objects.create(org=org, user=self.member, org_role="member", employment_status="active")
        self.anon = APIClient()

    def web(self, user):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return c

    def register(self, **extra):
        body = {"client_name": "Claude", "redirect_uris": [REDIRECT], **extra}
        return self.anon.post("/oauth/register", body, format="json")

    def authorize(self, client_id, challenge, redirect=REDIRECT, **extra):
        params = {
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect, "code_challenge": challenge,
            "code_challenge_method": "S256", "state": "xyz", "resource": RESOURCE, "scope": "mcp tasks:read", **extra,
        }
        return self.anon.get("/oauth/authorize", {k: v for k, v in params.items() if v is not None})

    def consent(self, signed, user=None, decision="approve", org=None, **extra):
        body = {"request": signed, "decision": decision, "org": str((org or self.org).id), **extra}
        return self.web(user or self.member).post("/api/v2/mcp/consent", body, format="json")

    def code_for(self, client_id=None, scope="mcp tasks:read"):
        client_id = client_id or self.register().json()["client_id"]
        verifier, challenge = pkce()
        signed = query(self.authorize(client_id, challenge, scope=scope)["Location"])["request"]
        redirect = self.consent(signed).json()["redirect"]
        return client_id, verifier, query(redirect)["code"]

    def exchange(self, client_id, code, verifier, redirect=REDIRECT, **extra):
        body = {"grant_type": "authorization_code", "client_id": client_id, "code": code, "code_verifier": verifier, "redirect_uri": redirect, **extra}
        return self.anon.post("/oauth/token", body)  # form-encoded, as OAuth requires

    def tokens(self, scope="mcp tasks:read"):
        client_id, verifier, code = self.code_for(scope=scope)
        response = self.exchange(client_id, code, verifier)
        self.assertEqual(response.status_code, 200, response.content)
        return client_id, response.json()

    def mcp(self, access, method="tools/list", params=None):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return c.post("/api/mcp", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, format="json")


class MetadataTests(OAuthBase):
    def test_protected_resource_and_authorization_server_metadata(self):
        for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/api/mcp"):
            doc = self.anon.get(path).json()
            self.assertEqual(doc["resource"], RESOURCE)
            self.assertEqual(doc["authorization_servers"], ["http://testserver"])
            self.assertIn("mcp", doc["scopes_supported"])
            self.assertEqual(doc["bearer_methods_supported"], ["header"])
        meta = self.anon.get("/.well-known/oauth-authorization-server").json()
        self.assertEqual(meta["issuer"], "http://testserver")
        self.assertEqual(meta["code_challenge_methods_supported"], ["S256"], "PKCE S256 only")
        self.assertEqual(meta["response_types_supported"], ["code"])
        self.assertEqual(set(meta["grant_types_supported"]), {"authorization_code", "refresh_token"})
        for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"):
            self.assertTrue(meta[key].startswith("http://testserver/oauth/"))

    def test_unauthenticated_mcp_points_to_the_metadata(self):
        response = self.anon.post("/api/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize"}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertIn('resource_metadata="http://testserver/.well-known/oauth-protected-resource/api/mcp"', response["WWW-Authenticate"])
        bad = self.mcp("fba_not-a-token")
        self.assertEqual(bad.status_code, 401)
        self.assertIn("resource_metadata=", bad["WWW-Authenticate"])

    @override_settings(PUBLIC_API_BASE_URL="https://api.flobrain.example")
    def test_configured_public_base_wins(self):
        self.assertEqual(self.anon.get("/.well-known/oauth-protected-resource").json()["resource"], "https://api.flobrain.example/api/mcp")


class RegistrationTests(OAuthBase):
    @override_settings(MCP_OAUTH_REGISTER_RATE="100/hour")  # failed attempts count toward the limit too
    def test_redirect_uri_rules(self):
        for bad in (
            ["http://evil.example.com/cb"],
            ["myapp://callback"],
            ["https://claude.ai/cb#frag"],
            ["https://user:pw@claude.ai/cb"],
            ["javascript:alert(1)"],
            [],
            ["https://a.example.com/cb"] * 6,
            "https://claude.ai/cb",
        ):
            response = self.anon.post("/oauth/register", {"client_name": "X", "redirect_uris": bad}, format="json")
            self.assertEqual(response.status_code, 400, bad)
            self.assertEqual(response.json()["error"], "invalid_redirect_uri")
        for good in ("http://localhost:6274/callback", "http://127.0.0.1:33418/cb", "http://[::1]:8080/cb", "https://chatgpt.com/connector_platform_oauth_redirect"):
            self.assertEqual(self.register(redirect_uris=[good]).status_code, 201, good)

    def test_metadata_validation_and_public_clients(self):
        self.assertEqual(self.register(token_endpoint_auth_method="private_key_jwt").json()["error"], "invalid_client_metadata")
        self.assertEqual(self.register(grant_types=["client_credentials"]).status_code, 400)
        self.assertEqual(self.register(response_types=["token"]).status_code, 400)
        self.assertEqual(self.register(client_name=["x"]).status_code, 400)
        made = self.register(client_name="Claude\x00\x1b[31m", scope="mcp tasks:read bogus")
        self.assertEqual(made.status_code, 201)
        body = made.json()
        self.assertTrue(body["client_id"].startswith("fbc_"))
        self.assertNotIn("client_secret", body, "public clients get no secret")
        self.assertEqual(body["token_endpoint_auth_method"], "none")
        client = OAuthClient.objects.get(client_id=body["client_id"])
        self.assertEqual(client.name, "Claude[31m", "control characters stripped")
        self.assertEqual(client.scope, "mcp tasks:read", "unknown scopes dropped")

    def test_confidential_client_secret_is_hashed_and_checked(self):
        body = self.register(token_endpoint_auth_method="client_secret_post").json()
        self.assertTrue(body["client_secret"].startswith("fbs_"))
        self.assertNotIn(body["client_secret"], json.dumps(list(OAuthClient.objects.values()), default=str))
        response = self.anon.post("/oauth/token", {"grant_type": "authorization_code", "client_id": body["client_id"], "client_secret": "fbs_wrong", "code": "x"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "invalid_client")

    @override_settings(MCP_OAUTH_REGISTER_RATE="3/hour")
    def test_registration_is_rate_limited_per_ip(self):
        codes = [self.register().status_code for _ in range(4)]
        self.assertEqual(codes, [201, 201, 201, 429])

    @override_settings(MCP_OAUTH_MAX_CLIENTS_PER_DAY=2)
    def test_daily_cap(self):
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register().status_code, 201)
        capped = self.register()
        self.assertEqual(capped.status_code, 429)
        self.assertEqual(capped.json()["error"], "temporarily_unavailable")


class AuthorizeAndConsentTests(OAuthBase):
    def test_unknown_client_or_redirect_never_redirects_to_the_app(self):
        _, challenge = pkce()
        client_id = self.register().json()["client_id"]
        for response in (self.authorize("fbc_nope", challenge), self.authorize(client_id, challenge, redirect="https://claude.ai/api/mcp/auth_callback/x")):
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response["Location"].startswith("https://app.example.com/w/oauth/consent?error="))

    def test_pkce_s256_and_response_type_are_required(self):
        client_id = self.register().json()["client_id"]
        _, challenge = pkce()
        for extra, error in (
            ({"code_challenge": None}, "invalid_request"),
            ({"code_challenge_method": "plain"}, "invalid_request"),
            ({"code_challenge": "short"}, "invalid_request"),
            ({"response_type": "token"}, "unsupported_response_type"),
            ({"resource": "https://other.example.com/mcp"}, "invalid_target"),
        ):
            location = self.authorize(client_id, challenge, **extra)["Location"]
            self.assertTrue(location.startswith(REDIRECT), extra)
            q = query(location)
            self.assertEqual((q["error"], q["state"], q["iss"]), (error, "xyz", "http://testserver"))

    def test_consent_screen_data_and_org_picker(self):
        client_id = self.register(client_name="Claude").json()["client_id"]
        _, challenge = pkce()
        location = self.authorize(client_id, challenge, scope="mcp tasks:read rooms:write")["Location"]
        self.assertTrue(location.startswith("https://app.example.com/w/oauth/consent?request="))
        signed = query(location)["request"]
        self.assertEqual(self.anon.get("/api/v2/mcp/consent", {"request": signed}).status_code, 401, "signed-in people only")
        info = self.web(self.member).get("/api/v2/mcp/consent", {"request": signed}).json()
        self.assertEqual(info["client"]["name"], "Claude")
        self.assertEqual(info["client"]["redirect_host"], "claude.ai")
        self.assertEqual([s["key"] for s in info["scopes"]], ["mcp", "tasks:read", "rooms:write"])
        self.assertTrue(all(s["label"] for s in info["scopes"]))
        orgs = {o["slug"]: o["available"] for o in info["orgs"]}
        self.assertEqual(orgs, {"hub-org": True, "off-org": False})
        self.assertEqual(self.web(self.member).get("/api/v2/mcp/consent", {"request": signed + "x"}).status_code, 400, "tampered")

    def test_consent_answers(self):
        client_id = self.register().json()["client_id"]
        _, challenge = pkce()
        signed = query(self.authorize(client_id, challenge)["Location"])["request"]
        denied = query(self.consent(signed, decision="deny").json()["redirect"])
        self.assertEqual((denied["error"], denied["state"]), ("access_denied", "xyz"))
        self.assertEqual(self.consent(signed, org=self.off).status_code, 501, "org without the hub")
        self.assertEqual(self.consent(signed, user=self.stranger).status_code, 404, "not a member")
        self.assertEqual(self.consent(signed, scopes=["mcp", "tasks:write"]).status_code, 400, "cannot add scopes")
        ok = self.consent(signed, scopes=[])
        self.assertEqual(ok.status_code, 200)
        q = query(ok.json()["redirect"])
        self.assertTrue(q["code"].startswith("fbo_"))
        self.assertEqual(OAuthGrant.objects.get().scopes, ["mcp"], "unticked scopes are not granted")
        self.assertFalse(OAuthAuthorizationCode.objects.filter(code_hash=q["code"]).exists(), "codes are hashed")


class TokenTests(OAuthBase):
    def test_happy_path_and_hashing_at_rest(self):
        _, body = self.tokens()
        self.assertEqual(body["token_type"], "Bearer")
        self.assertEqual(body["expires_in"], 3600)
        self.assertTrue(body["access_token"].startswith("fba_") and body["refresh_token"].startswith("fbr_"))
        dump = json.dumps([list(m.objects.values()) for m in (OAuthAccessToken, OAuthRefreshToken, OAuthAuthorizationCode)], default=str)
        self.assertNotIn(body["access_token"], dump)
        self.assertNotIn(body["refresh_token"], dump)
        token = OAuthAccessToken.objects.get()
        self.assertAlmostEqual((token.expires_at - timezone.now()).total_seconds(), 3600, delta=30)
        listed = self.mcp(body["access_token"])
        self.assertEqual(listed.status_code, 200, listed.content)
        names = {t["name"] for t in listed.json()["result"]["tools"]}
        self.assertIn("tasks_list", names)
        self.assertNotIn("tasks_create", names, "only granted scopes")

    def test_pkce_verifier_is_checked(self):
        client_id, verifier, code = self.code_for()
        self.assertEqual(self.exchange(client_id, code, "a" * 50).json()["error"], "invalid_grant")
        self.assertEqual(self.exchange(client_id, code, "").json()["error"], "invalid_grant")
        self.assertEqual(self.exchange(client_id, code, verifier).status_code, 200, "a failed verifier does not burn the code")

    def test_code_is_single_use_and_reuse_revokes(self):
        client_id, verifier, code = self.code_for()
        first = self.exchange(client_id, code, verifier).json()
        second = self.exchange(client_id, code, verifier)
        self.assertEqual(second.json()["error"], "invalid_grant")
        self.assertEqual(self.mcp(first["access_token"]).status_code, 401, "reusing a code stops what it issued")
        self.assertEqual(OAuthGrant.objects.get().revoked_reason, "code_reused")

    def test_code_expiry_redirect_and_client_binding(self):
        client_id, verifier, code = self.code_for()
        other = self.register().json()["client_id"]
        self.assertEqual(self.exchange(other, code, verifier).json()["error"], "invalid_grant", "another client")
        self.assertEqual(self.exchange(client_id, code, verifier, redirect=REDIRECT + "/").json()["error"], "invalid_grant", "exact redirect")
        self.assertEqual(self.exchange(client_id, code, verifier, resource="https://other.example.com/mcp").json()["error"], "invalid_target")
        OAuthAuthorizationCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.exchange(client_id, code, verifier).json()["error"], "invalid_grant")
        self.assertEqual(self.anon.post("/oauth/token", {"grant_type": "password", "client_id": client_id}).json()["error"], "unsupported_grant_type")

    def test_token_for_another_resource_is_refused(self):
        _, body = self.tokens()
        OAuthAccessToken.objects.update(resource="https://other.example.com/api/mcp")
        response = self.mcp(body["access_token"])
        self.assertEqual(response.status_code, 401)
        self.assertIn("another resource", response.content.decode())

    def test_refresh_rotation_and_reuse_detection(self):
        client_id, first = self.tokens()
        refreshed = self.anon.post("/oauth/token", {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": first["refresh_token"]})
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        second = refreshed.json()
        self.assertNotEqual(second["refresh_token"], first["refresh_token"])
        self.assertEqual(self.mcp(second["access_token"]).status_code, 200)
        widen = self.anon.post("/oauth/token", {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": second["refresh_token"], "scope": "mcp tasks:write"})
        self.assertEqual(widen.json()["error"], "invalid_scope")
        reused = self.anon.post("/oauth/token", {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": first["refresh_token"]})
        self.assertEqual(reused.json()["error"], "invalid_grant")
        self.assertEqual(self.mcp(second["access_token"]).status_code, 401, "the whole family is revoked")
        after = self.anon.post("/oauth/token", {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": second["refresh_token"]})
        self.assertEqual(after.json()["error"], "invalid_grant")
        self.assertEqual(OAuthGrant.objects.get().revoked_reason, "refresh_reused")

    def test_access_token_expiry(self):
        _, body = self.tokens()
        OAuthAccessToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.mcp(body["access_token"]).status_code, 401)

    def test_revoke_endpoint(self):
        client_id, body = self.tokens()
        self.assertEqual(self.anon.post("/oauth/revoke", {"client_id": client_id, "token": body["access_token"]}).status_code, 200)
        self.assertEqual(self.mcp(body["access_token"]).status_code, 401)
        self.assertEqual(self.anon.post("/oauth/revoke", {"client_id": client_id, "token": "fbr_unknown"}).status_code, 200, "unknown tokens: 200")
        other = self.register().json()["client_id"]
        self.anon.post("/oauth/revoke", {"client_id": other, "token": body["refresh_token"]})
        self.assertIsNone(OAuthGrant.objects.get().revoked_at, "another client cannot revoke it")
        self.anon.post("/oauth/revoke", {"client_id": client_id, "token": body["refresh_token"]})
        self.assertIsNotNone(OAuthGrant.objects.get().revoked_at)
        again = self.anon.post("/oauth/token", {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": body["refresh_token"]})
        self.assertEqual(again.json()["error"], "invalid_grant")

    def test_password_change_membership_and_flag(self):
        _, body = self.tokens()
        self.org.settings = {"flags": {"mcp_hub": False}}
        self.org.save()
        self.assertEqual(self.mcp(body["access_token"]).status_code, 501, "flag off")
        self.org.settings = {"flags": {"mcp_hub": True}}
        self.org.save()
        self.assertEqual(self.mcp(body["access_token"]).status_code, 200)
        self.member.password_changed_at = timezone.now() + timedelta(seconds=1)
        self.member.save()
        self.assertEqual(self.mcp(body["access_token"]).status_code, 401)
        self.assertEqual(OAuthGrant.objects.get().revoked_reason, "password_changed")

    def test_leaving_the_org_revokes(self):
        _, body = self.tokens()
        OrgMembership.objects.filter(org=self.org, user=self.member).update(employment_status="inactive")
        self.assertEqual(self.mcp(body["access_token"]).status_code, 401)
        self.assertEqual(OAuthGrant.objects.get().revoked_reason, "membership_ended")

    def test_personal_access_tokens_keep_working(self):
        c = self.web(self.member)
        raw = c.post("/api/v2/me/tokens", {"org": str(self.org.id), "name": "cli", "scopes": ["mcp", "tasks:read"]}, format="json").json()["token"]
        self.assertEqual(self.mcp(raw).status_code, 200)
