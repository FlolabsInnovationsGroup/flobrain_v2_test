from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from notifications.models import Notification
from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class NotificationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="N Org", slug="n-org")
        self.other = Organization.objects.create(name="N Other", slug="n-other")
        self.user = User.objects.create(email="n-user@example.com", password_hash=make_password("x"))
        self.outsider = User.objects.create(email="n-out@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(
            org=self.org,
            user=self.user,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )
        Notification.objects.create(org=self.org, user=self.user, kind="room_message", payload={"x": 1})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.user.id))}")

    def test_list_own_and_mark_read(self):
        listed = self.client.get(f"/api/v2/orgs/{self.org.id}/notifications")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 1)
        read = self.client.post(f"/api/v2/orgs/{self.org.id}/notifications/read", {}, format="json")
        self.assertEqual(read.status_code, 200)
        unread = self.client.get(f"/api/v2/orgs/{self.org.id}/notifications?unread=1")
        self.assertEqual(unread.json()["count"], 0)

    def test_other_org_denied(self):
        res = self.client.get(f"/api/v2/orgs/{self.other.id}/notifications")
        self.assertEqual(res.status_code, 403)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.outsider.id))}")
        res = self.client.get(f"/api/v2/orgs/{self.org.id}/notifications")
        self.assertEqual(res.status_code, 403)
