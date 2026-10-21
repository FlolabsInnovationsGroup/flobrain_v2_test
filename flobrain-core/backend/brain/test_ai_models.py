from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from model_registry.models import AIModel
from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class AIModelListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="AI Org", slug="ai-org")
        self.member = User.objects.create(email="models-member@example.com", password_hash=make_password("x"))
        self.other = User.objects.create(email="models-other@example.com", password_hash=make_password("x"))
        self.inactive = User.objects.create(email="models-off@example.com", password_hash=make_password("x"))
        self.outsider = User.objects.create(email="models-out@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(
            org=self.org, user=self.member, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org, user=self.other, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org,
            user=self.inactive,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_TERMINATED,
        )
        AIModel.objects.create(name="qwen", provider_name="platform", provider_type=AIModel.PROVIDER_OPEN_SOURCE)
        self.url = f"/api/v2/orgs/{self.org.id}/ai/models"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_member_sees_registry_and_no_personal_providers(self):
        self._auth(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["providers"], [])
        self.assertEqual(body["platform"][0]["name"], "qwen")
        self.assertNotIn("api_key", response.content.decode())
        self._auth(self.other)
        other = self.client.get(self.url)
        self.assertEqual(other.status_code, 200)
        self.assertEqual(other.json()["providers"], [])

    def test_outsider_and_inactive_are_forbidden(self):
        self._auth(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self._auth(self.inactive)
        self.assertEqual(self.client.get(self.url).status_code, 403)
