"""MCP hub (growth round M1): the added MCP tools (scopes, permissions, proposals only), tool
annotations, governance of outside MCP servers, the call log (redaction, retention) and the
settings endpoints (permissions, flag off)."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from actions.models import ActionProposal
from brain.llm.providers import ProviderResult
from buddies.models import Buddy
from meetings.models import Meeting, MeetingSummary
from organizations.models import OrgMembership
from platform_api import demo_hosts, demo_mcp, external_agents, mcp, mcp_client, mcp_hub, mcp_tools_extra
from platform_api.models import (
    SCOPES,
    ExternalAgentCall,
    ExternalAgentHost,
    ExternalAgentServer,
    MCPCallLog,
    MCPServerPolicy,
    OAuthClient,
    OAuthGrant,
)
from platform_api.tests import PlatformBase
from tasks.models import Task

FLAGS = {"api_access": True, "ai_actions": True, "mcp_hub": True, "buddies": True, "automations": True, "data_buddy": True, "external_agents": True, "memory_search": False}


class HubBase(PlatformBase):
    def setUp(self):
        super().setUp()
        self.org.settings = {"flags": dict(FLAGS)}
        self.org.save()

    def rpc(self, api, method, params=None):
        return api.post("/api/mcp", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, format="json")

    def call(self, api, name, args=None):
        response = self.rpc(api, "tools/call", {"name": name, "arguments": args or {}})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["result"]

    def pat(self, user, scopes):
        return self._pat(self._token(user, ["mcp", *scopes])["token"])


class ToolTests(HubBase):
    def test_every_tool_needs_its_scope(self):
        api = self.pat(self.member, [])
        listed = {t["name"] for t in self.rpc(api, "tools/list").json()["result"]["tools"]}
        self.assertEqual(listed, set(), "no tool without its scope")
        every = list(mcp.TOOLS) + list(mcp_tools_extra.TOOLS)
        for name in every:
            result = self.call(api, name, {})
            self.assertTrue(result["isError"], name)
            self.assertEqual(result["structuredContent"]["error"], "missing_scope", name)
        full = self.pat(self.member, [s for s in SCOPES if s != "mcp"])
        listed = {t["name"] for t in self.rpc(full, "tools/list").json()["result"]["tools"]}
        self.assertEqual(listed, set(every))

    def test_annotations(self):
        api = self.pat(self.member, [s for s in SCOPES if s != "mcp"])
        tools = {t["name"]: t for t in self.rpc(api, "tools/list").json()["result"]["tools"]}
        self.assertTrue(tools["meetings_recent"]["annotations"]["readOnlyHint"])
        self.assertEqual(tools["buddy_ask"]["annotations"]["title"], "Ask a buddy")
        create = tools["tasks_create"]["annotations"]
        self.assertEqual((create["readOnlyHint"], create["destructiveHint"]), (False, False))
        self.assertTrue(tools["automation_run"]["annotations"]["destructiveHint"])
        self.assertTrue(all("readOnlyHint" in t["annotations"] for t in tools.values()))

    def test_flag_off_hides_hub_tools_but_keeps_base_tools(self):
        self.org.settings = {"flags": {**FLAGS, "mcp_hub": False}}
        self.org.save()
        api = self.pat(self.member, [s for s in SCOPES if s != "mcp"])
        listed = {t["name"] for t in self.rpc(api, "tools/list").json()["result"]["tools"]}
        self.assertEqual(listed, set(mcp.TOOLS))
        self.assertEqual(self.call(api, "approvals_list")["structuredContent"]["error"], "unknown_tool")
        self.call(api, "tasks_list")
        self.assertFalse(MCPCallLog.objects.exists(), "no call log while the hub is off")

    def test_feature_flags_gate_each_tool(self):
        self.org.settings = {"flags": {**FLAGS, "automations": False, "buddies": False}}
        self.org.save()
        api = self.pat(self.member, [s for s in SCOPES if s != "mcp"])
        listed = {t["name"] for t in self.rpc(api, "tools/list").json()["result"]["tools"]}
        self.assertNotIn("automation_run", listed)
        self.assertNotIn("buddy_ask", listed)
        self.assertIn("approvals_list", listed)

    def test_meetings_only_from_rooms_you_can_open_and_summaries_only(self):
        seen = Meeting.objects.create(org=self.org, room=self.room, title="Standup")
        MeetingSummary.objects.create(meeting=seen, text="We shipped.", decisions=[{"text": "Ship Friday"}], action_items=[{"id": "a", "text": "Write notes"}])
        hidden = Meeting.objects.create(org=self.org, room=self.hidden_room, title="Secret board")
        MeetingSummary.objects.create(meeting=hidden, text="Layoffs.")
        Meeting.objects.create(org=self.org, room=self.room, title="Old", started_at=timezone.now() - timedelta(days=40))
        api = self.pat(self.member, ["meetings:read"])
        rows = self.call(api, "meetings_recent")["structuredContent"]["meetings"]
        self.assertEqual([m["title"] for m in rows], ["Standup"])
        self.assertEqual(rows[0]["decisions"], ["Ship Friday"])
        self.assertNotIn("transcript", json.dumps(rows))
        self.assertEqual(len(self.call(api, "meetings_recent", {"days": 60})["structuredContent"]["meetings"]), 2)
        self.assertTrue(self.call(api, "meetings_recent", {"days": 0})["isError"], "validated")

    def test_approvals_are_your_own(self):
        ActionProposal.objects.create(org=self.org, user=self.member, tool_key="tasks.create", arguments={"title": "Mine"}, summary="Create task Mine")
        ActionProposal.objects.create(org=self.org, user=self.other, tool_key="tasks.create", arguments={"title": "Theirs"}, summary="Create task Theirs")
        data = self.call(self.pat(self.member, ["approvals:read"]), "approvals_list")["structuredContent"]
        self.assertEqual([a["summary"] for a in data["actions"]], ["Create task Mine"])
        self.assertNotIn("arguments", data["actions"][0])

    def _buddy(self, owner, slug, **extra):
        return Buddy.objects.create(org=self.org, slug=slug, name=slug.title(), created_by=owner, system_prompt="Be brief.", **extra)

    def test_buddy_ask_reads_only_and_respects_visibility(self):
        self._buddy(self.member, "mine", allowed_tools=["tasks.create"])
        self._buddy(self.other, "theirs")
        api = self.pat(self.member, ["buddies:read"])
        self.assertEqual(self.call(api, "buddy_ask", {"buddy": "theirs", "question": "hi"})["structuredContent"]["error"], "not_found")
        answer = ProviderResult(text="Hello from the buddy", model="m", input_tokens=3, output_tokens=4, total_tokens=7, provider="test", tool_calls=[{"name": "tasks__create", "arguments": "{}"}])
        with patch("brain.llm.direct.is_configured", return_value=True), patch("brain.llm.providers.DirectProvider.complete", return_value=answer) as complete:
            result = self.call(api, "buddy_ask", {"buddy": "mine", "question": "hi"})
        self.assertFalse(result["isError"], result)
        self.assertEqual(result["structuredContent"]["answer"], "Hello from the buddy")
        self.assertIsNone(complete.call_args.kwargs["tools"], "no tools are offered")
        self.assertIn("Be brief.", complete.call_args.args[0][0]["content"])
        self.assertFalse(ActionProposal.objects.exists(), "tool calls in the answer are ignored")

    def test_buddy_ask_needs_ai_use(self):
        self._buddy(self.member, "mine")
        api = self.pat(self.member, ["buddies:read"])
        with patch("organizations.permissions.can", return_value=False):
            result = self.call(api, "buddy_ask", {"buddy": "mine", "question": "hi"})
        self.assertEqual(result["structuredContent"]["error"], "permission_denied")

    def test_data_ask_only_sees_your_datasets(self):
        api = self.pat(self.member, ["data:read"])
        result = self.call(api, "data_ask", {"question": "How many sign-ups?"})
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"], "not_found")

    def test_write_tools_only_propose(self):
        from automations.models import Workflow, WorkflowRun

        wf = Workflow.objects.create(org=self.org, name="Weekly digest", enabled=True, created_by=self.owner, run_as=self.owner, trigger={"type": "manual"}, steps=[])
        api = self.pat(self.member, ["tasks:write", "automations:write"])
        made = self.call(api, "tasks_create", {"title": "From Claude"})
        self.assertEqual(made["structuredContent"]["proposal"]["status"], "proposed")
        run = self.call(api, "automation_run", {"workflow_name": "weekly digest"})
        self.assertFalse(run["isError"], run)
        self.assertEqual(run["structuredContent"]["proposal"]["tool"], "automations.run")
        self.assertEqual(run["structuredContent"]["proposal"]["summary"], "Run workflow “Weekly digest”")
        self.assertFalse(Task.objects.filter(title="From Claude").exists())
        self.assertFalse(WorkflowRun.objects.filter(workflow=wf).exists(), "nothing runs before approval")
        self.assertEqual(ActionProposal.objects.filter(user=self.member).count(), 2)
        wf.enabled = False
        wf.save()
        self.assertEqual(self.call(api, "automation_run", {"workflow": str(wf.id)})["structuredContent"]["error"], "permission")

    def test_call_log_is_redacted(self):
        api = self.pat(self.member, ["tasks:write"])
        self.call(api, "tasks_create", {"title": "password is hunter2", "api_key": "sk-live-SECRET"})
        self.call(api, "tasks_create", {"title": "call Mona about hunter2"})
        rows = list(MCPCallLog.objects.order_by("created_at"))
        self.assertEqual(len(rows), 2)
        dump = json.dumps([r.args_summary for r in rows])
        self.assertNotIn("hunter2", dump)
        self.assertNotIn("sk-live", dump)
        self.assertEqual(rows[0].args_summary["api_key"], "[hidden]")
        self.assertEqual(rows[1].args_summary["title"], "text (23 chars)")
        self.assertEqual((rows[0].ok, rows[0].error), (False, "invalid_arguments"))
        self.assertTrue(rows[1].ok)
        self.assertTrue(rows[1].client_name.startswith("Personal token"))
        self.assertEqual(rows[1].direction, "inbound")

    def test_redact_summary_shapes(self):
        out = mcp_hub.redact_summary({"q": "x" * 5, "n": 4111111111111111, "ok": True, "items": [1, 2], "nested": {"password": "p", "a": "bc"}, "Authorization": "Bearer x"})
        self.assertEqual(out, {"q": "text (5 chars)", "n": "number", "ok": True, "items": "list (2 items)", "nested": {"password": "[hidden]", "a": "text (2 chars)"}, "Authorization": "[hidden]"})

    def test_retention(self):
        old = MCPCallLog.objects.create(org=self.org, tool="tasks_list")
        MCPCallLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=91))
        MCPCallLog.objects.create(org=self.org, tool="rooms_list")
        self.assertEqual(mcp_hub.purge_old_logs(), 1)
        self.assertEqual(list(MCPCallLog.objects.values_list("tool", flat=True)), ["rooms_list"])


@override_settings(DEMO_MODE=True)
class GovernanceTests(HubBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        ExternalAgentHost.objects.create(org=self.org, host=demo_hosts.DEMO_MCP_HOST, added_by=self.owner)
        tools = mcp_client.clean_tools(demo_mcp.TOOLS + [{"name": "delete_order", "description": "Delete", "inputSchema": {"type": "object"}}])
        self.server = ExternalAgentServer(org=self.org, name="Partner", url=demo_hosts.DEMO_MCP_URL, allowed=True, created_by=self.owner)
        external_agents._apply_tools(self.server, {"name": "demo"}, tools)
        self.server.tools_approved_hash = self.server.tools_hash
        self.server.save()
        self.buddy = Buddy.objects.create(org=self.org, slug="helper", name="Helper", created_by=self.member)
        self.other_buddy = Buddy.objects.create(org=self.org, slug="other", name="Other", created_by=self.member)

    def offered(self, buddy=None):
        return {t["function"]["name"].split("__", 2)[2] for t in external_agents.offered_tools(self.member, self.org, buddy=buddy)}

    def policy(self, user=None, **body):
        self._session(user or self.owner)
        return self.web.put(f"/api/v2/orgs/{self.org.id}/mcp/servers/{self.server.id}/policy", body, format="json")

    def test_allow_deny(self):
        self.assertEqual(self.offered(), {"partner_status", "echo", "delete_order"})
        self.assertEqual(self.policy(tool_rules={"echo": "deny"}).status_code, 200)
        self.assertEqual(self.offered(), {"partner_status", "delete_order"})
        with self.assertRaises(external_agents.AgentError) as denied:
            external_agents.propose(self.org, self.member, self.server, "echo", {"text": "hi"}, buddy=self.buddy)
        self.assertEqual(denied.exception.code, "tool_denied")
        with self.assertRaises(external_agents.AgentError):
            external_agents.test_call(self.org, self.owner, self.server, "echo", {"text": "hi"})
        self.assertFalse(ExternalAgentCall.objects.exists())

    def test_read_only_mode(self):
        self.policy(read_only=True)
        self.assertEqual(self.offered(), {"partner_status", "echo"}, "only tools the server marks read-only")
        with self.assertRaises(external_agents.AgentError) as blocked:
            external_agents.propose(self.org, self.member, self.server, "delete_order", {}, buddy=self.buddy)
        self.assertEqual(blocked.exception.code, "read_only")

    def test_expiry_also_stops_already_proposed_calls(self):
        call = external_agents.propose(self.org, self.member, self.server, "echo", {"text": "hi"}, buddy=self.buddy)
        self.policy(expires_at=(timezone.now() - timedelta(minutes=1)).isoformat())
        self.assertEqual(self.offered(), set())
        approved = external_agents.approve(self.org, self.member, call.id)
        self.assertEqual((approved.status, approved.error), ("failed", "server_expired"))
        self.assertEqual(approved.output, "", "nothing was sent")
        log = MCPCallLog.objects.get()
        self.assertEqual((log.direction, log.ok, log.error, log.server_id), ("outbound", False, "server_expired", self.server.id))
        self.policy(expires_at=None)
        self.assertEqual(len(self.offered()), 3)

    def test_buddy_restriction(self):
        self.policy(buddy_ids=[str(self.buddy.id)])
        self.assertEqual(len(self.offered(self.buddy)), 3)
        self.assertEqual(self.offered(self.other_buddy), set())
        with self.assertRaises(external_agents.AgentError) as blocked:
            external_agents.propose(self.org, self.member, self.server, "echo", {"text": "hi"}, buddy=self.other_buddy)
        self.assertEqual(blocked.exception.code, "buddy_not_allowed")
        call = external_agents.propose(self.org, self.member, self.server, "echo", {"text": "hello"}, buddy=self.buddy)
        sent = external_agents.approve(self.org, self.member, call.id)
        self.assertEqual(sent.status, "executed")
        log = MCPCallLog.objects.get()
        self.assertTrue(log.ok)
        self.assertEqual(log.args_summary, {"text": "text (5 chars)"})

    def test_policy_validation_and_permissions(self):
        self.assertEqual(self.policy(tool_rules={"nope": "deny"}).status_code, 400)
        self.assertEqual(self.policy(tool_rules={"echo": "maybe"}).status_code, 400)
        self.assertEqual(self.policy(buddy_ids=["not-a-uuid"]).status_code, 400)
        self.assertEqual(self.policy(read_only="yes").status_code, 400)
        self.assertEqual(self.policy(expires_at="tomorrow").status_code, 400)
        self.assertEqual(self.policy(user=self.member, read_only=True).status_code, 403, "mcp.manage")
        self.assertFalse(MCPServerPolicy.objects.exists())
        ok = self.policy(tool_rules={"echo": "deny"}, read_only=True).json()
        self.assertEqual({t["name"]: t["usable"] for t in ok["policy"]["tools"]}, {"partner_status": True, "echo": False, "delete_order": False})
        self._session(self.owner)
        listed = self.web.get(f"/api/v2/orgs/{self.org.id}/mcp/servers").json()
        self.assertEqual(listed["servers"][0]["policy"]["tool_rules"], {"echo": "deny"})
        self.assertEqual({b["slug"] for b in listed["buddies"]}, {"helper", "other"})


class HubViewTests(HubBase):
    def grant(self, user, name="Claude"):
        client = OAuthClient.objects.create(client_id=f"fbc_{name}_{user.username}", name=name, redirect_uris=["https://claude.ai/cb"])
        return OAuthGrant.objects.create(client=client, user=user, org=self.org, scopes=["mcp", "tasks:read"], resource="http://testserver/api/mcp")

    def test_flag_off_is_501(self):
        self.org.settings = {"flags": {**FLAGS, "mcp_hub": False}}
        self.org.save()
        self._session(self.owner)
        for path in ("overview", "clients", "servers", "calls"):
            self.assertEqual(self.web.get(f"/api/v2/orgs/{self.org.id}/mcp/{path}").status_code, 501, path)

    def test_clients_list_and_revoke(self):
        mine, theirs = self.grant(self.member), self.grant(self.other, "ChatGPT")
        self._session(self.member)
        listed = self.web.get(f"/api/v2/orgs/{self.org.id}/mcp/clients").json()["results"]
        self.assertEqual([g["client"]["name"] for g in listed], ["Claude"], "members see their own")
        self.assertEqual(self.web.delete(f"/api/v2/orgs/{self.org.id}/mcp/clients/{theirs.id}").status_code, 404)
        self.assertEqual(self.web.delete(f"/api/v2/orgs/{self.org.id}/mcp/clients/{mine.id}").status_code, 204)
        mine.refresh_from_db()
        self.assertEqual(mine.revoked_reason, "revoked_by_user")
        self._session(self.owner)
        listed = self.web.get(f"/api/v2/orgs/{self.org.id}/mcp/clients").json()["results"]
        self.assertEqual([g["client"]["name"] for g in listed], ["ChatGPT"], "admins see everyone's active apps")
        self.assertEqual(len(self.web.get(f"/api/v2/orgs/{self.org.id}/mcp/clients", {"all": "1"}).json()["results"]), 2)
        self.assertEqual(self.web.delete(f"/api/v2/orgs/{self.org.id}/mcp/clients/{theirs.id}").status_code, 204)
        theirs.refresh_from_db()
        self.assertEqual(theirs.revoked_reason, "revoked_by_admin")

    def test_call_log_needs_mcp_manage_and_filters(self):
        MCPCallLog.objects.create(org=self.org, user=self.member, tool="tasks_list", client_name="Claude", ok=True)
        MCPCallLog.objects.create(org=self.org, user=self.member, tool="buddy_ask", client_name="Claude", ok=False, error="not_found")
        MCPCallLog.objects.create(org=self.org, tool="echo", direction="outbound", client_name="Partner")
        self._session(self.member)
        self.assertEqual(self.web.get(f"/api/v2/orgs/{self.org.id}/mcp/calls").status_code, 403)
        self.assertEqual(self.web.get(f"/api/v2/orgs/{self.org.id}/mcp/servers").status_code, 403)
        overview = self.web.get(f"/api/v2/orgs/{self.org.id}/mcp/overview").json()
        self.assertEqual(overview["endpoint"], "http://testserver/api/mcp")
        self.assertFalse(overview["can_manage"])
        self._session(self.owner)
        base = f"/api/v2/orgs/{self.org.id}/mcp/calls"
        everything = self.web.get(base).json()
        self.assertEqual((everything["total"], everything["errors"]), (3, 1))
        self.assertEqual(everything["tools"], ["buddy_ask", "echo", "tasks_list"])
        self.assertEqual([r["tool"] for r in self.web.get(base, {"ok": "false"}).json()["results"]], ["buddy_ask"])
        self.assertEqual([r["tool"] for r in self.web.get(base, {"direction": "outbound"}).json()["results"]], ["echo"])
        self.assertEqual(self.web.get(base, {"client": "Claude", "tool": "tasks_list"}).json()["total"], 1)
        self.assertEqual(self.web.get(base, {"user": str(self.member.id)}).json()["total"], 2)
        self.assertEqual(self.web.get(base, {"days": "x"}).status_code, 400)

    def test_members_of_other_orgs_get_nothing(self):
        from organizations.models import Organization

        elsewhere = Organization.objects.create(name="Else", slug="else", settings={"flags": {"mcp_hub": True}})
        OrgMembership.objects.create(org=elsewhere, user=self.other, org_role="owner", employment_status="active")
        self.grant(self.member)
        self._session(self.other)
        self.assertEqual(self.web.get(f"/api/v2/orgs/{elsewhere.id}/mcp/clients").json()["results"], [])


@override_settings(DEMO_MODE=True, DEMO_AI=True, CREDENTIALS_ENCRYPTION_KEY="cd" * 32)
class HubDemoSeedTests(PlatformBase):
    def test_demo_has_a_connected_app_a_call_log_and_rules(self):
        from demo import seed
        from demo.models import DemoAccount

        org = seed.reset()
        owner = DemoAccount.objects.get(role="owner").user
        self._session(owner)
        apps_ = self.web.get(f"/api/v2/orgs/{org.id}/mcp/clients").json()["results"]
        self.assertEqual({a["client"]["name"] for a in apps_}, {"Claude (demo)"})
        calls = self.web.get(f"/api/v2/orgs/{org.id}/mcp/calls", {"days": "90"}).json()
        self.assertEqual(calls["total"], 30)
        self.assertTrue(calls["errors"] > 0)
        self.assertEqual({r["direction"] for r in calls["results"]}, {"inbound", "outbound"})
        servers = self.web.get(f"/api/v2/orgs/{org.id}/mcp/servers").json()["servers"]
        self.assertEqual(servers[0]["policy"]["tool_rules"], {"echo": "deny"})
        self.assertTrue(servers[0]["policy"]["read_only"])
        seed.reset()
        self.assertEqual(OAuthClient.objects.filter(client_id="fbc_demo_claude").count(), 1, "replaced, not duplicated")
