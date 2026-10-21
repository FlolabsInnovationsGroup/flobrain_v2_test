import json
import urllib.parse
from unittest.mock import patch

from django.test import override_settings

from bridges._testkit import (
    ALL_SECRETS,
    BOT_TOKEN,
    CLIENT_ID,
    TEAM,
    TEAMS_APP,
    TENANT,
    BridgesTestCase,
    FakeNet,
)
from bridges.models import BridgeLink, BridgeOAuthState, BridgeWorkspace
from buddies.models import Buddy
from organizations.models import Organization


class SecretsCheck:
    def assertNoSecrets(self, *responses):
        for res in responses:
            body = res.content.decode()
            for secret in ALL_SECRETS:
                self.assertNotIn(secret, body)


@patch("platform_api.net.fetch", new_callable=FakeNet)
class GateTests(BridgesTestCase, SecretsCheck):
    def test_flag_off_is_501_everywhere(self, net):
        self.set_flag("bridges", False)
        c = self.client_for("owner")
        for method, path in (
            ("get", "/bridges"), ("post", "/bridges/slack/install"), ("post", "/bridges/teams/connect"), ("get", "/bridges/teams/manifest"),
            ("get", "/bridges/links"), ("post", "/bridges/links"), ("post", "/bridges/demo/simulate"),
        ):
            res = getattr(c, method)(f"{self.base}{path}", {}, format="json")
            self.assertEqual(res.status_code, 501, path)
            self.assertEqual(res.json()["error"], "not_implemented")

    def test_admin_only_endpoints_need_bridges_manage(self, net):
        ws = self.slack_ws()
        c = self.client_for("member")
        for method, path in (
            ("post", "/bridges/slack/install"), ("post", "/bridges/slack/confirm"), ("post", "/bridges/teams/connect"),
            ("get", "/bridges/teams/manifest"), ("patch", f"/bridges/workspaces/{ws.id}"), ("delete", f"/bridges/workspaces/{ws.id}"),
            ("post", f"/bridges/workspaces/{ws.id}/test"), ("get", "/bridges/links?scope=all"),
        ):
            res = getattr(c, method)(f"{self.base}{path}", {}, format="json") if method != "get" else c.get(f"{self.base}{path}")
            self.assertEqual(res.status_code, 403, path)
        ws.refresh_from_db()
        self.assertEqual(ws.status, "active")

    def test_members_see_status_but_no_setup_or_hints(self, net):
        self.slack_ws()
        member = self.client_for("member").get(f"{self.base}/bridges").json()
        self.assertFalse(member["can_manage"])
        self.assertNotIn("setup", member)
        self.assertNotIn("secret_hints", member["workspaces"][0])
        admin = self.client_for("admin").get(f"{self.base}/bridges")
        data = admin.json()
        self.assertTrue(data["setup"]["slack"]["ready"])
        self.assertEqual(data["workspaces"][0]["secret_hints"], {"bot_token": "…uvwx"})
        self.assertNoSecrets(admin)

    def test_other_orgs_are_not_visible(self, net):
        other = Organization.objects.create(name="Other", slug="other-br", settings={"flags": {"bridges": True}})
        ws = BridgeWorkspace.objects.create(org=other, platform="slack", external_id="T0OTHERORG", status="active")
        res = self.client_for("owner").patch(f"{self.base}/bridges/workspaces/{ws.id}", {"mirror": {"approvals": False}}, format="json")
        self.assertEqual(res.status_code, 404)


@patch("platform_api.net.fetch", new_callable=FakeNet)
class SlackInstallTests(BridgesTestCase, SecretsCheck):
    def _start(self, who="admin"):
        res = self.client_for(who).post(f"{self.base}/bridges/slack/install")
        self.assertEqual(res.status_code, 200, res.content)
        url = urllib.parse.urlparse(res.json()["authorize_url"])
        query = dict(urllib.parse.parse_qsl(url.query))
        self.assertEqual((url.hostname, url.path), ("slack.com", "/oauth/v2/authorize"))
        self.assertEqual(query["client_id"], CLIENT_ID)
        self.assertIn("users:read.email", query["scope"])
        self.assertTrue(query["redirect_uri"].endswith("/api/v2/bridges/slack/oauth/callback"))
        return query["state"]

    def _callback(self, state, code="abc"):
        res = self.client.get("/api/v2/bridges/slack/oauth/callback", {"state": state, "code": code})
        self.assertEqual(res.status_code, 302)
        return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(res["Location"]).query)), res["Location"]

    def test_install_confirm_by_the_starter(self, net):
        state = self._start()
        params, location = self._callback(state)
        self.assertEqual(params["bridge_result"], "confirm")
        self.assertIn("/w/acme-br/settings/bridges", location)
        self.assertNotIn(BOT_TOKEN, location)
        # The callback is single use.
        self.assertEqual(self._callback(state)[0]["bridge_result"], "invalid_state")
        # Another admin can't finish it.
        self.assertEqual(self.client_for("owner").post(f"{self.base}/bridges/slack/confirm", {"code": params["bridge_confirm"]}, format="json").status_code, 404)
        res = self.client_for("admin").post(f"{self.base}/bridges/slack/confirm", {"code": params["bridge_confirm"]}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertNoSecrets(res)
        ws = BridgeWorkspace.objects.get()
        self.assertEqual((ws.external_id, ws.name, ws.status), (TEAM, "Acme Slack", "active"))
        self.assertNotIn(BOT_TOKEN.encode(), bytes(ws.secrets_ciphertext))
        from channels import vault

        self.assertEqual(vault.get(ws, "bot_token"), BOT_TOKEN)
        self.assertIsNone(BridgeOAuthState.objects.get().result_ciphertext)
        # The confirm code works once.
        self.assertEqual(self.client_for("admin").post(f"{self.base}/bridges/slack/confirm", {"code": params["bridge_confirm"]}, format="json").status_code, 404)
        exchange = net.slack("oauth.v2.access")[-1]
        self.assertTrue(exchange["headers"]["Authorization"].startswith("Basic "))

    def test_bad_state_and_cancel(self, net):
        self.assertEqual(self._callback("not-a-state")[0]["bridge_result"], "invalid_state")
        state = self._start()
        res = self.client.get("/api/v2/bridges/slack/oauth/callback", {"state": state, "error": "access_denied"})
        self.assertIn("bridge_result=cancelled", res["Location"])

    def test_a_slack_workspace_belongs_to_one_org(self, net):
        other = Organization.objects.create(name="Other", slug="other-br2", settings={"flags": {"bridges": True}})
        BridgeWorkspace.objects.create(org=other, platform="slack", external_id=TEAM, status="active")
        params, _ = self._callback(self._start())
        res = self.client_for("admin").post(f"{self.base}/bridges/slack/confirm", {"code": params["bridge_confirm"]}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertFalse(BridgeWorkspace.objects.filter(org=self.org).exists())

    @override_settings(FLOBRAIN_SLACK_CLIENT_ID="", FLOBRAIN_SLACK_CLIENT_SECRET="")
    def test_not_set_up(self, net):
        with patch.dict("os.environ", {"FLOBRAIN_SLACK_CLIENT_ID": "", "FLOBRAIN_SLACK_CLIENT_SECRET": ""}):
            res = self.client_for("admin").post(f"{self.base}/bridges/slack/install")
            overview = self.client_for("admin").get(f"{self.base}/bridges").json()
        self.assertEqual(res.status_code, 501)
        self.assertEqual(res.json()["missing"], ["FLOBRAIN_SLACK_CLIENT_ID", "FLOBRAIN_SLACK_CLIENT_SECRET"])
        self.assertFalse(overview["ready"]["slack"])

    def test_settings_test_and_disconnect(self, net):
        ws = self.slack_ws()
        planner = Buddy.objects.create(org=self.org, slug="planner", name="Planner", is_builtin=True, visibility=Buddy.VIS_ORG)
        c = self.client_for("admin")
        res = c.patch(f"{self.base}/bridges/workspaces/{ws.id}", {"default_buddy": str(planner.id), "mirror": {"automations": True}}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["mirror"], {"approvals": True, "automations": True, "escalations": False})
        self.assertEqual(c.patch(f"{self.base}/bridges/workspaces/{ws.id}", {"mirror": {"everything": True}}, format="json").status_code, 400)
        self.assertEqual(c.patch(f"{self.base}/bridges/workspaces/{ws.id}", {"default_buddy": "00000000-0000-4000-8000-000000000000"}, format="json").status_code, 400)
        test = c.post(f"{self.base}/bridges/workspaces/{ws.id}/test")
        self.assertEqual(test.json()["status"], "active")
        self.assertNoSecrets(res, test)
        link = self.link("member", ws, "U0MEMBER")
        self.assertEqual(c.delete(f"{self.base}/bridges/workspaces/{ws.id}").status_code, 204)
        ws.refresh_from_db()
        link.refresh_from_db()
        self.assertEqual((ws.status, ws.secrets_ciphertext, link.status), ("disconnected", None, "revoked"))
        self.assertEqual(len(net.slack("auth.revoke")), 1)
        # Once disconnected, the same Slack workspace can be installed again (even by another org).
        BridgeWorkspace.objects.create(org=Organization.objects.create(name="New", slug="new-br"), platform="slack", external_id=TEAM, status="active")


@patch("platform_api.net.fetch", new_callable=FakeNet)
class TeamsSettingsTests(BridgesTestCase, SecretsCheck):
    def test_connect_and_manifest(self, net):
        c = self.client_for("admin")
        self.assertEqual(c.post(f"{self.base}/bridges/teams/connect", {"tenant_id": "contoso.onmicrosoft.com"}, format="json").status_code, 400)
        res = c.post(f"{self.base}/bridges/teams/connect", {"tenant_id": TENANT.upper()}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(BridgeWorkspace.objects.get().external_id, TENANT)
        manifest = c.get(f"{self.base}/bridges/teams/manifest")
        self.assertEqual(manifest.status_code, 200)
        self.assertIn("attachment", manifest["Content-Disposition"])
        data = json.loads(manifest.content)
        self.assertEqual(data["bots"][0]["botId"], TEAMS_APP)
        self.assertEqual(data["manifestVersion"], "1.17")
        self.assertNoSecrets(res, manifest)
        test = c.post(f"{self.base}/bridges/workspaces/{BridgeWorkspace.objects.get().id}/test")
        self.assertEqual(test.json()["status"], "active")
        self.assertNoSecrets(test)

    def test_tenant_belongs_to_one_org(self, net):
        other = Organization.objects.create(name="Other", slug="other-br3")
        BridgeWorkspace.objects.create(org=other, platform="teams", external_id=TENANT, status="active")
        res = self.client_for("admin").post(f"{self.base}/bridges/teams/connect", {"tenant_id": TENANT}, format="json")
        self.assertEqual(res.status_code, 409)

    @override_settings(FLOBRAIN_TEAMS_APP_SECRET="")
    def test_not_set_up(self, net):
        with patch.dict("os.environ", {"FLOBRAIN_TEAMS_APP_SECRET": ""}):
            res = self.client_for("admin").post(f"{self.base}/bridges/teams/connect", {"tenant_id": TENANT}, format="json")
        self.assertEqual(res.status_code, 501)
        self.assertEqual(res.json()["missing"], ["FLOBRAIN_TEAMS_APP_SECRET"])


@patch("platform_api.net.fetch", new_callable=FakeNet)
class LinkMyAccountTests(BridgesTestCase, SecretsCheck):
    def setUp(self):
        super().setUp()
        self.ws = self.slack_ws()

    def test_link_my_slack_finds_by_email_then_i_confirm(self, net):
        net.profiles["U0MEMBER"] = {"email": "member@acme.test", "real_name": "Member Person"}
        c = self.client_for("member")
        res = c.post(f"{self.base}/bridges/links", {"workspace": str(self.ws.id)}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["status"], res.json()["account"], res.json()["email"]), ("pending", "Member Person", "m•••@acme.test"))
        self.assertEqual(net.slack("users.lookupByEmail")[-1]["url"].split("?")[1], "email=member%40acme.test")
        link_id = res.json()["id"]
        confirmed = c.post(f"{self.base}/bridges/links/{link_id}/confirm")
        self.assertEqual(confirmed.json()["status"], "active")
        self.assertEqual(c.post(f"{self.base}/bridges/links/{link_id}/confirm").status_code, 409)
        self.assertNoSecrets(res, confirmed)

    def test_no_slack_account_with_my_email(self, net):
        net.profiles["U0SOMEONE"] = {"email": "someone@else.test"}
        res = self.client_for("member").post(f"{self.base}/bridges/links", {"workspace": str(self.ws.id)}, format="json")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(BridgeLink.objects.exists())

    def test_one_person_per_account(self, net):
        old = self.link("other", self.ws, "U0SHARED")
        pending = self.link("member", self.ws, "U0SHARED", status="pending")
        self.client_for("member").post(f"{self.base}/bridges/links/{pending.id}/confirm")
        old.refresh_from_db()
        self.assertEqual(old.status, "revoked")

    def test_unlink_rules_and_admin_list(self, net):
        mine = self.link("member", self.ws, "U0MEMBER")
        theirs = self.link("other", self.ws, "U0OTHER")
        member = self.client_for("member")
        self.assertEqual(member.delete(f"{self.base}/bridges/links/{theirs.id}").status_code, 404)
        self.assertEqual(member.patch(f"{self.base}/bridges/links/{mine.id}", {"mirror": False}, format="json").json()["mirror"], False)
        self.assertEqual([r["id"] for r in member.get(f"{self.base}/bridges/links").json()], [str(mine.id)])
        everyone = self.client_for("admin").get(f"{self.base}/bridges/links?scope=all").json()
        self.assertEqual({r["person"]["email"] for r in everyone}, {"member@acme.test", "other@acme.test"})
        self.assertEqual(self.client_for("admin").delete(f"{self.base}/bridges/links/{theirs.id}").status_code, 204)
        self.assertEqual(member.delete(f"{self.base}/bridges/links/{mine.id}").status_code, 204)
        self.assertEqual(BridgeLink.objects.filter(status="active").count(), 0)

    @override_settings(BRIDGES_LIMITS={"link_lookups_per_hour": 2})
    def test_lookups_are_rate_limited(self, net):
        c = self.client_for("member")
        codes = [c.post(f"{self.base}/bridges/links", {"workspace": str(self.ws.id)}, format="json").status_code for _ in range(3)]
        self.assertEqual(codes, [404, 404, 429])

    def test_demo_endpoints_are_404_outside_the_demo(self, net):
        res = self.client_for("admin").post(f"{self.base}/bridges/demo/simulate", {"text": "hi"}, format="json")
        self.assertEqual(res.status_code, 404)
