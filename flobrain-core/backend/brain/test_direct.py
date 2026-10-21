import json
import socket
import urllib.error
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase, override_settings

from brain.llm.direct import chat_complete

DIRECT = {
    "AI_PROVIDER_BACKEND": "direct",
    "AI_DIRECT_BASE_URL": "https://provider.example",
    "AI_DIRECT_API_KEY": "test-key-not-live",
    "AI_DIRECT_MODEL_ALLOWLIST": "qwen,llama",
    "AI_DIRECT_DEFAULT_MODEL": "qwen",
    "AI_DIRECT_TIMEOUT": 5,
}


class _Body:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(code):
    return urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        code,
        "err",
        hdrs=None,
        fp=BytesIO(b"{}"),
    )


@override_settings(**DIRECT)
class DirectClientTests(TestCase):
    def test_sends_structured_messages_and_reads_usage(self):
        body = _Body({
            "model": "qwen",
            "choices": [{"message": {"role": "assistant", "content": "hello"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        })
        messages = [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "hi"},
        ]
        with patch("urllib.request.urlopen", return_value=body) as opened:
            result = chat_complete(messages, model="qwen")
        self.assertEqual(result.text, "hello")
        self.assertEqual(result.input_tokens, 4)
        self.assertEqual(result.output_tokens, 2)
        self.assertEqual(result.total_tokens, 6)
        request = opened.call_args.args[0]
        sent = json.loads(request.data.decode())
        self.assertEqual(sent["messages"], messages)
        self.assertEqual(sent["model"], "qwen")
        self.assertTrue(request.full_url.startswith("https://provider.example/v1/chat/completions"))

    def test_model_off_the_allowlist_does_not_call_the_network(self):
        with patch("urllib.request.urlopen") as opened:
            result = chat_complete([{"role": "user", "content": "hi"}], model="gpt-4o-mini")
        opened.assert_not_called()
        self.assertEqual(result.error_code, "invalid")
        self.assertIsNone(result.text)

    def test_http_errors_map_and_4xx_is_not_retried(self):
        cases = (
            (400, "invalid"),
            (401, "invalid_credential"),
            (429, "rate_limited"),
            (404, "provider_rejected"),
            (503, "provider_unavailable"),
        )
        for code, expected in cases:
            with self.subTest(code=code):
                with patch("urllib.request.urlopen", side_effect=_http_error(code)) as opened:
                    result = chat_complete([{"role": "user", "content": "hi"}])
                self.assertEqual(opened.call_count, 1)
                self.assertEqual(result.error_code, expected)
                self.assertIsNone(result.text)

    def test_timeout_is_provider_unavailable(self):
        with patch("urllib.request.urlopen", side_effect=socket.timeout("slow")):
            result = chat_complete([{"role": "user", "content": "hi"}])
        self.assertEqual(result.error_code, "provider_unavailable")

    def test_missing_usage_is_unknown(self):
        body = _Body({"choices": [{"message": {"content": "hello"}}]})
        with patch("urllib.request.urlopen", return_value=body):
            result = chat_complete([{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "hello")
        self.assertIsNone(result.total_tokens)
        self.assertIsNone(result.input_tokens)

    @override_settings(AI_DIRECT_BASE_URL="http://jarvis.example:8000", AI_DIRECT_API_KEY="")
    def test_missing_key_does_not_open_a_socket(self):
        with patch("urllib.request.urlopen") as opened:
            result = chat_complete([{"role": "user", "content": "hi"}])
        opened.assert_not_called()
        self.assertEqual(result.error_code, "not_configured")

    @override_settings(AI_DIRECT_BASE_URL="http://jarvis.example:8000")
    def test_self_hosted_base_url_is_only_a_setting(self):
        body = _Body({"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}})
        with patch("urllib.request.urlopen", return_value=body) as opened:
            result = chat_complete([{"role": "user", "content": "hi"}], model="llama")
        self.assertEqual(result.text, "ok")
        request = opened.call_args.args[0]
        self.assertTrue(request.full_url.startswith("http://jarvis.example:8000/v1/chat/completions"))
        self.assertEqual(json.loads(request.data.decode())["model"], "llama")
