from unittest.mock import patch

from django.test import override_settings

from brain.llm.demo_ai import _result
from channels._testkit import ChannelsTestCase
from channels.models import (
    CustomerConversation,
    CustomerKnowledge,
    CustomerMessage,
    CustomerSettings,
)
from channels.views_public import token_hash
from docs_app.models import Document
from rooms.models import Room

SHOP = "https://shop.example"
FRONTEND = "http://localhost:3000"


@override_settings(FRONTEND_BASE_URL=FRONTEND)
@patch("platform_api.net.fetch", side_effect=AssertionError("the website chat never calls a provider"))
class PublicChatTests(ChannelsTestCase):
    def setUp(self):
        super().setUp()
        self.site = self.website()
        room = Room.objects.create(org=self.org, name="Support", kind=Room.KIND_GROUP)
        doc = Document.objects.create(org=self.org, room=room, title="Hours", content_text="Support hours are 9 to 6, Sunday to Thursday.")
        CustomerKnowledge.objects.create(org=self.org, document=doc)
        CustomerSettings.objects.create(org=self.org, buddy_name="Acme helper")
        self.url = "/api/v2/public/chat/site-key-123/messages"

    def send(self, text="What are your support hours?", origin=SHOP, **extra):
        headers = {"HTTP_ORIGIN": origin} if origin else {}
        return self.client.post(self.url, {"text": text, **extra}, content_type="application/json", **headers)

    def test_config(self, fetch):
        res = self.client.get("/api/v2/public/chat/site-key-123", {"embed": SHOP}, HTTP_ORIGIN=FRONTEND)
        self.assertEqual((res.status_code, res.json()["name"], res.json()["embed_allowed"]), (200, "Acme helper", True))
        self.assertEqual(self.client.get("/api/v2/public/chat/site-key-123", {"embed": "https://evil.example"}, HTTP_ORIGIN=FRONTEND).status_code, 403)
        self.assertEqual(self.client.get("/api/v2/public/chat/nope").status_code, 404)

    def test_origin_checks(self, fetch):
        self.assertEqual(self.send(origin="https://evil.example").status_code, 403)
        self.assertEqual(self.send(origin="https://shop.example.evil.example").status_code, 403)
        self.assertEqual(self.send(origin=FRONTEND, embed_origin="https://evil.example").status_code, 403)
        self.assertEqual(self.send(origin=FRONTEND, embed_origin=SHOP).status_code, 201)
        self.assertEqual(self.send(origin=SHOP).status_code, 201)
        self.assertEqual(CustomerConversation.objects.count(), 2)

    def test_cors_only_for_allowed_origins(self, fetch):
        ok = self.client.options(self.url, HTTP_ORIGIN=SHOP, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertEqual(ok.headers.get("Access-Control-Allow-Origin"), SHOP)
        bad = self.client.options(self.url, HTTP_ORIGIN="https://evil.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertIsNone(bad.headers.get("Access-Control-Allow-Origin"))
        other = self.client.options(f"/api/v2/orgs/{self.org.id}/channels/connections", HTTP_ORIGIN=SHOP, HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET")
        self.assertIsNone(other.headers.get("Access-Control-Allow-Origin"), "only the chat API opens up to the site")

    def test_token_is_unguessable_and_only_hashed(self, fetch):
        res = self.send()
        token = res.json()["conversation"]
        self.assertGreaterEqual(len(token), 40)
        conv = CustomerConversation.objects.get()
        self.assertEqual(conv.token_hash, token_hash(token))
        self.assertNotIn(token, conv.token_hash)
        self.assertEqual(self.client.get(self.url, {"conversation": token[:-1] + "x"}, HTTP_ORIGIN=SHOP).status_code, 404)
        self.assertEqual(self.client.get(self.url, HTTP_ORIGIN=SHOP).status_code, 404)
        follow = self.send("And on Friday?", conversation=token)
        self.assertEqual(follow.status_code, 200)
        self.assertNotIn("conversation", follow.json(), "the token is returned once")

    def test_drafts_are_hidden_until_approved(self, fetch):
        with patch("brain.llm.direct.is_configured", return_value=True), patch("channels.customer_buddy._complete", return_value=_result("9 to 6. [1]")):
            res = self.send()
        token = res.json()["conversation"]
        roles = [m["role"] for m in self.client.get(self.url, {"conversation": token}, HTTP_ORIGIN=SHOP).json()["messages"]]
        self.assertEqual(roles, ["customer"])
        draft = CustomerMessage.objects.get(role="buddy", status="draft")
        approved = self.client_for("admin").post(f"{self.base}/customers/conversations/{draft.conversation_id}/messages/{draft.id}/approve", {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.content)
        shown = self.client.get(self.url, {"conversation": token}, HTTP_ORIGIN=SHOP).json()["messages"]
        self.assertEqual([m["role"] for m in shown], ["customer", "buddy"])
        self.assertEqual(shown[1]["citations"], [{"n": 1, "title": "Hours"}])
        self.assertNotIn("document", str(shown), "customers do not see internal ids")

    @override_settings(CHANNELS_LIMITS={"chat_messages_per_conversation_minute": 2})
    def test_rate_limit_per_conversation(self, fetch):
        token = self.send().json()["conversation"]
        self.assertEqual(self.send("two", conversation=token).status_code, 200)
        self.assertEqual(self.send("three", conversation=token).status_code, 429)

    @override_settings(CHANNELS_LIMITS={"chat_messages_per_ip_10min": 3, "chat_new_per_ip_hour": 100})
    def test_rate_limit_per_ip(self, fetch):
        codes = [self.send(f"hello {i}").status_code for i in range(4)]
        self.assertEqual(codes, [201, 201, 201, 429])

    @override_settings(CHANNELS_LIMITS={"chat_new_per_ip_hour": 2})
    def test_new_conversations_per_ip(self, fetch):
        codes = [self.send(f"hello {i}").status_code for i in range(3)]
        self.assertEqual(codes, [201, 201, 429])

    def test_validation_and_flags(self, fetch):
        self.assertEqual(self.send("").status_code, 400)
        self.assertEqual(self.send("x" * 2001).status_code, 400)
        self.set_flag("customer_buddy", False)
        self.assertEqual(self.send().status_code, 404)
        self.set_flag("customer_buddy", True)
        self.set_flag("channels", False)
        self.assertEqual(self.send().status_code, 404)
