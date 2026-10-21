from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization
from telemetry.models import FeedbackItem, ProductEvent
from users.jwt_utils import make_access_token
from users.models import User


class TelemetryApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Tel Org", slug="tel-org")
        self.owner = User.objects.create(email="tel-owner@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="tel-member@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(
            org=self.org,
            user=self.owner,
            org_role=OrgMembership.ORG_ROLE_OWNER,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )
        OrgMembership.objects.create(
            org=self.org,
            user=self.member,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_member_can_post_allowlisted_event(self):
        self._auth(self.member)
        res = self.client.post(
            f"/api/v2/orgs/{self.org.id}/events",
            {"name": "page.viewed", "properties": {"page": "/w/flolabs?secret=1", "drop": "nope"}},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        event = ProductEvent.objects.get()
        self.assertEqual(event.properties.get("page"), "/w/flolabs")
        self.assertNotIn("drop", event.properties)

    def test_rejects_unknown_event(self):
        self._auth(self.member)
        res = self.client.post(
            f"/api/v2/orgs/{self.org.id}/events",
            {"name": "message.sent", "properties": {"text": "secret"}},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_feedback_and_admin_list(self):
        self._auth(self.member)
        res = self.client.post(
            f"/api/v2/orgs/{self.org.id}/feedback",
            {"kind": "bug", "text": "broken", "page": "/w/x"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        self._auth(self.member)
        denied = self.client.get(f"/api/v2/orgs/{self.org.id}/admin/feedback")
        self.assertEqual(denied.status_code, 403)
        self._auth(self.owner)
        listed = self.client.get(f"/api/v2/orgs/{self.org.id}/admin/feedback")
        self.assertEqual(listed.status_code, 200)
        self.assertGreaterEqual(listed.json()["count"], 1)
        self.assertTrue(FeedbackItem.objects.filter(org=self.org).exists())
