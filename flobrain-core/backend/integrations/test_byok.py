import json
import logging
import socket
import urllib.error
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from brain.models import Chat
from integrations import crypto
from integrations.models import AICredential
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.services import ensure_team_room
from telemetry.models import Budget, UsageEvent
from users.jwt_utils import make_access_token
from users.models import User

TEST_KEY = "ab" * 32  # test-only, never a real key
SECRET = "sk-test-NOT-REAL-9f8e7d6c5b4a1234"
SECRET2 = "sk-test-NOT-REAL-rotated-00005678"


class _Body:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _ok_models(request, timeout=None):
    return _Body({"data": [{"id": "gpt-4o-mini"}]})


def _http_error(code):
    def raise_it(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, code, "err", hdrs=None, fp=BytesIO(b"{}"))

    return raise_it


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@override_settings(CREDENTIALS_ENCRYPTION_KEY=TEST_KEY)
class ByokBase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="B Org", slug="b-org", settings={"flags": {"byok": True, "room_ai": True}}
        )
        self.owner = User.objects.create(email="b-owner@example.com", password_hash=make_password("x"))
        self.admin = User.objects.create(email="b-admin@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="b-m@example.com", password_hash=make_password("x"))
        self.other = User.objects.create(email="b-o@example.com", password_hash=make_password("x"))
        self.outsider = User.objects.create(email="b-out@example.com", password_hash=make_password("x"))
        for user, role in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER),
            (self.admin, OrgMembership.ORG_ROLE_ADMIN),
            (self.member, OrgMembership.ORG_ROLE_MEMBER),
            (self.other, OrgMembership.ORG_ROLE_MEMBER),
        ):
            OrgMembership.objects.create(
                org=self.org, user=user, org_role=role, employment_status=OrgMembership.STATUS_ACTIVE
            )
        self.base = f"/api/v2/orgs/{self.org.id}"
        self.url = f"{self.base}/credentials"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _create(self, user, opener=_ok_models, **body):
        self._auth(user)
        data = {"provider": "openai", "secret": SECRET, "label": "mine", **body}
        with patch("integrations.credentials.open_customer", side_effect=opener) as opened:
            response = self.client.post(self.url, data, format="json")
        return response, opened


class CredentialApiTests(ByokBase):
    def test_flag_off_and_missing_key_are_501(self):
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        self._auth(self.member)
        self.assertEqual(self.client.get(self.url).status_code, 501)
        self.org.settings = {"flags": {"byok": True}}
        self.org.save(update_fields=["settings"])
        with override_settings(CREDENTIALS_ENCRYPTION_KEY=""):
            response, opened = self._create(self.member)
        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["error"], "not_configured")
        opened.assert_not_called()
        with override_settings(CREDENTIALS_ENCRYPTION_KEY="0" * 64):
            self.assertEqual(self._create(self.member)[0].status_code, 501, "all-zero key is refused")

    def test_outsider_is_403(self):
        self._auth(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_create_personal_key_is_checked_and_never_returned(self):
        response, opened = self._create(self.member)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["status"], "active")
        self.assertEqual(body["scope"], "personal")
        self.assertEqual(body["last4"], SECRET[-4:])
        self.assertEqual(body["base_url"], "https://api.openai.com")
        self.assertNotIn(SECRET, json.dumps(body))
        request = opened.call_args[0][0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/models")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {SECRET}")
        row = AICredential.objects.get(pk=body["id"])
        self.assertNotIn(SECRET.encode(), bytes(row.ciphertext))
        self.assertEqual(row.api_key(), SECRET)
        self.assertNotIn(SECRET, repr(row))
        listed = self.client.get(self.url).json()
        self.assertNotIn(SECRET, json.dumps(listed))

    def test_ciphertext_is_bound_to_its_row(self):
        response, _ = self._create(self.member)
        row = AICredential.objects.get(pk=response.json()["id"])
        copy = AICredential.objects.create(
            org=self.org, owner=self.other, base_url=row.base_url, ciphertext=row.ciphertext, last4="xxxx"
        )
        with self.assertRaises(crypto.CredentialCryptoError):
            copy.api_key()

    def test_personal_key_is_invisible_to_everyone_else(self):
        key_id = self._create(self.member)[0].json()["id"]
        for user in (self.other, self.owner, self.admin):
            self._auth(user)
            self.assertNotIn(key_id, {row["id"] for row in self.client.get(self.url).json()}, user.email)
            patched = self.client.patch(f"{self.url}/{key_id}", {"label": "x"}, format="json")
            self.assertEqual(patched.status_code, 404, user.email)
            self.assertEqual(self.client.delete(f"{self.url}/{key_id}").status_code, 404, user.email)
        self.assertTrue(AICredential.objects.filter(pk=key_id).exists())

    def test_org_key_rules(self):
        denied, opened = self._create(self.member, scope="org")
        self.assertEqual(denied.status_code, 403)
        opened.assert_not_called()
        created, _ = self._create(self.owner, scope="org")
        self.assertEqual(created.status_code, 201)
        key_id = created.json()["id"]
        self._auth(self.admin)
        self.assertIn(key_id, {row["id"] for row in self.client.get(self.url).json()})
        self._auth(self.member)
        self.assertNotIn(key_id, {row["id"] for row in self.client.get(self.url).json()})
        self.assertEqual(self.client.patch(f"{self.url}/{key_id}", {"label": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"{self.url}/{key_id}").status_code, 403)

    def test_check_states(self):
        cases = (
            (_http_error(401), "rejected"),
            (_http_error(404), "rejected"),
            (_http_error(429), "indeterminate"),
            (_http_error(503), "indeterminate"),
            (_http_error(302), "indeterminate"),
        )
        for opener, expected in cases:
            response, _ = self._create(self.member, opener=opener)
            self.assertEqual(response.json()["status"], expected)

        def timeout(request, timeout=None):
            raise socket.timeout("slow")

        self.assertEqual(self._create(self.member, opener=timeout)[0].json()["status"], "indeterminate")

    def test_check_uses_the_configured_timeout(self):
        with override_settings(BYOK_CHECK_TIMEOUT=20):
            _, opened = self._create(self.member)
        self.assertEqual(opened.call_args.kwargs["timeout"], 20)

    def test_base_url_must_be_https_and_allowlisted(self):
        for base in (
            "http://api.openai.com",
            "https://169.254.169.254",
            "https://internal.example",
            "https://user:pw@api.openai.com",
            "https://api.openai.com:8443",
            "https://api.openai.com/../admin",
        ):
            response, opened = self._create(self.member, provider="openai_compatible", base_url=base)
            self.assertEqual(response.status_code, 400, base)
            opened.assert_not_called()
        response, _ = self._create(self.member, provider="openai_compatible", base_url="https://openrouter.ai/v1")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["base_url"], "https://openrouter.ai")

    def test_secret_validation(self):
        for secret in ("short", "has space inside 12345", "x" * 600):
            response, opened = self._create(self.member, secret=secret)
            self.assertEqual(response.status_code, 400)
            opened.assert_not_called()

    def test_disable_enable_rotate(self):
        key_id = self._create(self.member)[0].json()["id"]
        self._auth(self.member)
        disabled = self.client.patch(f"{self.url}/{key_id}", {"status": "disabled"}, format="json")
        self.assertEqual(disabled.json()["status"], "disabled")
        with patch("integrations.credentials.open_customer", side_effect=_ok_models):
            enabled = self.client.patch(f"{self.url}/{key_id}", {"status": "enabled"}, format="json")
        self.assertEqual(enabled.json()["status"], "active")
        with patch("integrations.credentials.open_customer", side_effect=_http_error(401)):
            rotated = self.client.patch(f"{self.url}/{key_id}", {"secret": SECRET2}, format="json")
        self.assertEqual(rotated.json()["last4"], SECRET2[-4:])
        self.assertEqual(rotated.json()["status"], "rejected", "a failed check never leaves a key active")
        self.assertEqual(AICredential.objects.get(pk=key_id).api_key(), SECRET2)
        deleted = self.client.delete(f"{self.url}/{key_id}")
        self.assertEqual(deleted.status_code, 204)

    def test_expired_key(self):
        past = (timezone.now() - timedelta(days=1)).isoformat()
        response, opened = self._create(self.member, expires_at=past)
        self.assertEqual(response.json()["status"], "expired")
        opened.assert_not_called()


@override_settings(CREDENTIALS_ENCRYPTION_KEY=TEST_KEY, AI_PROVIDER_BACKEND="multimodal_legacy")
class CredentialUseTests(ByokBase):
    def setUp(self):
        super().setUp()
        team = Team.objects.create(org=self.org, name="Alpha")
        TeamMembership.objects.create(team=team, user=self.member)
        TeamMembership.objects.create(team=team, user=self.other)
        self.room = ensure_team_room(team)
        self.key_id = self._create(self.member)[0].json()["id"]
        self.chat = Chat.objects.create(user=self.member, org=self.org, room=self.room, title="t")
        self.send_url = f"{self.base}/ai/threads/{self.chat.id}/send"

    def _send(self, user, opener=None, **body):
        self._auth(user)
        calls = []

        def provider(request, timeout=None):
            calls.append(request)
            return _Body({
                "model": "gpt-4o-mini",
                "choices": [{"message": {"role": "assistant", "content": "hi from your key"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            })

        with patch("brain.llm.http.open_customer", side_effect=opener or provider), patch(
            "brain.llm.multimodal_adapter.MultimodalLLMAdapter.generate"
        ) as legacy, patch("urllib.request.urlopen") as platform:
            response = self.client.post(self.send_url, {"text": "hello", **body}, format="json")
        return response, calls, legacy, platform

    def test_model_list_shows_own_active_keys_only(self):
        self._auth(self.member)
        providers = self.client.get(f"{self.base}/ai/models").json()["providers"]
        self.assertEqual([p["credential_id"] for p in providers], [self.key_id])
        self.assertNotIn(SECRET, json.dumps(providers))
        self._auth(self.owner)
        self.assertEqual(self.client.get(f"{self.base}/ai/models").json()["providers"], [])

    def test_send_with_own_key_goes_direct_and_skips_platform_budget(self):
        self.org.settings = {"flags": {"byok": True, "room_ai": True, "budgets": True}}
        self.org.save(update_fields=["settings"])
        Budget.objects.create(org=self.org, cap_amount=Decimal("0"), currency="USD")
        response, calls, legacy, platform = self._send(self.member, credential_id=self.key_id, model="gpt-4o-mini")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(calls[0].get_header("Authorization"), f"Bearer {SECRET}")
        legacy.assert_not_called()
        platform.assert_not_called()
        event = UsageEvent.objects.get(org=self.org, user=self.member)
        self.assertEqual(event.credential_source, UsageEvent.CREDENTIAL_CUSTOMER)
        self.assertNotIn(SECRET, json.dumps(response.json()))

    def test_no_silent_fallback(self):
        AICredential.objects.filter(pk=self.key_id).update(status=AICredential.STATUS_REJECTED)
        response, calls, legacy, platform = self._send(self.member, credential_id=self.key_id, model="gpt-4o-mini")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(calls, [])
        legacy.assert_not_called()
        platform.assert_not_called()

        AICredential.objects.filter(pk=self.key_id).update(status=AICredential.STATUS_ACTIVE)
        response, calls, legacy, platform = self._send(
            self.member, opener=_http_error(500), credential_id=self.key_id, model="gpt-4o-mini"
        )
        self.assertEqual(response.status_code, 502)
        legacy.assert_not_called()
        platform.assert_not_called()

    def test_expired_at_use_time(self):
        AICredential.objects.filter(pk=self.key_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        response, calls, _, _ = self._send(self.member, credential_id=self.key_id, model="gpt-4o-mini")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(AICredential.objects.get(pk=self.key_id).status, "expired")
        self.assertEqual(calls, [])

    def test_someone_elses_key_is_404(self):
        chat = Chat.objects.create(user=self.other, org=self.org, room=self.room, title="o")
        self.send_url = f"{self.base}/ai/threads/{chat.id}/send"
        response, calls, legacy, platform = self._send(self.other, credential_id=self.key_id, model="gpt-4o-mini")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(calls, [])

    def test_model_is_required_with_a_key(self):
        response, calls, _, _ = self._send(self.member, credential_id=self.key_id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(calls, [])

    def test_legacy_platform_call_never_carries_a_credential(self):
        handler = _ListHandler()
        root = logging.getLogger()
        root.addHandler(handler)
        old_level = root.level
        root.setLevel(logging.DEBUG)
        sent = []

        def legacy_http(request, timeout=None):
            sent.append(request.data or b"")
            sent.append(json.dumps(dict(request.header_items())).encode())
            return _Body({"generated_response": "ok", "model": "gpt-4o-mini", "file_type": "text"})

        try:
            self._auth(self.member)
            with patch("urllib.request.urlopen", side_effect=legacy_http):
                response = self.client.post(self.send_url, {"text": "hello"}, format="json")
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
        self.assertIn(response.status_code, (200, 502))
        self.assertTrue(sent, "the legacy path made its request")
        for blob in sent:
            self.assertNotIn(SECRET.encode(), blob)
        self.assertFalse([line for line in handler.lines if SECRET in line])
        event = UsageEvent.objects.filter(org=self.org, user=self.member).first()
        self.assertEqual(event.credential_source, UsageEvent.CREDENTIAL_PLATFORM)


class NoRedirectTests(TestCase):
    def test_redirects_are_not_followed(self):
        from brain.llm.http import _NoRedirect

        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "Found", {}, "http://10.0.0.1/"))


class ByokRobustnessTests(ByokBase):
    def test_naive_expiry_is_utc_not_500(self):
        response, _ = self._create(self.member, expires_at="2000-01-01T00:00:00")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "expired")
        bad, _ = self._create(self.member, expires_at="not-a-date")
        self.assertEqual(bad.status_code, 400)

    def test_dropped_connection_during_check_is_indeterminate(self):
        import http.client

        def drop(request, timeout=None):
            raise http.client.RemoteDisconnected("gone")

        self.assertEqual(self._create(self.member, opener=drop)[0].json()["status"], "indeterminate")


class DirectOddRepliesTests(TestCase):
    def test_odd_bodies_and_disconnects_are_errors_not_500(self):
        import http.client

        from brain.llm.direct import chat_complete

        class _Cred:
            base_url, provider = "https://api.openai.com", "openai"

            def api_key(self):
                return SECRET

        for reply in ([1, 2], {"choices": "x"}, {"choices": [{"message": {"content": 5}}]}):
            with patch("brain.llm.http.open_customer", return_value=_Body(reply)):
                result = chat_complete([{"role": "user", "content": "hi"}], model="m", credential=_Cred())
            self.assertFalse(result.ok, reply)

        def drop(request, timeout=None):
            raise http.client.IncompleteRead(b"")

        with patch("brain.llm.http.open_customer", side_effect=drop):
            result = chat_complete([{"role": "user", "content": "hi"}], model="m", credential=_Cred())
        self.assertEqual(result.error_code, "provider_unavailable")
