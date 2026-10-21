import io
import json
from unittest import mock

from django.test import SimpleTestCase, override_settings

from meetings import asr


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@override_settings(ASR_BACKEND="http", ASR_BASE_URL="http://whisper:8000/", ASR_MODEL="large-v3", ASR_API_KEY="")
class AsrTests(SimpleTestCase):
    def test_posts_openai_style_and_parses_segments(self):
        seen = {}

        def fake(request, timeout):
            seen["url"], seen["body"], seen["ctype"] = request.full_url, request.data, request.headers["Content-type"]
            return _Resp(json.dumps({"text": " hi ", "language": "ar", "segments": [{"start": 0.123, "end": 1.5, "text": " hi "}, "junk"]}).encode())

        with mock.patch("urllib.request.urlopen", fake):
            out = asr.transcribe(b"OggS", "a.ogg", "audio/ogg")
        self.assertEqual(seen["url"], "http://whisper:8000/v1/audio/transcriptions")
        self.assertIn(b'name="model"\r\n\r\nlarge-v3', seen["body"])
        self.assertTrue(seen["ctype"].startswith("multipart/form-data; boundary="))
        self.assertEqual(out, {"text": "hi", "segments": [{"start": 0.12, "end": 1.5, "text": "hi"}], "language": "ar"})

    def test_not_configured_and_bad_response(self):
        with override_settings(ASR_BACKEND=""):
            self.assertFalse(asr.configured())
            with self.assertRaises(asr.ASRError):
                asr.transcribe(b"x")
        with mock.patch("urllib.request.urlopen", lambda r, timeout: _Resp(b"[]")):
            with self.assertRaises(asr.ASRError):
                asr.transcribe(b"x")
