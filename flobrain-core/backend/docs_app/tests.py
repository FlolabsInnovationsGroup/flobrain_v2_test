import shutil
import tempfile

from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from docs_app.models import Document
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.services import ensure_team_room
from users.jwt_utils import make_access_token
from users.models import User


class DocsApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()
        cls._storage = override_settings(DOCS_LOCAL_STORAGE_DIR=cls.media, DOCS_FILE_STORAGE="local")
        cls._storage.enable()

    @classmethod
    def tearDownClass(cls):
        cls._storage.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

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
        self.assertIn("/upload", presign.json()["upload_url"])
        self.assertNotIn("amazonaws", presign.json()["upload_url"])
        self.assertNotIn("s3.", presign.json()["upload_url"].lower())
        early = self.client.post(f"{self.base}/files/{presign.json()['id']}/complete", {}, format="json")
        self.assertEqual(early.status_code, 409, "nothing uploaded yet")
        upload = self.client.post(presign.json()["upload_url"], {"file": SimpleUploadedFile("notes.txt", b"hello")}, format="multipart")
        self.assertEqual(upload.status_code, 200, upload.content)
        complete = self.client.post(f"{self.base}/files/{presign.json()['id']}/complete", {}, format="json")
        self.assertEqual(complete.status_code, 200)
        self.assertTrue(complete.json()["url"].endswith("/download"))
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

    def _make(self, user, title="Plan", text="v1", room=None):
        self._auth(user)
        made = self.client.post(f"{self.base}/rooms/{(room or self.room_a).id}/docs", {"title": title, "content_text": text}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        return made.json()

    def test_conflict_returns_current_version_and_bad_input_is_400(self):
        doc = self._make(self.member_a)
        url = f"{self.base}/docs/{doc['id']}"
        self.assertEqual(self.client.patch(url, {"version": 1, "content_text": "mine"}, format="json").json()["version"], 2)
        stale = self.client.patch(url, {"version": 1, "content_text": "their draft"}, format="json")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["current"]["content_text"], "mine")
        self.assertEqual(stale.json()["current"]["version"], 2)
        self.assertEqual(stale.json()["current"]["updated_by"]["id"], str(self.member_a.id))
        self.assertEqual(self.client.patch(url, {"content_text": "no version"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"version": "x"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"version": 2, "title": "   "}, format="json").status_code, 400)
        same = self.client.patch(url, {"version": 2, "content_text": "mine"}, format="json")
        self.assertEqual(same.json()["version"], 2, "an unchanged save makes no new version")
        renamed = self.client.patch(url, {"version": 2, "title": "Launch plan"}, format="json")
        self.assertEqual((renamed.json()["title"], renamed.json()["content_text"], renamed.json()["version"]), ("Launch plan", "mine", 3))
        with override_settings(FLOBRAIN_V2={"DOCUMENT_MAX_CHARS": 10}):
            self.assertEqual(self.client.patch(url, {"version": 3, "content_text": "x" * 11}, format="json").status_code, 400)

    def test_revisions_and_restore(self):
        doc = self._make(self.member_a, text="first")
        url = f"{self.base}/docs/{doc['id']}"
        self.client.patch(url, {"version": 1, "content_text": "second"}, format="json")
        revs = self.client.get(f"{url}/revisions")
        self.assertEqual([r["version"] for r in revs.json()], [2, 1])
        self.assertTrue(revs.json()[0]["current"])
        self.assertEqual(self.client.get(f"{url}/revisions/1").json()["content_text"], "first")
        self.assertEqual(self.client.get(f"{url}/revisions/9").status_code, 404)
        self.assertEqual(self.client.post(f"{url}/revisions/1/restore", {"version": 1}, format="json").status_code, 409)
        self.assertEqual(self.client.post(f"{url}/revisions/1/restore", {}, format="json").status_code, 400)
        restored = self.client.post(f"{url}/revisions/1/restore", {"version": 2}, format="json")
        self.assertEqual(restored.status_code, 200, restored.content)
        self.assertEqual((restored.json()["content_text"], restored.json()["version"]), ("first", 3))
        self._auth(self.member_b)
        self.assertEqual(self.client.get(f"{url}/revisions").status_code, 404)
        self.assertEqual(self.client.get(f"{url}/revisions/1").status_code, 404)
        self.assertEqual(self.client.post(f"{url}/revisions/1/restore", {"version": 3}, format="json").status_code, 404)

    def test_delete_rules(self):
        lead = User.objects.create(email="d-lead@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=lead, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE)
        TeamMembership.objects.create(team=self.team_a, user=lead, team_role=TeamMembership.ROLE_LEAD)
        peer = User.objects.create(email="d-peer@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=peer, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE)
        TeamMembership.objects.create(team=self.team_a, user=peer)
        ensure_team_room(self.team_a)
        mine = self._make(self.member_a, title="Mine")
        self.assertTrue(mine["can_delete"])
        self._auth(peer)
        listed = {d["id"]: d for d in self.client.get(f"{self.base}/rooms/{self.room_a.id}/docs").json()}
        self.assertFalse(listed[mine["id"]]["can_delete"])
        self.assertEqual(self.client.delete(f"{self.base}/docs/{mine['id']}").status_code, 403, "a member can't delete someone else's doc")
        self._auth(self.member_b)
        self.assertEqual(self.client.delete(f"{self.base}/docs/{mine['id']}").status_code, 404, "not in the room")
        self._auth(self.member_a)
        self.assertEqual(self.client.delete(f"/api/v2/orgs/{self.other_org.id}/docs/{mine['id']}").status_code, 403)
        self._auth(lead)
        self.assertEqual(self.client.delete(f"{self.base}/docs/{mine['id']}").status_code, 204, "the team lead can")
        own = self._make(peer, title="Peer's")
        self.assertEqual(self.client.delete(f"{self.base}/docs/{own['id']}").status_code, 204, "authors delete their own")
        other = self._make(self.member_a, title="Other")
        self._auth(self.owner)
        self.assertEqual(self.client.delete(f"{self.base}/docs/{other['id']}").status_code, 204)
        self.assertFalse(Document.objects.filter(pk__in=[mine["id"], own["id"], other["id"]]).exists())

    def test_attachments_upload_download_and_visibility(self):
        doc = self._make(self.member_a)
        files = f"{self.base}/docs/{doc['id']}/files"
        self.assertEqual(self.client.get(files).json()["results"], [])
        bad_type = self.client.post(f"{self.base}/files/presign", {"name": "page.html", "document": doc["id"]}, format="json")
        self.assertEqual(bad_type.status_code, 400)
        self.assertEqual(self.client.post(f"{self.base}/files/presign", {"name": "x.txt"}, format="json").status_code, 400)
        big = self.client.post(f"{self.base}/files/presign", {"name": "a.pdf", "document": doc["id"], "size": 10**12}, format="json")
        self.assertEqual(big.status_code, 400)
        presign = self.client.post(f"{self.base}/files/presign", {"name": "brief.pdf", "document": doc["id"]}, format="json")
        self.assertEqual(presign.status_code, 201, presign.content)
        fid = presign.json()["id"]
        self._auth(self.member_b)
        self.assertEqual(self.client.post(f"{self.base}/files/{fid}/upload", {"file": SimpleUploadedFile("b.pdf", b"x")}, format="multipart").status_code, 404)
        self.assertEqual(self.client.post(f"{self.base}/files/presign", {"name": "b.pdf", "document": doc["id"]}, format="json").status_code, 404)
        self._auth(self.member_a)
        self.assertEqual(self.client.post(f"{self.base}/files/{fid}/upload", {}, format="multipart").status_code, 400)
        up = self.client.post(f"{self.base}/files/{fid}/upload", {"file": SimpleUploadedFile("brief.pdf", b"%PDF-1.4 demo")}, format="multipart")
        self.assertEqual(up.status_code, 200, up.content)
        self.assertEqual(self.client.post(f"{self.base}/files/{fid}/complete", {}, format="json").status_code, 200)
        self.assertEqual(self.client.post(f"{self.base}/files/{fid}/upload", {"file": SimpleUploadedFile("brief.pdf", b"again")}, format="multipart").status_code, 409)
        listed = self.client.get(files).json()["results"]
        self.assertEqual([(f["name"], f["size_bytes"]) for f in listed], [("brief.pdf", 13)])
        download = self.client.get(f"{self.base}/files/{fid}/download")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), b"%PDF-1.4 demo")
        self.assertIn("attachment", download["Content-Disposition"])
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")
        self._auth(self.member_b)
        self.assertEqual(self.client.get(f"{self.base}/files/{fid}/download").status_code, 404)
        self.assertEqual(self.client.get(files).status_code, 404)
        self.assertEqual(self.client.delete(f"{self.base}/files/{fid}").status_code, 404)
        self._auth(self.member_a)
        self.assertEqual(self.client.delete(f"{self.base}/files/{fid}").status_code, 204)
        self.assertEqual(self.client.get(f"{self.base}/files/{fid}/download").status_code, 404)

    def test_presign_without_storage_is_501(self):
        doc = self._make(self.member_a)
        with override_settings(DOCS_FILE_STORAGE="s3"):
            off = self.client.post(f"{self.base}/files/presign", {"name": "a.pdf", "document": doc["id"]}, format="json")
        self.assertEqual(off.status_code, 501)
