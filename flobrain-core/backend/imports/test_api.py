"""Imports API: flag and permission gates, Slack import end to end (people matching, private
rooms, threads, idempotency, undo), Notion export and API, Google Drive (mocked), file uploads,
indexing and audit without content. Nothing reaches the network."""

import io
import json
import shutil
import tempfile
import zipfile
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from docs_app.models import Document
from imports import services
from imports.models import ImportedObject, ImportRun
from imports.test_parsing import docx_bytes
from knowledge.models import KnowledgeChunk
from notifications.models import Notification
from organizations.models import AuditEvent, OrgMembership, Organization, Team, TeamMembership
from rooms.models import Announcement, Room, RoomMember, RoomMessage
from users.jwt_utils import make_access_token
from users.models import User

KEY = "ef" * 32  # test-only encryption key
D = "demo.flobrain.example"
SECRET_TEXT = "Release 2.4 is on staging"  # a message in the fixture; must never reach audit or previews


class ImportsBase(TestCase):
    def setUp(self):
        cache.clear()
        self.tmp = tempfile.mkdtemp(prefix="imports-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        storage = override_settings(CONTENT_LOCAL_DIR=self.tmp, CONTENT_STORAGE="local", CREDENTIALS_ENCRYPTION_KEY=KEY)
        storage.enable()
        self.addCleanup(storage.disable)
        self.client = APIClient()
        self.org = Organization.objects.create(name="I Org", slug="i-org", settings={"flags": {"imports": True}})
        self.u = {}
        for key, email, name, role in (
            ("owner", f"owner@{D}", "Nadia Hassan", "owner"),
            ("admin", f"ADMIN@{D}", "Omar Khaled", "admin"),
            ("lead", f"lead@{D}", "Layla Mansour", "member"),
            ("member", f"member@{D}", "Youssef Adel", "member"),
        ):
            user = User.objects.create(email=email, username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status="active")
            self.u[key] = user
        # Same email as a Slack person, but not in this org: must not be matched.
        self.outsider = User.objects.create(email=f"designer@{D}", username="Sara Nabil", password_hash=make_password("x"))
        self.eng = Team.objects.create(org=self.org, name="Engineering")
        for key in ("lead", "member"):
            TeamMembership.objects.create(team=self.eng, user=self.u[key])
        self.base = f"/api/v2/orgs/{self.org.id}/imports"

    def auth(self, user):
        user = self.u[user] if isinstance(user, str) else user
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def upload(self, data, name="export.zip", source="slack", who="admin"):
        self.auth(who)
        files = data if isinstance(data, list) else [SimpleUploadedFile(name, data, content_type="application/zip")]
        return self.client.post(f"{self.base}/upload", {"source": source, "file": files}, format="multipart")

    def slack_zip(self) -> bytes:
        return services.fixture_zip("slack_export").getvalue()

    def ready_slack(self):
        res = self.upload(self.slack_zip())
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["status"], "ready", res.json())
        return res.json()

    def mapping(self, include_private=True):
        return {
            "channels": {
                "C01GENERAL": {"target": "new_team"},
                "C02ENGINEER": {"target": "team", "team_id": str(self.eng.id)},
                "G03DESIGNCR": {"target": "private"},
            },
            "include_private": include_private,
        }

    def start(self, run_id, mapping, who="admin"):
        self.auth(who)
        return self.client.post(f"{self.base}/{run_id}/start", {"mapping": mapping}, format="json")


class GateTests(ImportsBase):
    def test_flag_off_is_501(self):
        self.org.settings = {"flags": {"imports": False}}
        self.org.save()
        self.auth("admin")
        for path in ("", "/meta", "/drive/files"):
            self.assertEqual(self.client.get(self.base + path).status_code, 501, path)
        self.assertEqual(self.upload(self.slack_zip()).status_code, 501)

    def test_members_need_imports_run(self):
        self.auth("member")
        self.assertEqual(self.client.get(self.base).status_code, 403)
        self.assertEqual(self.upload(self.slack_zip(), who="member").status_code, 403)
        self.assertFalse(ImportRun.objects.exists())

    def test_outsider_and_anonymous(self):
        self.assertEqual(self.client.get(self.base).status_code, 401)
        self.auth(self.outsider)
        self.assertEqual(self.client.get(self.base).status_code, 403)

    def test_meta(self):
        self.auth("admin")
        meta = self.client.get(f"{self.base}/meta").json()
        self.assertEqual(meta["max_upload_mb"], 500)
        self.assertIn("Engineering", [t["name"] for t in meta["teams"]])
        self.assertEqual(meta["drive"]["status"], "not_connected")
        self.assertFalse(meta["demo"])

    def test_upload_validation(self):
        self.assertEqual(self.upload(b"x", name="export.txt").status_code, 400)
        self.assertEqual(self.upload(self.slack_zip(), source="dropbox").status_code, 400)
        self.auth("admin")
        self.assertEqual(self.client.post(f"{self.base}/upload", {"source": "slack"}, format="multipart").status_code, 400)
        with override_settings(IMPORTS_MAX_UPLOAD_MB=0):
            self.assertEqual(self.upload(self.slack_zip()).status_code, 413)

    def test_sample_only_in_demo_org(self):
        self.auth("admin")
        self.assertEqual(self.client.post(f"{self.base}/sample", {"source": "slack"}, format="json").status_code, 403)


class SlackImportTests(ImportsBase):
    def test_preview_matches_people_and_has_no_message_text(self):
        run = self.ready_slack()
        preview = run["preview"]
        channels = {c["name"]: c for c in preview["channels"]}
        self.assertEqual(channels["general"]["messages"], 55)
        self.assertEqual(channels["design-crit"]["kind"], "private")
        self.assertEqual(preview["totals"]["messages"], 150)
        people = {p["name"]: p for p in preview["people"]}
        self.assertTrue(people["Omar Khaled"]["matched"])  # email matched case-insensitively
        self.assertFalse(people["Sara Nabil"]["matched"])  # same email, but not a member of this org
        self.assertEqual(people["Karim Fawzy"]["shown_as"], "Imported: Karim Fawzy")
        self.assertNotIn("Deploy Bot", people)
        self.assertNotIn(SECRET_TEXT, json.dumps(run))
        self.assertNotIn("imports/", json.dumps(run["files"]))  # storage keys stay private

    def test_full_import_rooms_people_threads_and_undo(self):
        run = self.ready_slack()
        res = self.start(run["id"], self.mapping())
        self.assertEqual(res.status_code, 202, res.content)
        done = res.json()
        self.assertEqual(done["status"], "done", done)
        self.assertEqual(done["counts"]["messages"], 150)
        self.assertEqual(done["counts"]["teams_created"], 1)
        self.assertEqual(RoomMessage.objects.filter(room__org=self.org).count(), 150)

        # public -> the chosen team's room; general -> a new team with the matched people
        eng_room = Room.objects.get(team=self.eng, kind=Room.KIND_TEAM)
        self.assertEqual(eng_room.messages.count(), 60)
        general = Team.objects.get(org=self.org, name="general")
        self.assertEqual(
            set(TeamMembership.objects.filter(team=general).values_list("user_id", flat=True)),
            {self.u[k].id for k in ("owner", "admin", "lead", "member")},
        )
        # private -> a private room whose members are the matched people only
        private = Room.objects.get(org=self.org, name="design-crit")
        self.assertEqual(private.kind, Room.KIND_GROUP)
        self.assertEqual(set(RoomMember.objects.filter(room=private).values_list("user_id", flat=True)), {self.u["member"].id})

        # original author and time; unmatched people labelled; threads, reactions, files, mentions
        msgs = list(RoomMessage.objects.filter(room__org=self.org).order_by("created_at"))
        self.assertTrue(all(m.created_at.year == 2026 and m.created_at.month == 9 for m in msgs))
        unmatched = [m for m in msgs if m.author_id is None]
        self.assertTrue(unmatched)
        self.assertTrue(all(m.body.split("\n")[0] in ("Imported: Karim Fawzy", "Imported: Mona Saleh", "Imported: Sara Nabil") for m in unmatched))
        self.assertTrue(any(m.body.split("\n")[0] == "↳ Reply in thread: “" + m.body.split("“")[1].split("”")[0] + "”" for m in msgs if "↳" in m.body))
        self.assertTrue(any("Reactions: :" in m.body for m in msgs))
        self.assertTrue(any("File: Meeting notes (demo).pdf (https://demo-workspace.slack.com/files/" in m.body for m in msgs))
        self.assertFalse(any("<@U0" in m.body for m in msgs))
        self.assertFalse(any("has joined the channel" in m.body or "Deployed build" in m.body for m in msgs))
        self.assertTrue(any("(edited)" in m.body for m in msgs))
        self.assertTrue(Announcement.objects.filter(room=eng_room, body__startswith="Imported from Slack #engineering: 60 messages").exists())

        # Someone writes in the imported private room; then undo.
        RoomMessage.objects.create(room=private, author=self.u["member"], body="my own note")
        RoomMessage.objects.create(room=eng_room, author=self.u["lead"], body="unrelated")
        self.auth("admin")
        undone = self.client.post(f"{self.base}/{run['id']}/undo").json()
        self.assertEqual(undone["status"], "undone", undone)
        self.assertEqual(set(RoomMessage.objects.filter(room__org=self.org).values_list("body", flat=True)), {"my own note", "unrelated"})
        self.assertTrue(Room.objects.filter(pk=private.pk).exists(), "a room with someone's own message stays")
        self.assertFalse(Team.objects.filter(pk=general.pk).exists(), "an untouched imported team goes")
        self.assertTrue(Team.objects.filter(pk=self.eng.pk).exists())
        self.assertFalse(Announcement.objects.filter(org=self.org).exists())
        self.assertFalse(ImportedObject.objects.filter(run_id=run["id"]).exists())
        self.assertEqual(ImportRun.objects.get(pk=run["id"]).files, [])

    def test_rerun_is_idempotent_and_undo_only_removes_its_own(self):
        first = self.ready_slack()
        self.start(first["id"], self.mapping())
        second = self.ready_slack()
        res = self.start(second["id"], self.mapping()).json()
        self.assertEqual(res["status"], "done")
        self.assertEqual(res["counts"].get("messages", 0), 0)
        self.assertEqual(res["counts"]["messages_existing"], 150)
        self.assertEqual(RoomMessage.objects.filter(room__org=self.org).count(), 150)
        self.assertEqual(Team.objects.filter(org=self.org, name__startswith="general").count(), 1, "the team is reused, not duplicated")
        self.auth("admin")
        self.client.post(f"{self.base}/{second['id']}/undo")
        self.assertEqual(RoomMessage.objects.filter(room__org=self.org).count(), 150, "undoing the re-run removes nothing of the first")

    def test_resume_after_a_crash_skips_what_is_in(self):
        run = self.ready_slack()
        with patch("imports.services._message_body", side_effect=[f"m{i}" for i in range(60)] + [RuntimeError("boom")]):
            res = self.start(run["id"], self.mapping()).json()
        self.assertEqual(res["status"], "failed")
        partial = RoomMessage.objects.filter(room__org=self.org).count()
        self.assertLess(partial, 150)
        self.auth("admin")
        res = self.client.post(f"{self.base}/{run['id']}/resume").json()
        self.assertEqual(res["status"], "done", res)
        self.assertEqual(RoomMessage.objects.filter(room__org=self.org).count(), 150)

    def test_private_channels_need_opt_in_and_mapping_rules(self):
        run = self.ready_slack()
        res = self.start(run["id"], self.mapping(include_private=False)).json()
        self.assertEqual(res["status"], "done")
        self.assertFalse(Room.objects.filter(name="design-crit").exists())
        run = self.ready_slack()
        bad = {"channels": {"G03DESIGNCR": {"target": "new_team"}}, "include_private": True}
        self.assertEqual(self.start(run["id"], bad).status_code, 400)
        bad = {"channels": {"C02ENGINEER": {"target": "team", "team_id": "not-a-uuid"}}}
        self.assertEqual(self.start(run["id"], bad).status_code, 400)
        self.assertEqual(self.start(run["id"], {"channels": {}}).status_code, 400)

    def test_cancel_and_one_import_at_a_time(self):
        run = self.ready_slack()
        ImportRun.objects.filter(pk=run["id"]).update(status=ImportRun.QUEUED, mapping=self.mapping())
        self.assertEqual(self.upload(self.slack_zip()).status_code, 409)
        self.auth("admin")
        res = self.client.post(f"{self.base}/{run['id']}/cancel").json()
        self.assertEqual(res["status"], "cancelled")
        self.assertEqual(self.client.post(f"{self.base}/{run['id']}/cancel").status_code, 409)

    def test_cancel_requested_stops_between_batches(self):
        run = self.ready_slack()
        ImportRun.objects.filter(pk=run["id"]).update(cancel_requested=False)
        original = services.Runner.checkpoint

        def cancel_then_check(runner, *a, **k):
            ImportRun.objects.filter(pk=runner.run.pk).update(cancel_requested=True)
            return original(runner, *a, **k)

        with patch.object(services.Runner, "checkpoint", cancel_then_check):
            res = self.start(run["id"], self.mapping()).json()
        self.assertEqual(res["status"], "cancelled")
        self.assertLess(RoomMessage.objects.filter(room__org=self.org).count(), 150)

    def test_audit_and_logs_hold_no_content(self):
        run = self.ready_slack()
        with self.assertLogs("imports", level="INFO") as logs:
            self.start(run["id"], self.mapping())
        events = AuditEvent.objects.filter(org=self.org, action__startswith="imports.")
        self.assertEqual(set(events.values_list("action", flat=True)), {"imports.uploaded", "imports.started", "imports.finished"})
        dump = json.dumps(list(events.values_list("payload", flat=True))) + "\n".join(logs.output)
        for text in (SECRET_TEXT, "Karim", "design-crit", "Lunch order"):
            self.assertNotIn(text, dump)
        finished = events.get(action="imports.finished")
        self.assertEqual(finished.payload["counts"]["messages"], 150)
        self.assertTrue(Notification.objects.filter(user=self.u["admin"], kind="import_finished").exists())

    def test_imported_messages_and_documents_are_indexed(self):
        self.org.settings = {"flags": {"imports": True, "memory_search": True}}
        self.org.save()
        run = self.ready_slack()
        self.start(run["id"], {"channels": {"C02ENGINEER": {"target": "team", "team_id": str(self.eng.id)}}})
        eng_room = Room.objects.get(team=self.eng, kind=Room.KIND_TEAM)
        ids = set(str(i) for i in RoomMessage.objects.filter(room=eng_room).values_list("id", flat=True))
        indexed = set(str(i) for i in KnowledgeChunk.objects.filter(source_type=KnowledgeChunk.SOURCE_ROOM_MESSAGE).values_list("source_id", flat=True))
        self.assertEqual(ids, indexed)
        self.assertTrue(KnowledgeChunk.objects.filter(room=eng_room).exists(), "chunks carry the room, so search respects room access")
        self.auth("admin")
        self.client.post(f"{self.base}/{run['id']}/undo")
        self.assertFalse(KnowledgeChunk.objects.filter(source_type=KnowledgeChunk.SOURCE_ROOM_MESSAGE).exists())

    def test_unsafe_archive_fails_with_a_reason(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("users.json", "[]")
            zf.writestr("../evil.json", "[]")
        res = self.upload(buf.getvalue())
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["status"], "failed")
        self.assertTrue(res.json()["error"].startswith("traversal"))
        bomb = io.BytesIO()
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("users.json", b"0" * (3 * 1024 * 1024))
        self.assertTrue(self.upload(bomb.getvalue()).json()["error"].startswith("bomb"))

    def test_discard_a_ready_import(self):
        run = self.ready_slack()
        self.auth("admin")
        self.assertEqual(self.client.delete(f"{self.base}/{run['id']}").status_code, 204)
        self.assertFalse(ImportRun.objects.filter(pk=run["id"]).exists())


class DocumentImportTests(ImportsBase):
    def setUp(self):
        super().setUp()
        self.room = Room.objects.get(team=self.eng, kind=Room.KIND_TEAM)
        self.private = Room.objects.create(org=self.org, name="Private", kind=Room.KIND_GROUP)
        RoomMember.objects.create(room=self.private, user=self.u["lead"])

    def test_notion_export_becomes_documents_with_source_links(self):
        res = self.upload(services.fixture_zip("notion_export").getvalue(), source="notion_zip")
        run = res.json()
        self.assertEqual(run["status"], "ready", run)
        self.assertEqual(run["preview"]["totals"]["items"], 4)
        # a private room the importer can't open is refused (room visibility)
        self.assertEqual(self.start(run["id"], {"room_id": str(self.private.id)}).status_code, 400)
        done = self.start(run["id"], {"room_id": str(self.room.id)}).json()
        self.assertEqual(done["status"], "done", done)
        self.assertEqual(done["counts"]["documents"], 4)
        doc = Document.objects.get(org=self.org, title="Onboarding checklist")
        self.assertTrue(doc.content_text.startswith("Source: Notion · https://www.notion.so/2b3c4d5e6f708192a3b4c5d6e7f8091a"))
        self.assertEqual(doc.room, self.room)
        self.assertIn("Nour Schools | Signed", Document.objects.get(title="Customers").content_text)
        # again: nothing duplicated
        again = self.upload(services.fixture_zip("notion_export").getvalue(), source="notion_zip").json()
        res = self.start(again["id"], {"room_id": str(self.room.id)}).json()
        self.assertEqual(res["counts"]["documents_existing"], 4)
        self.assertEqual(Document.objects.filter(org=self.org).count(), 4)
        self.auth("admin")
        self.client.post(f"{self.base}/{run['id']}/undo")
        self.assertEqual(Document.objects.filter(org=self.org).count(), 0)

    def test_file_uploads_and_takeout(self):
        takeout = io.BytesIO()
        with zipfile.ZipFile(takeout, "w") as zf:
            zf.writestr("Takeout/Drive/Handbook.docx", docx_bytes())
            zf.writestr("Takeout/Drive/notes.txt", "Plain notes")
            zf.writestr("Takeout/Drive/scan.pdf", b"%PDF-1.4")
            zf.writestr("Takeout/Drive/photo.jpg", b"\xff\xd8")
        files = [
            SimpleUploadedFile("takeout-2026.zip", takeout.getvalue(), content_type="application/zip"),
            SimpleUploadedFile("Policy.md", b"# Policy\n\nBe kind.", content_type="text/markdown"),
        ]
        with patch.dict("sys.modules", {"pypdf": None}):  # a server without pypdf skips PDFs
            run = self.upload(files, source="files").json()
        self.assertEqual(run["status"], "ready", run)
        items = {i["name"]: i for i in run["preview"]["items"]}
        self.assertEqual(set(items), {"Handbook.docx", "notes.txt", "scan.pdf", "Policy.md"})
        self.assertFalse(items["scan.pdf"]["supported"])
        self.assertEqual(items["scan.pdf"]["reason"], "pdf_unavailable")
        done = self.start(run["id"], {"room_id": str(self.room.id)}).json()
        self.assertEqual(done["counts"]["documents"], 3, done)
        handbook = Document.objects.get(title="Handbook")
        self.assertTrue(handbook.content_text.startswith("Source: Google Takeout (Handbook.docx)"))
        self.assertIn("# Handbook", handbook.content_text)
        self.assertEqual(self.upload([SimpleUploadedFile("x.exe", b"MZ")], source="files").status_code, 400)


class FakeNotion:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, body=b"", headers=None, timeout=10, max_bytes=4096):
        self.calls.append((method, url))
        assert url.startswith("https://api.notion.com/v1/")
        assert headers["Authorization"] == "Bearer ntn_" + "b" * 40
        page_id = "5e6f7081-92a3-b4c5-d6e7-f8091a2b3c4d"
        if url.endswith("/search"):
            return 200, json.dumps({"results": [
                {"object": "page", "id": page_id, "properties": {"Name": {"type": "title", "title": [{"plain_text": "Brand voice"}]}}, "last_edited_time": "2026-10-01T00:00:00Z"},
                {"object": "page", "id": "x" * 32, "properties": {}},
                {"object": "database", "id": "708192a3b4c5d6e7f8091a2b3c4d5e6f", "title": [{"plain_text": "Pipeline"}], "archived": True},
            ], "has_more": False}).encode()
        if f"/pages/{page_id}" in url:
            return 200, json.dumps({"object": "page", "id": page_id, "properties": {"Name": {"type": "title", "title": [{"plain_text": "Brand voice"}]}, "Owner": {"type": "rich_text", "rich_text": [{"plain_text": "Sara"}]}}}).encode()
        if f"/blocks/{page_id}/children" in url:
            return 200, json.dumps({"results": [{"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Tone"}]}}, {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "Short sentences"}]}}], "has_more": False}).encode()
        return 404, b""


@override_settings(DEMO_MODE=False)
class NotionApiTests(ImportsBase):
    def setUp(self):
        super().setUp()
        from connectors.models import Connection
        from integrations import crypto

        self.room = Room.objects.get(team=self.eng, kind=Room.KIND_TEAM)
        self.conn = Connection.objects.create(org=self.org, connector="notion", room=self.room, config={"database_id": "a" * 32})
        self.conn.secret_ciphertext = crypto.encrypt("ntn_" + "b" * 40, self.conn.id, self.org.id)
        self.conn.save()

    def test_list_and_import_pages(self):
        fake = FakeNotion()
        self.auth("admin")
        with patch("platform_api.net.fetch", side_effect=fake):
            pages = self.client.get(f"{self.base}/notion/pages", {"connection_id": str(self.conn.id)}).json()["results"]
            self.assertEqual([p["title"] for p in pages], ["Brand voice"])
            res = self.client.post(f"{self.base}/notion", {"connection_id": str(self.conn.id), "room_id": str(self.room.id), "items": [{"id": pages[0]["id"], "type": "page"}]}, format="json")
        self.assertEqual(res.status_code, 202, res.content)
        self.assertEqual(res.json()["status"], "done", res.json())
        doc = Document.objects.get(org=self.org)
        self.assertEqual(doc.title, "Brand voice")
        self.assertIn("Owner: Sara", doc.content_text)
        self.assertIn("## Tone\n- Short sentences", doc.content_text)
        self.assertIn("https://www.notion.so/5e6f708192a3b4c5d6e7f8091a2b3c4d", doc.content_text)
        self.assertNotIn("ntn_", json.dumps(res.json()))

    def test_bad_input(self):
        self.auth("admin")
        self.assertEqual(self.client.get(f"{self.base}/notion/pages").status_code, 404)
        res = self.client.post(f"{self.base}/notion", {"connection_id": str(self.conn.id), "room_id": str(self.room.id), "items": [{"id": "../../x", "type": "page"}]}, format="json")
        self.assertEqual(res.status_code, 400)
        with patch("platform_api.net.fetch", side_effect=lambda *a, **k: (401, b"")):
            self.assertEqual(self.client.get(f"{self.base}/notion/pages", {"connection_id": str(self.conn.id)}).status_code, 400)


@override_settings(DEMO_MODE=False, FLOBRAIN_OAUTH_GOOGLE_WORKSPACE_CLIENT_ID="test-client", FLOBRAIN_OAUTH_GOOGLE_WORKSPACE_CLIENT_SECRET="test-secret-NOT-REAL")
class DriveApiTests(ImportsBase):
    def setUp(self):
        super().setUp()
        self.room = Room.objects.get(team=self.eng, kind=Room.KIND_TEAM)

    def connect(self, scopes):
        from integrations.write.models import WriteConnection

        conn = WriteConnection(org=self.org, provider="google_workspace", scopes=scopes, connected_by=self.u["admin"], secret_hint="1234")
        conn.set_secrets("tok-ACCESS-NOT-REAL-1234", "tok-REFRESH-NOT-REAL")
        conn.save()
        return conn

    def test_needs_drive_read_scope(self):
        self.connect(["https://www.googleapis.com/auth/drive.file"])
        self.auth("admin")
        res = self.client.get(f"{self.base}/drive/files")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"], "needs_scope")
        self.assertEqual(self.client.get(f"{self.base}/meta").json()["drive"]["status"], "needs_scope")

    def test_list_and_import_with_mocked_api(self):
        self.connect(["https://www.googleapis.com/auth/drive.readonly"])
        calls = []

        def fake(method, url, headers, max_bytes):
            calls.append(url)
            self.assertTrue(url.startswith("https://www.googleapis.com/drive/v3/files"))
            self.assertEqual(headers["Authorization"], "Bearer tok-ACCESS-NOT-REAL-1234")
            if "/export?" in url:
                return 200, b"# Q4 plan\n\nShip it."
            if "alt=media" in url:
                return 200, docx_bytes()
            if "/files/gdoc0000001?" in url:
                return 200, json.dumps({"id": "gdoc0000001", "name": "Q4 plan", "mimeType": "application/vnd.google-apps.document", "webViewLink": "https://docs.google.com/document/d/gdoc0000001/edit"}).encode()
            if "/files/docx0000002?" in url:
                return 200, json.dumps({"id": "docx0000002", "name": "Handbook.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "size": "3000"}).encode()
            if "/files/huge0000003?" in url:
                return 200, json.dumps({"id": "huge0000003", "name": "Huge.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "size": str(500 * 1024 * 1024)}).encode()
            return 200, json.dumps({"files": [
                {"id": "gdoc0000001", "name": "Q4 plan", "mimeType": "application/vnd.google-apps.document"},
                {"id": "sheet000004", "name": "Budget", "mimeType": "application/vnd.google-apps.spreadsheet"},
            ], "nextPageToken": ""}).encode()

        self.auth("admin")
        with patch("imports.drive._fetch", side_effect=fake):
            listing = self.client.get(f"{self.base}/drive/files", {"q": "plan' or 1=1"}).json()
            self.assertEqual([f["name"] for f in listing["files"]], ["Q4 plan"])
            self.assertIn("plan%5C%27+or+1%3D1", calls[0])  # the quote is escaped in the Drive query
            res = self.client.post(f"{self.base}/drive", {"room_id": str(self.room.id), "file_ids": ["gdoc0000001", "docx0000002", "huge0000003"]}, format="json").json()
        self.assertEqual(res["status"], "done", res)
        self.assertEqual(res["counts"]["documents"], 2)
        self.assertEqual(res["counts"]["files_too_big"], 1)
        q4 = Document.objects.get(title="Q4 plan")
        self.assertTrue(q4.content_text.startswith("Source: Google Drive · https://docs.google.com/document/d/gdoc0000001/edit"))
        self.assertIn("# Handbook", Document.objects.get(title="Handbook").content_text)

    def test_bad_file_ids(self):
        self.connect(["https://www.googleapis.com/auth/drive.readonly"])
        self.auth("admin")
        res = self.client.post(f"{self.base}/drive", {"room_id": str(self.room.id), "file_ids": ["../etc"]}, format="json")
        self.assertEqual(res.status_code, 400)


@override_settings(DEMO_MODE=True)
class DemoTests(ImportsBase):
    def test_demo_sample_import_and_undo_without_network(self):
        self.org.settings = {"flags": {"imports": True}, "demo": True}
        self.org.save()
        self.auth("admin")
        with patch("platform_api.net.fetch", side_effect=AssertionError("network")), patch("platform_api.net.fetch_full", side_effect=AssertionError("network")):
            run = self.client.post(f"{self.base}/sample", {"source": "slack"}, format="json").json()
            self.assertEqual(run["status"], "ready", run)
            self.assertTrue(run["is_demo"])
            done = self.start(run["id"], self.mapping()).json()
            self.assertEqual(done["counts"]["messages"], 150)
            self.client.post(f"{self.base}/{run['id']}/undo")
            self.assertEqual(RoomMessage.objects.filter(room__org=self.org).count(), 0)
            notion_run = self.client.post(f"{self.base}/sample", {"source": "notion"}, format="json").json()
            room = Room.objects.get(team=self.eng, kind=Room.KIND_TEAM)
            self.assertEqual(self.start(notion_run["id"], {"room_id": str(room.id)}).json()["counts"]["documents"], 4)


class DemoSeedTests(ImportsBase):
    def test_seed_leaves_a_finished_import_with_undo(self):
        import importlib

        from django.utils import timezone

        design = Team.objects.create(org=self.org, name="Design")
        TeamMembership.objects.create(team=design, user=self.u["member"])
        importlib.import_module("demo.extras.a6_imports").seed(self.org, {"admin": self.u["admin"]}, timezone.now())
        run = ImportRun.objects.get(org=self.org)
        self.assertEqual(run.status, ImportRun.DONE)
        self.assertEqual(run.counts["documents"], 4)
        self.assertTrue(services.run_payload(run)["can_undo"])
        self.assertEqual(Document.objects.filter(room__team=design).count(), 4)
