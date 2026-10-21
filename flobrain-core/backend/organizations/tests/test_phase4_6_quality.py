from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from docs_app.models import Document, StoredFile
from meetings.models import Meeting, Recording, Transcript
from organizations.models import OrgMembership, Organization, PermissionGrant, Team, TeamMembership
from organizations.permissions.engine import can
from organizations.permissions.registry import PHASE_4_TO_6_API_KEYS, ROLE_DEFAULTS
from rooms.models import Announcement, RoomMessage
from rooms.services import ensure_team_room
from users.jwt_utils import make_access_token
from users.models import User


def _user(email: str) -> User:
    return User.objects.create(email=email, password_hash=make_password("x"), username=email.split("@")[0])


class Phase46PermissionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="P46 Org", slug="p46-org")
        self.other_org = Organization.objects.create(name="P46 Other", slug="p46-other")
        self.owner = _user("p46-owner@example.com")
        self.member = _user("p46-member@example.com")
        self.other_member = _user("p46-other@example.com")
        self.inactive = _user("p46-off@example.com")
        self.outsider = _user("p46-out@example.com")
        OrgMembership.objects.create(
            org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org, user=self.member, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org,
            user=self.other_member,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )
        OrgMembership.objects.create(
            org=self.org,
            user=self.inactive,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_TERMINATED,
        )
        self.team_a = Team.objects.create(org=self.org, name="Alpha")
        self.team_b = Team.objects.create(org=self.org, name="Beta")
        TeamMembership.objects.create(team=self.team_a, user=self.member)
        TeamMembership.objects.create(team=self.team_b, user=self.other_member)
        self.room_a = ensure_team_room(self.team_a)
        self.room_b = ensure_team_room(self.team_b)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _probe(self, key, as_user):
        self._auth(as_user)
        if key == "room.view":
            return self.client.get(f"{self.base}/rooms")
        if key == "room.manage":
            return self.client.post(f"{self.base}/rooms", {"name": f"Room-{as_user.id}"}, format="json")
        if key == "announcement.manage":
            return self.client.post(
                f"{self.base}/announcements",
                {"room": str(self.room_a.id), "body": "All hands"},
                format="json",
            )
        if key == "notification.view":
            return self.client.get(f"{self.base}/notifications")
        if key == "meeting.view":
            return self.client.get(f"{self.base}/rooms/{self.room_a.id}/meetings")
        if key == "meeting.manage":
            return self.client.post(
                f"{self.base}/rooms/{self.room_a.id}/meetings",
                {"title": "Standup"},
                format="json",
            )
        if key == "docs.view":
            return self.client.get(f"{self.base}/rooms/{self.room_a.id}/docs")
        if key == "docs.write":
            return self.client.post(
                f"{self.base}/rooms/{self.room_a.id}/docs",
                {"title": "Note", "content_text": "hello"},
                format="json",
            )
        if key == "tools.manage":
            return self.client.post(
                f"{self.base}/tools",
                {"name": "Linear", "url": "https://linear.app"},
                format="json",
            )
        if key == "search.use":
            return self.client.get(f"{self.base}/search", {"q": "hello"})
        raise AssertionError(f"no probe for {key}")

    def test_every_phase_4_to_6_key_allowed_and_denied(self):
        member_defaults = ROLE_DEFAULTS[OrgMembership.ORG_ROLE_MEMBER]
        for key in PHASE_4_TO_6_API_KEYS:
            self.assertIn(key, ROLE_DEFAULTS[OrgMembership.ORG_ROLE_OWNER])
            allowed_user = self.member if key in member_defaults else self.owner
            allowed = self._probe(key, allowed_user)
            self.assertIn(
                allowed.status_code,
                {200, 201, 204},
                msg=f"{key} allowed {allowed.status_code} {allowed.content}",
            )
            denied = self._probe(key, self.outsider)
            self.assertIn(denied.status_code, {401, 403}, msg=f"{key} outsider {denied.status_code}")
            if key not in member_defaults:
                member_denied = self._probe(key, self.member)
                self.assertEqual(member_denied.status_code, 403, msg=f"{key} member should be 403")

    def test_can_matches_role_defaults_for_every_key(self):
        for key in PHASE_4_TO_6_API_KEYS:
            self.assertTrue(can(self.owner, key, self.org))
            self.assertEqual(can(self.member, key, self.org), key in ROLE_DEFAULTS[OrgMembership.ORG_ROLE_MEMBER])
            self.assertFalse(can(self.outsider, key, self.org))
            self.assertFalse(can(self.inactive, key, self.org))

    def test_isolation_other_team_other_org_inactive(self):
        self._auth(self.member)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_b.id}").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_b.id}/messages").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_b.id}/meetings").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_b.id}/docs").status_code, 404)
        listed = self.client.get(f"{self.base}/rooms")
        ids = {row["id"] for row in listed.json()}
        self.assertIn(str(self.room_a.id), ids)
        self.assertNotIn(str(self.room_b.id), ids)
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.other_org.id}/rooms").status_code, 403)
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.other_org.id}/search?q=x").status_code, 403)
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.other_org.id}/tools").status_code, 403)
        self._auth(self.inactive)
        self.assertEqual(self.client.get(f"{self.base}/rooms").status_code, 403)
        self.assertEqual(self.client.get(f"{self.base}/notifications").status_code, 403)
        self.assertEqual(self.client.get(f"{self.base}/search?q=x").status_code, 403)

    def test_search_hides_other_team_content(self):
        RoomMessage.objects.create(room=self.room_b, author=self.other_member, body="secret beta launch")
        Document.objects.create(
            org=self.org,
            room=self.room_b,
            title="Beta plan",
            content_text="secret beta launch",
            created_by=self.other_member,
        )
        self._auth(self.member)
        res = self.client.get(f"{self.base}/search", {"q": "secret beta"})
        self.assertEqual(res.status_code, 200)
        titles = {row["title"] for row in res.json()["results"]}
        self.assertNotIn("Beta", titles)
        self.assertNotIn("Beta plan", titles)
        self.assertFalse(any(row["id"] == str(self.room_b.id) for row in res.json()["results"]))

    def test_announcements_isolated_and_denied(self):
        self._auth(self.owner)
        pin_a = self.client.post(
            f"{self.base}/announcements",
            {"room": str(self.room_a.id), "body": "Alpha pin"},
            format="json",
        )
        self.assertEqual(pin_a.status_code, 201, pin_a.content)
        pin_b = self.client.post(
            f"{self.base}/announcements",
            {"room": str(self.room_b.id), "body": "Beta pin"},
            format="json",
        )
        self.assertEqual(pin_b.status_code, 201, pin_b.content)
        self._auth(self.member)
        listed = self.client.get(f"{self.base}/announcements")
        self.assertEqual(listed.status_code, 200)
        bodies = {row["body"] for row in listed.json()}
        self.assertIn("Alpha pin", bodies)
        self.assertNotIn("Beta pin", bodies)
        PermissionGrant.objects.create(
            org=self.org,
            grantee=self.other_member,
            perm_key="announcement.manage",
            scope_type=PermissionGrant.SCOPE_ORG,
            granted_by=self.owner,
        )
        self._auth(self.other_member)
        foreign_pin = self.client.post(
            f"{self.base}/announcements",
            {"room": str(self.room_a.id), "body": "Should not land"},
            format="json",
        )
        self.assertEqual(foreign_pin.status_code, 404)
        foreign_unpin = self.client.post(f"{self.base}/announcements/{pin_a.json()['id']}/unpin", {}, format="json")
        self.assertEqual(foreign_unpin.status_code, 404)
        self._auth(self.inactive)
        self.assertEqual(self.client.get(f"{self.base}/announcements").status_code, 403)
        self._auth(self.member)
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.other_org.id}/announcements").status_code, 403)

    def test_recordings_and_transcripts_isolated(self):
        meeting = Meeting.objects.create(org=self.org, room=self.room_a, title="Standup", created_by=self.owner)
        recording = Recording.objects.create(org=self.org, meeting=meeting, play_url="https://files.local/r.mp4")
        self._auth(self.member)
        listed = self.client.get(f"{self.base}/rooms/{self.room_a.id}/recordings")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["results"][0]["id"], str(recording.id))
        self._auth(self.other_member)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_a.id}/recordings").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/recordings/{recording.id}/transcript").status_code, 404)
        PermissionGrant.objects.create(
            org=self.org,
            grantee=self.other_member,
            perm_key="meeting.manage",
            scope_type=PermissionGrant.SCOPE_ORG,
            granted_by=self.owner,
        )
        self.assertEqual(self.client.post(f"{self.base}/recordings/{recording.id}/transcribe", {}, format="json").status_code, 404)
        self.assertEqual(self.client.post(f"{self.base}/meetings/{meeting.id}/summarize", {}, format="json").status_code, 404)
        self._auth(self.inactive)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_a.id}/recordings").status_code, 403)
        self._auth(self.member)
        self.assertEqual(
            self.client.get(f"/api/v2/orgs/{self.other_org.id}/rooms/{self.room_a.id}/recordings").status_code,
            403,
        )
        Transcript.objects.create(recording=recording, text="Agreed next steps", segments=[])
        self._auth(self.owner)
        self.assertEqual(
            self.client.post(f"{self.base}/recordings/{recording.id}/transcribe", {}, format="json").status_code,
            501,
        )
        own = self.client.get(f"{self.base}/recordings/{recording.id}/transcript")
        self.assertEqual(own.status_code, 200)
        self.assertNotIn("stub", own.json()["text"].lower())
        self._auth(self.other_member)
        self.assertEqual(self.client.get(f"{self.base}/recordings/{recording.id}/transcript").status_code, 404)

    def test_files_complete_denied_outside_creator_and_org(self):
        self._auth(self.member)
        presign = self.client.post(
            f"{self.base}/files/presign",
            {"name": "notes.txt", "content_type": "text/plain", "room": str(self.room_a.id)},
            format="json",
        )
        self.assertEqual(presign.status_code, 201, presign.content)
        file_id = presign.json()["id"]
        self._auth(self.other_member)
        denied = self.client.post(f"{self.base}/files/{file_id}/complete", {}, format="json")
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(StoredFile.objects.get(pk=file_id).status, StoredFile.STATUS_PENDING)
        self._auth(self.member)
        self.assertEqual(
            self.client.post(
                f"/api/v2/orgs/{self.other_org.id}/files/presign",
                {"name": "notes.txt", "room": str(self.room_a.id)},
                format="json",
            ).status_code,
            403,
        )
        bad_name = self.client.post(
            f"{self.base}/files/presign",
            {"name": "../secret.txt", "room": str(self.room_a.id)},
            format="json",
        )
        self.assertEqual(bad_name.status_code, 400)
        self._auth(self.other_member)
        foreign_room = self.client.post(
            f"{self.base}/files/presign",
            {"name": "notes.txt", "room": str(self.room_a.id)},
            format="json",
        )
        self.assertEqual(foreign_room.status_code, 404)

    def test_docs_inactive_and_messages_other_org_denied(self):
        self._auth(self.inactive)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_a.id}/docs").status_code, 403)
        self._auth(self.member)
        self.assertEqual(
            self.client.get(f"/api/v2/orgs/{self.other_org.id}/rooms/{self.room_a.id}/messages").status_code,
            403,
        )

    def test_room_members_and_message_edit_denied(self):
        self._auth(self.member)
        members = self.client.get(f"{self.base}/rooms/{self.room_a.id}/members")
        self.assertEqual(members.status_code, 200)
        self.assertTrue(any(row["user_id"] == str(self.member.id) for row in members.json()))
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_b.id}/members").status_code, 404)
        posted = self.client.post(f"{self.base}/rooms/{self.room_a.id}/messages", {"body": "hello"}, format="json")
        self.assertEqual(posted.status_code, 201, posted.content)
        message_id = posted.json()["id"]
        edited = self.client.patch(
            f"{self.base}/rooms/{self.room_a.id}/messages/{message_id}",
            {"body": "hello edited"},
            format="json",
        )
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["body"], "hello edited")
        self._auth(self.owner)
        owner_denied = self.client.patch(
            f"{self.base}/rooms/{self.room_a.id}/messages/{message_id}",
            {"body": "owner rewrite"},
            format="json",
        )
        self.assertEqual(owner_denied.status_code, 403)
        self._auth(self.other_member)
        self.assertEqual(
            self.client.patch(
                f"{self.base}/rooms/{self.room_b.id}/messages/{message_id}",
                {"body": "nope"},
                format="json",
            ).status_code,
            404,
        )
        self._auth(self.member)
        deleted = self.client.delete(f"{self.base}/rooms/{self.room_a.id}/messages/{message_id}")
        self.assertEqual(deleted.status_code, 204)

    def test_tool_non_http_url_and_realtime_outsider_denied(self):
        self._auth(self.owner)
        ftp = self.client.post(
            f"{self.base}/tools",
            {"name": "Ftp", "url": "ftp://files.example"},
            format="json",
        )
        self.assertEqual(ftp.status_code, 400)
        self.org.settings = {"flags": {"realtime": True}}
        self.org.save(update_fields=["settings"])
        self._auth(self.outsider)
        ticket = self.client.post("/api/v2/realtime/ticket", {"org_id": str(self.org.id)}, format="json")
        self.assertEqual(ticket.status_code, 403)

    def test_me_omits_secrets(self):
        self._auth(self.member)
        res = self.client.get("/api/v2/me")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        for key in ("password", "password_hash", "secret", "token", "refresh"):
            self.assertNotIn(key, body)
