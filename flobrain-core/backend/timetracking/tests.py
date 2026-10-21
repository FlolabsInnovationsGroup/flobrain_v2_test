from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class TimerApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Time Org", slug="time-org")
        self.user = User.objects.create(email="time@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(
            org=self.org,
            user=self.user,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.user.id))}")

    def test_start_stop_and_one_open_timer(self):
        start = self.client.post(f"/api/v2/orgs/{self.org.id}/timer/start", {"description": "work"}, format="json")
        self.assertEqual(start.status_code, 201, start.content)
        again = self.client.post(f"/api/v2/orgs/{self.org.id}/timer/start", {}, format="json")
        self.assertEqual(again.status_code, 409)
        running = self.client.get(f"/api/v2/orgs/{self.org.id}/timer")
        self.assertIsNotNone(running.json()["running"])
        stop = self.client.post(f"/api/v2/orgs/{self.org.id}/timer/stop", {}, format="json")
        self.assertEqual(stop.status_code, 200)
        self.assertIsNotNone(stop.json()["ended_at"])
        report = self.client.get(f"/api/v2/orgs/{self.org.id}/time-reports/me")
        self.assertEqual(report.status_code, 200)
        self.assertGreaterEqual(report.json()["entries"], 1)
        calendar = self.client.get(f"/api/v2/orgs/{self.org.id}/calendar")
        self.assertEqual(calendar.status_code, 200)
        dashboard = self.client.get(f"/api/v2/orgs/{self.org.id}/dashboard/me")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIsNone(dashboard.json()["impact_score"])
