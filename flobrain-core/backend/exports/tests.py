import io
import json
import zipfile

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from brain.models import Chat
from docs_app.models import Document
from exports.builder import build_bytes
from organizations.models import AuditEvent, OrgMembership, Organization, Team
from rooms.models import Room, RoomMessage
from users.jwt_utils import make_access_token
from users.models import User


@override_settings(CONTENT_STORAGE="local")
class MemoryExportTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme-export")
        self.owner = User.objects.create(email="o@acme.test", password_hash=make_password("x"))
        self.admin = User.objects.create(email="a@acme.test", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status="active")
        OrgMembership.objects.create(org=self.org, user=self.admin, org_role=OrgMembership.ORG_ROLE_ADMIN, employment_status="active")
        team = Team.objects.create(org=self.org, name="Eng")
        self.team_room = Room.objects.create(org=self.org, name="Eng room", kind=Room.KIND_TEAM, team=team)
        self.dm = Room.objects.create(org=self.org, name="dm", kind=Room.KIND_DIRECT, pair_key="x")
        self.group = Room.objects.create(org=self.org, name="secret group", kind=Room.KIND_GROUP)
        RoomMessage.objects.create(room=self.team_room, author=self.owner, body="ship friday")
        RoomMessage.objects.create(room=self.team_room, author=self.owner, body="deleted one", deleted_at="2026-01-01T00:00:00Z")
        RoomMessage.objects.create(room=self.dm, author=self.owner, body="private dm text")
        RoomMessage.objects.create(room=self.group, author=self.owner, body="private group text")
        Document.objects.create(org=self.org, room=self.team_room, title="Plan / Q4", content_text="the plan body")
        Document.objects.create(org=self.org, room=self.group, title="Group doc", content_text="group doc body")
        self.base = f"/api/v2/orgs/{self.org.id}/exports/memory"

    def _as(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return client

    def test_zip_contains_only_team_and_project_memory(self):
        Chat.objects.create(user=self.owner, title="my ai thread", org=self.org)
        data, counts = build_bytes(self.org)
        self.assertEqual((counts["rooms"], counts["messages"], counts["documents"]), (1, 1, 1))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            text = " ".join(zf.read(n).decode() for n in zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))
        self.assertIn("ship friday", text)
        self.assertIn("the plan body", text)
        for leaked in ("private dm text", "private group text", "group doc body", "deleted one", "my ai thread"):
            self.assertNotIn(leaked, text)
        self.assertIn("direct rooms", manifest["excluded"])

    def test_owner_only_and_audited(self):
        self.assertEqual(self._as(self.admin).post(self.base).status_code, 403)
        made = self._as(self.owner).post(self.base)
        self.assertEqual(made.status_code, 202, made.content)
        export_id = made.json()["id"]
        detail = self._as(self.owner).get(f"{self.base}/{export_id}").json()
        self.assertEqual(detail["status"], "succeeded")
        self.assertTrue(detail["download_url"])
        self.assertEqual(self._as(self.admin).get(f"{self.base}/{export_id}").status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="export.memory.download").exists())

    @override_settings(EXPORT_MAX_PER_DAY=1)
    def test_daily_limit(self):
        self.assertEqual(self._as(self.owner).post(self.base).status_code, 202)
        self.assertEqual(self._as(self.owner).post(self.base).status_code, 429)

    @override_settings(CONTENT_STORAGE="")
    def test_not_configured(self):
        self.assertEqual(self._as(self.owner).post(self.base).status_code, 501)

    def test_owner_only_cannot_be_granted_or_bypassed(self):
        grant = self._as(self.owner).post(f"/api/v2/orgs/{self.org.id}/grants", {"grantee": str(self.admin.id), "perm_key": "exports.memory"}, format="json")
        self.assertEqual(grant.status_code, 400)
        asked = self._as(self.admin).post(f"/api/v2/orgs/{self.org.id}/permission-requests", {"perm_key": "exports.memory", "reason": "x"}, format="json")
        self.assertIn(asked.status_code, (400, 404))
        staff = User.objects.create(email="s@flobrain.test", password_hash=make_password("x"), is_platform_admin=True)
        self.assertEqual(self._as(staff).get(self.base).status_code, 403, "platform admins need a real owner seat")
        self.assertEqual(self._as(self.admin).put(f"/api/v2/orgs/{self.org.id}/policy", {"inference_scope": "private_only"}, format="json").status_code, 403)

    def test_purge_deletes_local_files(self):
        import os
        import tempfile
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        from exports.models import MemoryExport

        with tempfile.TemporaryDirectory() as root, override_settings(CONTENT_LOCAL_DIR=root):
            export_id = self._as(self.owner).post(self.base).json()["id"]
            export = MemoryExport.objects.get(pk=export_id)
            path = os.path.join(root, *export.storage_key.split("/"))
            self.assertTrue(os.path.isfile(path))
            MemoryExport.objects.filter(pk=export_id).update(expires_at=timezone.now() - timedelta(minutes=1))
            call_command("purge_exports", stdout=io.StringIO())
            self.assertFalse(os.path.exists(path))
