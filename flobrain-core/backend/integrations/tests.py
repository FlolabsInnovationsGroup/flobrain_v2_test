from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from integrations.models import ExternalTool
from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class ToolsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Tools Org", slug="tools-org")
        self.other = Organization.objects.create(name="Tools Other", slug="tools-other")
        self.owner = User.objects.create(email="t-owner@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="t-member@example.com", password_hash=make_password("x"))
        self.inactive = User.objects.create(email="t-off@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(
            org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org, user=self.member, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org,
            user=self.inactive,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_TERMINATED,
        )
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_member_lists_defaults_owner_manages(self):
        self._auth(self.member)
        listed = self.client.get(f"{self.base}/tools")
        self.assertEqual(listed.status_code, 200)
        names = {row["name"] for row in listed.json()}
        self.assertIn("Figma", names)
        denied = self.client.post(f"{self.base}/tools", {"name": "Evil", "url": "https://evil.example"}, format="json")
        self.assertEqual(denied.status_code, 403)
        self._auth(self.owner)
        bad = self.client.post(f"{self.base}/tools", {"name": "Nope", "url": "not-a-url"}, format="json")
        self.assertEqual(bad.status_code, 400)
        created = self.client.post(
            f"{self.base}/tools",
            {"name": "Linear", "url": "https://linear.app"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        tool_id = created.json()["id"]
        patched = self.client.patch(
            f"{self.base}/tools/{tool_id}",
            {"name": "Linear App"},
            format="json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["name"], "Linear App")
        self._auth(self.member)
        self.assertEqual(self.client.delete(f"{self.base}/tools/{tool_id}").status_code, 403)
        self._auth(self.owner)
        self.assertEqual(self.client.delete(f"{self.base}/tools/{tool_id}").status_code, 204)
        self.assertFalse(ExternalTool.objects.filter(pk=tool_id).exists())

    def test_other_org_and_inactive_denied(self):
        self._auth(self.member)
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.other.id}/tools").status_code, 403)
        self._auth(self.inactive)
        self.assertEqual(self.client.get(f"{self.base}/tools").status_code, 403)
