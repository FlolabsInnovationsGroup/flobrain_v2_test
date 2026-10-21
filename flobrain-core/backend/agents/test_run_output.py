"""Run history shows the buddy's output and proposals to the creator only; runs are traced as scheduled agents."""

from unittest.mock import patch

from django.test import TestCase, override_settings

from agents.models import AgentRun
from agents.tests import DIRECT, AgentTests, _Model
from telemetry.models import AITrace, UsageEvent


@override_settings(**DIRECT)
class RunOutputTests(TestCase):
    setUp = AgentTests.setUp
    _auth = AgentTests._auth
    _create = AgentTests._create

    def _run_now(self, schedule_id, calls=()):
        model = _Model(calls)
        self._auth(self.member)
        with patch("urllib.request.urlopen", side_effect=model):
            res = self.client.post(f"{self.base}/{schedule_id}/run", {}, format="json")
        self.assertEqual(res.status_code, 202, res.content)
        return res.json()

    def test_creator_sees_output_and_proposals(self):
        schedule_id = self._create().json()["id"]
        run = self._run_now(schedule_id, [("tasks__create", {"title": "Follow up"})])
        self.assertEqual(run["status"], "done")
        self.assertEqual(run["output"], "weekly plan ready")
        self.assertEqual(len(run["proposal_items"]), 1)
        self.assertEqual(run["proposal_items"][0]["status"], "proposed")
        history = self.client.get(f"{self.base}/{schedule_id}/runs").json()
        self.assertEqual(history[0]["output"], "weekly plan ready")

    def test_admin_sees_the_run_but_not_its_output(self):
        schedule_id = self._create().json()["id"]
        self._run_now(schedule_id)
        self._auth(self.owner)
        history = self.client.get(f"{self.base}/{schedule_id}/runs").json()
        self.assertEqual(history[0]["status"], "done")
        self.assertNotIn("output", history[0])
        self.assertNotIn("proposal_items", history[0])

    def test_run_is_traced_as_a_scheduled_agent(self):
        schedule_id = self._create().json()["id"]
        self._run_now(schedule_id)
        run = AgentRun.objects.get(schedule_id=schedule_id)
        self.assertEqual(run.trace.surface, "scheduled_agent")
        self.assertTrue(UsageEvent.objects.filter(chat=run.chat, surface="scheduled_agent").exists())
        self.assertFalse(AITrace.objects.filter(org=self.org, surface="buddy").exists())
