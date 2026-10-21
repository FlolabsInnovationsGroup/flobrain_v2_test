import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from actions.models import ActionProposal, AutoReport, EmailDraft
from actions.schema import SchemaError, validate
from brain.models import Chat
from buddies.models import Buddy
from organizations.models import AuditEvent, OrgMembership, Organization, Project, Team, TeamMembership
from rooms.models import RoomMessage
from rooms.services import ensure_team_room
from tasks.models import Task, TaskAssignment
from timetracking.models import TimeEntry
from users.jwt_utils import make_access_token
from users.models import User

DIRECT = {
    "AI_DIRECT_BASE_URL": "https://provider.example",
    "AI_DIRECT_API_KEY": "test-key-not-live",
    "AI_DIRECT_MODEL_ALLOWLIST": "qwen",
    "AI_DIRECT_DEFAULT_MODEL": "qwen",
}


class _Body:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _ToolModel:
    """Fake provider that answers with the given tool calls and records requests."""

    def __init__(self, calls, text=""):
        self.calls, self.text, self.requests = calls, text, []

    def __call__(self, request, timeout=None):
        self.requests.append(json.loads(request.data.decode()))
        tool_calls = [
            {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for i, (name, args) in enumerate(self.calls)
        ]
        return _Body({
            "model": "qwen",
            "choices": [{"message": {"role": "assistant", "content": self.text, "tool_calls": tool_calls}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        })


def _user(email):
    return User.objects.create(email=email, password_hash=make_password("x"))


@override_settings(**DIRECT)
class ActionBase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="Act Org",
            slug="act-org",
            settings={"flags": {"buddies": True, "ai_actions": True, "auto_reports": True}},
        )
        self.other_org = Organization.objects.create(name="Other", slug="act-other")
        self.owner = _user("ac-owner@example.com")
        self.lead = _user("ac-lead@example.com")
        self.member_a = _user("ac-a@example.com")
        self.member_b = _user("ac-b@example.com")
        for user, role in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER),
            (self.lead, OrgMembership.ORG_ROLE_MEMBER),
            (self.member_a, OrgMembership.ORG_ROLE_MEMBER),
            (self.member_b, OrgMembership.ORG_ROLE_MEMBER),
        ):
            OrgMembership.objects.create(
                org=self.org, user=user, org_role=role, employment_status=OrgMembership.STATUS_ACTIVE
            )
        self.team_a = Team.objects.create(org=self.org, name="Alpha")
        self.team_b = Team.objects.create(org=self.org, name="Beta")
        TeamMembership.objects.create(team=self.team_a, user=self.lead, team_role=TeamMembership.ROLE_LEAD)
        self.membership_a = TeamMembership.objects.create(team=self.team_a, user=self.member_a)
        TeamMembership.objects.create(team=self.team_b, user=self.member_b)
        self.room_a = ensure_team_room(self.team_a)
        self.room_b = ensure_team_room(self.team_b)
        self.buddy = Buddy.objects.create(
            org=self.org,
            slug="pm",
            name="PM",
            is_builtin=True,
            visibility=Buddy.VIS_ORG,
            share_status=Buddy.SHARE_APPROVED,
            allowed_tools=["tasks.create", "tasks.assign", "tasks.update_status", "rooms.post_message", "email.draft"],
        )
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _turn(self, user, calls, buddy=None, text=""):
        buddy = buddy or self.buddy
        chat = Chat.objects.create(user=user, org=self.org, buddy=buddy, title="t")
        self._auth(user)
        model = _ToolModel(calls, text)
        with patch("urllib.request.urlopen", side_effect=model):
            response = self.client.post(f"{self.base}/buddies/threads/{chat.id}/send", {"text": "do it"}, format="json")
        return response, model, chat

    def _decide(self, user, proposal_id, decision="approve", **body):
        self._auth(user)
        return self.client.post(f"{self.base}/actions/{proposal_id}/{decision}", body, format="json")


class ProposeTests(ActionBase):
    def test_tool_call_becomes_a_proposal_and_nothing_runs(self):
        response, model, chat = self._turn(self.member_a, [("tasks__create", {"title": "Write spec"})])
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(len(body["proposals"]), 1)
        self.assertEqual(body["proposals"][0]["status"], "proposed")
        self.assertIn("approval", body["messages"][-1]["text"])
        self.assertFalse(Task.objects.filter(title="Write spec").exists(), "proposing never executes")
        offered = {t["function"]["name"] for t in model.requests[0]["tools"]}
        self.assertIn("tasks__create", offered)

    def test_tools_are_offered_only_when_held_and_enabled(self):
        self.org.settings = {"flags": {"buddies": True}}
        self.org.save(update_fields=["settings"])
        _, model, _ = self._turn(self.member_a, [])
        self.assertNotIn("tools", model.requests[0])

    def test_unoffered_invalid_and_out_of_scope_calls_are_refused(self):
        response, _, _ = self._turn(
            self.member_a,
            [
                ("meetings__create", {"room": str(self.room_a.id), "title": "x"}),
                ("tasks__create", {"title": "ok", "evil": 1}),
                ("rooms__post_message", {"room": str(self.room_b.id), "body": "hi"}),
                ("tasks__create", {"title": "x", "project": "not-a-uuid"}),
            ],
        )
        errors = [e["error"] for e in response.json()["proposal_errors"]]
        self.assertEqual(errors, ["tool_not_allowed", "invalid_arguments", "not_found"])
        self.assertEqual(ActionProposal.objects.count(), 0)

    def test_member_cannot_propose_assigning_someone_else(self):
        task = Task.objects.create(org=self.org, team=self.team_a, title="T", created_by=self.member_a)
        response, _, _ = self._turn(
            self.member_a, [("tasks__assign", {"task": str(task.id), "user": str(self.lead.id)})]
        )
        self.assertEqual(response.json()["proposal_errors"][0]["error"], "permission")


class ApproveTests(ActionBase):
    def _propose(self, user, name, args):
        response, _, chat = self._turn(user, [(name, args)])
        proposals = response.json()["proposals"]
        self.assertEqual(len(proposals), 1, response.json())
        return proposals[0]["id"], chat

    def test_approve_executes_once_and_audits(self):
        pid, chat = self._propose(self.member_a, "tasks__create", {"title": "Ship it", "team": str(self.team_a.id)})
        response = self._decide(self.member_a, pid)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "executed")
        task = Task.objects.get(title="Ship it")
        self.assertEqual(task.team, self.team_a)
        self.assertEqual(self._decide(self.member_a, pid).status_code, 409)
        self.assertEqual(Task.objects.filter(title="Ship it").count(), 1)
        audit = AuditEvent.objects.get(action="action.executed")
        self.assertEqual(audit.payload["tool"], "tasks.create")
        self.assertTrue(chat.messages.filter(text__startswith="Done:").exists())

    def test_permission_is_rechecked_at_approve(self):
        pid, _ = self._propose(self.member_a, "rooms__post_message", {"room": str(self.room_a.id), "body": "hello"})
        self.membership_a.delete()
        response = self._decide(self.member_a, pid)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(RoomMessage.objects.filter(body="hello").exists())
        self.assertEqual(ActionProposal.objects.get(pk=pid).status, "proposed")

    def test_only_the_proposer_decides(self):
        pid, _ = self._propose(self.member_a, "tasks__create", {"title": "Mine"})
        self.assertEqual(self._decide(self.member_b, pid).status_code, 404)
        self.assertEqual(self._decide(self.owner, pid).status_code, 404)
        self._auth(self.member_b)
        self.assertEqual(self.client.get(f"{self.base}/actions").json(), [])

    def test_expired_proposal_cannot_run(self):
        pid, _ = self._propose(self.member_a, "tasks__create", {"title": "Late"})
        ActionProposal.objects.filter(pk=pid).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self._decide(self.member_a, pid).status_code, 409)
        self.assertEqual(ActionProposal.objects.get(pk=pid).status, "expired")
        self.assertFalse(Task.objects.filter(title="Late").exists())

    def test_edited_arguments_are_validated_again(self):
        pid, _ = self._propose(self.member_a, "tasks__create", {"title": "Draft"})
        bad = self._decide(self.member_a, pid, arguments={"title": "x", "team": str(self.team_b.id), "extra": 1})
        self.assertEqual(bad.status_code, 400)
        hidden = self._decide(self.member_a, pid, arguments={"title": "x", "team": str(self.team_b.id)})
        self.assertEqual(hidden.status_code, 404, "a team the approver cannot write is refused")
        ok = self._decide(self.member_a, pid, arguments={"title": "Final title"})
        self.assertEqual(ok.json()["status"], "executed")
        self.assertTrue(Task.objects.filter(title="Final title").exists())

    def test_reject_then_approve_is_refused(self):
        pid, _ = self._propose(self.member_a, "tasks__create", {"title": "No"})
        self.assertEqual(self._decide(self.member_a, pid, "reject").json()["status"], "rejected")
        self.assertEqual(self._decide(self.member_a, pid).status_code, 409)
        self.assertFalse(Task.objects.filter(title="No").exists())

    def test_email_draft_is_stored_not_sent(self):
        pid, _ = self._propose(self.member_a, "email__draft", {"to": ["a@example.com"], "subject": "Hi", "body": "Hello"})
        with patch("urllib.request.urlopen") as network:
            self.assertEqual(self._decide(self.member_a, pid).json()["status"], "executed")
        network.assert_not_called()
        self.assertTrue(EmailDraft.objects.filter(user=self.member_a, subject="Hi").exists())

    def test_flag_off_is_501(self):
        self.org.settings = {"flags": {"buddies": True}}
        self.org.save(update_fields=["settings"])
        self._auth(self.member_a)
        self.assertEqual(self.client.get(f"{self.base}/actions").status_code, 501)


class SchemaTests(TestCase):
    def test_subset(self):
        schema = {
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 3}, "d": {"type": "string", "format": "date"}},
            "required": ["n"],
            "additionalProperties": False,
        }
        self.assertEqual(validate(schema, {"n": 2, "d": "2026-10-20"}), {"n": 2, "d": "2026-10-20"})
        for bad in ({"n": 5}, {"n": True}, {"d": "2026-10-20"}, {"n": 1, "d": "tomorrow"}, {"n": 1, "x": 1}, []):
            with self.assertRaises(SchemaError):
                validate(schema, bad)


class TaskCreateScopeTests(ActionBase):
    def test_project_from_another_org_is_404(self):
        foreign = Project.objects.create(org=self.other_org, name="Foreign")
        self._auth(self.member_a)
        response = self.client.post(f"{self.base}/tasks", {"title": "x", "project": str(foreign.id)}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Task.objects.filter(title="x").exists())
        garbage = self.client.post(f"{self.base}/tasks", {"title": "y", "project": "nope"}, format="json")
        self.assertEqual(garbage.status_code, 404)


class ReportTests(ActionBase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.done = Task.objects.create(org=self.org, team=self.team_a, title="Done A", status=Task.STATUS_DONE)
        self.blocked = Task.objects.create(
            org=self.org, team=self.team_a, title="Blocked A", is_blocked=True, blocked_reason="waiting on API"
        )
        self.other = Task.objects.create(org=self.org, team=self.team_b, title="Beta secret task")
        TaskAssignment.objects.create(task=self.done, user=self.member_a)
        self.entry = TimeEntry.objects.create(
            org=self.org, user=self.member_a, task=self.done, started_at=now - timedelta(hours=3), ended_at=now - timedelta(hours=1)
        )
        TimeEntry.objects.create(
            org=self.org, user=self.member_b, started_at=now - timedelta(hours=3), ended_at=now - timedelta(hours=2)
        )
        self.url = f"{self.base}/teams/{self.team_a.id}/reports"

    def test_lead_generates_a_cited_report_for_their_team_only(self):
        self._auth(self.lead)
        response = self.client.post(f"{self.url}/generate", {"kind": "daily_standup"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertIn(f"[task:{self.done.id}]", body["content"])
        self.assertIn("waiting on API", body["content"])
        self.assertNotIn("Beta secret task", body["content"])
        self.assertNotIn("ac-b@example.com", body["content"])
        self.assertIn(str(self.done.id), body["sources"]["tasks"])
        self.assertEqual(body["sources"]["time_entries"], [str(self.entry.id)])
        self.assertIn("2.0 h", body["content"])

    def test_access(self):
        self._auth(self.member_a)
        self.assertEqual(self.client.post(f"{self.url}/generate", {"kind": "daily_standup"}, format="json").status_code, 403)
        self._auth(self.member_b)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self._auth(self.owner)
        self.assertEqual(self.client.post(f"{self.url}/generate", {"kind": "weekly_report"}, format="json").status_code, 201)
        self._auth(self.lead)
        self.assertEqual(self.client.post(f"{self.url}/generate", {"kind": "monthly"}, format="json").status_code, 400)
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        self.assertEqual(self.client.get(self.url).status_code, 501)

    def test_post_to_team_room_once(self):
        self._auth(self.lead)
        report_id = self.client.post(f"{self.url}/generate", {"kind": "daily_standup"}, format="json").json()["id"]
        posted = self.client.post(f"{self.url}/{report_id}/post")
        self.assertEqual(posted.status_code, 200, posted.content)
        self.assertTrue(RoomMessage.objects.filter(room=self.room_a, body__startswith="# Daily standup").exists())
        self.assertEqual(self.client.post(f"{self.url}/{report_id}/post").status_code, 409)

    def test_report_tool_through_an_approved_action(self):
        lead_buddy = Buddy.objects.create(
            org=self.org, slug="lead-pm", name="Lead PM", created_by=self.lead, allowed_tools=["reports.generate"]
        )
        response, _, _ = self._turn(
            self.lead, [("reports__generate", {"team": str(self.team_a.id), "kind": "weekly_report"})], buddy=lead_buddy
        )
        pid = response.json()["proposals"][0]["id"]
        self.assertFalse(AutoReport.objects.exists())
        self.assertEqual(self._decide(self.lead, pid).json()["status"], "executed")
        self.assertEqual(AutoReport.objects.get().team, self.team_a)


class ReviewFixTests(ReportTests):
    def test_report_has_no_emails_and_only_this_teams_hours(self):
        beta_task = Task.objects.create(org=self.org, team=self.team_b, title="Beta work")
        now = timezone.now()
        leak = TimeEntry.objects.create(
            org=self.org, user=self.member_a, task=beta_task, started_at=now - timedelta(hours=5), ended_at=now - timedelta(hours=4)
        )
        self._auth(self.lead)
        body = self.client.post(f"{self.url}/generate", {"kind": "daily_standup"}, format="json").json()
        self.assertNotIn("@example.com", body["content"])
        self.assertNotIn(str(leak.id), body["sources"]["time_entries"])
        self.assertTrue(AuditEvent.objects.filter(action="report.generate").exists())

    def test_disabled_tool_blocks_pending_proposals(self):
        from actions.models import ToolDefinition
        from actions.service import sync_tool_definitions

        sync_tool_definitions()
        response, _, _ = self._turn(self.member_a, [("tasks__create", {"title": "Later"})])
        pid = response.json()["proposals"][0]["id"]
        self.assertTrue(AuditEvent.objects.filter(action="action.proposed").exists())
        ToolDefinition.objects.filter(key="tasks.create").update(enabled=False)
        self.assertEqual(self._decide(self.member_a, pid).status_code, 501)
        self.assertFalse(Task.objects.filter(title="Later").exists())
        self.assertTrue(AuditEvent.objects.filter(action="action.denied").exists())

    def test_bad_edited_date_is_400(self):
        response, _, _ = self._turn(self.member_a, [("tasks__create", {"title": "Dated"})])
        pid = response.json()["proposals"][0]["id"]
        self.assertEqual(self._decide(self.member_a, pid, arguments={"title": "x", "due_on": "2026-02-30"}).status_code, 400)

    def test_hidden_project_is_404_for_rest_and_tools(self):
        hidden = Project.objects.create(org=self.org, name="Secret")
        self._auth(self.member_a)
        self.assertEqual(
            self.client.post(f"{self.base}/tasks", {"title": "x", "project": str(hidden.id)}, format="json").status_code, 404
        )
        response, _, _ = self._turn(self.member_a, [("tasks__create", {"title": "x", "project": str(hidden.id)})])
        self.assertEqual(response.json()["proposal_errors"][0]["error"], "not_found")

    def test_assign_summary_has_no_email(self):
        task = Task.objects.create(org=self.org, team=self.team_a, title="T")
        lead_buddy = Buddy.objects.create(
            org=self.org, slug="lb", name="LB", created_by=self.lead, allowed_tools=["tasks.assign"]
        )
        response, _, _ = self._turn(
            self.lead, [("tasks__assign", {"task": str(task.id), "user": str(self.member_a.id)})], buddy=lead_buddy
        )
        self.assertNotIn("@", response.json()["proposals"][0]["summary"])
