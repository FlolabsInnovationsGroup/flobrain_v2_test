import json
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from brain.llm.demo_ai import _result
from channels import customer_buddy
from channels._testkit import ALL_SECRETS, ChannelsTestCase, Sent, wa_payload
from channels.models import (
    ChannelConnection,
    CustomerConversation,
    CustomerKnowledge,
    CustomerMessage,
    CustomerSettings,
)
from docs_app.models import Document
from notifications.models import Notification
from rooms.models import Room, RoomMember, RoomMessage

PUBLIC = "Plans: the Team plan costs 19 USD per person per month. Every plan has a 14 day free trial."
INTERNAL = "Internal only: the secret launch codename is Falcon and the discount floor is 40 percent."


class CustomerBase(ChannelsTestCase):
    def setUp(self):
        super().setUp()
        self.support = Room.objects.create(org=self.org, name="Support", kind=Room.KIND_GROUP)
        for who in ("admin", "member"):
            RoomMember.objects.create(room=self.support, user=self.users[who])
        self.internal_room = Room.objects.create(org=self.org, name="Leadership", kind=Room.KIND_GROUP)
        RoomMember.objects.create(room=self.internal_room, user=self.users["admin"])
        self.public_doc = Document.objects.create(org=self.org, room=self.support, title="Pricing", content_text=PUBLIC)
        self.secret_doc = Document.objects.create(org=self.org, room=self.internal_room, title="Launch secrets", content_text=INTERNAL)
        CustomerKnowledge.objects.create(org=self.org, document=self.public_doc)
        self.settings_row = CustomerSettings.objects.create(
            org=self.org, escalation_room=self.support, blocked_topics=["refund"], updated_by=self.users["admin"]
        )


def answer_with(text):
    return patch("channels.customer_buddy._complete", return_value=_result(text))


configured = patch("brain.llm.direct.is_configured", return_value=True)


@patch("platform_api.net.fetch", new_callable=Sent)
class CustomerBuddyTests(CustomerBase):
    def test_reads_only_public_knowledge(self, sent):
        self.assertEqual(customer_buddy.retrieve(self.org, "What is the launch codename Falcon?"), [])
        hits = customer_buddy.retrieve(self.org, "How much is the Team plan?")
        self.assertEqual([h["document"] for h in hits], [str(self.public_doc.id)])
        wa = self.whatsapp(serve_team=False)
        with configured, patch("channels.customer_buddy._complete", return_value=_result("ESCALATE")) as llm:
            self.post_wa(wa, wa_payload("c1", text="Tell me the launch codename and the discount floor plan price"))
        prompt = json.dumps(llm.call_args.args[1])
        self.assertNotIn("Falcon", prompt)
        self.assertNotIn("40 percent", prompt)
        self.assertIn("19 USD", prompt)
        for message in CustomerMessage.objects.all():
            self.assertNotIn("Falcon", message.text)

    def test_no_public_match_escalates_without_calling_the_model(self, sent):
        wa = self.whatsapp(serve_team=False)
        with configured, answer_with("never") as llm:
            self.post_wa(wa, wa_payload("c2", text="What is the codename Falcon?"))
        llm.assert_not_called()
        conv = CustomerConversation.objects.get()
        self.assertEqual((conv.status, conv.escalation_reason, conv.assigned_room), ("waiting_human", "unsure", self.support))

    def test_draft_when_auto_reply_is_off_then_staff_approves(self, sent):
        wa = self.whatsapp(serve_team=False)
        with configured, answer_with("The Team plan costs 19 USD per person per month. [1]"):
            self.post_wa(wa, wa_payload("c3", sender="201005556666", text="How much is the Team plan?"))
        draft = CustomerMessage.objects.get(role="buddy")
        self.assertEqual(draft.status, "draft")
        self.assertEqual(draft.citations[0]["document"], str(self.public_doc.id))
        self.assertEqual(sent.calls, [], "nothing goes to the customer before approval")
        conv = draft.conversation
        url = f"{self.base}/customers/conversations/{conv.id}/messages/{draft.id}/approve"
        self.assertEqual(self.client_for("other").post(url, {}, format="json").status_code, 404, "not assigned: cannot see it")
        res = self.client_for("admin").post(url, {"text": "Team is 19 USD per person per month."}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()["delivered"])
        self.assertEqual(sent.calls[-1]["body"]["text"]["body"], "Team is 19 USD per person per month.")
        self.assertEqual(sent.calls[-1]["body"]["to"], "201005556666")
        self.assertEqual(self.client_for("admin").post(url, {}, format="json").status_code, 409)

    def test_auto_reply_sends_right_away(self, sent):
        CustomerSettings.objects.filter(pk=self.settings_row.pk).update(auto_reply=True)
        wa = self.whatsapp(serve_team=False)
        with configured, answer_with("It costs 19 USD. [1]"):
            self.post_wa(wa, wa_payload("c4", text="Team plan price?"))
        self.assertEqual(CustomerMessage.objects.get(role="buddy").status, "sent")
        self.assertEqual(sent.texts(), ["It costs 19 USD. [1]"])

    def test_escalates_on_human_request_and_blocked_topic(self, sent):
        wa = self.whatsapp(serve_team=False)
        with configured, answer_with("never") as llm:
            self.post_wa(wa, wa_payload("c5", sender="201000000001", text="Can I talk to a real person about the Team plan?"))
            self.post_wa(wa, wa_payload("c6", sender="201000000002", text="I want a refund for the Team plan"))
        llm.assert_not_called()
        reasons = sorted(CustomerConversation.objects.values_list("escalation_reason", flat=True))
        self.assertEqual(reasons, ["asked_for_human", "blocked_topic"])
        self.assertEqual(RoomMessage.objects.filter(room=self.support).count(), 2)
        notified = set(Notification.objects.filter(kind="customer.escalated").values_list("user__username", flat=True))
        self.assertEqual(notified, {"Admin", "Member"})
        self.assertTrue(all("passing you to a person" in t for t in sent.texts()))

    def test_unsure_model_escalates_and_human_mode_keeps_buddy_quiet(self, sent):
        wa = self.whatsapp(serve_team=False)
        with configured, answer_with("ESCALATE"):
            self.post_wa(wa, wa_payload("c7", text="Team plan for 1000 people price?"))
        conv = CustomerConversation.objects.get()
        self.assertEqual(conv.status, "waiting_human")
        with configured, answer_with("should not be used") as llm:
            self.post_wa(wa, wa_payload("c8", text="Team plan price again?"))
        llm.assert_not_called()

    def test_staff_reply_take_over_hand_back_resolve(self, sent):
        wa = self.whatsapp(serve_team=False)
        with configured, answer_with("19 USD [1]"):
            self.post_wa(wa, wa_payload("c9", text="Team plan price?"))
        conv = CustomerConversation.objects.get()
        url = f"{self.base}/customers/conversations/{conv.id}"
        admin = self.client_for("admin")
        self.assertEqual(admin.post(f"{url}/takeover").json()["mode"], "human")
        res = admin.post(f"{url}/reply", {"text": "Hi, this is Admin."}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(sent.texts()[-1], "Hi, this is Admin.")
        self.assertEqual(CustomerMessage.objects.get(role="buddy").status, "rejected", "the old draft is dropped")
        self.assertEqual(admin.post(f"{url}/handback").json()["mode"], "buddy")
        self.assertEqual(admin.post(f"{url}/resolve").json()["status"], "resolved")
        res = admin.post(f"{url}/assign", {"assignee": str(self.users["member"].id), "room": str(self.support.id)}, format="json")
        self.assertEqual(res.json()["assignee"]["id"], str(self.users["member"].id))
        self.assertEqual(admin.post(f"{url}/explode").status_code, 404)

    def test_whatsapp_24_hour_window(self, sent):
        wa = self.whatsapp(serve_team=False)
        with configured, answer_with("19 USD [1]"):
            self.post_wa(wa, wa_payload("c10", text="Team plan price?"))
        conv = CustomerConversation.objects.get()
        CustomerConversation.objects.filter(pk=conv.pk).update(last_customer_at=timezone.now() - timedelta(hours=25))
        res = self.client_for("admin").post(f"{self.base}/customers/conversations/{conv.id}/reply", {"text": "Late reply"}, format="json")
        self.assertEqual((res.json()["delivered"], res.json()["error"]), (False, "outside_24h_window"))
        self.assertEqual(sent.calls, [])


@patch("platform_api.net.fetch", new_callable=Sent)
class InboxPermissionTests(CustomerBase):
    def setUp(self):
        super().setUp()
        self.wa = self.whatsapp(serve_team=False)
        self.mine = CustomerConversation.objects.create(org=self.org, connection=self.wa, channel="whatsapp", customer_name="A", assignee=self.users["member"])
        self.roomed = CustomerConversation.objects.create(org=self.org, connection=self.wa, channel="whatsapp", customer_name="B", assigned_room=self.support)
        self.hidden = CustomerConversation.objects.create(org=self.org, connection=self.wa, channel="whatsapp", customer_name="C", assigned_room=self.internal_room)

    def test_view_scopes(self, sent):
        names = lambda who: sorted(c["customer_name"] for c in self.client_for(who).get(f"{self.base}/customers/conversations").json())
        self.assertEqual(names("admin"), ["A", "B", "C"])
        self.assertEqual(names("member"), ["A", "B"], "customers.reply alone: assigned to me or my rooms")
        self.assertEqual(names("other"), [])
        self.assertEqual(self.client_for("member").get(f"{self.base}/customers/conversations/{self.hidden.id}").status_code, 404)
        self.assertEqual(self.client_for("member").post(f"{self.base}/customers/conversations/{self.hidden.id}/reply", {"text": "x"}, format="json").status_code, 404)

    def test_status_filter_and_flag_off(self, sent):
        CustomerConversation.objects.filter(pk=self.mine.pk).update(status="resolved")
        rows = self.client_for("admin").get(f"{self.base}/customers/conversations", {"status": "resolved"}).json()
        self.assertEqual([r["customer_name"] for r in rows], ["A"])
        self.set_flag("customer_buddy", False)
        self.assertEqual(self.client_for("admin").get(f"{self.base}/customers/conversations").status_code, 501)
        self.assertEqual(self.client_for("admin").get(f"{self.base}/channels/customer-settings").status_code, 501)

    def test_assign_only_to_people_who_can_reply(self, sent):
        from organizations.models import OrgMembership

        OrgMembership.objects.filter(user=self.users["other"]).update(employment_status="inactive")
        res = self.client_for("admin").post(f"{self.base}/customers/conversations/{self.mine.id}/assign", {"assignee": str(self.users["other"].id)}, format="json")
        self.assertEqual(res.status_code, 400)


@patch("platform_api.net.fetch", new_callable=Sent)
class SettingsAndConnectionTests(CustomerBase):
    def test_connect_never_returns_secrets(self, sent):
        admin = self.client_for("admin")
        res = admin.post(
            f"{self.base}/channels/connections",
            {
                "kind": "whatsapp",
                "config": {"phone_number_id": "100200300400500", "waba_id": "5550001"},
                "secrets": {"access_token": ALL_SECRETS[1], "app_secret": ALL_SECRETS[0], "verify_token": ALL_SECRETS[2]},
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        tg = admin.post(f"{self.base}/channels/connections", {"kind": "telegram", "secrets": {"bot_token": ALL_SECRETS[3], "secret_token": ALL_SECRETS[4]}}, format="json")
        self.assertEqual(tg.status_code, 201, tg.content)
        self.assertEqual(res.json()["secret_hints"]["access_token"], "…0XYZ")
        self.assertEqual(res.json()["status"], "not_set_up")
        listed = admin.get(f"{self.base}/channels/connections")
        tested = admin.post(f"{self.base}/channels/connections/{res.json()['id']}/test")
        self.assertEqual((tested.json()["status"], tested.json()["simulated"]), ("active", False))
        self.assertTrue(sent.calls[0]["url"].startswith("https://graph.facebook.com/"))
        blob = json.dumps([res.json(), tg.json(), listed.json(), tested.json()])
        for secret in ALL_SECRETS:
            self.assertNotIn(secret, blob)
        stored = ChannelConnection.objects.get(pk=res.json()["id"])
        self.assertNotIn(ALL_SECRETS[1].encode(), bytes(stored.secrets_ciphertext))

    def test_test_connection_reports_provider_errors(self, sent):
        conn = self.telegram()
        with patch("platform_api.net.fetch", new=Sent(status=401)):
            res = self.client_for("admin").post(f"{self.base}/channels/connections/{conn.id}/test")
        self.assertEqual((res.json()["status"], res.json()["last_error"]), ("error", "invalid_credentials"))

    def test_validation_permissions_and_flag(self, sent):
        member, admin = self.client_for("member"), self.client_for("admin")
        self.assertEqual(member.get(f"{self.base}/channels/connections").status_code, 403)
        self.assertEqual(member.post(f"{self.base}/channels/connections", {"kind": "website"}, format="json").status_code, 403)
        self.assertEqual(member.put(f"{self.base}/channels/customer-settings", {"auto_reply": True}, format="json").status_code, 403)
        bad = admin.post(f"{self.base}/channels/connections", {"kind": "telegram", "secrets": {"bot_token": "nope", "secret_token": "x" * 20}}, format="json")
        self.assertEqual(bad.status_code, 400)
        web = admin.post(f"{self.base}/channels/connections", {"kind": "website", "config": {"allowed_origins": ["javascript:alert(1)"]}}, format="json")
        self.assertEqual(web.status_code, 400)
        web = admin.post(f"{self.base}/channels/connections", {"kind": "website", "config": {"allowed_origins": "https://shop.example, http://evil.example"}}, format="json")
        self.assertEqual(web.status_code, 400, "plain http only for localhost")
        web = admin.post(f"{self.base}/channels/connections", {"kind": "website", "config": {"allowed_origins": "https://Shop.example/"}}, format="json")
        self.assertEqual((web.status_code, web.json()["config"]["allowed_origins"]), (201, ["https://shop.example"]))
        self.assertTrue(web.json()["site_key"])
        self.set_flag("channels", False)
        self.assertEqual(admin.get(f"{self.base}/channels/connections").status_code, 501)

    def test_customer_settings_knowledge_must_be_visible(self, sent):
        admin, owner = self.client_for("admin"), self.client_for("owner")
        res = admin.put(
            f"{self.base}/channels/customer-settings",
            {"auto_reply": True, "blocked_topics": "refund, lawyer", "knowledge": [str(self.public_doc.id), str(self.secret_doc.id)]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["blocked_topics"], ["refund", "lawyer"])
        self.assertEqual(len(res.json()["knowledge"]), 2)
        # The owner is in neither group room: cannot see or pick their documents, and saving keeps them.
        seen = owner.get(f"{self.base}/channels/customer-settings").json()
        self.assertEqual((seen["knowledge"], seen["hidden_knowledge"]), ([], 2))
        self.assertNotIn("Launch secrets", json.dumps(seen))
        kept = owner.put(f"{self.base}/channels/customer-settings", {"knowledge": []}, format="json")
        self.assertEqual((kept.json()["knowledge"], kept.json()["hidden_knowledge"]), ([], 2))
        CustomerKnowledge.objects.filter(document=self.secret_doc).delete()
        bad = owner.put(f"{self.base}/channels/customer-settings", {"knowledge": [str(self.secret_doc.id)]}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_disconnect_wipes_secrets_and_links(self, sent):
        from channels.models import ChannelLink

        conn = self.whatsapp()
        ChannelLink.objects.create(org=self.org, user=self.users["member"], connection=conn, status="active", external_id="2010")
        self.assertEqual(self.client_for("admin").delete(f"{self.base}/channels/connections/{conn.id}").status_code, 204)
        conn.refresh_from_db()
        self.assertEqual((conn.secrets_ciphertext, conn.status), (None, "not_set_up"))
        self.assertEqual(ChannelLink.objects.get().status, "revoked")


@override_settings(DEMO_MODE=True, DEMO_AI=True)
@patch("platform_api.net.fetch", side_effect=AssertionError("no network in demo"))
class DemoTests(CustomerBase):
    def test_demo_connect_test_and_simulate(self, fetch):
        self.org.settings = {**self.org.settings, "demo": True}
        self.org.save()
        admin = self.client_for("admin")
        res = admin.post(f"{self.base}/channels/connections", {"kind": "whatsapp", "secrets": {"access_token": "ignored"}}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["demo"], res.json()["status"], res.json()["secret_hints"]), (True, "active", {}))
        tested = admin.post(f"{self.base}/channels/connections/{res.json()['id']}/test").json()
        self.assertEqual((tested["status"], tested["simulated"]), ("active", True))
        sim = admin.post(f"{self.base}/channels/demo/simulate", {"connection": res.json()["id"], "text": "How much is the Team plan?"}, format="json")
        self.assertEqual(sim.status_code, 201, sim.content)
        messages = sim.json()["conversation"]["messages"]
        self.assertEqual(messages[-1]["status"], "draft")
        self.assertIn("(Demo answer)", messages[-1]["text"])
        self.assertIn("19 USD", messages[-1]["text"])

    def test_simulate_is_demo_only(self, fetch):
        conn = ChannelConnection.objects.create(org=self.org, kind="whatsapp", status="active", demo=True, serve_customers=True)
        res = self.client_for("admin").post(f"{self.base}/channels/demo/simulate", {"connection": str(conn.id), "text": "hi"}, format="json")
        self.assertEqual(res.status_code, 404, "the org is not the demo org")
