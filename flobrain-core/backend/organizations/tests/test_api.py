from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization, PermissionGrant, PermissionRequest
from users.jwt_utils import make_access_token
from users.models import User


def _user(email: str) -> User:
    return User.objects.create(email=email, password_hash=make_password("pass-word-1"))


class OrgPermissionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="FloLabs", slug="flolabs-api")
        self.owner = _user("api-owner@example.com")
        self.member = _user("api-member@example.com")
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

    def test_member_cannot_create_grant(self):
        self._auth(self.member)
        res = self.client.post(
            f"/api/v2/orgs/{self.org.id}/grants",
            {"grantee": str(self.member.id), "perm_key": "audit.view"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_owner_can_create_and_revoke_grant(self):
        self._auth(self.owner)
        res = self.client.post(
            f"/api/v2/orgs/{self.org.id}/grants",
            {"grantee": str(self.member.id), "perm_key": "audit.view"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        grant_id = res.json()["id"]
        self.assertTrue(PermissionGrant.objects.filter(pk=grant_id).exists())
        res = self.client.delete(f"/api/v2/orgs/{self.org.id}/grants/{grant_id}")
        self.assertEqual(res.status_code, 204)

    def test_member_can_request_permission(self):
        self._auth(self.member)
        res = self.client.post(
            f"/api/v2/orgs/{self.org.id}/permission-requests",
            {"perm_key": "audit.view", "reason": "need logs"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)

    def test_member_cannot_list_audit(self):
        self._auth(self.member)
        res = self.client.get(f"/api/v2/orgs/{self.org.id}/audit-events")
        self.assertEqual(res.status_code, 403)

    def test_owner_lists_audit_after_grant(self):
        self._auth(self.owner)
        self.client.post(
            f"/api/v2/orgs/{self.org.id}/grants",
            {"grantee": str(self.member.id), "perm_key": "org.members.view_contact"},
            format="json",
        )
        res = self.client.get(f"/api/v2/orgs/{self.org.id}/audit-events")
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(res.json()["count"], 1)

    def test_owner_decides_request(self):
        req = PermissionRequest.objects.create(
            org=self.org,
            requester=self.member,
            perm_key="audit.view",
        )
        self._auth(self.owner)
        res = self.client.post(
            f"/api/v2/orgs/{self.org.id}/permission-requests/{req.id}/approve",
            {},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        req.refresh_from_db()
        self.assertEqual(req.status, PermissionRequest.STATUS_APPROVED)
