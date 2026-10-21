from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import MemberSkill, OrgMembership, Organization, Team, TeamMembership
from tasks.models import Task, TaskAssignment
from users.jwt_utils import make_access_token
from users.models import User


def _user(email):
    return User.objects.create(email=email, username=email.split("@")[0], password_hash=make_password("x"))


class SkillAndSuggestionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="S", slug="s-org", settings={"flags": {"assign_suggestions": True}})
        self.owner = _user("s-owner@example.com")
        self.lead = _user("s-lead@example.com")
        self.dev = _user("s-dev@example.com")
        self.busy = _user("s-busy@example.com")
        self.outsider_team = _user("s-other@example.com")
        self.inactive = _user("s-off@example.com")
        for user, role, status in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER, OrgMembership.STATUS_ACTIVE),
            (self.lead, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.dev, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.busy, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.outsider_team, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.inactive, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_TERMINATED),
        ):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status=status)
        self.team = Team.objects.create(org=self.org, name="Eng")
        other = Team.objects.create(org=self.org, name="Ops")
        TeamMembership.objects.create(team=self.team, user=self.lead, team_role=TeamMembership.ROLE_LEAD)
        for user in (self.dev, self.busy, self.inactive):
            TeamMembership.objects.create(team=self.team, user=user)
        TeamMembership.objects.create(team=other, user=self.outsider_team)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_skill_rules(self):
        self._auth(self.dev)
        own = self.client.post(f"{self.base}/members/{self.dev.id}/skills", {"name": "Django"}, format="json")
        self.assertEqual(own.status_code, 201)
        self.assertFalse(own.json()["confirmed"])
        self.assertEqual(
            self.client.post(f"{self.base}/members/{self.busy.id}/skills", {"name": "x"}, format="json").status_code, 403
        )
        self._auth(self.lead)
        confirmed = self.client.post(f"{self.base}/members/{self.busy.id}/skills", {"name": "react"}, format="json")
        self.assertTrue(confirmed.json()["confirmed"])
        self.assertEqual(
            self.client.post(f"{self.base}/members/{self.outsider_team.id}/skills", {"name": "x"}, format="json").status_code,
            403,
            "a lead confirms only their own team",
        )
        same = self.client.post(f"{self.base}/members/{self.busy.id}/skills", {"name": "React"}, format="json")
        self.assertEqual(same.json()["id"], confirmed.json()["id"], "skill names are case-insensitive")
        self._auth(self.outsider_team)
        names = [row["name"] for row in self.client.get(f"{self.base}/members/{self.dev.id}/skills").json()]
        self.assertEqual(names, ["Django"])
        skill_id = own.json()["id"]
        self.assertEqual(self.client.delete(f"{self.base}/members/{self.dev.id}/skills/{skill_id}").status_code, 403)
        self._auth(self.dev)
        self.assertEqual(self.client.delete(f"{self.base}/members/{self.dev.id}/skills/{skill_id}").status_code, 204)

    def test_suggestions_rank_skill_and_load_and_respect_assign_rules(self):
        task = Task.objects.create(org=self.org, team=self.team, title="Fix Django migration", created_by=self.lead)
        self._auth(self.lead)
        self.client.post(f"{self.base}/members/{self.dev.id}/skills", {"name": "django"}, format="json")
        self.client.post(f"{self.base}/members/{self.busy.id}/skills", {"name": "django"}, format="json")
        for i in range(4):
            t = Task.objects.create(org=self.org, team=self.team, title=f"open {i}")
            TaskAssignment.objects.create(task=t, user=self.busy)
        response = self.client.get(f"{self.base}/tasks/{task.id}/suggest-assignee")
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["suggestions"]
        ids = [r["user_id"] for r in rows]
        self.assertEqual(ids[0], str(self.dev.id))
        self.assertIn("django", rows[0]["reasons"]["matched_skills"])
        self.assertNotIn(str(self.inactive.id), ids)
        self.assertNotIn(str(self.outsider_team.id), ids, "a lead assigns inside the team only")
        self.assertFalse(Task.objects.get(pk=task.pk).assignments.exists(), "suggestions never assign")
        self._auth(self.dev)
        member_view = self.client.get(f"{self.base}/tasks/{task.id}/suggest-assignee").json()["suggestions"]
        self.assertEqual([r["user_id"] for r in member_view], [str(self.dev.id)], "a member may only assign themselves")
        self.assertNotIn("email", member_view[0])

    def test_flag_off_is_501(self):
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        task = Task.objects.create(org=self.org, team=self.team, title="t")
        self._auth(self.lead)
        self.assertEqual(self.client.get(f"{self.base}/tasks/{task.id}/suggest-assignee").status_code, 501)
