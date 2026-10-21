"""Demo workspace (``demo/extras/70_ai_admin.py`` and ``brain/llm/demo_handlers/agents.py``)."""

import json

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from actions.models import ActionProposal
from agents.models import AgentSchedule
from brain.llm.demo_handlers import agents as handler
from demo import seed
from integrations.models import AICredential
from notifications.models import Notification
from telemetry.models import Budget
from users.jwt_utils import make_access_token
from users.models import User

TEST_KEY = "cd" * 32  # test-only


@override_settings(DEMO_MODE=True, DEMO_AI=True, CREDENTIALS_ENCRYPTION_KEY=TEST_KEY)
class DemoAiAdminTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = seed.reset()
        self.client = APIClient()
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _as(self, role):
        user = User.objects.get(email=seed.email_for(role))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return user

    def test_demo_keys_are_active_on_the_demo_provider_and_never_shown(self):
        keys = AICredential.objects.filter(org=self.org)
        self.assertEqual({k.provider for k in keys}, {"demo"})
        self.assertTrue(all(k.status == "active" for k in keys))
        self._as("member")
        res = self.client.get(f"{self.base}/credentials")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertNotIn("demo-key-not-real", res.content.decode())
        self.assertEqual(len(res.json()), 1, "a member sees only their own key")

    def test_budgets_at_three_scopes_and_one_alert(self):
        self.assertEqual(set(Budget.objects.filter(org=self.org).values_list("scope_type", flat=True)), {"org", "team", "user"})
        self._as("owner")
        status = self.client.get(f"{self.base}/budgets/status").json()
        states = {r["scope_type"]: r["state"] for r in status["results"]}
        self.assertEqual(states["team"], "alert")
        self.assertEqual(states["org"], "ok")
        team = next(r for r in status["results"] if r["scope_type"] == "team")
        self.assertAlmostEqual(team["ratio"], 0.85, places=2)
        alerts = Notification.objects.filter(org=self.org, kind="budget_alert")
        self.assertEqual(alerts.count(), 2, "owner and admin, once")
        summary = self.client.get(f"{self.base}/usage/summary", {"group": "surface"}).json()
        self.assertGreater(summary["totals"]["own_key_calls"], 0)

    def test_pending_share_request_for_admins(self):
        self._as("admin")
        rows = self.client.get(f"{self.base}/buddies/share-requests").json()
        self.assertIn("Brand voice checker", [r["name"] for r in rows])

    def test_seeded_runs_show_output_and_run_now_ends_in_approvals(self):
        lead = self._as("lead")
        schedule = AgentSchedule.objects.get(org=self.org, name="Monday release notes")
        runs = self.client.get(f"{self.base}/agents/schedules/{schedule.id}/runs").json()
        self.assertTrue(runs and all("Release notes" in r["output"] for r in runs))
        res = self.client.post(f"{self.base}/agents/schedules/{schedule.id}/run", {}, format="json")
        self.assertEqual(res.status_code, 202, res.content)
        self.assertEqual(res.json()["status"], "done", res.json())
        pending = ActionProposal.objects.filter(org=self.org, user=lead, status="proposed", tool_key="rooms.post_message")
        self.assertEqual(pending.count(), 1)
        self.assertIn("Set up CI for the mobile app", pending.get().arguments["body"])
        listed = self.client.get(f"{self.base}/actions", {"status": "proposed"}).json()
        self.assertIn(str(pending.get().id), [p["id"] for p in listed])


class DemoAgentHandlerTests(TestCase):
    SYSTEM = "You are a FloBrain buddy helping one member of a workspace."

    def _tools(self, *names):
        return [{"type": "function", "function": {"name": n, "parameters": {}}} for n in names]

    def test_plural_tasks_propose_a_task(self):
        result = handler.handle(self.SYSTEM, "", [{"role": "user", "content": "Follow up on overdue tasks"}], self._tools("tasks__create"))
        self.assertEqual(result.tool_calls[0]["name"], "tasks__create")
        self.assertTrue(json.loads(result.tool_calls[0]["arguments"])["title"])

    def test_passes_without_tools_or_outside_buddies(self):
        msg = [{"role": "user", "content": "Follow up on overdue tasks"}]
        self.assertIsNone(handler.handle(self.SYSTEM, "", msg, None))
        self.assertIsNone(handler.handle("Translate this", "", msg, self._tools("tasks__create")))
        self.assertIsNone(handler.handle(self.SYSTEM, "", [{"role": "user", "content": "hello"}], self._tools("tasks__create")))

    def test_post_without_a_known_room_falls_back(self):
        msg = [{"role": "user", "content": "Draft release notes and post them in Nowhere"}]
        self.assertIsNone(handler.handle(self.SYSTEM, "", msg, self._tools("rooms__post_message")))


@override_settings(DEMO_MODE=True, DEMO_AI=True, CREDENTIALS_ENCRYPTION_KEY=TEST_KEY)
class DemoKeyChatTests(TestCase):
    def test_buddy_chat_on_the_demo_key_uses_the_demo_model_and_counts_as_own_key(self):
        from unittest.mock import patch

        from buddies.models import Buddy
        from telemetry.models import UsageEvent

        cache.clear()
        org = seed.reset()
        member = User.objects.get(email=seed.email_for("member"))
        key = AICredential.objects.get(org=org, owner=member)
        buddy = Buddy.objects.filter(org=org, is_builtin=True).first()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(member.id))}")
        thread = client.post(f"/api/v2/orgs/{org.id}/buddies/{buddy.id}/threads", {}, format="json").json()
        with patch("urllib.request.urlopen") as network:
            res = client.post(
                f"/api/v2/orgs/{org.id}/buddies/threads/{thread['id']}/send",
                {"text": "hello", "credential_id": str(key.id), "model": "flobrain-demo"},
                format="json",
            )
        network.assert_not_called()
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(UsageEvent.objects.filter(org=org, user=member, credential_source="customer", surface="buddy").exists())
