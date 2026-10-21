from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import Notification
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from pulse.alerts import evaluate
from pulse.models import AlertRule
from telemetry.models import AITrace, PriceTable, UsageEvent
from users.jwt_utils import make_access_token
from users.models import User


class PulseTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="P", slug="p-org", settings={"flags": {"pulse": True}})
        self.other = Organization.objects.create(name="O", slug="o-org", settings={"flags": {"pulse": True}})
        self.users = {}
        for name, role in (("admin", "admin"), ("lead", "member"), ("member", "member")):
            u = User.objects.create(email=f"{name}@p.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            self.users[name] = u
        self.team = Team.objects.create(org=self.org, name="Eng")
        TeamMembership.objects.create(team=self.team, user=self.users["lead"], team_role="lead")
        PriceTable.objects.create(provider="openai", model="m1", input_price=Decimal("1"), output_price=Decimal("2"), valid_from=timezone.now() - timedelta(days=30))
        for i in range(10):
            UsageEvent.objects.create(
                org=self.org, provider="openai", model="m1", input_tokens=1000, output_tokens=1000, total_tokens=2000,
                latency_ms=100 * (i + 1), status="ok" if i < 8 else "error", team=self.team if i < 4 else None,
            )
        UsageEvent.objects.create(org=self.other, provider="openai", model="m1", total_tokens=5, status="error")
        AITrace.objects.create(org=self.org, request_id="r1", surface="buddy", model="m1", outcome="completed", context_sources=[{"type": "doc", "id": "x"}])
        self.base = f"/api/v2/orgs/{self.org.id}/pulse"

    def _as(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return c

    def test_numbers_come_from_records_and_stay_in_the_org(self):
        o = self._as("admin").get(f"{self.base}/overview").json()
        self.assertEqual((o["calls"], o["errors"], o["error_rate"]), (10, 2, 0.2))
        self.assertEqual(o["cost"], "0.0300")  # 10 × (1000×1 + 1000×2) / 1e6
        self.assertEqual((o["latency_p50_ms"], o["latency_p95_ms"]), (500, 1000))
        lead = self._as("lead").get(f"{self.base}/overview").json()
        self.assertEqual((lead["scope"], lead["calls"]), ("teams", 4))
        self.assertEqual(self._as("member").get(f"{self.base}/overview").status_code, 403)
        self.assertEqual(self._as("lead").get(f"{self.base}/traces").status_code, 403)
        traces = self._as("admin").get(f"{self.base}/traces").json()
        self.assertNotIn("context_sources", traces[0])
        detail = self._as("admin").get(f"{self.base}/traces/{traces[0]['id']}").json()
        self.assertEqual(detail["context_sources"], [{"type": "doc", "id": "x"}])

    @override_settings(DEMO_MODE=True, DEMO_AI=True)
    def test_eval_suite_runs_with_deterministic_checks(self):
        admin = self._as("admin")
        suite = admin.post(
            f"{self.base}/suites",
            {"name": "Smoke", "threshold": 50, "cases": [{"prompt": "hello", "must_contain": ["demo model"]}, {"prompt": "x", "must_contain": ["nope"]}]},
            format="json",
        ).json()
        run = admin.post(f"{self.base}/suites/{suite['id']}/run", {}, format="json").json()
        detail = admin.get(f"{self.base}/runs/{run['id']}").json()
        self.assertEqual((detail["status"], detail["pass_rate"]), ("done", 50.0))
        self.assertEqual(admin.post(f"{self.base}/suites", {"name": "x", "cases": []}, format="json").status_code, 400)

    def test_routing_rules(self):
        admin = self._as("admin")
        with override_settings(AI_DIRECT_MODEL_ALLOWLIST="m1,m2", AI_DIRECT_BASE_URL="https://api.example", AI_DIRECT_API_KEY="k"):
            self.assertEqual(admin.put(f"{self.base}/routing", {"primary_model": "gpt-unknown"}, format="json").status_code, 400)
            self.assertEqual(admin.put(f"{self.base}/routing", {"require_approval_for_writes": False}, format="json").status_code, 400)
            self.assertEqual(admin.put(f"{self.base}/routing", {"primary_model": "m1", "fallback_models": ["m2"]}, format="json").status_code, 200)
            preview = admin.get(f"{self.base}/routing/preview").json()
        self.assertEqual(preview["model"], "m1")

    def test_alerts_fire_once_per_window(self):
        AlertRule.objects.create(org=self.org, metric="error_rate", threshold=0.1, window_minutes=60)
        self.assertEqual(evaluate(), 1)
        self.assertEqual(evaluate(), 0)
        self.assertEqual(Notification.objects.filter(kind="pulse_alert").count(), 1, "one admin notified once")
