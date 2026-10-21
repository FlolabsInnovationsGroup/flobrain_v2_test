from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from meetings.models import Meeting, MeetingSummary, Recording
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.services import ensure_team_room
from users.jwt_utils import make_access_token
from users.models import User


class MeetingApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Meet Org", slug="meet-org")
        self.other_org = Organization.objects.create(name="Meet Other", slug="meet-other")
        self.owner = User.objects.create(email="m-owner@example.com", password_hash=make_password("x"))
        self.member_a = User.objects.create(email="m-a@example.com", password_hash=make_password("x"))
        self.member_b = User.objects.create(email="m-b@example.com", password_hash=make_password("x"))
        self.inactive = User.objects.create(email="m-off@example.com", password_hash=make_password("x"))
        for user, role, status in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER, OrgMembership.STATUS_ACTIVE),
            (self.member_a, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.member_b, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.inactive, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_TERMINATED),
        ):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status=status)
        self.team_a = Team.objects.create(org=self.org, name="A")
        self.team_b = Team.objects.create(org=self.org, name="B")
        TeamMembership.objects.create(team=self.team_a, user=self.member_a)
        TeamMembership.objects.create(team=self.team_b, user=self.member_b)
        self.room_a = ensure_team_room(self.team_a)
        self.room_b = ensure_team_room(self.team_b)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_owner_creates_and_member_isolated(self):
        self._auth(self.owner)
        created = self.client.post(f"{self.base}/rooms/{self.room_a.id}/meetings", {"title": "Standup"}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertIn(created.json()["join_url"], (None, ""))
        meeting_id = created.json()["id"]
        self._auth(self.member_b)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_a.id}/meetings").status_code, 404)
        self._auth(self.member_a)
        listed = self.client.get(f"{self.base}/rooms/{self.room_a.id}/meetings")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["id"], meeting_id)
        self._auth(self.inactive)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_a.id}/meetings").status_code, 403)

    def test_member_cannot_manage_and_confirm_required(self):
        self._auth(self.member_a)
        denied = self.client.post(f"{self.base}/rooms/{self.room_a.id}/meetings", {"title": "Nope"}, format="json")
        self.assertEqual(denied.status_code, 403)
        meeting = Meeting.objects.create(org=self.org, room=self.room_a, title="Done", created_by=self.owner)
        recording = Recording.objects.create(org=self.org, meeting=meeting, play_url="https://files.local/r.mp4")
        self._auth(self.owner)
        self.assertEqual(
            self.client.post(f"{self.base}/recordings/{recording.id}/transcribe", {}, format="json").status_code,
            501,
        )
        self.assertEqual(
            self.client.post(f"{self.base}/meetings/{meeting.id}/summarize", {}, format="json").status_code,
            501,
        )
        MeetingSummary.objects.create(
            meeting=meeting,
            text="Agreed next steps",
            action_items=[{"id": "a1", "title": "Follow up", "done": False}],
        )
        summary = self.client.get(f"{self.base}/meetings/{meeting.id}/summary")
        self.assertEqual(summary.status_code, 200)
        self.assertNotIn("stub", summary.json()["text"].lower())
        no_confirm = self.client.post(
            f"{self.base}/meetings/{meeting.id}/action-items/a1/to-task",
            {},
            format="json",
        )
        self.assertEqual(no_confirm.status_code, 400)
        ok = self.client.post(
            f"{self.base}/meetings/{meeting.id}/action-items/a1/to-task",
            {"confirm": True},
            format="json",
        )
        self.assertEqual(ok.status_code, 201, ok.content)

    def test_voice_video_defaults_off_and_join_url_stays_empty(self):
        self.assertFalse(self.org.settings.get("flags", {}).get("voice_video", False))
        self._auth(self.owner)
        created = self.client.post(
            f"{self.base}/rooms/{self.room_a.id}/meetings",
            {"title": "No call"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertIn(created.json()["join_url"], (None, ""))
        self.org.settings = {"flags": {"voice_video": True}}
        self.org.save(update_fields=["settings"])
        flagged = self.client.post(
            f"{self.base}/rooms/{self.room_a.id}/meetings",
            {"title": "Flag on"},
            format="json",
        )
        self.assertEqual(flagged.status_code, 201, flagged.content)
        self.assertIn(flagged.json()["join_url"], (None, ""))

    def test_other_org_denied(self):
        self._auth(self.member_a)
        res = self.client.get(f"/api/v2/orgs/{self.other_org.id}/rooms/{self.room_a.id}/meetings")
        self.assertIn(res.status_code, {403, 404})
