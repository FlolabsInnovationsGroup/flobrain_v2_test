"""Inbound WhatsApp / Telegram voice notes are downloaded and transcribed (W2 + W7 wiring)."""

from unittest.mock import patch

from channels import voice
from channels._testkit import ACCESS_TOKEN, BOT_TOKEN, ChannelsTestCase


class FakeNet:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, body=b"", headers=None, timeout=10, max_bytes=4096):
        self.calls.append((method, url, dict(headers or {})))
        for prefix, reply in self.routes:
            if url.startswith(prefix):
                return reply
        return 404, b"{}"


class InboundVoiceTests(ChannelsTestCase):
    def setUp(self):
        super().setUp()
        self.set_flag("voice_notes", True)

    def test_flag_off_returns_none_without_network(self):
        self.set_flag("voice_notes", False)
        conn = self.whatsapp()
        with patch("platform_api.net.fetch") as fetch:
            self.assertIsNone(voice.transcribe_inbound(conn, {"type": "voice", "ref": "123", "mime": "audio/ogg"}))
        fetch.assert_not_called()

    def test_demo_connection_never_downloads(self):
        conn = self.whatsapp(demo=True)
        with patch("platform_api.net.fetch") as fetch:
            self.assertIsNone(voice.transcribe_inbound(conn, {"type": "voice", "ref": "123"}))
        fetch.assert_not_called()

    def test_whatsapp_media_is_downloaded_with_token_and_transcribed(self):
        conn = self.whatsapp()
        net = FakeNet([
            ("https://graph.facebook.com/", (200, b'{"url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1"}')),
            ("https://lookaside.fbsbx.com/", (200, b"OggS-audio")),
        ])
        with patch("platform_api.net.fetch", net), patch("rooms.voice.transcribe_bytes", return_value=("ازيك", "ar-EG")) as tb:
            text = voice.transcribe_inbound(conn, {"type": "voice", "ref": "998877", "mime": "audio/ogg"})
        self.assertEqual(text, "ازيك")
        self.assertEqual(tb.call_args.args[1], b"OggS-audio")
        self.assertEqual([c[2].get("Authorization") for c in net.calls], [f"Bearer {ACCESS_TOKEN}"] * 2)

    def test_media_url_on_other_host_is_refused(self):
        conn = self.whatsapp()
        net = FakeNet([("https://graph.facebook.com/", (200, b'{"url": "https://evil.example/a.ogg"}'))])
        with patch("platform_api.net.fetch", net), patch("rooms.voice.transcribe_bytes") as tb:
            self.assertIsNone(voice.transcribe_inbound(conn, {"type": "voice", "ref": "998877"}))
        tb.assert_not_called()
        self.assertEqual(len(net.calls), 1)

    def test_bad_media_ref_is_refused(self):
        conn = self.whatsapp()
        with patch("platform_api.net.fetch") as fetch:
            self.assertIsNone(voice.transcribe_inbound(conn, {"type": "voice", "ref": "../../me?x=1"}))
        fetch.assert_not_called()

    def test_telegram_file_path_is_checked(self):
        conn = self.telegram()
        net = FakeNet([
            (f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", (200, b'{"ok": true, "result": {"file_path": "voice/file_1.oga"}}')),
            (f"https://api.telegram.org/file/bot{BOT_TOKEN}/voice/file_1.oga", (200, b"OggS-tg")),
        ])
        with patch("platform_api.net.fetch", net), patch("rooms.voice.transcribe_bytes", return_value=("hello", "en")):
            self.assertEqual(voice.transcribe_inbound(conn, {"type": "voice", "ref": "AwACAgQ"}), "hello")
        bad = FakeNet([(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", (200, b'{"ok": true, "result": {"file_path": "../secrets"}}'))])
        with patch("platform_api.net.fetch", bad), patch("rooms.voice.transcribe_bytes") as tb:
            self.assertIsNone(voice.transcribe_inbound(conn, {"type": "voice", "ref": "AwACAgQ"}))
        tb.assert_not_called()

    def test_transcription_failure_returns_none(self):
        from rooms.voice import VoiceError

        conn = self.whatsapp()
        net = FakeNet([
            ("https://graph.facebook.com/", (200, b'{"url": "https://lookaside.fbsbx.com/a"}')),
            ("https://lookaside.fbsbx.com/", (200, b"OggS")),
        ])
        with patch("platform_api.net.fetch", net), patch("rooms.voice.transcribe_bytes", side_effect=VoiceError("unavailable")):
            self.assertIsNone(voice.transcribe_inbound(conn, {"type": "voice", "ref": "1"}))
