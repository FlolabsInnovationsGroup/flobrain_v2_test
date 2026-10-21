import json
import time
from unittest.mock import patch

from django.test import override_settings

from actions import plugins, registry
from actions.models import ActionProposal
from actions.service import ActionDenied
from bridges import slack
from bridges._testkit import (
    ALL_SECRETS,
    SIGNING,
    TEAM,
    BridgesTestCase,
    FakeNet,
    fake_turn,
)
from bridges.models import BridgeCard, BridgeEvent, BridgeLink, BridgeThread
from buddies.models import Buddy
from organizations.models import OrgMembership

ECHO = "test.bridges_echo"
RAN = []


def _check(user, org, args):
    if args.get("deny"):
        raise ActionDenied("permission", "no")
    return f"Echo {args.get('text', '')}"


def _execute(user, org, args):
    RAN.append((user.id, args))
    return {"ok": True}


class SignatureTests(BridgesTestCase):
    def test_signature_function(self):
        body, now = b'{"a":1}', 1_700_000_000
        good = slack.sign(body, now, SIGNING)
        self.assertTrue(slack.signature_ok(body, str(now), good, now=now))
        self.assertFalse(slack.signature_ok(body + b" ", str(now), good, now=now))  # body changed
        self.assertFalse(slack.signature_ok(body, str(now), good, secret="other-secret", now=now))
        self.assertFalse(slack.signature_ok(body, str(now), good, now=now + 301))  # too old
        self.assertFalse(slack.signature_ok(body, str(now), good, now=now - 301))  # from the future
        self.assertTrue(slack.signature_ok(body, str(now), good, now=now + 299))
        self.assertFalse(slack.signature_ok(body, None, good, now=now))
        self.assertFalse(slack.signature_ok(body, str(now), None, now=now))
        self.assertFalse(slack.signature_ok(body, "not-a-number", good, now=now))
        self.assertFalse(slack.signature_ok(body, str(now), good.replace("v0=", "v1="), now=now))
        self.assertFalse(slack.signature_ok(body, str(now), good, secret="", now=now))

    @patch("platform_api.net.fetch", new_callable=FakeNet)
    def test_endpoints_refuse_bad_old_or_missing_signatures(self, net):
        self.slack_ws()
        payload = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()
        for path, ctype in (("events", "application/json"), ("commands", "application/x-www-form-urlencoded"), ("interactions", "application/x-www-form-urlencoded")):
            self.assertEqual(self.slack_post(path, payload, ctype, secret="wrong-secret").status_code, 401)
            self.assertEqual(self.slack_post(path, payload, ctype, ts=int(time.time()) - 600).status_code, 401)
            self.assertEqual(self.slack_post(path, payload, ctype, signature=False).status_code, 401)
        self.assertEqual(BridgeEvent.objects.count(), 0)
        self.assertEqual(net.calls, [])

    def test_url_verification(self):
        res = self.slack_post("events", json.dumps({"type": "url_verification", "challenge": "3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P"}).encode(), "application/json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"challenge": "3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P"})
        bad = self.slack_post("events", json.dumps({"type": "url_verification", "challenge": "<script>"}).encode(), "application/json")
        self.assertEqual(bad.status_code, 400)

    @override_settings(FLOBRAIN_SLACK_SIGNING_SECRET="")
    def test_not_set_up_without_the_signing_secret(self):
        with patch.dict("os.environ", {"FLOBRAIN_SLACK_SIGNING_SECRET": ""}):
            res = self.slack_post("events", b"{}", "application/json")
        self.assertEqual(res.status_code, 501)
        self.assertEqual(res.json()["error"], "not_configured")

    def test_large_bodies_are_refused(self):
        res = self.slack_post("events", b"{" + b" " * (300 * 1024) + b"}", "application/json")
        self.assertEqual(res.status_code, 413)


@patch("platform_api.net.fetch", new_callable=FakeNet)
class SlackBuddyTests(BridgesTestCase):
    def setUp(self):
        super().setUp()
        self.ws = self.slack_ws()
        Buddy.objects.create(org=self.org, slug="helper", name="Helper", is_builtin=True, visibility=Buddy.VIS_ORG)
        self.finance = Buddy.objects.create(org=self.org, slug="finance", name="Finance Buddy", is_builtin=True, visibility=Buddy.VIS_ORG)
        self.member_link = self.link("member", self.ws, "U0MEMBER")
        plugins.register_tool(ECHO, {"perm_key": "ai.use", "risk": "write", "label": "Echo", "description": "Echo", "schema": {"type": "object"}}, check=_check, execute=_execute)
        RAN.clear()

    def tearDown(self):
        registry.TOOLS.pop(ECHO, None)
        plugins._HANDLERS.pop(ECHO, None)
        super().tearDown()

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_mention_from_a_linked_person_is_answered_in_the_thread(self, turn, net):
        res = self.slack_event(self.mention(text="<@U0BOT> what is due today?"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(turn.call_args.args[0], self.users["member"])
        self.assertEqual(turn.call_args.args[3], "what is due today?")
        post = net.slack("chat.postMessage")[-1]
        self.assertEqual(post["body"]["channel"], "C0LAUNCH")
        self.assertEqual(post["body"]["thread_ts"], "1700000000.000100")
        self.assertEqual(post["body"]["text"], "Buddy says: what is due today?")
        self.assertEqual(post["headers"]["Authorization"], f"Bearer {self.ws_token()}")
        self.assertEqual(BridgeEvent.objects.get().outcome, "answered:0")

    def ws_token(self):
        from channels import vault

        return vault.get(self.ws, "bot_token")

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_event_id_is_handled_once(self, turn, net):
        self.slack_event(self.mention(), event_id="EvSAME")
        again = self.slack_event(self.mention(), event_id="EvSAME")
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.json()["duplicate"])
        self.assertEqual(turn.call_count, 1)
        self.assertEqual(BridgeEvent.objects.count(), 1)

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_direct_message_and_thread_context(self, turn, net):
        self.slack_event(self.dm(text="first"), event_id="Ev1")
        self.slack_event(self.dm(text="second", ts="1700000002.000100"), event_id="Ev2")
        self.assertEqual(turn.call_count, 2)
        # The same DM keeps one FloBrain chat; the reply goes back to the DM, not a thread.
        self.assertEqual(BridgeThread.objects.count(), 1)
        post = net.slack("chat.postMessage")[-1]
        self.assertEqual(post["body"]["channel"], "D0DMMEM")
        self.assertNotIn("thread_ts", post["body"])

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_bots_edits_and_other_events_are_ignored(self, turn, net):
        self.slack_event({**self.mention(), "bot_id": "B1"}, event_id="E1")
        self.slack_event({**self.dm(), "subtype": "message_changed"}, event_id="E2")
        self.slack_event({"type": "reaction_added", "user": "U0MEMBER"}, event_id="E3")
        self.slack_event({**self.mention(), "channel_type": "im", "channel": "D0X"}, event_id="E4")  # message.im covers DMs
        turn.assert_not_called()
        self.assertEqual(BridgeEvent.objects.count(), 0)

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_unlinked_people_get_no_answer(self, turn, net):
        self.slack_event(self.mention(user="U0STRANGER"), event_id="E5")
        turn.assert_not_called()
        self.assertEqual(net.slack("chat.postMessage"), [])  # nothing in the channel
        notice = net.slack("chat.postEphemeral")[-1]
        self.assertEqual(notice["body"]["user"], "U0STRANGER")
        self.assertIn("not linked", notice["body"]["text"])
        self.assertEqual(BridgeEvent.objects.get().outcome, "not_linked")

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_matching_email_suggests_a_link_but_never_links_silently(self, turn, net):
        net.profiles["U0OTHER"] = {"email": "other@acme.test", "real_name": "Other Person"}
        self.slack_event(self.mention(user="U0OTHER"), event_id="E6")
        turn.assert_not_called()
        link = BridgeLink.objects.get(external_id="U0OTHER")
        self.assertEqual((link.user, link.status, link.found_via), (self.users["other"], "pending", "platform"))
        self.assertEqual(link.email_masked, "o•••@acme.test")
        self.assertIn("confirm", net.slack("chat.postEphemeral")[-1]["body"]["text"])
        # Still pending: a second question gets no answer.
        self.slack_event(self.mention(user="U0OTHER", ts="1700000005.000100"), event_id="E7")
        turn.assert_not_called()
        # Confirming in FloBrain makes it active; then the buddy answers.
        res = self.client_for("other").post(f"{self.base}/bridges/links/{link.id}/confirm")
        self.assertEqual(res.status_code, 200, res.content)
        self.slack_event(self.mention(user="U0OTHER", ts="1700000006.000100"), event_id="E8")
        self.assertEqual(turn.call_args.args[0], self.users["other"])

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_a_member_cannot_confirm_someone_elses_pending_link(self, turn, net):
        pending = self.link("other", self.ws, "U0OTHER", status="pending")
        res = self.client_for("member").post(f"{self.base}/bridges/links/{pending.id}/confirm")
        self.assertEqual(res.status_code, 404)
        pending.refresh_from_db()
        self.assertEqual(pending.status, "pending")

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_unknown_email_and_inactive_members_are_not_suggested(self, turn, net):
        net.profiles["U0X"] = {"email": "someone@elsewhere.test"}
        self.slack_event(self.mention(user="U0X"), event_id="E9")
        OrgMembership.objects.filter(user=self.users["other"]).update(employment_status="offboarded")
        net.profiles["U0Y"] = {"email": "other@acme.test"}
        self.slack_event(self.mention(user="U0Y"), event_id="E10")
        self.assertFalse(BridgeLink.objects.filter(status="pending").exists())

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_named_buddy_answers(self, turn, net):
        self.slack_event(self.mention(text="<@U0BOT> Finance Buddy: what is left in the budget?"), event_id="E11")
        chat = turn.call_args.args[2]
        self.assertEqual(chat.buddy, self.finance)
        self.assertEqual(turn.call_args.args[3], "what is left in the budget?")

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_default_buddy_and_flo(self, turn, net):
        self.ws.default_buddy = self.finance
        self.ws.save()
        self.slack_event(self.mention(), event_id="E12")
        self.assertEqual(turn.call_args.args[2].buddy, self.finance)
        self.ws.default_buddy = None
        self.ws.save()
        self.set_flag("flo_router", True)
        with patch("buddies.router.flo_turn", side_effect=lambda u, o, chat, text, data: fake_turn(u, o, chat, text, data)) as flo:
            self.slack_event(self.mention(ts="1700000009.000100"), event_id="E13")
        self.assertEqual(flo.call_args.args[2].buddy.slug, "flo")

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_slash_command_answers_only_the_person(self, turn, net):
        res = self.slack_command("what is due?")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["response_type"], "ephemeral")
        self.assertEqual(turn.call_args.args[3], "what is due?")
        hook = [c for c in net.calls if c["host"] == "hooks.slack.com"][-1]
        self.assertEqual(hook["body"]["response_type"], "ephemeral")
        self.assertEqual(net.slack("chat.postMessage"), [])  # nothing posted in the channel
        # The response URL is not kept after use.
        self.assertNotIn("response_url", BridgeEvent.objects.get().context)
        # Same trigger again is a duplicate.
        self.slack_command("what is due?")
        self.assertEqual(turn.call_count, 1)

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_flag_off(self, turn, net):
        self.set_flag("bridges", False)
        res = self.slack_event(self.mention(), event_id="E14")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["ignored"], "unknown_workspace")
        turn.assert_not_called()
        self.set_flag("bridges", True)
        OrgMembership.objects.filter(user=self.users["member"]).update(feature_flags={"bridges": False})
        self.slack_event(self.mention(ts="1700000010.000100"), event_id="E15")
        turn.assert_not_called()
        self.assertIn("switched off", net.slack("chat.postEphemeral")[-1]["body"]["text"])

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_other_workspaces_are_ignored(self, turn, net):
        res = self.slack_event(self.mention(), event_id="E16", team="T0OTHER")
        self.assertEqual(res.json()["ignored"], "unknown_workspace")
        turn.assert_not_called()

    @override_settings(BRIDGES_LIMITS={"turns_per_minute": 2})
    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_turns_are_rate_limited_per_person(self, turn, net):
        for i in range(4):
            self.slack_event(self.mention(ts=f"17000001{i}.000100"), event_id=f"R{i}")
        self.assertEqual(turn.call_count, 2)
        self.assertEqual(BridgeEvent.objects.filter(outcome="rate_limited").count(), 2)

    @override_settings(BRIDGES_LIMITS={"hook_per_workspace_per_minute": 2})
    def test_hooks_are_rate_limited_per_workspace(self, net):
        codes = [self.slack_event({"type": "reaction_added"}, event_id=f"L{i}").status_code for i in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_answers_are_escaped(self, turn, net):
        turn.side_effect = lambda u, o, chat, text, data, surface="buddy": (
            chat.messages.create(role="assistant", text="<!channel> ping <@U0BOSS>"),
            (200, {"proposals": []}),
        )[1]
        self.slack_event(self.mention(), event_id="E17")
        text = net.slack("chat.postMessage")[-1]["body"]["text"]
        self.assertNotIn("<!channel>", text)
        self.assertIn("&lt;!channel&gt;", text)

    def test_uninstall_disconnects(self, net):
        self.slack_event({"type": "app_uninstalled"}, event_id="E18")
        self.ws.refresh_from_db()
        self.member_link.refresh_from_db()
        self.assertEqual(self.ws.status, "disconnected")
        self.assertIsNone(self.ws.secrets_ciphertext)
        self.assertEqual(self.member_link.status, "revoked")

    # --- approvals ---

    def _turn_with_proposal(self, who="member"):
        def turn(user, org, chat, text, data, surface="buddy"):
            proposal = ActionProposal.objects.create(org=org, user=user, thread=chat, buddy=chat.buddy, tool_key=ECHO, arguments={"text": "hi"}, summary="Echo hi")
            chat.messages.create(role="assistant", text="I prepared 1 action(s) for your approval.")
            return 200, {"proposals": [{"id": str(proposal.id)}]}

        return turn

    def test_proposal_becomes_a_card_in_the_dm_and_the_approver_decides(self, net):
        with patch("buddies.chat.run_buddy_turn", side_effect=self._turn_with_proposal()):
            self.slack_event(self.mention(text="<@U0BOT> echo hi"), event_id="A1")
        thread_reply = net.slack("chat.postMessage")[0]["body"]
        self.assertEqual(thread_reply["channel"], "C0LAUNCH")
        self.assertIn("direct message", thread_reply["text"])
        card_post = net.slack("chat.postMessage")[-1]["body"]
        self.assertTrue(card_post["channel"].startswith("D0DM"))
        self.assertEqual(card_post["blocks"][-1]["elements"][0]["action_id"], "flo_approve")
        card = BridgeCard.objects.get()
        # Someone else pressing the button (a forwarded message) decides nothing.
        other = self.link("other", self.ws, "U0OTHER")
        self.slack_action(card, "approve", user="U0OTHER")
        card.proposal.refresh_from_db()
        self.assertEqual(card.proposal.status, "proposed")
        self.assertIn("Only the person", net.slack("chat.postEphemeral")[-1]["body"]["text"])
        self.assertTrue(other)
        # The approver approves: it runs once, and the message is updated.
        self.slack_action(card, "approve", action_ts="1700000100.1")
        card.proposal.refresh_from_db()
        self.assertEqual(card.proposal.status, "executed")
        self.assertEqual(card.proposal.decided_by, self.users["member"])
        self.assertEqual(RAN, [(self.users["member"].id, {"text": "hi"})])
        update = net.slack("chat.update")[-1]["body"]
        self.assertEqual((update["channel"], update["ts"]), (card.channel, card.message_id))
        self.assertIn("Approved and done", update["blocks"][0]["text"]["text"])
        # A second press finds it already decided.
        self.slack_action(card, "approve", action_ts="1700000101.1")
        self.assertEqual(len(RAN), 1)

    def test_reject_and_unknown_cards(self, net):
        with patch("buddies.chat.run_buddy_turn", side_effect=self._turn_with_proposal()):
            self.slack_event(self.dm(text="echo hi"), event_id="A2")
        card = BridgeCard.objects.get()
        # A forged button on a message that is not our card is refused.
        card.message_id, real = "1699999999.000001", card.message_id
        self.slack_action(card, "approve")
        card.message_id = real
        self.assertEqual(ActionProposal.objects.get().status, "proposed")
        self.slack_action(card, "reject", action_ts="1700000200.1")
        self.assertEqual(ActionProposal.objects.get().status, "rejected")
        self.assertEqual(RAN, [])

    def test_unlinked_or_actions_off_cannot_decide(self, net):
        with patch("buddies.chat.run_buddy_turn", side_effect=self._turn_with_proposal()):
            self.slack_event(self.dm(text="echo hi"), event_id="A3")
        card = BridgeCard.objects.get()
        self.set_flag("ai_actions", False)
        self.slack_action(card, "approve")
        self.assertEqual(ActionProposal.objects.get().status, "proposed")
        self.set_flag("ai_actions", True)
        BridgeLink.objects.filter(pk=self.member_link.pk).update(status="revoked")
        self.slack_action(card, "approve", action_ts="1700000300.1")
        self.assertEqual(ActionProposal.objects.get().status, "proposed")

    def test_proposals_made_in_flobrain_are_mirrored_when_enabled(self, net):
        with self.captureOnCommitCallbacks(execute=True):
            proposal = ActionProposal.objects.create(org=self.org, user=self.users["member"], tool_key=ECHO, arguments={"text": "hi"}, summary="Echo hi")
        self.assertEqual(BridgeCard.objects.get().proposal, proposal)
        # Turned off for the workspace, nothing is mirrored.
        self.ws.mirror = {"approvals": False}
        self.ws.save()
        with self.captureOnCommitCallbacks(execute=True):
            ActionProposal.objects.create(org=self.org, user=self.users["member"], tool_key=ECHO, arguments={"text": "x"}, summary="Echo x")
        self.assertEqual(BridgeCard.objects.count(), 1)
        # Someone else's proposal never reaches this person's Slack.
        self.ws.mirror = {"approvals": True}
        self.ws.save()
        with self.captureOnCommitCallbacks(execute=True):
            ActionProposal.objects.create(org=self.org, user=self.users["other"], tool_key=ECHO, arguments={"text": "y"}, summary="Echo y")
        self.assertEqual(BridgeCard.objects.count(), 1)

    def test_notifications_are_mirrored_to_the_dm(self, net):
        from bridges.engine import mirror_notifications
        from notifications.services import notify

        self.ws.mirror = {"approvals": True, "automations": True, "escalations": False}
        self.ws.save()
        notify(self.org, [self.users["member"], self.users["other"]], "automation.notice", {"text": "Weekly report is ready", "title": "Reports"}, link="automations")
        notify(self.org, [self.users["member"]], "customer.escalated", {"text": "A customer needs a person"}, link="customers")
        self.assertEqual(mirror_notifications(), 1)
        post = net.slack("chat.postMessage")[-1]["body"]
        self.assertIn("Reports: Weekly report is ready", post["text"])
        self.assertTrue(post["channel"].startswith("D0DM"))
        self.assertEqual(mirror_notifications(), 0)  # once only
        BridgeLink.objects.filter(pk=self.member_link.pk).update(mirror=False)
        notify(self.org, [self.users["member"]], "automation.notice", {"text": "Again"}, link="automations")
        self.assertEqual(mirror_notifications(), 0)

    def test_secrets_never_in_requests_to_other_hosts_or_events(self, net):
        with patch("buddies.chat.run_buddy_turn", side_effect=fake_turn):
            self.slack_event(self.mention(), event_id="S1")
        stored = json.dumps([e.context for e in BridgeEvent.objects.all()])
        for secret in ALL_SECRETS:
            self.assertNotIn(secret, stored)
        for call in net.calls:
            self.assertIn(call["host"], ("slack.com", "hooks.slack.com"))
        self.assertTrue(TEAM)
