import json
import time
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings
from jwt.algorithms import RSAAlgorithm

from actions import plugins, registry
from actions.models import ActionProposal
from bridges import outbound, teams
from bridges._testkit import TEAMS_APP, TENANT, BridgesTestCase, FakeNet, fake_turn
from bridges.models import BridgeCard, BridgeEvent, BridgeLink
from buddies.models import Buddy

SERVICE = "https://smba.trafficmanager.net/emea/"
AAD = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER_AAD = "99999999-bbbb-4ccc-8ddd-eeeeeeeeeeee"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ROGUE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ECHO = "test.bridges_teams_echo"
RAN = []


def jwk(private=KEY, kid="k1", endorsements=("msteams",)):
    data = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    data.update({"kid": kid, "use": "sig"})
    if endorsements is not None:
        data["endorsements"] = list(endorsements)
    return data


def token(private=KEY, kid="k1", alg="RS256", **claims):
    now = int(time.time())
    body = {"iss": "https://api.botframework.com", "aud": TEAMS_APP, "exp": now + 600, "nbf": now - 10, "serviceUrl": SERVICE, **claims}
    body = {k: v for k, v in body.items() if v is not None}
    return jwt.encode(body, private, algorithm=alg, headers={"kid": kid})


def activity(text="<at>FloBrain</at> what is due?", aad=AAD, conv_type="personal", activity_id="1:abc", service=SERVICE, **extra):
    return {
        "type": "message",
        "id": activity_id,
        "channelId": "msteams",
        "serviceUrl": service,
        "from": {"id": "29:member", "name": "Member", "aadObjectId": aad},
        "recipient": {"id": "28:bot", "name": "FloBrain"},
        "conversation": {"id": "a:personal-conv" if conv_type == "personal" else "19:launch@thread.tacv2;messageid=1", "conversationType": conv_type, "tenantId": TENANT},
        "channelData": {"tenant": {"id": TENANT}},
        "text": text,
        **extra,
    }


def _check(user, org, args):
    return f"Echo {args.get('text', '')}"


def _execute(user, org, args):
    RAN.append(user.id)
    return {"ok": True}


class TeamsCase(BridgesTestCase):
    def setUp(self):
        super().setUp()
        self.ws = self.teams_ws()
        Buddy.objects.create(org=self.org, slug="helper", name="Helper", is_builtin=True, visibility=Buddy.VIS_ORG)

    def post(self, body, auth="good", **token_kw):
        headers = {}
        if auth == "good":
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token(**token_kw)}"
        elif auth:
            headers["HTTP_AUTHORIZATION"] = auth
        return self.client.post("/api/v2/hooks/teams/messages", data=json.dumps(body), content_type="application/json", **headers)


@patch("platform_api.net.fetch", new_callable=FakeNet)
class TeamsTokenTests(TeamsCase):
    def setUp(self):
        super().setUp()
        self.link("member", self.ws, AAD)

    def _keys(self, net, *keys):
        net.jwks = {"keys": list(keys) or [jwk()]}

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_good_token_reaches_the_buddy_and_replies_on_the_service_url(self, turn, net):
        self._keys(net)
        res = self.post(activity())
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(turn.call_args.args[0], self.users["member"])
        self.assertEqual(turn.call_args.args[3], "what is due?")
        reply = [c for c in net.calls if c["host"] == "smba.trafficmanager.net"][-1]
        self.assertEqual(reply["path"], "/emea/v3/conversations/a%3Apersonal-conv/activities/1%3Aabc")
        self.assertEqual(reply["headers"]["Authorization"], "Bearer ms-bot-access-token")
        self.assertEqual(reply["body"]["text"], "Buddy says: what is due?")
        token_call = [c for c in net.calls if c["host"] == "login.microsoftonline.com"][-1]
        self.assertEqual(token_call["body"]["scope"], "https://api.botframework.com/.default")

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_refused_tokens(self, turn, net):
        self._keys(net)
        cases = {
            "bad issuer": {"iss": "https://evil.example.com"},
            "bad audience": {"aud": "00000000-0000-4000-8000-000000000000"},
            "expired": {"exp": int(time.time()) - 3600},
            "service url mismatch": {"serviceUrl": "https://smba.trafficmanager.net/amer/"},
            "no service url claim": {"serviceUrl": None},
            "no expiry": {"exp": None},
            "wrong key": {"private": ROGUE},
            "unknown key id": {"kid": "nope"},
        }
        for name, kw in cases.items():
            with self.subTest(name):
                self.assertEqual(self.post(activity(activity_id=f"x{name}"), **kw).status_code, 401)
        self.assertEqual(self.post(activity(), auth=False).status_code, 401)
        self.assertEqual(self.post(activity(), auth="Basic abc").status_code, 401)
        hs = jwt.encode({"iss": "https://api.botframework.com", "aud": TEAMS_APP, "exp": int(time.time()) + 60, "serviceUrl": SERVICE}, "secret-key-for-hmac-test-1234567890", algorithm="HS256", headers={"kid": "k1"})
        self.assertEqual(self.post(activity(), auth=f"Bearer {hs}").status_code, 401)
        turn.assert_not_called()
        self.assertEqual(BridgeEvent.objects.count(), 0)

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_key_must_endorse_the_channel(self, turn, net):
        self._keys(net, jwk(endorsements=("skype",)))
        self.assertEqual(self.post(activity()).status_code, 401)

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_service_url_outside_the_allowlist_is_refused_even_when_signed(self, turn, net):
        self._keys(net)
        evil = "https://evil.example.com/"
        self.assertEqual(self.post(activity(service=evil), serviceUrl=evil).status_code, 401)
        evil2 = "https://smba.trafficmanager.net.evil.example/"
        self.assertEqual(self.post(activity(service=evil2), serviceUrl=evil2).status_code, 401)
        turn.assert_not_called()

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_signing_keys_are_cached(self, turn, net):
        self._keys(net)
        self.post(activity(activity_id="1:a"))
        self.post(activity(activity_id="1:b"))
        metadata = [c for c in net.calls if c["host"] == "login.botframework.com"]
        self.assertEqual(len(metadata), 2)  # openid configuration + keys, once
        self.assertEqual(turn.call_count, 2)

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_new_key_triggers_one_refresh(self, turn, net):
        self._keys(net)
        self.post(activity(activity_id="1:a"))
        teams._last_refresh["at"] = 0.0
        net.jwks = {"keys": [jwk(), jwk(ROGUE, kid="k2")]}
        self.assertEqual(self.post(activity(activity_id="1:b"), private=ROGUE, kid="k2").status_code, 200)

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_activity_handled_once_and_channel_posts_need_a_mention(self, turn, net):
        self._keys(net)
        self.post(activity(activity_id="1:dup"))
        self.post(activity(activity_id="1:dup"))
        self.assertEqual(turn.call_count, 1)
        self.post(activity(conv_type="channel", activity_id="1:nomention"))
        self.assertEqual(turn.call_count, 1)
        mention = {"type": "mention", "mentioned": {"id": "28:bot", "name": "FloBrain"}, "text": "<at>FloBrain</at>"}
        self.post(activity(conv_type="channel", activity_id="1:mention", entities=[mention]))
        self.assertEqual(turn.call_count, 2)

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_unknown_tenant_and_flag_off_are_ignored(self, turn, net):
        self._keys(net)
        other = activity(activity_id="1:t")
        other["conversation"]["tenantId"] = "11111111-1111-4111-8111-111111111111"
        other["channelData"]["tenant"]["id"] = "11111111-1111-4111-8111-111111111111"
        self.assertEqual(self.post(other).status_code, 200)
        self.set_flag("bridges", False)
        self.assertEqual(self.post(activity(activity_id="1:f")).status_code, 200)
        turn.assert_not_called()

    @override_settings(FLOBRAIN_TEAMS_APP_ID="")
    def test_not_set_up(self, net):
        with patch.dict("os.environ", {"FLOBRAIN_TEAMS_APP_ID": ""}):
            self.assertEqual(self.post(activity()).status_code, 501)


@patch("platform_api.net.fetch", new_callable=FakeNet)
class TeamsLinkAndApprovalTests(TeamsCase):
    def setUp(self):
        super().setUp()
        plugins.register_tool(ECHO, {"perm_key": "ai.use", "risk": "write", "label": "Echo", "description": "Echo", "schema": {"type": "object"}}, check=_check, execute=_execute)
        RAN.clear()

    def tearDown(self):
        registry.TOOLS.pop(ECHO, None)
        plugins._HANDLERS.pop(ECHO, None)
        super().tearDown()

    @patch("buddies.chat.run_buddy_turn", side_effect=fake_turn)
    def test_aad_user_is_suggested_then_confirmed_in_flobrain(self, turn, net):
        net.jwks = {"keys": [jwk()]}
        net.teams_member = {"aadObjectId": AAD, "name": "Member", "email": "member@acme.test"}
        self.post(activity(activity_id="1:first"))
        turn.assert_not_called()
        link = BridgeLink.objects.get(external_id=AAD)
        self.assertEqual((link.status, link.user), ("pending", self.users["member"]))
        self.assertIn("confirm", net.texts()[-1])
        listed = self.client_for("member").get(f"{self.base}/bridges").json()
        self.assertEqual(listed["my_links"][0]["status"], "pending")
        self.assertEqual(self.client_for("member").post(f"{self.base}/bridges/links/{link.id}/confirm").status_code, 200)
        self.post(activity(activity_id="1:second"))
        self.assertEqual(turn.call_args.args[0], self.users["member"])

    def test_adaptive_card_approval_only_by_the_proposer(self, net):
        net.jwks = {"keys": [jwk()]}
        self.link("member", self.ws, AAD)
        self.link("other", self.ws, OTHER_AAD)

        def turn(user, org, chat, text, data, surface="buddy"):
            proposal = ActionProposal.objects.create(org=org, user=user, thread=chat, buddy=chat.buddy, tool_key=ECHO, arguments={"text": "hi"}, summary="Echo hi")
            chat.messages.create(role="assistant", text="Prepared.")
            return 200, {"proposals": [{"id": str(proposal.id)}]}

        with patch("buddies.chat.run_buddy_turn", side_effect=turn):
            self.post(activity(activity_id="1:ask"))
        card = BridgeCard.objects.get()
        self.assertEqual(card.channel, "a:personal-conv")
        sent = [c for c in net.calls if c["path"].endswith("/v3/conversations/a%3Apersonal-conv/activities")][-1]
        content = sent["body"]["attachments"][0]["content"]
        self.assertEqual(content["actions"][0]["data"], {"flo_action": "approve", "proposal": str(card.proposal_id)})

        submit = {"flo_action": "approve", "proposal": str(card.proposal_id)}
        self.post(activity(text="", aad=OTHER_AAD, activity_id="1:other", value=submit, replyToId=card.message_id))
        card.proposal.refresh_from_db()
        self.assertEqual(card.proposal.status, "proposed")
        self.post(activity(text="", activity_id="1:mine", value=submit, replyToId=card.message_id))
        card.proposal.refresh_from_db()
        self.assertEqual(card.proposal.status, "executed")
        self.assertEqual(RAN, [self.users["member"].id])
        update = [c for c in net.calls if c["method"] == "PUT"][-1]
        self.assertIn(card.message_id, update["path"])
        self.assertEqual(update["body"]["attachments"][0]["content"]["body"][0]["text"], "Approved and done")


@patch("platform_api.net.fetch", new_callable=FakeNet)
class OutboundAllowlistTests(BridgesTestCase):
    def test_hosts(self, net):
        allowed = ["https://slack.com/api/chat.postMessage", "https://smba.trafficmanager.net/emea/v3/x", "https://europe.webchat.botframework.com/v3/x", "https://login.microsoftonline.com/x"]
        refused = [
            "http://slack.com/api/x", "https://evil.example.com/", "https://slack.com.evil.example/", "https://smba.trafficmanager.net:8443/x",
            "https://user:pw@slack.com/api/x", "https://botframework.com.evil.example/", "https://10.0.0.1/", "https://hooks.slack.com/commands/x",
            "https://evilbotframework.com/",
        ]
        for url in allowed:
            self.assertTrue(outbound.host_allowed(url), url)
        for url in refused:
            self.assertFalse(outbound.host_allowed(url), url)
            with self.assertRaises(outbound.BridgeHTTPError):
                outbound.request("GET", url)
        self.assertEqual(net.calls, [])

    def test_teams_replies_never_go_to_other_hosts(self, net):
        ws = self.teams_ws()
        result = teams.reply(ws, {"service_url": "https://evil.example.com/", "conversation": "a:x", "activity": "1"}, "hi")
        self.assertEqual(result, {"ok": False, "error": "host_not_allowed"})
        self.assertEqual(net.calls, [])

    def test_slash_command_response_url_must_be_slack(self, net):
        from bridges import slack

        ws = self.slack_ws()
        self.assertFalse(slack.respond(ws, "https://evil.example.com/commands/abcdefghijk", "hi"))
        self.assertEqual(slack.parse_command({"user_id": "U1X", "trigger_id": "t", "response_url": "https://evil.example.com/x"})["context"]["response_url"], "")
        self.assertEqual(net.calls, [])

    def test_demo_rows_never_call_out(self, net):
        from bridges import slack

        ws = self.slack_ws(demo=True)
        with outbound.capture() as calls:
            self.assertTrue(slack.post(ws, "C0X", "hello")["ok"])
            teams.reply(self.teams_ws_demo(), {"service_url": SERVICE, "conversation": "a:x", "activity": "1"}, "hi")
        self.assertEqual([c["call"] for c in calls], ["slack.chat.postMessage", "teams.send"])
        self.assertEqual(net.calls, [])

    def teams_ws_demo(self):
        ws = self.teams_ws()
        ws.demo = True
        return ws
