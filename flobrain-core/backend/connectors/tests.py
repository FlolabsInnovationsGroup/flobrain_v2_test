import json
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from connectors.models import Connection, ExternalItem
from jobs.models import Job
from meetings.models import Meeting, MeetingBotSession
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.models import Room, RoomMember, RoomMessage
from rooms.services import ensure_team_room
from tasks.models import Task
from users.jwt_utils import make_access_token
from users.models import User

KEY = "cd" * 32
ISSUES = [
    {"number": 7, "title": "Fix login", "html_url": "https://github.com/acme/app/issues/7", "state": "open"},
    {"number": 8, "title": "Add CI", "html_url": "https://github.com/acme/app/pull/8", "state": "closed", "pull_request": {"merged_at": "2026-10-01T00:00:00Z"}},
    {"number": 9, "title": "Bad link", "html_url": "javascript:alert(1)", "state": "open"},
]


def fake_github(method, url, body=b"", headers=None, timeout=10, max_bytes=4096):
    assert headers["Authorization"] == "Bearer ghp_test"
    if url.endswith("/repos/acme/app"):
        return 200, json.dumps({"full_name": "acme/app"}).encode()
    if "/issues" in url:
        return 200, json.dumps(ISSUES).encode()
    return 404, b""


@override_settings(CREDENTIALS_ENCRYPTION_KEY=KEY)
class ConnectorTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="I", slug="i-org", settings={"flags": {"integrations": True, "meeting_bot": True}})
        self.users = {}
        for name, role in (("admin", "admin"), ("eng", "member"), ("other", "member")):
            u = User.objects.create(email=f"{name}@i.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            self.users[name] = u
        self.team = Team.objects.create(org=self.org, name="Eng")
        for name in ("admin", "eng"):
            TeamMembership.objects.create(team=self.team, user=self.users[name], team_role="lead" if name == "eng" else "member")
        self.room = ensure_team_room(self.team)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _as(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return c

    def _connect(self):
        with patch("platform_api.net.fetch", side_effect=fake_github):
            return self._as("admin").post(
                f"{self.base}/integrations/github/connect", {"room": str(self.room.id), "token": "ghp_test", "config": {"repo": "acme/app"}}, format="json"
            )

    def test_connect_sync_visibility_and_disconnect(self):
        self.assertEqual(self._as("eng").post(f"{self.base}/integrations/github/connect", {}, format="json").status_code, 403)
        made = self._connect()
        self.assertEqual(made.status_code, 201, made.content)
        self.assertNotIn("ghp_test", json.dumps(made.json()))
        self.assertEqual(ExternalItem.objects.count(), 3)
        self.assertEqual(ExternalItem.objects.get(external_id="9").url, "", "only github.com links are kept")
        self.assertEqual(ExternalItem.objects.get(external_id="8").state, "merged")
        self.assertEqual(len(self._as("eng").get(f"{self.base}/integrations/items").json()), 3)
        self.assertEqual(self._as("other").get(f"{self.base}/integrations/items").json(), [], "not in the room: sees nothing")
        task = Task.objects.create(org=self.org, team=self.team, title="Login")
        item = ExternalItem.objects.get(external_id="7")
        self.assertEqual(self._as("eng").post(f"{self.base}/tasks/{task.id}/links", {"item": str(item.id)}, format="json").status_code, 201)
        self.assertEqual(self._as("other").post(f"{self.base}/tasks/{task.id}/links", {"item": str(item.id)}, format="json").status_code, 404)
        conn = Connection.objects.get()
        Job.objects.create(kind="connectors.sync", payload={"connection_id": str(conn.id)})
        self.assertEqual(self._as("admin").delete(f"{self.base}/integrations/connections/{conn.id}").status_code, 204)
        conn.refresh_from_db()
        self.assertEqual((conn.status, conn.secret_ciphertext), ("revoked", None))
        self.assertEqual(Job.objects.get().status, "failed")
        self.assertEqual(self._as("eng").get(f"{self.base}/integrations/items").json(), [], "a disconnected source shows nothing")
        self.assertEqual(self._as("eng").get(f"{self.base}/tasks/{task.id}/links").json(), [])

    def test_bad_input_and_unconfigured_connectors(self):
        admin = self._as("admin")
        with patch("platform_api.net.fetch", side_effect=fake_github):
            bad = admin.post(f"{self.base}/integrations/github/connect", {"room": str(self.room.id), "token": "ghp_test", "config": {"repo": "../../etc"}}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(admin.post(f"{self.base}/integrations/google_calendar/connect", {}, format="json").status_code, 501)
        dm = Room.objects.create(org=self.org, name="dm", kind=Room.KIND_DIRECT, pair_key="x")
        RoomMember.objects.create(room=dm, user=self.users["eng"])
        with patch("platform_api.net.fetch", side_effect=fake_github):
            hidden = admin.post(f"{self.base}/integrations/github/connect", {"room": str(dm.id), "token": "ghp_test", "config": {"repo": "acme/app"}}, format="json")
        self.assertEqual(hidden.status_code, 400, "only rooms the admin can open")

    def test_meeting_bot_rules(self):
        meeting = Meeting.objects.create(org=self.org, room=self.room, title="Sync")
        url = f"{self.base}/rooms/{self.room.id}/meetings/{meeting.id}/bot"
        body = {"platform": "meet", "meeting_url": "https://meet.google.com/abc-defg-hij", "host_consent": True}
        self.assertEqual(self._as("other").post(url, body, format="json").status_code, 404)
        self.assertEqual(self._as("eng").post(url, body, format="json").status_code, 403, "needs meeting.manage")
        self.assertEqual(self._as("admin").post(url, {**body, "host_consent": False}, format="json").status_code, 400)
        self.assertEqual(self._as("admin").post(url, {**body, "meeting_url": "https://evil.example/x"}, format="json").status_code, 400)
        self.assertEqual(self._as("admin").post(url, body, format="json").status_code, 501, "no vendor adapter yet")
        from meetings import bot

        with patch.dict(bot.VENDORS, {"recall": object()}), override_settings(MEETING_BOT_VENDOR="recall", MEETING_BOT_API_KEY="k"):
            made = self._as("admin").post(url, body, format="json")
        self.assertEqual(made.status_code, 201)
        self.assertIsNotNone(MeetingBotSession.objects.get().recording_notice_sent_at)
        self.assertTrue(RoomMessage.objects.filter(room=self.room, body__startswith="Recording notice").exists())
        self.assertFalse(bot.proactive_allowed(["admin@i.test", "guest@else.test"], self.org))
        self.assertTrue(bot.proactive_allowed(["admin@i.test", "eng@i.test"], self.org))


DB = "0123456789abcdef0123456789abcdef"
DB_DASHED = "01234567-89ab-cdef-0123-456789abcdef"
NOTION_TOKEN = "ntn_" + "a" * 40


def _page(pid, title, team=None, status="Published", url=None, archived=False):
    props = {"Name": {"type": "title", "title": [{"plain_text": title}]}, "Status": {"type": "status", "status": {"name": status}}}
    if team is not None:
        props["Team"] = {"type": "multi_select", "multi_select": [{"name": t} for t in team]}
    return {"object": "page", "id": pid, "url": url or f"https://www.notion.so/{pid}", "archived": archived, "last_edited_time": "2026-10-01T10:00:00.000Z", "properties": props}


class FakeNotion:
    def __init__(self, pages, pages2=None):
        self.pages, self.pages2, self.calls = pages, pages2, []

    def __call__(self, method, url, body=b"", headers=None, timeout=10, max_bytes=4096):
        self.calls.append((method, url))
        assert headers["Authorization"] == f"Bearer {NOTION_TOKEN}"
        assert headers["Notion-Version"]
        if url.endswith(f"/databases/{DB_DASHED}") and method == "GET":
            return 200, json.dumps({"object": "database", "title": [{"plain_text": "Masterclasses"}], "properties": {
                "Name": {"type": "title"}, "Team": {"type": "multi_select"}, "Status": {"type": "status"}, "Notes": {"type": "rich_text"}}}).encode()
        if url.endswith(f"/databases/{DB_DASHED}/query"):
            sent = json.loads(body.decode())
            if self.pages2 is not None and not sent.get("start_cursor"):
                return 200, json.dumps({"results": self.pages, "has_more": True, "next_cursor": "c2"}).encode()
            return 200, json.dumps({"results": self.pages2 if sent.get("start_cursor") else self.pages, "has_more": False}).encode()
        return 404, b""


@override_settings(CREDENTIALS_ENCRYPTION_KEY=KEY)
class NotionConnectorTests(TestCase):
    setUp = ConnectorTests.setUp
    _as = ConnectorTests._as

    def _connect(self, fake, config=None):
        with patch("platform_api.net.fetch", side_effect=fake):
            return self._as("admin").post(
                f"{self.base}/integrations/notion/connect",
                {"room": str(self.room.id), "token": NOTION_TOKEN, "config": config or {"database_id": f"https://www.notion.so/acme/Masterclasses-{DB}?v={'f' * 32}", "audience_property": "Team"}},
                format="json",
            )

    def test_catalog_lists_notion_as_a_token_connector(self):
        notion = next(c for c in self._as("eng").get(f"{self.base}/integrations").json()["connectors"] if c["key"] == "notion")
        self.assertEqual((notion["auth"], notion["available"]), ("token", True))
        self.assertTrue(any(f.get("optional") for f in notion["config_fields"]))

    def test_connect_sync_prune_and_secret_stays_encrypted(self):
        fake = FakeNotion([_page("p1", "Git basics", ["Eng"]), _page("p2", "Old", []), _page("p3", "Gone", [], archived=True), _page("p4", "Evil", [], url="javascript:alert(1)")])
        made = self._connect(fake)
        self.assertEqual(made.status_code, 201, made.content)
        self.assertNotIn(NOTION_TOKEN, json.dumps(made.json()))
        conn = Connection.objects.get(connector="notion")
        self.assertNotIn(NOTION_TOKEN.encode(), bytes(conn.secret_ciphertext))
        self.assertEqual(conn.config["database_id"], DB_DASHED, "the ?v= view id is ignored")
        self.assertEqual((conn.config["audience_property"], conn.config["status_property"], conn.config["database_title"]), ("Team", "Status", "Masterclasses"))
        items = {i.external_id: i for i in ExternalItem.objects.filter(connection=conn)}
        self.assertEqual(set(items), {"p1", "p2", "p4"}, "archived pages are skipped")
        self.assertEqual((items["p1"].kind, items["p1"].state, items["p1"].meta), ("masterclass", "Published", {"audience": ["eng"]}))
        self.assertIsNotNone(items["p1"].external_updated_at)
        self.assertEqual(items["p4"].url, "", "only Notion links are kept")
        fake.pages = [_page("p1", "Git basics v2", ["Eng"])]
        with patch("platform_api.net.fetch", side_effect=fake):
            self.assertEqual(self._as("admin").post(f"{self.base}/integrations/connections/{conn.id}/sync").status_code, 200)
        self.assertEqual(list(ExternalItem.objects.filter(connection=conn).values_list("title", flat=True)), ["Git basics v2"], "deleted pages are pruned")

    def test_pagination(self):
        fake = FakeNotion([_page("p1", "One")], pages2=[_page("p2", "Two")])
        self.assertEqual(self._connect(fake).status_code, 201)
        self.assertEqual(ExternalItem.objects.filter(connection__connector="notion").count(), 2)

    def test_bad_input_is_400_and_members_cannot_connect(self):
        fake = FakeNotion([])
        self.assertEqual(self._connect(fake, {"database_id": "nope"}).status_code, 400)
        self.assertEqual(self._connect(fake, {"database_id": DB, "audience_property": "Missing"}).status_code, 400)
        self.assertEqual(self._connect(fake, {"database_id": DB, "audience_property": "Notes"}).status_code, 400, "rich text can't name an audience")
        with patch("platform_api.net.fetch", side_effect=fake):
            bad_token = self._as("admin").post(f"{self.base}/integrations/notion/connect", {"room": str(self.room.id), "token": "hello", "config": {"database_id": DB}}, format="json")
            self.assertEqual(bad_token.status_code, 400)
            self.assertEqual(self._as("eng").post(f"{self.base}/integrations/notion/connect", {"room": str(self.room.id), "token": NOTION_TOKEN, "config": {"database_id": DB}}, format="json").status_code, 403)
        refused = lambda *a, **k: (401, b"{}")  # noqa: E731
        with patch("platform_api.net.fetch", side_effect=refused):
            res = self._as("admin").post(f"{self.base}/integrations/notion/connect", {"room": str(self.room.id), "token": NOTION_TOKEN, "config": {"database_id": DB}}, format="json")
        self.assertEqual((res.status_code, res.json()["error"]), (400, "invalid_credential"))
        self.assertFalse(Connection.objects.filter(connector="notion").exists())

    def test_sync_errors_are_recorded(self):
        self.assertEqual(self._connect(FakeNotion([_page("p1", "One")])).status_code, 201)
        conn = Connection.objects.get(connector="notion")
        with patch("platform_api.net.fetch", side_effect=lambda *a, **k: (429, b"")):
            self._as("admin").post(f"{self.base}/integrations/connections/{conn.id}/sync")
        conn.refresh_from_db()
        self.assertEqual(conn.last_error, "rate_limited")
        self.assertEqual(ExternalItem.objects.filter(connection=conn).count(), 1, "a failed sync keeps the old items")

    @override_settings(DEMO_MODE=True)
    def test_demo_mode_never_calls_the_network(self):
        with patch("platform_api.net.fetch", side_effect=AssertionError("network in demo")):
            made = self._as("admin").post(
                f"{self.base}/integrations/notion/connect", {"room": str(self.room.id), "token": "", "config": {"database_id": DB, "audience_property": "Team"}}, format="json"
            )
            self.assertEqual(made.status_code, 201, made.content)
            self.assertTrue(made.json()["demo"])
            self.assertIn("(demo)", made.json()["label"])
            conn = Connection.objects.get(connector="notion")
            self.assertIsNone(conn.secret_ciphertext)
            self.assertGreater(ExternalItem.objects.filter(connection=conn, kind="masterclass").count(), 3)
            gh = self._as("admin").post(f"{self.base}/integrations/github/connect", {"room": str(self.room.id), "config": {"repo": "acme/app"}}, format="json")
            self.assertEqual(gh.status_code, 201)
            gh_conn = Connection.objects.get(pk=gh.json()["id"])
            self.assertEqual(ExternalItem.objects.filter(connection=gh_conn).count(), 4)
            synced = self._as("admin").post(f"{self.base}/integrations/connections/{gh_conn.id}/sync")
            self.assertEqual((synced.status_code, synced.json()["last_error"]), (200, ""))
            real = Connection.objects.create(org=self.org, connector="github", room=self.room, config={"repo": "acme/app"}, secret_ciphertext=b"x")
            self._as("admin").post(f"{self.base}/integrations/connections/{real.id}/sync")
            real.refresh_from_db()
            self.assertIn("Demo mode", real.last_error)

    def test_demo_connection_does_nothing_outside_demo_mode(self):
        conn = Connection.objects.create(org=self.org, connector="github", room=self.room, config={"repo": "acme/app", "demo": True})
        with patch("platform_api.net.fetch", side_effect=AssertionError("network")):
            self._as("admin").post(f"{self.base}/integrations/connections/{conn.id}/sync")
        conn.refresh_from_db()
        self.assertFalse(ExternalItem.objects.filter(connection=conn).exists())
        self.assertIn("Demo connection", conn.last_error)
