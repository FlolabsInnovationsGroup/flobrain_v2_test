from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization, Team, TeamMembership
from privacy.models import PrivacySettings
from tasks.models import Task, TaskAssignment
from timetracking.models import TimeEntry
from users.jwt_utils import make_access_token
from users.models import User


class InsightsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="I", slug="insights-org")
        self.team = Team.objects.create(org=self.org, name="Eng")
        self.users = {}
        for name, role, team_role in (("lead", "member", "lead"), ("ana", "member", "member"), ("ben", "member", "member"), ("out", "member", None)):
            u = User.objects.create(email=f"{name}@i.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            if team_role:
                TeamMembership.objects.create(team=self.team, user=u, team_role=team_role)
            self.users[name] = u
        now = timezone.now()
        for name in ("ana", "ben"):
            task = Task.objects.create(org=self.org, title=f"t-{name}", created_by=self.users[name], status=Task.STATUS_DONE, completed_at=now - timedelta(days=1))
            TaskAssignment.objects.create(task=task, user=self.users[name])
            TimeEntry.objects.create(org=self.org, user=self.users[name], started_at=now - timedelta(days=2, hours=2), ended_at=now - timedelta(days=2))
        PrivacySettings.objects.create(org=self.org, user=self.users["ben"], analytics_personal_only=True)

    def _as(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return c

    def test_personal_insights_are_your_own(self):
        data = self._as("ana").get(f"/api/v2/orgs/{self.org.id}/me/insights").json()
        self.assertEqual((data["current"]["tasks_done"], data["current"]["seconds"]), (1, 7200))
        self.assertEqual(data["previous"]["tasks_done"], 0)
        self.assertEqual(sum(d["seconds"] for d in data["hours_by_day"]), 7200)
        self.assertFalse(data["personal_only"])
        self.assertEqual(self._as("ana").get(f"/api/v2/orgs/{self.org.id}/me/insights?days=2").status_code, 400)
        stranger = User.objects.create(email="s@x.test", username="s")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(stranger.id))}")
        self.assertEqual(c.get(f"/api/v2/orgs/{self.org.id}/me/insights").status_code, 404)

    def test_team_insights_leave_out_people_who_keep_them_personal(self):
        url = f"/api/v2/orgs/{self.org.id}/teams/{self.team.id}/insights"
        res = self._as("lead").get(url)
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        names = {r["name"] for r in data["members"]}
        self.assertIn("ana", names)
        self.assertNotIn("ben", names, "ben keeps his insights personal")
        self.assertEqual((data["private_count"], data["totals"]["tasks_done"]), (1, 1), "totals don't include ben either")
        self.assertNotIn("messages", data["members"][0], "no message counts for leads")
        self.assertEqual(self._as("ana").get(url).status_code, 403)
        self.assertEqual(self._as("out").get(url).status_code, 403)
