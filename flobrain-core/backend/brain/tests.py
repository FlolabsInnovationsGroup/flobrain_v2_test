from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from brain.llm.base import LLMResult
from brain.models import Chat
from users.jwt_utils import make_access_token
from users.models import User


class FakeAdapter:
    def generate(self, messages, model=None):
        return LLMResult(generated_response="hello from stub", model=model or "stub-model", total_tokens=3)


class V1SendTelemetryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            email="chat@example.com",
            password_hash=make_password("pass-word-1"),
        )
        self.chat = Chat.objects.create(user=self.user, title="Test chat")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.user.id))}")

    @patch("brain.views.get_llm_adapter", return_value=FakeAdapter())
    @patch("telemetry.writers.record_v1_chat", side_effect=RuntimeError("telemetry down"))
    def test_send_returns_200_when_telemetry_raises(self, _write, _adapter):
        res = self.client.post(
            f"/api/brain/chats/{self.chat.id}/send/",
            {"text": "hi"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["id"], self.chat.id)
        self.assertIn("messages", body)
        self.assertIn("usage", body)
        self.assertEqual(body["usage"]["model"], "stub-model")
        self.assertEqual(body["usage"]["total_tokens"], 3)
        texts = [m.get("text") for m in body["messages"]]
        self.assertIn("hi", texts)
        self.assertIn("hello from stub", texts)

    @patch("brain.views.get_llm_adapter", return_value=FakeAdapter())
    def test_send_writes_usage_when_telemetry_works(self, _adapter):
        from telemetry.models import AITrace, UsageEvent

        res = self.client.post(
            f"/api/brain/chats/{self.chat.id}/send/",
            {"text": "hi"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(UsageEvent.objects.filter(chat=self.chat, user=self.user).count(), 1)
        self.assertEqual(AITrace.objects.filter(user=self.user, surface="v1_chat").count(), 1)
