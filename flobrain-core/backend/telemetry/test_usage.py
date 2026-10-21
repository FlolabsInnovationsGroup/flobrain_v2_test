from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization
from telemetry.models import UsageEvent
from users.jwt_utils import make_access_token
from users.models import User


class UsageReadTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Usage Org", slug="usage-org")
        self.other_org = Organization.objects.create(name="Other Usage", slug="other-usage")
        self.owner = User.objects.create(email="u-owner@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="u-member@example.com", password_hash=make_password("x"))
        self.peer = User.objects.create(email="u-peer@example.com", password_hash=make_password("x"))
        self.inactive = User.objects.create(email="u-off@example.com", password_hash=make_password("x"))
        self.outsider = User.objects.create(email="u-out@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(
            org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org, user=self.member, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org, user=self.peer, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org,
            user=self.inactive,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_TERMINATED,
        )
        self.mine = UsageEvent.objects.create(
            org=self.org, user=self.member, model="qwen", total_tokens=None, estimated=False, status="ok"
        )
        self.peer_row = UsageEvent.objects.create(
            org=self.org, user=self.peer, model="qwen", total_tokens=12, estimated=False, status="ok"
        )
        self.estimated = UsageEvent.objects.create(
            org=self.org, user=self.member, model="legacy", total_tokens=40, estimated=True, status="ok"
        )
        UsageEvent.objects.create(org=self.other_org, user=self.member, model="qwen", total_tokens=99)
        self.url = f"/api/v2/orgs/{self.org.id}/usage"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_member_sees_only_own_rows_and_unknown_is_null(self):
        self._auth(self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["results"]
        ids = {row["id"] for row in rows}
        self.assertIn(str(self.mine.id), ids)
        self.assertIn(str(self.estimated.id), ids)
        self.assertNotIn(str(self.peer_row.id), ids)
        by_id = {row["id"]: row for row in rows}
        unknown = by_id[str(self.mine.id)]
        self.assertIsNone(unknown["total_tokens"])
        self.assertEqual(unknown["token_state"], "unknown")
        self.assertNotEqual(unknown["total_tokens"], 0)
        estimated = by_id[str(self.estimated.id)]
        self.assertEqual(estimated["token_state"], "estimated")
        self.assertTrue(estimated["estimated"])
        self.assertNotIn("api_key", response.content.decode())

    def test_owner_sees_org_usage(self):
        self._auth(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.json()["results"]}
        self.assertIn(str(self.mine.id), ids)
        self.assertIn(str(self.peer_row.id), ids)
        self.assertNotIn("99", [str(row["total_tokens"]) for row in response.json()["results"] if row["id"] not in ids])

    def test_outsider_inactive_and_other_org(self):
        self._auth(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self._auth(self.inactive)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self._auth(self.member)
        other = self.client.get(f"/api/v2/orgs/{self.other_org.id}/usage")
        self.assertEqual(other.status_code, 403)
