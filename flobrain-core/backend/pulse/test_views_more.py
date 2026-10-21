"""Pulse Agents, Cost, Governance and Incidents views: numbers from records, admins only, org-isolated."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from actions.models import ActionProposal
from agents.models import AgentRun, AgentSchedule
from brain.models import Chat
from buddies.models import Buddy
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from platform_api.models import Incident
from telemetry.models import Budget, PriceTable, UsageEvent
from users.jwt_utils import make_access_token
from users.models import User


class PulseMoreTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="PM", slug="pm-org", settings={"flags": {"pulse": True, "budgets": True}})
        self.other = Organization.objects.create(name="PO", slug="po-org", settings={"flags": {"pulse": True}})
        self.users = {}
        for name, role in (("admin", "admin"), ("lead", "member"), ("member", "member")):
            u = User.objects.create(email=f"{name}@pm.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            self.users[name] = u
        self.outsider = User.objects.create(email="out@pm.test", username="out", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.other, user=self.outsider, org_role="owner", employment_status="active")
        self.team = Team.objects.create(org=self.org, name="Eng")
        TeamMembership.objects.create(team=self.team, user=self.users["lead"], team_role="lead")
        PriceTable.objects.create(provider="p", model="m", input_price=Decimal("1000000"), output_price=Decimal("1000000"),
                                  valid_from=timezone.now() - timedelta(days=60))
        self.buddy = Buddy.objects.create(org=self.org, slug="b", name="Notes buddy", created_by=self.users["member"])
        member = self.users["member"]
        self.chat = Chat.objects.create(user=member, org=self.org, buddy=self.buddy, title="t")
        UsageEvent.objects.create(org=self.org, user=member, chat=self.chat, provider="p", model="m", total_tokens=2, surface="buddy", team=self.team)
        UsageEvent.objects.create(org=self.org, user=member, provider="p", model="m", total_tokens=1, surface="room_ai", status="error")
        UsageEvent.objects.create(org=self.org, user=member, provider="openai", model="gpt", total_tokens=50,
                                  credential_source=UsageEvent.CREDENTIAL_CUSTOMER, surface="room_ai")
        UsageEvent.objects.create(org=self.other, user=self.outsider, provider="p", model="m", total_tokens=99)
        schedule = AgentSchedule.objects.create(org=self.org, buddy=self.buddy, created_by=member, name="Weekly", trigger_type="cron",
                                                cron="0 9 * * 1", instructions="x", is_active=False, paused_reason="creator_inactive")
        AgentRun.objects.create(org=self.org, schedule=schedule, status="done", chat=self.chat, proposals=1)
        AgentRun.objects.create(org=self.org, schedule=schedule, status="failed")
        ActionProposal.objects.create(org=self.org, user=member, buddy=self.buddy, tool_key="tasks.create",
                                      arguments={"title": "PRIVATE-TITLE"}, summary="Create task PRIVATE-TITLE", status="executed",
                                      decided_at=timezone.now(), original_arguments={"title": "x"})
        ActionProposal.objects.create(org=self.org, user=member, buddy=self.buddy, tool_key="rooms.post_message",
                                      arguments={}, summary="s", status="rejected", decided_at=timezone.now())
        ActionProposal.objects.create(org=self.org, user=member, tool_key="tasks.create", arguments={}, summary="s")
        ActionProposal.objects.create(org=self.other, user=self.outsider, tool_key="tasks.create", arguments={}, summary="s")
        self.base = f"/api/v2/orgs/{self.org.id}/pulse"

    def _as(self, user):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return c

    def test_agents(self):
        body = self._as(self.users["admin"]).get(f"{self.base}/agents").json()
        buddy = next(b for b in body["buddies"] if b["name"] == "Notes buddy")
        self.assertEqual((buddy["calls"], buddy["cost"], buddy["proposals"], buddy["executed"], buddy["rejected"]), (1, "2.0000", 2, 1, 1))
        self.assertEqual(buddy["approval_rate"], 0.5)
        schedule = body["schedules"][0]
        self.assertEqual((schedule["runs"], schedule["done"], schedule["failed"], schedule["proposals"]), (2, 1, 1, 1))
        self.assertEqual(schedule["cost"], "2.0000")
        self.assertFalse(schedule["is_active"])

    def test_cost(self):
        Budget.objects.create(org=self.org, cap_amount=Decimal("3"))
        body = self._as(self.users["admin"]).get(f"{self.base}/cost").json()
        self.assertEqual(body["platform_cost"], "3.0000")
        self.assertEqual((body["own_key_calls"], body["own_key_tokens"]), (1, 50))
        self.assertEqual({r["label"] for r in body["by_surface"]}, {"buddy", "room_ai"})
        self.assertEqual({r["label"]: r["cost"] for r in body["by_team"]}, {"Eng": "2.0000", "No team": "1.0000"})
        self.assertEqual(body["budgets"][0]["state"], "exceeded")
        self.assertEqual(body["gpu_seconds"], 0)

    def test_governance_has_counts_not_content(self):
        res = self._as(self.users["admin"]).get(f"{self.base}/governance")
        body = res.json()
        self.assertEqual(body["proposals"], 3, "the other org is not counted")
        self.assertEqual(body["by_status"], {"executed": 1, "rejected": 1, "proposed": 1})
        self.assertEqual(body["edited_before_approval"], 1)
        self.assertEqual(body["approval_rate"], 0.5)
        self.assertEqual(body["paused_agents"], [{"name": "Weekly", "reason": "creator_inactive"}])
        self.assertNotIn("PRIVATE-TITLE", res.content.decode())

    def test_incidents_with_ai_error_rate(self):
        Incident.objects.create(org=self.org, title="Slow answers", severity="major", created_at=timezone.now() - timedelta(hours=1))
        Incident.objects.create(org=self.other, title="Not ours")
        rows = self._as(self.users["admin"]).get(f"{self.base}/incidents").json()
        self.assertEqual([r["title"] for r in rows], ["Slow answers"])
        self.assertEqual((rows[0]["ai_calls"], rows[0]["ai_errors"]), (3, 1))

    def test_admins_only_and_flag(self):
        for path in ("agents", "cost", "governance", "incidents"):
            self.assertEqual(self._as(self.users["member"]).get(f"{self.base}/{path}").status_code, 403, path)
            self.assertEqual(self._as(self.users["lead"]).get(f"{self.base}/{path}").status_code, 403, path)
            self.assertEqual(self._as(self.outsider).get(f"{self.base}/{path}").status_code, 403, path)
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        self.assertEqual(self._as(self.users["admin"]).get(f"{self.base}/cost").status_code, 501)
