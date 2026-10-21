import hashlib
import hmac
import json

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class MemberLifecycleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="FloLabs", slug="flolabs-p1")
        self.owner = User.objects.create(email="p1-owner@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="p1-member@example.com", password_hash=make_password("x"))
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

    def test_member_list_hides_email_from_members(self):
        self._auth(self.member)
        res = self.client.get(f"/api/v2/orgs/{self.org.id}/members")
        self.assertEqual(res.status_code, 200, res.content)
        row = next(r for r in res.json()["results"] if r["id"] == str(self.owner.id))
        self.assertNotIn("email", row)
        self.assertIn("username", row)

    def test_owner_sees_contact_and_can_invite(self):
        self._auth(self.owner)
        listed = self.client.get(f"/api/v2/orgs/{self.org.id}/members")
        self.assertEqual(listed.status_code, 200)
        row = next(r for r in listed.json()["results"] if r["id"] == str(self.member.id))
        self.assertEqual(row["email"], "p1-member@example.com")
        created = self.client.post(
            f"/api/v2/orgs/{self.org.id}/members",
            {"email": "new.intern@example.com", "username": "Intern"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["employment_status"], OrgMembership.STATUS_PENDING)
        user = User.objects.get(email="new.intern@example.com")
        self.assertTrue(user.must_change_password)

    def test_member_cannot_invite(self):
        self._auth(self.member)
        res = self.client.post(
            f"/api/v2/orgs/{self.org.id}/members",
            {"email": "nope@example.com"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_deactivate_bumps_password_changed_at(self):
        self._auth(self.owner)
        before = self.member.password_changed_at
        res = self.client.patch(
            f"/api/v2/orgs/{self.org.id}/members/{self.member.id}",
            {"employment_status": OrgMembership.STATUS_TERMINATED},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.member.refresh_from_db()
        self.assertIsNotNone(self.member.password_changed_at)
        self.assertNotEqual(self.member.password_changed_at, before)

    def test_q34_attaches_existing_user(self):
        existing = User.objects.create(email="already@example.com", password_hash=make_password("keep"))
        self._auth(self.owner)
        res = self.client.post(
            f"/api/v2/orgs/{self.org.id}/members",
            {"email": "already@example.com"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        existing.refresh_from_db()
        self.assertEqual(User.objects.filter(email="already@example.com").count(), 1)
        self.assertTrue(OrgMembership.objects.filter(org=self.org, user=existing).exists())

    def test_teams_and_projects(self):
        self._auth(self.owner)
        team = self.client.post(
            f"/api/v2/orgs/{self.org.id}/teams",
            {"name": "Engineering"},
            format="json",
        )
        self.assertEqual(team.status_code, 201, team.content)
        project = self.client.post(
            f"/api/v2/orgs/{self.org.id}/projects",
            {"name": "Workspace"},
            format="json",
        )
        self.assertEqual(project.status_code, 201, project.content)
        listed = self.client.get(f"/api/v2/orgs/{self.org.id}/teams")
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(t["name"] == "Engineering" for t in listed.json()))


class HRWebhookTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="FloLabs", slug="flolabs")
        self.client = APIClient()

    @override_settings(HR_WEBHOOK_SECRET="test-hr-secret")
    def test_hmac_required_and_creates_applicant(self):
        body = json.dumps({"email": "hire@example.com", "full_name": "Hire Me", "org_slug": "flolabs"})
        sig = hmac.new(b"test-hr-secret", body.encode(), hashlib.sha256).hexdigest()
        bad = self.client.post(
            "/api/v2/integrations/hr/applicants",
            data=body,
            content_type="application/json",
            HTTP_X_FLOBRAIN_SIGNATURE="nope",
        )
        self.assertEqual(bad.status_code, 401)
        ok = self.client.post(
            "/api/v2/integrations/hr/applicants",
            data=body,
            content_type="application/json",
            HTTP_X_FLOBRAIN_SIGNATURE=sig,
        )
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertTrue(User.objects.filter(email="hire@example.com").exists())
