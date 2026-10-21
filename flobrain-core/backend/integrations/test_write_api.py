"""Write-back connector endpoints: gating, catalog without secrets, OAuth state and PKCE, the
confirm step, Odoo API keys, disconnect, action switches, the actions log and demo connect."""

import base64
import hashlib
import json
import urllib.parse
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from actions.models import ActionProposal
from integrations.write.models import WriteActionToggle, WriteConnection, WriteOAuthState
from integrations.write.testing import FakeNet, WriteBase

TOKEN_RESPONSE = {"access_token": "tok-OAUTH-ACCESS-NOT-REAL", "refresh_token": "tok-OAUTH-REFRESH-NOT-REAL", "expires_in": 3600, "scope": "read:jira-work write:jira-work offline_access"}
SITES = [{"id": "11111111-2222-4333-8444-555555555555", "url": "https://nile.atlassian.net", "name": "nile"}]


class GateTests(WriteBase):
    def test_flag_off_is_501(self):
        self.org.settings = {"flags": {}}
        self.org.save()
        self.auth(self.admin)
        self.assertEqual(self.client.get(self.base).status_code, 501)
        self.assertEqual(self.client.get(f"{self.base}/log").status_code, 501)

    def test_without_act_or_manage_is_403(self):
        from organizations.permissions import engine

        self.auth(self.member)
        member_defaults = frozenset(k for k in engine.ROLE_DEFAULTS["member"] if k != "integrations.act")
        with patch.dict(engine.ROLE_DEFAULTS, {"member": member_defaults}):
            self.assertEqual(self.client.get(self.base).status_code, 403)

    def test_outsider_is_403(self):
        from django.contrib.auth.hashers import make_password

        from users.models import User

        outsider = User.objects.create(email="w-out@example.com", password_hash=make_password("x"))
        self.auth(outsider)
        self.assertEqual(self.client.get(self.base).status_code, 403)


class CatalogTests(WriteBase):
    def test_catalog_lists_providers_and_never_secrets(self):
        self.connect("jira", config={"cloud_id": SITES[0]["id"], "site_url": "https://nile.atlassian.net"})
        self.connect("google_workspace", owner=self.member, token="tok-PERSONAL-NOT-REAL")
        self.auth(self.admin)
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        text = json.dumps(body)
        self.assertNotIn("tok-", text)
        self.assertNotIn("ciphertext", text)
        providers = {p["key"]: p for p in body["providers"]}
        self.assertEqual(set(providers), {"google_workspace", "microsoft_365", "jira", "hubspot", "odoo", "zoho"})
        self.assertEqual(providers["jira"]["status"], "connected")
        self.assertEqual(providers["hubspot"]["status"], "not_connected")
        self.assertIsNone(providers["google_workspace"]["personal"])  # the admin can't see Youssef's account
        self.assertTrue(body["can_manage"])
        self.assertEqual(len(providers["jira"]["actions"]), 3)
        self.auth(self.member)
        mine = {p["key"]: p for p in self.client.get(self.base).json()["providers"]}
        self.assertEqual(mine["google_workspace"]["status"], "connected_personal")
        self.assertNotIn("tok-", json.dumps(mine))

    def test_not_set_up_without_env(self):
        self.auth(self.admin)
        with override_settings(FLOBRAIN_OAUTH_HUBSPOT_CLIENT_ID="", FLOBRAIN_OAUTH_HUBSPOT_CLIENT_SECRET=""):
            providers = {p["key"]: p for p in self.client.get(self.base).json()["providers"]}
            self.assertEqual(providers["hubspot"]["status"], "not_set_up")
            self.assertEqual(providers["hubspot"]["env"], ["FLOBRAIN_OAUTH_HUBSPOT_CLIENT_ID", "FLOBRAIN_OAUTH_HUBSPOT_CLIENT_SECRET"])
            self.assertEqual(self.client.post(f"{self.base}/hubspot/connect", {}, format="json").status_code, 501)


class OAuthTests(WriteBase):
    def _start(self, user=None, provider="jira", scope="org"):
        self.auth(user or self.admin)
        response = self.client.post(f"{self.base}/{provider}/connect", {"scope": scope}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        url = response.json()["authorize_url"]
        return url, dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))

    def _callback(self, provider, state, code="good-code"):
        from rest_framework.test import APIClient

        return APIClient().get(f"/api/v2/integrations/write/oauth/callback/{provider}", {"state": state, "code": code})

    def _jira_net(self):
        return FakeNet({("POST", "https://auth.atlassian.com/oauth/token"): [(200, TOKEN_RESPONSE)], ("GET", "https://api.atlassian.com/oauth/token/accessible-resources"): [(200, SITES)]})

    def test_authorize_url_uses_pkce_and_server_side_state(self):
        url, params = self._start()
        self.assertTrue(url.startswith("https://auth.atlassian.com/authorize?"))
        self.assertEqual(params["code_challenge_method"], "S256")
        self.assertEqual(params["client_id"], "test-jira-client")
        self.assertEqual(params["redirect_uri"], "http://localhost:8000/api/v2/integrations/write/oauth/callback/jira")
        self.assertIn("write:jira-work", params["scope"])
        self.assertNotIn("client_secret", url)
        row = WriteOAuthState.objects.get()
        self.assertEqual(row.state_hash, hashlib.sha256(params["state"].encode()).hexdigest())
        self.assertNotIn(params["state"].encode(), bytes(row.verifier_ciphertext))

    def test_full_flow_with_confirm(self):
        _, params = self._start()
        net = self._jira_net()
        with net.patch():
            response = self._callback("jira", params["state"])
        self.assertEqual(response.status_code, 302)
        location = urllib.parse.urlparse(response["Location"])
        query = dict(urllib.parse.parse_qsl(location.query))
        self.assertEqual(location.path, "/w/w-org/integrations")
        self.assertEqual(query["write_result"], "confirm")
        self.assertNotIn("tok-", response["Location"])
        # the verifier sent to the token endpoint matches the challenge in the authorize URL
        sent = dict(urllib.parse.parse_qsl(net.calls[0]["body"].decode()))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, params["code_challenge"])
        self.assertEqual(sent["grant_type"], "authorization_code")
        self.assertEqual(net.calls[1]["headers"]["Authorization"], "Bearer tok-OAUTH-ACCESS-NOT-REAL")
        self.assertFalse(WriteConnection.objects.exists())  # nothing connected before the confirm
        # someone else can't finish it
        self.auth(self.member)
        self.assertEqual(self.client.post(f"{self.base}/confirm", {"code": query["write_confirm"]}, format="json").status_code, 404)
        self.auth(self.admin)
        confirmed = self.client.post(f"{self.base}/confirm", {"code": query["write_confirm"]}, format="json")
        self.assertEqual(confirmed.status_code, 201)
        self.assertNotIn("tok-", json.dumps(confirmed.json()))
        conn = WriteConnection.objects.get(provider="jira")
        self.assertIsNone(conn.owner_id)
        self.assertEqual(conn.access_token(), "tok-OAUTH-ACCESS-NOT-REAL")
        self.assertEqual(conn.refresh_token(), "tok-OAUTH-REFRESH-NOT-REAL")
        self.assertEqual(conn.config["cloud_id"], SITES[0]["id"])
        self.assertEqual(conn.config["site_url"], "https://nile.atlassian.net")
        self.assertIn("write:jira-work", conn.scopes)
        self.assertIsNone(WriteOAuthState.objects.get().result_ciphertext)
        # the code works once
        self.assertEqual(self.client.post(f"{self.base}/confirm", {"code": query["write_confirm"]}, format="json").status_code, 404)

    def test_state_is_single_use_and_expires(self):
        _, params = self._start()
        with self._jira_net().patch():
            self.assertIn("write_result=confirm", self._callback("jira", params["state"])["Location"])
            self.assertIn("write_result=invalid_state", self._callback("jira", params["state"])["Location"])
        _, params = self._start()
        WriteOAuthState.objects.filter(used_at__isnull=True).update(expires_at=timezone.now() - timedelta(seconds=1))
        net = FakeNet()
        with net.patch():
            self.assertIn("write_result=invalid_state", self._callback("jira", params["state"])["Location"])
            self.assertIn("write_result=invalid_state", self._callback("jira", "guessed-state")["Location"])
            self.assertIn("write_result=invalid_state", self._callback("hubspot", params["state"])["Location"])
        self.assertEqual(net.calls, [])

    def test_failed_exchange(self):
        _, params = self._start()
        with FakeNet({("POST", "https://auth.atlassian.com"): [(400, {"error": "invalid_grant"})]}).patch():
            self.assertIn("write_result=exchange_failed", self._callback("jira", params["state"])["Location"])
        self.assertFalse(WriteConnection.objects.exists())

    def test_org_connect_needs_manage_personal_needs_act(self):
        self.auth(self.member)
        self.assertEqual(self.client.post(f"{self.base}/jira/connect", {}, format="json").status_code, 403)
        self.assertEqual(self.client.post(f"{self.base}/jira/connect", {"scope": "personal"}, format="json").status_code, 400)
        url, params = self._start(user=self.member, provider="google_workspace", scope="personal")
        self.assertEqual(params["access_type"], "offline")
        self.assertTrue(WriteOAuthState.objects.get().personal)
        net = FakeNet(
            {
                ("POST", "https://oauth2.googleapis.com/token"): [(200, {"access_token": "tok-G-NOT-REAL", "expires_in": 3599, "scope": "openid email https://www.googleapis.com/auth/gmail.send"})],
                ("GET", "https://www.googleapis.com/oauth2/v3/userinfo"): [(200, {"email": "youssef@example.com"})],
            }
        )
        with net.patch():
            location = self._callback("google_workspace", params["state"])["Location"]
        code = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(location).query))["write_confirm"]
        self.auth(self.member)
        self.assertEqual(self.client.post(f"{self.base}/confirm", {"code": code}, format="json").status_code, 201)
        conn = WriteConnection.objects.get(provider="google_workspace")
        self.assertEqual(conn.owner_id, self.member.id)
        self.assertEqual(conn.account_label, "youssef@example.com")

    def test_encryption_not_configured(self):
        self.auth(self.admin)
        with override_settings(CREDENTIALS_ENCRYPTION_KEY=""):
            self.assertEqual(self.client.post(f"{self.base}/jira/connect", {}, format="json").status_code, 501)


class OdooConnectTests(WriteBase):
    def test_connect_with_api_key(self):
        self.auth(self.admin)
        net = FakeNet({("POST", "https://nile.odoo.com/jsonrpc"): [(200, {"result": 7})]})
        body = {"url": "https://nile.odoo.com", "database": "nile", "login": "ops@example.com", "api_key": "odoo-KEY-NOT-REAL-abcd"}
        with net.patch():
            response = self.client.post(f"{self.base}/odoo/connect", body, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["secret_hint"], "…abcd")
        self.assertNotIn("odoo-KEY", json.dumps(response.json()))
        self.assertEqual(net.json(0)["params"]["args"], ["nile", "ops@example.com", "odoo-KEY-NOT-REAL-abcd", {}])
        conn = WriteConnection.objects.get(provider="odoo")
        self.assertEqual(conn.config["uid"], 7)
        self.assertEqual(conn.access_token(), "odoo-KEY-NOT-REAL-abcd")

    def test_bad_host_and_bad_key(self):
        self.auth(self.admin)
        net = FakeNet({("POST", "https://nile.odoo.com/jsonrpc"): [(200, {"result": False})]})
        with net.patch():
            self.assertEqual(self.client.post(f"{self.base}/odoo/connect", {"url": "https://10.0.0.1", "database": "x", "login": "a", "api_key": "12345678"}, format="json").status_code, 400)
            self.assertEqual(self.client.post(f"{self.base}/odoo/connect", {"url": "https://erp.internal.example", "database": "x", "login": "a", "api_key": "12345678"}, format="json").status_code, 400)
            bad = self.client.post(f"{self.base}/odoo/connect", {"url": "https://nile.odoo.com", "database": "nile", "login": "a", "api_key": "wrong-key-123"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(len(net.calls), 1)
        self.assertFalse(WriteConnection.objects.exists())


class ManageTests(WriteBase):
    def test_disconnect(self):
        conn = self.connect("jira")
        mine = self.connect("google_workspace", owner=self.member)
        self.auth(self.member)
        self.assertEqual(self.client.delete(f"{self.base}/connections/{conn.id}").status_code, 403)
        self.auth(self.admin)
        self.assertEqual(self.client.delete(f"{self.base}/connections/{mine.id}").status_code, 404)  # someone's personal account
        self.assertEqual(self.client.delete(f"{self.base}/connections/{conn.id}").status_code, 204)
        self.auth(self.member)
        self.assertEqual(self.client.delete(f"{self.base}/connections/{mine.id}").status_code, 204)
        self.assertFalse(WriteConnection.objects.exists())

    def test_toggle_action(self):
        self.auth(self.member)
        self.assertEqual(self.client.patch(f"{self.base}/actions/jira.create_issue", {"enabled": False}, format="json").status_code, 403)
        self.auth(self.admin)
        self.assertEqual(self.client.patch(f"{self.base}/actions/jira.nope", {"enabled": False}, format="json").status_code, 404)
        self.assertEqual(self.client.patch(f"{self.base}/actions/jira.create_issue", {"enabled": "no"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(f"{self.base}/actions/jira.create_issue", {"enabled": False}, format="json").status_code, 200)
        self.assertFalse(WriteActionToggle.objects.get(tool_key="jira.create_issue").enabled)
        jira = next(p for p in self.client.get(self.base).json()["providers"] if p["key"] == "jira")
        self.assertFalse(next(a for a in jira["actions"] if a["key"] == "create_issue")["enabled"])

    def test_log_states_and_visibility(self):
        for user, status in ((self.member, ActionProposal.STATUS_PROPOSED), (self.other, ActionProposal.STATUS_EXECUTED), (self.member, ActionProposal.STATUS_FAILED)):
            ActionProposal.objects.create(
                org=self.org, user=user, tool_key="jira.create_issue", arguments={}, summary="Create Jira Task", status=status,
                result={"url": "https://nile.atlassian.net/browse/APP-1"} if status == ActionProposal.STATUS_EXECUTED else {},
            )
        ActionProposal.objects.create(org=self.org, user=self.member, tool_key="tasks.create", arguments={"title": "x"}, summary="x")
        self.auth(self.admin)
        rows = self.client.get(f"{self.base}/log").json()
        self.assertEqual(sorted(r["state"] for r in rows), ["done", "failed", "waiting"])
        self.assertEqual(next(r for r in rows if r["state"] == "done")["url"], "https://nile.atlassian.net/browse/APP-1")
        self.assertEqual(len(self.client.get(f"{self.base}/log", {"state": "waiting"}).json()), 1)
        self.auth(self.member)
        self.assertEqual(len(self.client.get(f"{self.base}/log").json()), 2)


@override_settings(DEMO_MODE=True)
class DemoConnectTests(WriteBase):
    def test_demo_connect_is_simulated(self):
        self.org.settings = {**self.org.settings, "demo": True}
        self.org.save()
        self.auth(self.admin)
        net = FakeNet()
        with net.patch(), override_settings(FLOBRAIN_OAUTH_ZOHO_CLIENT_ID=""):
            catalog = {p["key"]: p for p in self.client.get(self.base).json()["providers"]}
            self.assertEqual(catalog["zoho"]["status"], "not_connected")  # demo can connect without an OAuth app
            response = self.client.post(f"{self.base}/zoho/connect", {}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["simulated"])
        self.assertEqual(net.calls, [])
        conn = WriteConnection.objects.get(provider="zoho")
        self.assertTrue(conn.demo)
        self.assertIsNone(conn.access_ciphertext)
