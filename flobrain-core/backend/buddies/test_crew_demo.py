"""The demo shows Flo, the specialists and buddy quality with the demo model (growth round W5)."""

import json

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from buddies.models import Buddy, BuddyFeedback, BuddyRoute


@override_settings(DEMO_MODE=True, DEMO_AI=True)
class CrewDemoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        res = self.client.post("/api/v2/demo/signin", {"role": "member"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.json()['access']}")
        from organizations.models import Organization

        self.org = Organization.objects.get(slug="demo")
        self.base = f"/api/v2/orgs/{self.org.id}"

    def test_seeded_crew_and_quality(self):
        slugs = set(Buddy.objects.filter(org=self.org).values_list("slug", flat=True))
        self.assertTrue({"flo", "sales", "onboarding-coach", "meeting-prep", "customer"} <= slugs)
        self.assertEqual(BuddyFeedback.objects.filter(org=self.org).count(), 60)
        self.assertTrue(BuddyRoute.objects.filter(org=self.org).exists())
        data = self.client.get(f"{self.base}/buddies/quality", {"days": "30"}).json()
        self.assertGreater(data["totals"]["answers"], 50)
        self.assertGreater(data["totals"]["ratings"], 40)
        sales = next(r for r in data["buddies"] if r["slug"] == "sales")
        self.assertGreater(sales["approvals"]["proposed"], 0)
        self.assertTrue(any(r["median_latency_ms"] for r in data["buddies"]))
        self.assertTrue(any(r["cost"] != "0.0000" for r in data["buddies"]))
        self.assertTrue(data["reasons"])

    def test_demo_routing_by_topic(self):
        cases = {
            "Book a trip to Dubai": "travel",
            "How much budget is left?": "finance",
            "Is the NDA safe to sign?": "legal",
            "What changed in sign-ups this week?": "data",
            "What's blocking the launch?": "space",
            "How is my sales pipeline?": "sales",
            "Plan onboarding for our new hire": "onboarding-coach",
            "Prepare me for the meeting": "meeting-prep",
        }
        for text, slug in cases.items():
            res = self.client.post(f"{self.base}/buddies/route", {"text": text}, format="json")
            self.assertEqual(res.status_code, 200, res.content)
            body = res.json()
            self.assertEqual(body["method"], "llm", text)
            self.assertEqual(body["buddies"][0]["slug"], slug, text)

    def test_flo_turn_with_a_specialist_in_the_demo(self):
        flo = Buddy.objects.get(org=self.org, slug="flo")
        thread = self.client.post(f"{self.base}/buddies/{flo.id}/threads", {}, format="json").json()["id"]
        res = self.client.post(f"{self.base}/buddies/threads/{thread}/send", {"text": "How is my sales pipeline?"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        text = res.json()["messages"][-1]["text"]
        self.assertTrue(text.startswith("Answered by Sales Buddy"), text)
        self.assertIn("Delta Clinics", text, "built from the member's own leads")
        self.assertIn("demo model", text)

    def test_specialist_drafts_wait_for_approval(self):
        sales = Buddy.objects.get(org=self.org, slug="sales")
        thread = self.client.post(f"{self.base}/buddies/{sales.id}/threads", {}, format="json").json()["id"]
        res = self.client.post(f"{self.base}/buddies/threads/{thread}/send", {"text": "Draft a follow-up email for Cairo Bikes"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        proposals = res.json()["proposals"]
        self.assertEqual(len(proposals), 1, json.dumps(res.json())[:400])
        self.assertEqual(proposals[0]["tool_key"] if "tool_key" in proposals[0] else proposals[0].get("tool"), "email.draft")
