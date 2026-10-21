import json
from unittest.mock import patch

from django.test import override_settings

from channels import providers
from channels._testkit import (
    PHONE_ID,
    VERIFY_TOKEN,
    ChannelsTestCase,
    Sent,
    sign,
    tg_payload,
    wa_payload,
)
from channels.models import (
    ChannelConnection,
    CustomerConversation,
    CustomerMessage,
    InboundEvent,
)


@patch("platform_api.net.fetch", new_callable=Sent)
class WhatsAppWebhookTests(ChannelsTestCase):
    def test_verify_challenge(self, sent):
        conn = self.whatsapp()
        url = f"/api/v2/hooks/whatsapp/{conn.id}"
        ok = self.client.get(url, {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1158201444"})
        self.assertEqual((ok.status_code, ok.content), (200, b"1158201444"))
        self.assertEqual(self.client.get(url, {"hub.mode": "subscribe", "hub.verify_token": "wrong-token", "hub.challenge": "1"}).status_code, 403)
        self.assertEqual(self.client.get(url, {"hub.mode": "subscribe", "hub.challenge": "1"}).status_code, 403)
        self.assertEqual(self.client.get(url, {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "<script>"}).status_code, 403)
        self.assertEqual(self.client.get(f"/api/v2/hooks/whatsapp/{self.org.id}", {"hub.mode": "subscribe"}).status_code, 404)

    def test_signature_good_bad_missing(self, sent):
        conn = self.whatsapp(serve_customers=False)
        self.assertEqual(self.post_wa(conn, wa_payload("m1"), signature="sha256=" + "0" * 64).status_code, 401)
        self.assertEqual(self.post_wa(conn, wa_payload("m2"), signature=None).status_code, 401)
        self.assertEqual(self.post_wa(conn, wa_payload("m3"), signature="md5=abc").status_code, 401)
        body = json.dumps(wa_payload("m4")).encode()
        tampered = self.client.post(
            f"/api/v2/hooks/whatsapp/{conn.id}", data=body.replace(b"hello", b"HELLO"), content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sign(body),
        )
        self.assertEqual(tampered.status_code, 401)
        self.assertEqual(InboundEvent.objects.count(), 0)
        good = self.post_wa(conn, wa_payload("m5"))
        self.assertEqual(good.status_code, 200, good.content)
        self.assertEqual(InboundEvent.objects.get().provider_message_id, "m5")
        self.assertEqual(InboundEvent.objects.get().outcome, "not_linked")

    def test_idempotent_on_message_id(self, sent):
        conn = self.whatsapp(serve_team=False)
        for _ in range(3):
            self.assertEqual(self.post_wa(conn, wa_payload("wamid.same", text="Do you have a human?")).status_code, 200)
        self.assertEqual(InboundEvent.objects.count(), 1)
        self.assertEqual(CustomerConversation.objects.count(), 1)
        self.assertEqual(CustomerMessage.objects.filter(role="customer").count(), 1)

    def test_other_phone_numbers_and_statuses_are_skipped(self, sent):
        conn = self.whatsapp()
        self.assertEqual(self.post_wa(conn, wa_payload("x1", phone="999")).json()["received"], 0)
        status_only = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": PHONE_ID}, "statuses": [{"id": "s"}]}}]}]}
        self.assertEqual(self.post_wa(conn, status_only).json()["received"], 0)

    def test_payload_size_limit(self, sent):
        conn = self.whatsapp()
        big = wa_payload("big", text="x" * (300 * 1024))
        self.assertEqual(self.post_wa(conn, big).status_code, 413)
        self.assertEqual(InboundEvent.objects.count(), 0)

    @override_settings(CHANNELS_LIMITS={"webhook_per_minute": 2})
    def test_rate_limited(self, sent):
        conn = self.whatsapp(serve_customers=False)
        codes = [self.post_wa(conn, wa_payload(f"r{i}")).status_code for i in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_flag_off_demo_and_unknown(self, sent):
        conn = self.whatsapp()
        self.set_flag("channels", False)
        self.assertEqual(self.post_wa(conn, wa_payload("f1")).status_code, 404)
        self.set_flag("channels", True)
        demo = ChannelConnection.objects.create(org=self.org, kind="whatsapp", status="active", demo=True, config={"phone_number_id": PHONE_ID})
        self.assertEqual(self.post_wa(demo, wa_payload("f2")).status_code, 404, "demo connections never take webhooks")
        tg = self.telegram()
        self.assertEqual(self.post_wa(tg, wa_payload("f3")).status_code, 404, "a Telegram id is not a WhatsApp hook")


@patch("platform_api.net.fetch", new_callable=Sent)
class TelegramWebhookTests(ChannelsTestCase):
    def test_secret_token_good_bad_missing(self, sent):
        conn = self.telegram()
        self.assertEqual(self.post_tg(conn, tg_payload(1), secret="nope-nope-nope-nope").status_code, 401)
        self.assertEqual(self.post_tg(conn, tg_payload(2), secret=None).status_code, 401)
        self.assertEqual(InboundEvent.objects.count(), 0)
        ok = self.post_tg(conn, tg_payload(3))
        self.assertEqual((ok.status_code, ok.json()["received"]), (200, 1))
        self.assertEqual(self.post_tg(conn, tg_payload(3)).json()["received"], 0, "a retried update is processed once")
        self.assertEqual(self.client.get(f"/api/v2/hooks/telegram/{conn.id}").status_code, 405)

    def test_group_chats_are_skipped(self, sent):
        conn = self.telegram()
        payload = tg_payload(9)
        payload["message"]["chat"]["type"] = "group"
        self.assertEqual(self.post_tg(conn, payload).json()["received"], 0)


class ProviderUnitTests(ChannelsTestCase):
    def test_signature_helper_is_strict(self):
        self.assertTrue(providers.whatsapp_signature_ok("s3cret", b"{}", sign(b"{}", "s3cret")))
        self.assertFalse(providers.whatsapp_signature_ok("", b"{}", sign(b"{}", "")))
        self.assertFalse(providers.whatsapp_signature_ok("s3cret", b"{}", None))
        self.assertFalse(providers.telegram_secret_ok("", ""))

    def test_only_allowlisted_hosts(self):
        with patch("platform_api.net.fetch", new_callable=Sent) as sent:
            with self.assertRaises(providers.ProviderError):
                providers._call("GET", "https://evil.example/bot123/getMe")
            with self.assertRaises(providers.ProviderError):
                providers._call("GET", "http://api.telegram.org/bot123/getMe")
            self.assertEqual(sent.calls, [])

    def test_send_whatsapp_and_telegram(self):
        wa, tg = self.whatsapp(), self.telegram()
        with patch("platform_api.net.fetch", new_callable=Sent) as sent:
            self.assertEqual(providers.send(wa, "201001112222", "Hi"), "")
            self.assertEqual(providers.send(tg, "555111", "Hi"), "")
        self.assertTrue(sent.calls[0]["url"].startswith(f"https://graph.facebook.com/v21.0/{PHONE_ID}/messages"))
        self.assertEqual(sent.calls[0]["body"]["to"], "201001112222")
        self.assertIn("Bearer", sent.calls[0]["headers"]["Authorization"])
        self.assertTrue(sent.calls[1]["url"].startswith("https://api.telegram.org/bot"))
        with patch("platform_api.net.fetch", new_callable=Sent):
            self.assertEqual(providers.send(wa, "not-a-number", "Hi"), "invalid_target")
        with patch("platform_api.net.fetch", new=Sent(status=401)):
            self.assertEqual(providers.send(wa, "201001112222", "Hi"), "invalid_credentials")
