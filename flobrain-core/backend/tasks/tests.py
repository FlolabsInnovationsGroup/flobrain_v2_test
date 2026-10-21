from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class TaskApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Task Org", slug="task-org")
        self.owner = User.objects.create(email="t-owner@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="t-member@example.com", password_hash=make_password("x"))
        self.other = User.objects.create(email="t-other@example.com", password_hash=make_password("x"))
        for user, role in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER),
            (self.member, OrgMembership.ORG_ROLE_MEMBER),
            (self.other, OrgMembership.ORG_ROLE_MEMBER),
        ):
            OrgMembership.objects.create(
                org=self.org,
                user=user,
                org_role=role,
                employment_status=OrgMembership.STATUS_ACTIVE,
            )

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_member_creates_and_cannot_assign_others(self):
        self._auth(self.member)
        created = self.client.post(
            f"/api/v2/orgs/{self.org.id}/tasks",
            {"title": "Write tests"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        task_id = created.json()["id"]
        denied = self.client.post(
            f"/api/v2/orgs/{self.org.id}/tasks/{task_id}/assign",
            {"user_id": str(self.other.id)},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

    def test_owner_can_assign_others_and_member_can_move_own(self):
        self._auth(self.member)
        created = self.client.post(
            f"/api/v2/orgs/{self.org.id}/tasks",
            {"title": "Ship"},
            format="json",
        )
        task_id = created.json()["id"]
        moved = self.client.post(
            f"/api/v2/orgs/{self.org.id}/tasks/{task_id}/move",
            {"status": "in_progress"},
            format="json",
        )
        self.assertEqual(moved.status_code, 200, moved.content)
        self._auth(self.owner)
        assigned = self.client.post(
            f"/api/v2/orgs/{self.org.id}/tasks/{task_id}/assign",
            {"user_id": str(self.other.id)},
            format="json",
        )
        self.assertEqual(assigned.status_code, 200, assigned.content)
        self.assertIn(str(self.other.id), assigned.json()["assignees"])

    def test_mission_control(self):
        self._auth(self.owner)
        self.client.post(f"/api/v2/orgs/{self.org.id}/tasks", {"title": "A"}, format="json")
        res = self.client.get(f"/api/v2/orgs/{self.org.id}/mission-control")
        self.assertEqual(res.status_code, 200)
        self.assertIn("assigned_open", res.json())
        self.assertGreaterEqual(res.json()["assigned_open"], 1)
        self.assertIn("accomplishments", res.json())
        self.assertIn("blockers", res.json())
        self.assertIn("deadlines", res.json())
        self.assertIn("workload", res.json())

    def test_member_cannot_open_mission_control(self):
        self._auth(self.member)
        res = self.client.get(f"/api/v2/orgs/{self.org.id}/mission-control")
        self.assertEqual(res.status_code, 403)
