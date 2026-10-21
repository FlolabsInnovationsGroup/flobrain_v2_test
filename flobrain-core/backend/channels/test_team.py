from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from actions import plugins, registry
from actions.models import ActionProposal
from actions.service import ActionDenied
from brain.models import Message
from buddies.models import Buddy
from channels._testkit import ChannelsTestCase, Sent, tg_payload, wa_payload
from channels.models import ChannelLink, InboundEvent

ECHO = "test.channels_echo"
RAN = []


def _check(user, org, args):
    if args.get("deny"):
        raise ActionDenied("permission", "no")
    return f"Echo {args.get('text', '')}"


def _execute(user, org, args):
    RAN.append((user.id, args))
    return {"ok": True}


def fake_turn(user, org, chat, text, data, surface="buddy"):
    Message.objects.create(chat=chat, role=Message.ROLE_USER, text=text)
    Message.objects.create(chat=chat, role=Message.ROLE_ASSISTANT, text=f"Buddy says: {text}")
    return 200, {"usage": {}, "proposals": []}


@patch("platform_api.net.fetch", new_callable=Sent)
class LinkingTests(ChannelsTestCase):
    def setUp(self):
        super().setUp()
        self.tg = self.telegram()
        Buddy.objects.create(org=self.org, slug="helper", name="Helper", is_builtin=True, visibility=Buddy.VIS_ORG)

    def _code(self, who="member"):
        res = self.client_for(who).post(f"{self.base}/channels/links", {"connection": str(self.tg.id)}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertRegex(res.json()["code"], r"^\d{6}$")
        return res.json()["code"]

    def test_code_links_once_and_is_never_listed(self, sent):
        code = self._code()
        listed = self.client_for("member").get(f"{self.base}/channels/links").json()
        self.assertNotIn(code, str(listed))
        self.assertEqual(listed["links"][0]["status"], "pending")
        self.assertNotIn(code, ChannelLink.objects.get().code_hash)
        self.post_tg(self.tg, tg_payload(1, chat_id=4242, text=code))
        link = ChannelLink.objects.get(status="active")
        self.assertEqual((link.user, link.external_id), (self.users["member"], "4242"))
        self.assertIn("Linked", sent.texts()[-1])
        # Single use: the same code from another chat does nothing.
        self.post_tg(self.tg, tg_payload(2, chat_id=9999, text=code))
        self.assertEqual(ChannelLink.objects.filter(status="active").count(), 1)
        self.assertIn("not right", sent.texts()[-1])

    def test_expired_code(self, sent):
        code = self._code()
        ChannelLink.objects.update(code_expires_at=timezone.now() - timedelta(seconds=1))
        self.post_tg(self.tg, tg_payload(1, chat_id=4242, text=code))
        self.assertFalse(ChannelLink.objects.filter(status="active").exists())
        self.assertIn("expired", sent.texts()[-1])

    def test_new_code_replaces_the_old_one(self, sent):
        old = self._code()
        new = self._code()
        self.post_tg(self.tg, tg_payload(1, chat_id=4242, text=old if old != new else "000000"))
        self.assertFalse(ChannelLink.objects.filter(status="active").exists())
        self.post_tg(self.tg, tg_payload(2, chat_id=4242, text=new))
        self.assertTrue(ChannelLink.objects.filter(status="active").exists())

    def test_brute_force_is_limited(self, sent):
        code = self._code()
        wrong = "111111" if code != "111111" else "222222"
        for i in range(5):
            self.post_tg(self.tg, tg_payload(10 + i, chat_id=4242, text=wrong))
        self.post_tg(self.tg, tg_payload(20, chat_id=4242, text=code))
        self.assertFalse(ChannelLink.objects.filter(status="active").exists(), "locked out even with the right code")
        self.assertIn("Too many", sent.texts()[-1])

    @override_settings(CHANNELS_LIMITS={"link_failures_per_connection": 3})
    def test_brute_force_across_senders_is_limited(self, sent):
        code = self._code()
        wrong = "111111" if code != "111111" else "222222"
        for i in range(3):
            self.post_tg(self.tg, tg_payload(10 + i, chat_id=7000 + i, text=wrong))
        self.post_tg(self.tg, tg_payload(20, chat_id=8000, text=code))
        self.assertFalse(ChannelLink.objects.filter(status="active").exists())

    def test_linking_needs_the_flag_and_a_team_connection(self, sent):
        self.set_flag("channels", False)
        self.assertEqual(self.client_for("member").post(f"{self.base}/channels/links", {"connection": str(self.tg.id)}, format="json").status_code, 501)
        self.set_flag("channels", True)
        web = self.website()
        self.assertEqual(self.client_for("member").post(f"{self.base}/channels/links", {"connection": str(web.id)}, format="json").status_code, 404)

    def test_unlink_from_settings_and_phone(self, sent):
        code = self._code()
        self.post_tg(self.tg, tg_payload(1, chat_id=4242, text=code))
        link = ChannelLink.objects.get(status="active")
        self.assertEqual(self.client_for("other").delete(f"{self.base}/channels/links/{link.id}").status_code, 404)
        self.post_tg(self.tg, tg_payload(2, chat_id=4242, text="unlink"))
        link.refresh_from_db()
        self.assertEqual(link.status, "revoked")


@patch("platform_api.net.fetch", new_callable=Sent)
class TeamBuddyTests(ChannelsTestCase):
    def setUp(self):
        super().setUp()
        self.wa = self.whatsapp(serve_customers=False)
        Buddy.objects.create(org=self.org, slug="helper", name="Helper", is_builtin=True, visibility=Buddy.VIS_ORG)
        self.link = ChannelLink.objects.create(
            org=self.org, user=self.users["member"], connection=self.wa, status="active", external_id="201001112222", linked_at=timezone.now()
        )
        plugins.register_tool(ECHO, {"perm_key": "ai.use", "risk": "write", "label": "Echo", "description": "Echo", "schema": {"type": "object"}}, check=_check, execute=_execute)
        RAN.clear()

    def tearDown(self):
        registry.TOOLS.pop(ECHO, None)
        plugins._HANDLERS.pop(ECHO, None)
        super().tearDown()

    def _proposal(self, who="member", **args):
        return ActionProposal.objects.create(org=self.org, user=self.users[who], tool_key=ECHO, arguments={"text": "hi", **args}, summary="Echo hi")

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_linked_person_talks_to_their_buddy(self, turn, sent):
        self.post_wa(self.wa, wa_payload("t1", sender="201001112222", text="What is due today?"))
        self.assertEqual(turn.call_args.args[0], self.users["member"])
        self.assertEqual(sent.texts()[-1], "Buddy says: What is due today?")
        self.assertEqual(sent.calls[-1]["body"]["to"], "201001112222")
        self.assertEqual(InboundEvent.objects.get().outcome, "team")

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_flag_off_for_the_person(self, turn, sent):
        from organizations.models import OrgMembership

        OrgMembership.objects.filter(user=self.users["member"]).update(feature_flags={"channels": False})
        self.post_wa(self.wa, wa_payload("t2", sender="201001112222", text="hi"))
        turn.assert_not_called()
        self.assertIn("switched off", sent.texts()[-1])

    def test_approve_by_reply(self, sent):
        proposal = self._proposal()
        code = proposal.id.hex[:6].upper()
        self.post_wa(self.wa, wa_payload("a1", sender="201001112222", text=f"approve {code}"))
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "executed")
        self.assertEqual(proposal.decided_by, self.users["member"])
        self.assertEqual(RAN, [(self.users["member"].id, {"text": "hi"})])
        self.assertTrue(sent.texts()[-1].startswith("Done"))

    def test_reject_by_reply(self, sent):
        proposal = self._proposal()
        self.post_wa(self.wa, wa_payload("a2", sender="201001112222", text=f"reject {proposal.id.hex[:6].lower()}"))
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "rejected")
        self.assertEqual(RAN, [])

    def test_only_the_approver_can_answer(self, sent):
        theirs = self._proposal("other")
        code = theirs.id.hex[:6]
        self.post_wa(self.wa, wa_payload("a3", sender="201001112222", text=f"approve {code}"))
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, "proposed")
        self.assertIn("No approval", sent.texts()[-1])
        # A phone that is not linked cannot approve anything.
        self.post_wa(self.wa, wa_payload("a4", sender="209999999999", text=f"approve {code}"))
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, "proposed")
        self.assertEqual(RAN, [])

    def test_permission_rechecked_and_flag(self, sent):
        denied = self._proposal(deny=True)
        self.post_wa(self.wa, wa_payload("a5", sender="201001112222", text=f"approve {denied.id.hex[:6]}"))
        denied.refresh_from_db()
        self.assertEqual(denied.status, "proposed")
        self.set_flag("ai_actions", False)
        ok = self._proposal()
        self.post_wa(self.wa, wa_payload("a6", sender="201001112222", text=f"approve {ok.id.hex[:6]}"))
        ok.refresh_from_db()
        self.assertEqual(ok.status, "proposed")
        self.assertIn("switched off", sent.texts()[-1])

    def test_left_the_org_unlinks(self, sent):
        from organizations.models import OrgMembership

        OrgMembership.objects.filter(user=self.users["member"]).update(employment_status="inactive")
        self.post_wa(self.wa, wa_payload("a7", sender="201001112222", text="hi"))
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, "revoked")

    @patch("channels.voice.transcribe_inbound", return_value=None)
    def test_voice_note_hook(self, transcribe, sent):
        payload = wa_payload("v1", sender="201001112222")
        msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        msg.pop("text")
        msg.update({"type": "audio", "audio": {"id": "media-77", "mime_type": "audio/ogg"}})
        self.post_wa(self.wa, payload)
        self.assertEqual(InboundEvent.objects.get().media["ref"], "media-77")
        self.assertEqual(transcribe.call_args.args[1]["ref"], "media-77")
        self.assertIn("voice notes", sent.texts()[-1])
