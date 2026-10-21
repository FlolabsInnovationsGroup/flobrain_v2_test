from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization, Team, TeamMembership
from users.jwt_utils import make_access_token
from users.models import User

TEST_KEY = "ab" * 32  # test-only, never a real key
MASTER_KEY = "cd" * 32  # test-only


@override_settings(CREDENTIALS_ENCRYPTION_KEY=TEST_KEY)
class ComplianceBase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(name="Acme Org", slug="acme", settings={"flags": {"compliance": True}})
        self.users = {}
        for key, role in (("owner", "owner"), ("admin", "admin"), ("lead", "member"), ("member", "member"), ("teammate", "member")):
            user = User.objects.create(email=f"c-{key}@example.com", username=key.capitalize(), password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status="active")
            self.users[key] = user
        self.outsider = User.objects.create(email="c-out@example.com", password_hash=make_password("x"))
        self.team = Team.objects.create(org=self.org, name="Engineering")
        TeamMembership.objects.create(team=self.team, user=self.users["lead"], team_role=TeamMembership.ROLE_LEAD)
        for key in ("member", "teammate"):
            TeamMembership.objects.create(team=self.team, user=self.users[key])
        self.base = f"/api/v2/orgs/{self.org.id}/compliance"

    def auth(self, key):
        user = self.users[key] if isinstance(key, str) else key
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def membership(self, key):
        return OrgMembership.objects.get(org=self.org, user=self.users[key])
