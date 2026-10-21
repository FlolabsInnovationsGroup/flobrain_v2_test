import json
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings

from brain.llm.providers import DirectProvider, LegacyMultimodalProvider, get_provider
from brain.models import Chat
from telemetry.models import UsageEvent
from telemetry.writers import record_v1_chat, record_v2_provider_event
from users.models import User


class _Body:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ProviderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="ai@flolabs.local",
            password_hash=make_password("pass-pass-pass"),
        )

    def test_echo_is_a_provider_error(self):
        body = _Body({
            "result": "Perception system temporarily unavailable. Echoing input: hi",
            "model": "gpt-4o-mini",
            "file_type": "text",
        })
        with patch("urllib.request.urlopen", return_value=body) as opened:
            result = LegacyMultimodalProvider().complete([{"role": "user", "content": "hi"}])
        opened.assert_called_once()
        self.assertIsNone(result.text)
        self.assertEqual(result.error_code, "provider_error")
        self.assertIsNone(result.total_tokens)
        record_v2_provider_event(self.user, result)
        row = UsageEvent.objects.get()
        self.assertIsNone(row.total_tokens)
        self.assertEqual(row.status, "error")

    def test_missing_tokens_are_null_on_the_v2_writer(self):
        body = _Body({"result": "hello", "model": "gpt-4o-mini", "file_type": "text"})
        with patch("urllib.request.urlopen", return_value=body):
            result = LegacyMultimodalProvider().complete([{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "hello")
        self.assertIsNone(result.total_tokens)
        record_v2_provider_event(self.user, result)
        self.assertIsNone(UsageEvent.objects.get().total_tokens)

    def test_default_backend_is_legacy_and_direct_does_not_open_a_socket(self):
        self.assertIsInstance(get_provider(), LegacyMultimodalProvider)
        with override_settings(AI_PROVIDER_BACKEND="direct"):
            provider = get_provider()
        self.assertIsInstance(provider, DirectProvider)
        with patch("urllib.request.urlopen") as opened:
            result = provider.complete([{"role": "user", "content": "hi"}])
        opened.assert_not_called()
        self.assertEqual(result.error_code, "not_configured")
        self.assertIsNone(result.text)

    def test_v1_send_keeps_integer_token_count(self):
        from rest_framework.test import APIClient

        from users.jwt_utils import make_access_token

        chat = Chat.objects.create(user=self.user, title="t")
        body = _Body({"result": "hello", "model": "gpt-4o-mini", "file_type": "text"})
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.user.id))}")
        with patch("urllib.request.urlopen", return_value=body):
            response = client.post(
                f"/api/brain/chats/{chat.id}/send/",
                {"text": "hi"},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        usage = response.json()["usage"]["total_tokens"]
        self.assertIsInstance(usage, int)
        self.assertEqual(usage, 0)
        self.assertEqual(UsageEvent.objects.get().total_tokens, 0)
        llm = type("R", (), {"model": "m", "total_tokens": 3})()
        record_v1_chat(self.user, chat, llm)
        self.assertEqual(UsageEvent.objects.filter(total_tokens=3).count(), 1)
