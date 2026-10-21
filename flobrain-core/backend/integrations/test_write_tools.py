"""Write-back connectors: registration, schemas, check() gating, approval gating, executors with a
mocked network, token refresh, the host allowlist, and demo simulation."""

import base64
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from actions import registry as action_registry
from actions.models import ActionProposal
from actions.plugins import handler
from actions.schema import validate
from actions.service import ActionDenied, approve, propose_from_calls, reject
from integrations.write import registry
from integrations.write.models import WriteActionToggle, WriteConnection
from integrations.write.testing import FakeNet, WriteBase
from integrations.write.transport import Client, WriteError, check_url

CLOUD = "11111111-2222-4333-8444-555555555555"
SAMPLES = {
    "google_workspace.gmail_send": {"to": ["counsel@example.com"], "subject": "NDA for review", "body": "Please review."},
    "google_workspace.gmail_draft": {"subject": "Draft", "body": "Hello"},
    "google_workspace.calendar_create_event": {"title": "Sync", "starts_at": "2026-10-22T10:00:00+02:00", "ends_at": "2026-10-22T10:30:00+02:00", "attendees": ["a@example.com"]},
    "google_workspace.docs_create": {"title": "Launch plan", "body": "Step one"},
    "google_workspace.sheets_append": {"spreadsheet_id": "1AbCdEfGhIjKlMnOpQrStUvWx", "rows": [["Acme", "=1+1"]]},
    "google_workspace.drive_upload": {"name": "notes.md", "content": "# Notes", "mime_type": "text/markdown"},
    "microsoft_365.outlook_send": {"to": ["b@example.com"], "subject": "Hi", "body": "Hello"},
    "microsoft_365.calendar_create_event": {"title": "Sync", "starts_at": "2026-10-22T10:00:00+02:00", "ends_at": "2026-10-22T11:00:00+02:00"},
    "microsoft_365.teams_post_message": {"team_id": CLOUD, "channel_id": "19:abc@thread.tacv2", "channel_name": "General", "body": "Shipped"},
    "microsoft_365.onedrive_upload": {"name": "notes.txt", "content": "hello"},
    "jira.create_issue": {"project_key": "APP", "summary": "Android login bug", "issue_type": "Bug", "description": "Steps"},
    "jira.add_comment": {"issue_key": "APP-12", "body": "Fixed in build 42"},
    "jira.transition_issue": {"issue_key": "APP-12", "to_status": "Done"},
    "hubspot.create_contact": {"email": "mona@example.com", "firstname": "Mona"},
    "hubspot.update_contact": {"email": "mona@example.com", "company": "Delta"},
    "hubspot.create_deal": {"dealname": "Delta renewal", "amount": "12000"},
    "hubspot.log_note": {"body": "Called Mona", "contact_email": "mona@example.com"},
    "odoo.create_lead": {"name": "Acme expansion", "email": "a@example.com", "expected_revenue": "5000"},
    "odoo.create_invoice_draft": {"customer": "Delta Trading", "lines": [{"description": "Workshop", "quantity": 2, "unit_price": "750.50"}]},
    "odoo.create_task": {"name": "Call the bank", "project_id": 3},
    "zoho.crm_create_lead": {"last_name": "Saleh", "company": "Delta"},
    "zoho.crm_create_deal": {"deal_name": "Delta renewal", "amount": "9000"},
    "zoho.books_create_invoice": {"customer_id": "460000000012345", "line_items": [{"name": "Workshop", "rate": "100", "quantity": 3}]},
}
CONFIG = {
    "jira": {"cloud_id": CLOUD, "site_url": "https://nile.atlassian.net"},
    "hubspot": {"portal_id": "4400"},
    "odoo": {"url": "https://nile.odoo.com", "database": "nile", "login": "ops@example.com", "uid": 7},
    "zoho": {"dc": "com", "api_domain": "https://www.zohoapis.com", "books_org_id": "700001"},
}


def _call(key, args):
    return {"name": action_registry.function_name(key), "arguments": json.dumps(args)}


class RegistrationTests(TestCase):
    def test_every_action_is_a_registered_approval_tool(self):
        keys = registry.tool_keys()
        self.assertEqual(len(keys), 23)
        self.assertEqual(set(keys), set(SAMPLES))
        for key in keys:
            spec = action_registry.TOOLS[key]
            self.assertEqual(spec["perm_key"], "integrations.act")
            self.assertIn(spec["risk"], ("high", "medium"))
            self.assertIsNotNone(handler(key))
            self.assertEqual(action_registry.tool_key_for(action_registry.function_name(key)), key)
            self.assertLessEqual(len(action_registry.function_name(key)), 64)

    def test_risk_levels(self):
        high = {k for k in registry.tool_keys() if action_registry.TOOLS[k]["risk"] == "high"}
        self.assertEqual(
            high,
            {
                "google_workspace.gmail_send",
                "microsoft_365.outlook_send",
                "microsoft_365.teams_post_message",
                "odoo.create_invoice_draft",
                "zoho.books_create_invoice",
            },
        )

    def test_schemas_are_strict_and_accept_samples(self):
        for key, sample in SAMPLES.items():
            schema = action_registry.TOOLS[key]["schema"]
            self.assertEqual(schema["type"], "object")
            self.assertIs(schema["additionalProperties"], False)
            validate(schema, sample)
            with self.assertRaises(ValueError):
                validate(schema, {**sample, "unexpected": 1})

    def test_oauth_providers_declare_scopes_for_their_actions(self):
        for provider in registry.providers():
            if provider.auth == "oauth2":
                self.assertTrue(provider.env_names()[0].startswith("FLOBRAIN_OAUTH_"))
                for action in provider.actions:
                    self.assertTrue(action.scopes, action.tool_key)
                    self.assertTrue(set(action.scopes) <= set(provider.scopes()))


class CheckGatingTests(WriteBase):
    def _check(self, key, args=None, user=None):
        return handler(key).check(user or self.member, self.org, args if args is not None else SAMPLES[key])

    def test_previews_for_every_action(self):
        for provider in registry.providers():
            self.connect(provider.key, config=CONFIG.get(provider.key))
        for key in SAMPLES:
            line = self._check(key)
            self.assertTrue(line and len(line) <= 300, key)
        self.assertEqual(self._check("google_workspace.gmail_send"), "Send email to counsel@example.com: Subject “NDA for review”")
        self.assertIn("total 1,501.00 (draft only, not posted or sent)", self._check("odoo.create_invoice_draft"))
        self.assertIn("invites", self._check("google_workspace.calendar_create_event"))

    def test_flag_off(self):
        self.connect("jira", config=CONFIG["jira"])
        self.org.settings = {"flags": {"write_integrations": False}}
        self.org.save()
        with self.assertRaises(ActionDenied) as ctx:
            self._check("jira.create_issue")
        self.assertEqual(ctx.exception.code, "not_available")

    def test_permission_missing(self):
        from organizations.permissions import engine

        self.connect("jira", config=CONFIG["jira"])
        member_defaults = frozenset(k for k in engine.ROLE_DEFAULTS["member"] if k != "integrations.act")
        with patch.dict(engine.ROLE_DEFAULTS, {"member": member_defaults}):
            with self.assertRaises(ActionDenied) as ctx:
                self._check("jira.create_issue")
        self.assertEqual(ctx.exception.code, "permission")

    def test_not_connected_and_not_set_up(self):
        with self.assertRaises(ActionDenied) as ctx:
            self._check("jira.create_issue")
        self.assertEqual(ctx.exception.code, "not_available")
        self.assertIn("Connect Jira first", str(ctx.exception))
        with override_settings(FLOBRAIN_OAUTH_JIRA_CLIENT_ID="", FLOBRAIN_OAUTH_JIRA_CLIENT_SECRET=""), patch.dict("os.environ", {}, clear=False):
            with self.assertRaises(ActionDenied) as ctx:
                self._check("jira.create_issue")
        self.assertIn("not set up", str(ctx.exception))

    def test_expired_connection_refused(self):
        conn = self.connect("hubspot", refresh=None, config=CONFIG["hubspot"], expires_at=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(ActionDenied):
            self._check("hubspot.create_contact")
        conn.refresh_from_db()
        self.assertEqual(conn.status, WriteConnection.STATUS_EXPIRED)

    def test_disabled_action(self):
        self.connect("jira", config=CONFIG["jira"])
        WriteActionToggle.objects.create(org=self.org, tool_key="jira.create_issue", enabled=False)
        with self.assertRaises(ActionDenied) as ctx:
            self._check("jira.create_issue")
        self.assertEqual(ctx.exception.code, "not_available")
        self._check("jira.add_comment")  # other actions still work

    def test_invalid_arguments(self):
        self.connect("google_workspace")
        for bad in (
            {"to": [], "subject": "x", "body": "y"},
            {"to": ["a@example.com"], "subject": "x\r\nBcc: evil@example.com", "body": "y"},
            {"to": ["not-an-email"], "subject": "x", "body": "y"},
        ):
            with self.assertRaises(ActionDenied) as ctx:
                self._check("google_workspace.gmail_send", bad)
            self.assertEqual(ctx.exception.code, "invalid")

    def test_missing_scope(self):
        self.connect("google_workspace", scopes=["openid", "email", "https://www.googleapis.com/auth/gmail.compose"])
        self._check("google_workspace.gmail_draft")
        with self.assertRaises(ActionDenied) as ctx:
            self._check("google_workspace.gmail_send")
        self.assertIn("gmail.send", str(ctx.exception))

    def test_personal_connection_preferred_for_google(self):
        self.connect("google_workspace", token="tok-ORG-NOT-REAL-0000")
        self.connect("google_workspace", token="tok-MINE-NOT-REAL-1111", owner=self.member)
        net = FakeNet({("POST", "https://gmail.googleapis.com"): [(200, {"id": "m1"})]})
        with net.patch():
            handler("google_workspace.gmail_send").execute(self.member, self.org, SAMPLES["google_workspace.gmail_send"])
            handler("google_workspace.gmail_send").execute(self.other, self.org, SAMPLES["google_workspace.gmail_send"])
        self.assertEqual(net.calls[0]["headers"]["Authorization"], "Bearer tok-MINE-NOT-REAL-1111")
        self.assertEqual(net.calls[1]["headers"]["Authorization"], "Bearer tok-ORG-NOT-REAL-0000")


class ApprovalGatingTests(WriteBase):
    def setUp(self):
        super().setUp()
        self.connect("jira", config=CONFIG["jira"])
        self.key = "jira.create_issue"

    def _propose(self):
        return propose_from_calls(self.member, self.org, None, None, [_call(self.key, SAMPLES[self.key])], [self.key])

    def test_nothing_runs_until_approved(self):
        net = FakeNet({("POST", "https://api.atlassian.com"): [(201, {"id": "10001", "key": "APP-7"})]})
        with net.patch():
            proposals, errors = self._propose()
            self.assertEqual(errors, [])
            self.assertEqual(len(proposals), 1)
            self.assertEqual(net.calls, [])
            self.assertEqual(proposals[0].summary, "Create Jira Bug in APP: “Android login bug”")
            done = approve(proposals[0].id, self.member, self.org)
        self.assertEqual(done.status, ActionProposal.STATUS_EXECUTED)
        self.assertEqual(len(net.calls), 1)
        self.assertEqual(done.result["url"], "https://nile.atlassian.net/browse/APP-7")
        self.assertFalse(done.result["simulated"])
        from organizations.models import AuditEvent

        audit = AuditEvent.objects.filter(org=self.org, action="integration.write").first()
        self.assertIsNotNone(audit)
        self.assertNotIn("Android login bug", json.dumps(audit.payload))

    def test_rejected_never_runs(self):
        net = FakeNet()
        with net.patch():
            proposals, _ = self._propose()
            reject(proposals[0].id, self.member, self.org)
            with self.assertRaises(ActionDenied):
                approve(proposals[0].id, self.member, self.org)
        self.assertEqual(net.calls, [])

    def test_disconnected_after_proposal_rolls_back(self):
        net = FakeNet()
        with net.patch():
            proposals, _ = self._propose()
            WriteConnection.objects.filter(org=self.org).delete()
            with self.assertRaises(ActionDenied):
                approve(proposals[0].id, self.member, self.org)
        proposals[0].refresh_from_db()
        self.assertEqual(proposals[0].status, ActionProposal.STATUS_PROPOSED)
        self.assertEqual(net.calls, [])

    def test_provider_error_marks_failed(self):
        net = FakeNet({("POST", "https://api.atlassian.com"): [(400, {"errorMessages": ["Project APP does not exist"]})]})
        with net.patch():
            proposals, _ = self._propose()
            done = approve(proposals[0].id, self.member, self.org)
        self.assertEqual(done.status, ActionProposal.STATUS_FAILED)
        self.assertIn("Jira answered 400: Project APP does not exist", done.error)


class ExecutorTests(WriteBase):
    def run_action(self, key, routes, args=None, config=None, user=None):
        provider = key.split(".")[0]
        if not WriteConnection.objects.filter(org=self.org, provider=provider).exists():
            self.connect(provider, config=config if config is not None else CONFIG.get(provider))
        net = FakeNet(routes)
        with net.patch():
            result = handler(key).execute(user or self.member, self.org, args or SAMPLES[key])
        return net, result

    def test_gmail_send(self):
        net, result = self.run_action("google_workspace.gmail_send", {("POST", "https://gmail.googleapis.com"): [(200, {"id": "18c"})]})
        call = net.calls[0]
        self.assertEqual(call["url"], "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
        self.assertEqual(call["headers"]["Authorization"], "Bearer tok-ACCESS-NOT-REAL-1234")
        raw = base64.urlsafe_b64decode(net.json(0)["raw"]).decode()
        self.assertIn("To: counsel@example.com", raw)
        self.assertIn("Subject: NDA for review", raw)
        self.assertEqual(result["url"], "https://mail.google.com/mail/u/0/#all/18c")

    def test_calendar_event_and_sheets_raw(self):
        net, result = self.run_action(
            "google_workspace.calendar_create_event",
            {("POST", "https://www.googleapis.com/calendar"): [(200, {"id": "ev1", "htmlLink": "https://calendar.google.com/event?eid=ev1"})]},
        )
        self.assertIn("sendUpdates=none", net.calls[0]["url"])
        self.assertEqual(net.json(0)["attendees"], [{"email": "a@example.com"}])
        self.assertEqual(result["url"], "https://calendar.google.com/event?eid=ev1")
        net, _ = self.run_action("google_workspace.sheets_append", {("POST", "https://sheets.googleapis.com"): [(200, {"updates": {"updatedRange": "Sheet1!A5:B5"}})]})
        self.assertIn("valueInputOption=RAW", net.calls[0]["url"])
        self.assertNotIn("USER_ENTERED", net.calls[0]["url"])
        self.assertEqual(net.json(0)["values"], [["Acme", "=1+1"]])

    def test_docs_create_two_calls(self):
        net, result = self.run_action(
            "google_workspace.docs_create",
            {("POST", "https://docs.googleapis.com/v1/documents/doc1"): [(200, {})], ("POST", "https://docs.googleapis.com/v1/documents"): [(200, {"documentId": "doc1"})]},
        )
        self.assertEqual([c["url"] for c in net.calls], ["https://docs.googleapis.com/v1/documents", "https://docs.googleapis.com/v1/documents/doc1:batchUpdate"])
        self.assertEqual(result["url"], "https://docs.google.com/document/d/doc1/edit")

    def test_outlook_and_teams(self):
        net, result = self.run_action("microsoft_365.outlook_send", {("POST", "https://graph.microsoft.com"): [(202, b"")]})
        self.assertEqual(net.calls[0]["url"], "https://graph.microsoft.com/v1.0/me/sendMail")
        self.assertEqual(net.json(0)["message"]["toRecipients"], [{"emailAddress": {"address": "b@example.com"}}])
        net, result = self.run_action(
            "microsoft_365.teams_post_message", {("POST", "https://graph.microsoft.com"): [(201, {"id": "m1", "webUrl": "https://teams.microsoft.com/l/message/m1"})]}
        )
        self.assertEqual(net.calls[0]["url"], f"https://graph.microsoft.com/v1.0/teams/{CLOUD}/channels/19%3Aabc%40thread.tacv2/messages")
        self.assertEqual(result["url"], "https://teams.microsoft.com/l/message/m1")

    def test_onedrive_put(self):
        net, _ = self.run_action("microsoft_365.onedrive_upload", {("PUT", "https://graph.microsoft.com"): [(201, {"id": "f1", "webUrl": "https://onedrive.live.com/f1"})]})
        self.assertEqual(net.calls[0]["method"], "PUT")
        self.assertTrue(net.calls[0]["url"].startswith("https://graph.microsoft.com/v1.0/me/drive/root:/FloBrain/notes.txt:/content"))
        self.assertEqual(net.calls[0]["body"], b"hello")

    def test_jira_create_comment_transition(self):
        net, result = self.run_action("jira.create_issue", {("POST", "https://api.atlassian.com"): [(201, {"id": "1", "key": "APP-9"})]})
        self.assertEqual(net.calls[0]["url"], f"https://api.atlassian.com/ex/jira/{CLOUD}/rest/api/3/issue")
        fields = net.json(0)["fields"]
        self.assertEqual(fields["issuetype"], {"name": "Bug"})
        self.assertEqual(fields["description"]["type"], "doc")
        net, result = self.run_action(
            "jira.transition_issue",
            {
                ("GET", "https://api.atlassian.com"): [(200, {"transitions": [{"id": "21", "name": "Start"}, {"id": "31", "name": "Finish", "to": {"name": "Done"}}]})],
                ("POST", "https://api.atlassian.com"): [(204, b"")],
            },
        )
        self.assertEqual(net.json(1), {"transition": {"id": "31"}})
        self.assertEqual(result["url"], "https://nile.atlassian.net/browse/APP-12")

    def test_hubspot_contact_and_note(self):
        net, result = self.run_action("hubspot.create_contact", {("POST", "https://api.hubapi.com"): [(201, {"id": "501"})]})
        self.assertEqual(net.calls[0]["url"], "https://api.hubapi.com/crm/v3/objects/contacts")
        self.assertEqual(net.json(0), {"properties": {"email": "mona@example.com", "firstname": "Mona"}})
        self.assertEqual(result["url"], "https://app.hubspot.com/contacts/4400/record/0-1/501")
        net, _ = self.run_action(
            "hubspot.log_note",
            {("GET", "https://api.hubapi.com"): [(200, {"id": "501"})], ("POST", "https://api.hubapi.com"): [(201, {"id": "n1"})]},
        )
        self.assertIn("idProperty=email", net.calls[0]["url"])
        self.assertEqual(net.json(1)["associations"][0]["to"], {"id": "501"})

    def test_odoo_jsonrpc_invoice(self):
        net, result = self.run_action(
            "odoo.create_invoice_draft",
            {("POST", "https://nile.odoo.com/jsonrpc"): [(200, {"result": [42]}), (200, {"result": 99})]},
        )
        search, create = net.json(0)["params"], net.json(1)["params"]
        self.assertEqual(search["args"][:5], ["nile", 7, "tok-ACCESS-NOT-REAL-1234", "res.partner", "search"])
        self.assertEqual(create["args"][3:5], ["account.move", "create"])
        values = create["args"][5][0]
        self.assertEqual(values["move_type"], "out_invoice")
        self.assertEqual(values["partner_id"], 42)
        self.assertEqual(values["invoice_line_ids"][0][2], {"name": "Workshop", "quantity": 2, "price_unit": 750.5})
        self.assertNotIn("action_post", json.dumps(create))
        self.assertEqual(result["url"], "https://nile.odoo.com/web#id=99&model=account.move&view_type=form")
        self.assertNotIn("Authorization", net.calls[0]["headers"])

    def test_odoo_rpc_error_is_reported(self):
        self.connect("odoo", config=CONFIG["odoo"])
        net = FakeNet({("POST", "https://nile.odoo.com/jsonrpc"): [(200, {"error": {"message": "Odoo Server Error", "data": {"message": "Invalid field"}}})]})
        with net.patch(), self.assertRaises(ActionDenied) as ctx:
            handler("odoo.create_lead").execute(self.member, self.org, SAMPLES["odoo.create_lead"])
        self.assertEqual(ctx.exception.code, "provider_error")
        self.assertIn("Invalid field", str(ctx.exception))

    def test_zoho_auth_header_and_books(self):
        net, result = self.run_action(
            "zoho.crm_create_lead", {("POST", "https://www.zohoapis.com"): [(201, {"data": [{"status": "success", "details": {"id": "5551"}}]})]}
        )
        self.assertEqual(net.calls[0]["headers"]["Authorization"], "Zoho-oauthtoken tok-ACCESS-NOT-REAL-1234")
        self.assertEqual(net.calls[0]["url"], "https://www.zohoapis.com/crm/v6/Leads")
        self.assertEqual(result["url"], "https://crm.zoho.com/crm/tab/Leads/5551")
        net, result = self.run_action(
            "zoho.books_create_invoice", {("POST", "https://www.zohoapis.com"): [(201, {"invoice": {"invoice_id": "9001", "invoice_number": "INV-1"}})]}
        )
        self.assertIn("organization_id=700001", net.calls[0]["url"])
        self.assertIn("send=false", net.calls[0]["url"])
        self.assertEqual(result["title"], "INV-1")

    def test_zoho_api_domain_outside_allowlist_is_ignored(self):
        self.connect("zoho", config={**CONFIG["zoho"], "api_domain": "https://evil.example.com"})
        net, _ = self.run_action("zoho.crm_create_deal", {("POST", "https://www.zohoapis.com"): [(201, {"data": [{"status": "success", "details": {"id": "1"}}]})]})
        self.assertTrue(all(c["url"].startswith("https://www.zohoapis.com/") for c in net.calls))


class RefreshTests(WriteBase):
    def test_refresh_once_on_401_then_retry(self):
        conn = self.connect("hubspot", config=CONFIG["hubspot"])
        net = FakeNet(
            {
                ("POST", "https://api.hubapi.com/oauth/v1/token"): [(200, {"access_token": "tok-NEW-NOT-REAL-9999", "refresh_token": "tok-R2-NOT-REAL", "expires_in": 1800})],
                ("POST", "https://api.hubapi.com/crm"): [(401, {"message": "expired"}), (201, {"id": "77"})],
            }
        )
        with net.patch():
            result = handler("hubspot.create_contact").execute(self.member, self.org, SAMPLES["hubspot.create_contact"])
        self.assertEqual(result["id"], "77")
        self.assertEqual([c["url"].split("?")[0] for c in net.calls], [
            "https://api.hubapi.com/crm/v3/objects/contacts",
            "https://api.hubapi.com/oauth/v1/token",
            "https://api.hubapi.com/crm/v3/objects/contacts",
        ])
        self.assertIn(b"grant_type=refresh_token", net.calls[1]["body"])
        self.assertIn(b"client_secret=test-hubspot-secret-NOT-REAL", net.calls[1]["body"])
        self.assertEqual(net.calls[2]["headers"]["Authorization"], "Bearer tok-NEW-NOT-REAL-9999")
        conn.refresh_from_db()
        self.assertEqual(conn.access_token(), "tok-NEW-NOT-REAL-9999")
        self.assertEqual(conn.refresh_token(), "tok-R2-NOT-REAL")
        self.assertIsNotNone(conn.expires_at)

    def test_second_401_expires_connection(self):
        from integrations.write.connections import connection_for

        conn = self.connect("hubspot", config=CONFIG["hubspot"])
        net = FakeNet(
            {
                ("POST", "https://api.hubapi.com/oauth/v1/token"): [(200, {"access_token": "tok-NEW-NOT-REAL-9999"})],
                ("POST", "https://api.hubapi.com/crm"): [(401, {})],
            }
        )
        with net.patch(), self.assertRaises(WriteError) as ctx:
            Client(registry.get("hubspot"), conn).call("POST", "https://api.hubapi.com/crm/v3/objects/contacts", json_body={})
        self.assertEqual(ctx.exception.code, "expired")
        self.assertEqual(len([c for c in net.calls if "oauth" in c["url"]]), 1)  # refreshed once only
        conn.refresh_from_db()
        self.assertEqual(conn.status, WriteConnection.STATUS_EXPIRED)
        self.assertIsNone(connection_for(self.member, self.org, registry.get("hubspot"))[0])

    def test_failed_refresh_expires(self):
        conn = self.connect("jira", config=CONFIG["jira"])
        net = FakeNet({("POST", "https://auth.atlassian.com"): [(400, {"error": "invalid_grant"})], ("POST", "https://api.atlassian.com"): [(401, {})]})
        with net.patch(), self.assertRaises(WriteError):
            Client(registry.get("jira"), conn).call("POST", f"https://api.atlassian.com/ex/jira/{CLOUD}/rest/api/3/issue", json_body={})
        conn.refresh_from_db()
        self.assertEqual(conn.status, WriteConnection.STATUS_EXPIRED)
        self.assertEqual(conn.last_error, "refresh_failed")

    def test_expired_access_token_refreshed_before_call(self):
        conn = self.connect("jira", config=CONFIG["jira"], expires_at=timezone.now() - timedelta(minutes=5))
        net = FakeNet({("POST", "https://auth.atlassian.com"): [(200, {"access_token": "tok-FRESH-NOT-REAL", "expires_in": 3600})], ("POST", "https://api.atlassian.com"): [(201, {"key": "APP-1"})]})
        with net.patch():
            handler("jira.create_issue").execute(self.member, self.org, SAMPLES["jira.create_issue"])
        self.assertEqual(net.calls[0]["url"], "https://auth.atlassian.com/oauth/token")
        self.assertEqual(net.calls[1]["headers"]["Authorization"], "Bearer tok-FRESH-NOT-REAL")


class AllowlistTests(WriteBase):
    def test_hosts_outside_the_list_are_blocked_before_any_socket(self):
        google = registry.get("google_workspace")
        for url in (
            "https://evil.example.com/x",
            "http://gmail.googleapis.com/x",
            "https://gmail.googleapis.com:8443/x",
            "https://user:pw@gmail.googleapis.com/x",
            "https://169.254.169.254/latest",
            "file:///etc/passwd",
        ):
            with self.assertRaises(WriteError) as ctx:
                check_url(google, url)
            self.assertEqual(ctx.exception.code, "blocked_host")
        self.assertEqual(check_url(google, "https://gmail.googleapis.com/gmail/v1"), "gmail.googleapis.com")

    def test_client_never_sends_to_unlisted_host(self):
        conn = self.connect("hubspot")
        net = FakeNet()
        with net.patch(), self.assertRaises(WriteError):
            Client(registry.get("hubspot"), conn).call("POST", "https://internal.example.com/admin", json_body={})
        self.assertEqual(net.calls, [])

    def test_odoo_hosts(self):
        from integrations.write.catalog import odoo

        self.assertEqual(odoo.normalize_url("https://nile.odoo.com/"), "https://nile.odoo.com")
        for bad in ("http://nile.odoo.com", "https://erp.internal", "https://10.0.0.5", "https://nile.odoo.com/web?x=1", "https://nile.odoo.com:8069"):
            self.assertIsNone(odoo.normalize_url(bad), bad)
        with override_settings(FLOBRAIN_ODOO_ALLOWED_HOSTS="erp.acme.example"):
            self.assertEqual(odoo.normalize_url("https://erp.acme.example"), "https://erp.acme.example")
        conn = self.connect("odoo", config=CONFIG["odoo"])
        prov = registry.get("odoo")
        self.assertTrue(prov.host_allowed("nile.odoo.com", conn))
        self.assertFalse(prov.host_allowed("other.odoo.com", conn))

    def test_private_address_from_dns_is_blocked(self):
        from platform_api import net as platform_net

        conn = self.connect("hubspot")
        with patch("platform_api.net.resolve", return_value=["10.0.0.8"]), self.assertRaises(WriteError) as ctx:
            Client(registry.get("hubspot"), conn).call("POST", "https://api.hubapi.com/crm/v3/objects/contacts", json_body={})
        self.assertEqual(ctx.exception.code, "blocked_host")
        self.assertTrue(hasattr(platform_net, "fetch_full"))


class SecretsTests(WriteBase):
    def test_tokens_are_encrypted_and_never_in_repr(self):
        conn = self.connect("jira", config=CONFIG["jira"])
        raw = bytes(WriteConnection.objects.get(pk=conn.pk).access_ciphertext)
        self.assertNotIn(b"tok-ACCESS-NOT-REAL-1234", raw)
        self.assertNotIn("tok-", repr(conn))
        # a ciphertext copied to another row does not decrypt
        other = self.connect("hubspot")
        other.access_ciphertext = conn.access_ciphertext
        from integrations.crypto import CredentialCryptoError

        with self.assertRaises(CredentialCryptoError):
            other.access_token()

    def test_provider_error_text_never_has_token(self):
        self.connect("hubspot", config=CONFIG["hubspot"])
        net = FakeNet({("POST", "https://api.hubapi.com"): [(500, b"internal tok-ACCESS-NOT-REAL-1234")]})
        with net.patch(), self.assertRaises(ActionDenied) as ctx:
            handler("hubspot.create_deal").execute(self.member, self.org, SAMPLES["hubspot.create_deal"])
        self.assertNotIn("tok-", str(ctx.exception))


@override_settings(DEMO_MODE=True)
class DemoTests(WriteBase):
    def setUp(self):
        super().setUp()
        self.org.settings = {**self.org.settings, "demo": True}
        self.org.save()

    def test_demo_connection_simulates_without_network(self):
        self.connect("jira", demo=True, config={"cloud_id": CLOUD})
        net = FakeNet()
        with net.patch():
            proposals, errors = propose_from_calls(self.member, self.org, None, None, [_call("jira.create_issue", SAMPLES["jira.create_issue"])], ["jira.create_issue"])
            self.assertEqual(errors, [])
            self.assertTrue(proposals[0].summary.endswith("[demo, simulated]"))
            done = approve(proposals[0].id, self.member, self.org)
        self.assertEqual(net.calls, [])
        self.assertEqual(done.status, ActionProposal.STATUS_EXECUTED)
        self.assertTrue(done.result["simulated"])
        self.assertTrue(done.result["url"].startswith("https://jira.example.com/browse/APP-"))

    def test_every_demo_executor(self):
        for provider in registry.providers():
            self.connect(provider.key, demo=True, config=provider.demo_config)
        with FakeNet().patch():
            for key, args in SAMPLES.items():
                result = handler(key).execute(self.member, self.org, args)
                self.assertTrue(result["simulated"], key)
                self.assertRegex(result["url"], r"^https://[a-z0-9.-]+\.example\.com/", key)

    def test_demo_connection_refused_outside_demo(self):
        self.connect("jira", demo=True)
        with override_settings(DEMO_MODE=False), self.assertRaises(ActionDenied) as ctx:
            handler("jira.create_issue").check(self.member, self.org, SAMPLES["jira.create_issue"])
        self.assertIn("demo", str(ctx.exception))

    def test_demo_handler_proposes_the_right_action(self):
        from brain.llm.demo_handlers import connectors

        tools = action_registry.provider_tools(registry.tool_keys())
        cases = {
            "create a Jira issue for the Android login bug": ("jira__create_issue", {"summary": "Android login bug", "issue_type": "Bug"}),
            "send the NDA to counsel by Gmail": ("google_workspace__gmail_send", {"to": ["counsel@example.com"], "subject": "NDA"}),
            "add Mona to HubSpot": ("hubspot__create_contact", {"firstname": "Mona", "email": "mona@example.com"}),
        }
        for question, (name, expected) in cases.items():
            result = connectors.handle("You are a FloBrain buddy helping", question, [{"role": "user", "content": question}], tools)
            self.assertEqual(result.tool_calls[0]["name"], name)
            args = json.loads(result.tool_calls[0]["arguments"])
            for k, v in expected.items():
                self.assertEqual(args[k], v)
            key = action_registry.tool_key_for(name)
            validate(action_registry.TOOLS[key]["schema"], args)
        self.assertIsNone(connectors.handle("You are a FloBrain buddy", "hello", [{"role": "user", "content": "hello"}], tools))
        self.assertIsNone(connectors.handle("Translate", "add Mona to HubSpot", [], tools))
        self.assertIsNone(connectors.handle("You are a FloBrain buddy", "add Mona to HubSpot", [], action_registry.provider_tools(["tasks.create"])))

    def test_demo_seed(self):
        import importlib

        from buddies.models import Buddy

        extras = importlib.import_module("demo.extras.94_connectors")
        Buddy.objects.create(org=self.org, slug="project-management", name="PM", allowed_tools=["tasks.create"])
        extras.seed(self.org, {"admin": self.admin, "member": self.member, "lead": self.other, "owner": self.owner}, timezone.now())
        self.assertEqual(WriteConnection.objects.filter(org=self.org, demo=True).count(), 7)
        self.assertEqual(ActionProposal.objects.filter(org=self.org, tool_key__in=registry.tool_keys()).count(), 5)
        buddy = Buddy.objects.get(org=self.org, slug="back-office")
        self.assertEqual(len(buddy.allowed_tools), 23)
        self.assertIn("jira.create_issue", Buddy.objects.get(org=self.org, slug="project-management").allowed_tools)
        handler("jira.create_issue").check(self.member, self.org, SAMPLES["jira.create_issue"])
