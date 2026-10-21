import json
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from integrations.models import AICredential
from organizations.models import OrgMembership, OrgPolicy, Organization, Team, TeamMembership
from rooms.services import ensure_team_room
from users.jwt_utils import make_access_token
from users.models import User

DIRECT = {
    "AI_DIRECT_BASE_URL": "https://api.openai.example",
    "AI_DIRECT_API_KEY": "test-key-not-live",
    "AI_DIRECT_MODEL_ALLOWLIST": "qwen",
    "AI_DIRECT_DEFAULT_MODEL": "qwen",
}


class PrivateOnlyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="Sov", slug="sov", settings={"flags": {"memory_search": True, "live_translation": True, "room_ai": True, "buddies": True}}
        )
        self.owner = User.objects.create(email="sov-o@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="sov-m@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status="active")
        OrgMembership.objects.create(org=self.org, user=self.member, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status="active")
        team = Team.objects.create(org=self.org, name="T")
        TeamMembership.objects.create(team=team, user=self.member)
        self.room = ensure_team_room(team)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _private(self):
        self._auth(self.owner)
        return self.client.put(f"{self.base}/policy", {"inference_scope": "private_only"}, format="json")

    @override_settings(**DIRECT)
    def test_private_only_blocks_external_models_everywhere(self):
        key = AICredential.objects.create(org=self.org, owner=self.member, base_url="https://api.openai.com", ciphertext=b"x", last4="1234", status="active")
        response = self._private()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["keys_disabled"], 1)
        key.refresh_from_db()
        self.assertEqual((key.status, key.last_error), ("disabled", "private_only"))
        self._auth(self.member)
        with patch("urllib.request.urlopen") as network, patch("brain.llm.multimodal_adapter.MultimodalLLMAdapter.generate") as legacy:
            ask = self.client.post(f"{self.base}/knowledge/ask", {"question": "q"}, format="json")
            translate = self.client.get(f"{self.base}/rooms/{self.room.id}/messages?translate_to=ar")
            thread = self.client.post(f"{self.base}/rooms/{self.room.id}/ai/threads", {}, format="json").json()
            send = self.client.post(f"{self.base}/ai/threads/{thread['id']}/send", {"text": "hi"}, format="json")
        self.assertEqual((ask.status_code, translate.status_code, send.status_code), (409, 409, 409))
        network.assert_not_called()
        legacy.assert_not_called()

    @override_settings(AI_SELF_HOSTED_HOSTS="api.openai.example", **DIRECT)
    def test_self_hosted_direct_is_allowed(self):
        self._private()
        from brain.llm.policy import check_ai

        self.assertEqual(check_ai(self.org, "direct"), "")
        self.assertEqual(check_ai(self.org, "legacy"), "private_only")

    def test_only_policy_managers_change_it(self):
        self._auth(self.member)
        self.assertEqual(self.client.put(f"{self.base}/policy", {"inference_scope": "private_only"}, format="json").status_code, 403)
        self.assertEqual(self.client.get(f"{self.base}/policy").json()["inference_scope"], "external_allowed")
        self._auth(self.owner)
        self.assertEqual(self.client.put(f"{self.base}/policy", {"inference_scope": "nope"}, format="json").status_code, 400)
        self.assertEqual(self.client.put(f"{self.base}/policy", {"pii_redaction": "always"}, format="json").status_code, 501)
        self.assertFalse(OrgPolicy.objects.filter(org=self.org, inference_scope="private_only").exists())

    @override_settings(AI_FORCE_PRIVATE_ONLY=True, AI_SELF_HOSTED_HOSTS="vllm")
    def test_sovereign_lock(self):
        from brain.llm.policy import check_ai

        self._auth(self.owner)
        self.assertEqual(self.client.get(f"{self.base}/policy").json()["inference_scope"], "private_only")
        self.assertEqual(self.client.put(f"{self.base}/policy", {"inference_scope": "external_allowed"}, format="json").status_code, 409)
        self.assertEqual(check_ai(self.org, "legacy"), "private_only", "no policy row needed")
        self.assertEqual(check_ai(None, "external_agent"), "private_only")
        from brain.models import Chat

        chat = Chat.objects.create(user=self.owner)
        with patch("brain.llm.multimodal_adapter.MultimodalLLMAdapter.generate") as legacy:
            sent = self.client.post(f"/api/brain/chats/{chat.id}/send/", {"text": "hi"}, format="json")
        self.assertEqual(sent.status_code, 409, sent.content)
        legacy.assert_not_called()


class PlaintextHostTests(TestCase):
    def test_http_only_for_listed_in_cluster_hosts(self):
        from brain.llm import direct
        from knowledge import embeddings

        for check in (direct._base_is_allowed, embeddings._base_is_allowed):
            self.assertTrue(check("https://models.example.com"))
            self.assertTrue(check("http://localhost:8000"))
            self.assertFalse(check("http://vllm:8000"))
            with override_settings(AI_ALLOW_PLAINTEXT_HOSTS="vllm,embeddings"):
                self.assertTrue(check("http://vllm:8000"))
                self.assertTrue(check("http://EMBEDDINGS:80"))
                self.assertFalse(check("http://evil.example.com"))
                self.assertFalse(check("ftp://vllm"))
