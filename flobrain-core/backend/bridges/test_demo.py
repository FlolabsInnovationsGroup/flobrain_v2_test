"""demo/extras/a2_bridges.py: Slack and Teams show as connected (simulated) and the full flow runs without a network."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.jwt_utils import make_access_token

KEY = "cd" * 32


@override_settings(DEMO_MODE=True, DEMO_AI=True, CREDENTIALS_ENCRYPTION_KEY=KEY)
@patch("platform_api.net.fetch", side_effect=AssertionError("no network in demo"))
class BridgesDemoTests(TestCase):
    def test_seeded_and_simulated_end_to_end(self, fetch):
        from actions.models import ActionProposal
        from bridges.models import BridgeLink, BridgeWorkspace
        from demo import seed
        from demo.models import DemoAccount

        cache.clear()
        org = seed.reset()
        workspaces = BridgeWorkspace.objects.filter(org=org)
        self.assertEqual(sorted(workspaces.values_list("platform", flat=True)), ["slack", "teams"])
        self.assertTrue(all(w.demo and w.status == "active" and "(demo)" in w.name for w in workspaces))
        self.assertEqual(BridgeLink.objects.filter(org=org, status="active").values("user").distinct().count(), 3)

        member = DemoAccount.objects.get(role="member").user
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(member.id))}")
        overview = client.get(f"/api/v2/orgs/{org.id}/bridges").json()
        self.assertTrue(overview["demo"])
        self.assertEqual(len(overview["workspaces"]), 2)

        sim = client.post(
            f"/api/v2/orgs/{org.id}/bridges/demo/simulate",
            {"platform": "slack", "text": "Project Management Buddy: create a task to send the launch checklist to Delta Clinics"},
            format="json",
        )
        self.assertEqual(sim.status_code, 200, sim.content)
        data = sim.json()
        self.assertTrue(data["simulated"])
        self.assertTrue(data["reply"])
        self.assertEqual(len(data["cards"]), 1, data)
        card = data["cards"][0]
        self.assertEqual(card["proposal"]["status"], "proposed")
        self.assertEqual(card["message"]["blocks"][-1]["elements"][0]["action_id"], "flo_approve")

        decided = client.post(f"/api/v2/orgs/{org.id}/bridges/demo/decide", {"card": card["id"], "decision": "approve"}, format="json")
        self.assertEqual(decided.status_code, 200, decided.content)
        self.assertEqual(decided.json()["card"]["status"], "decided")
        self.assertEqual(ActionProposal.objects.get(pk=card["proposal"]["id"]).status, "executed")

        teams = client.post(f"/api/v2/orgs/{org.id}/bridges/demo/simulate", {"platform": "teams", "text": "What is due this week?"}, format="json")
        self.assertEqual(teams.status_code, 200, teams.content)
        self.assertTrue(teams.json()["reply"])
        fetch.assert_not_called()

        # Someone else can't press the demo button on Youssef's card.
        other = DemoAccount.objects.get(role="lead").user
        c2 = APIClient()
        c2.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(other.id))}")
        sim2 = client.post(f"/api/v2/orgs/{org.id}/bridges/demo/simulate", {"platform": "slack", "text": "Project Management Buddy: create a task to call Lotus Tea"}, format="json")
        card2 = sim2.json()["cards"][0]
        res = c2.post(f"/api/v2/orgs/{org.id}/bridges/demo/decide", {"card": card2["id"], "decision": "approve"}, format="json")
        self.assertEqual(res.json()["outcome"], "decision:not_yours")
        self.assertEqual(ActionProposal.objects.get(pk=card2["proposal"]["id"]).status, "proposed")
