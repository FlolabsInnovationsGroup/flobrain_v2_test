from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from docs_app.models import Document
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.services import ensure_team_room
from users.jwt_utils import make_access_token
from users.models import User


class DocsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Docs Org", slug="docs-org")
        self.other_org = Organization.objects.create(name="Docs Other", slug="docs-other")
        self.owner = User.objects.create(email="d-owner@example.com", password_hash=make_password("x"))
        self.member_a = User.objects.create(email="d-a@example.com", password_hash=make_password("x"))
        self.member_b = User.objects.create(email="d-b@example.com", password_hash=make_password("x"))
        self.inactive = User.objects.create(email="d-off@example.com", password_hash=make_password("x"))
        for user, role, status in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER, OrgMembership.STATUS_ACTIVE),
            (self.member_a, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.member_b, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.inactive, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_TERMINATED),
        ):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status=status)
        self.team_a = Team.objects.create(org=self.org, name="Writers")
        self.team_b = Team.objects.create(org=self.org, name="Readers")
        TeamMembership.objects.create(team=self.team_a, user=self.member_a)
        TeamMembership.objects.create(team=self.team_b, user=self.member_b)
        self.room_a = ensure_team_room(self.team_a)
        self.room_b = ensure_team_room(self.team_b)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_write_conflict_and_isolation(self):
        self._auth(self.member_a)
        created = self.client.post(
            f"{self.base}/rooms/{self.room_a.id}/docs",
            {"title": "Spec", "content_text": "v1"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        doc_id = created.json()["id"]
        stale = self.client.patch(
            f"{self.base}/docs/{doc_id}",
            {"version": 0, "content_text": "stale"},
            format="json",
        )
        self.assertEqual(stale.status_code, 409)
        ok = self.client.patch(
            f"{self.base}/docs/{doc_id}",
            {"version": 1, "content_text": "v2"},
            format="json",
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["version"], 2)
        self._auth(self.member_b)
        self.assertEqual(self.client.get(f"{self.base}/docs/{doc_id}").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_a.id}/docs").status_code, 404)
        hidden = Document.objects.create(
            org=self.org, room=self.room_b, title="Hidden", content_text="beta only", created_by=self.member_b
        )
        self._auth(self.member_a)
        search = self.client.get(f"{self.base}/docs/search", {"q": "Hidden"})
        self.assertEqual(search.status_code, 200)
        self.assertFalse(any(row["id"] == str(hidden.id) for row in search.json()))

    def test_files_stay_local_and_inactive_denied(self):
        self._auth(self.member_a)
        presign = self.client.post(
            f"{self.base}/files/presign",
            {"name": "notes.txt", "content_type": "text/plain", "room": str(self.room_a.id)},
            format="json",
        )
        self.assertEqual(presign.status_code, 201, presign.content)
        self.assertIn("/local-uploads/", presign.json()["upload_url"])
        self.assertNotIn("amazonaws", presign.json()["upload_url"])
        self.assertNotIn("s3.", presign.json()["upload_url"].lower())
        complete = self.client.post(f"{self.base}/files/{presign.json()['id']}/complete", {}, format="json")
        self.assertEqual(complete.status_code, 200)
        self.assertTrue(complete.json()["url"].startswith("/media/local/"))
        self._auth(self.inactive)
        self.assertEqual(
            self.client.post(
                f"{self.base}/files/presign",
                {"name": "x", "room": str(self.room_a.id)},
                format="json",
            ).status_code,
            403,
        )
        self._auth(self.member_a)
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.other_org.id}/docs/search").status_code, 403)
