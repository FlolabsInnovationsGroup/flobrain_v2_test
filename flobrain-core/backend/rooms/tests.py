from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization, Project, ProjectMembership, Team, TeamMembership
from rooms.models import Room, RoomMember, RoomMessage
from rooms.services import ensure_project_room, ensure_team_room
from users.jwt_utils import make_access_token
from users.models import User


class RoomApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Room Org", slug="room-org")
        self.other_org = Organization.objects.create(name="Other Org", slug="other-org")
        self.owner = User.objects.create(email="r-owner@example.com", password_hash=make_password("x"))
        self.lead = User.objects.create(email="r-lead@example.com", password_hash=make_password("x"))
        self.member_a = User.objects.create(email="r-a@example.com", password_hash=make_password("x"))
        self.member_b = User.objects.create(email="r-b@example.com", password_hash=make_password("x"))
        self.inactive = User.objects.create(email="r-off@example.com", password_hash=make_password("x"))
        self.outsider = User.objects.create(email="r-out@example.com", password_hash=make_password("x"))
        for user, role, status in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER, OrgMembership.STATUS_ACTIVE),
            (self.lead, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.member_a, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.member_b, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.inactive, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_TERMINATED),
        ):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status=status)
        self.team_a = Team.objects.create(org=self.org, name="Alpha")
        self.team_b = Team.objects.create(org=self.org, name="Beta")
        TeamMembership.objects.create(team=self.team_a, user=self.lead, team_role=TeamMembership.ROLE_LEAD)
        TeamMembership.objects.create(team=self.team_a, user=self.member_a)
        TeamMembership.objects.create(team=self.team_b, user=self.member_b)
        self.room_a = ensure_team_room(self.team_a)
        self.room_b = ensure_team_room(self.team_b)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_member_posts_and_cannot_see_other_team_room(self):
        self._auth(self.member_a)
        posted = self.client.post(f"{self.base}/rooms/{self.room_a.id}/messages", {"body": "hello"}, format="json")
        self.assertEqual(posted.status_code, 201, posted.content)
        self.assertEqual(posted.json()["body"], "hello")
        empty = self.client.post(f"{self.base}/rooms/{self.room_a.id}/messages", {"body": "   "}, format="json")
        self.assertEqual(empty.status_code, 400)
        hidden = self.client.get(f"{self.base}/rooms/{self.room_b.id}")
        self.assertEqual(hidden.status_code, 404)
        hidden_msgs = self.client.get(f"{self.base}/rooms/{self.room_b.id}/messages")
        self.assertEqual(hidden_msgs.status_code, 404)
        listed = self.client.get(f"{self.base}/rooms")
        ids = {row["id"] for row in listed.json()}
        self.assertIn(str(self.room_a.id), ids)
        self.assertNotIn(str(self.room_b.id), ids)

    def test_translation_keeps_original(self):
        self._auth(self.member_a)
        posted = self.client.post(f"{self.base}/rooms/{self.room_a.id}/messages", {"body": "hello"}, format="json")
        translated = self.client.get(f"{self.base}/rooms/{self.room_a.id}/messages?translate_to=ar")
        self.assertEqual(translated.status_code, 501)
        listed = self.client.get(f"{self.base}/rooms/{self.room_a.id}/messages")
        self.assertEqual(listed.status_code, 200)
        row = listed.json()["results"][0]
        self.assertEqual(row["body"], "hello")
        self.assertFalse(row["translated"])
        stored = RoomMessage.objects.get(pk=posted.json()["id"])
        self.assertEqual(stored.body, "hello")

    def test_other_org_and_inactive_denied(self):
        self._auth(self.outsider)
        self.assertEqual(self.client.get(f"{self.base}/rooms").status_code, 403)
        self._auth(self.inactive)
        self.assertEqual(self.client.get(f"{self.base}/rooms").status_code, 403)
        self._auth(self.member_a)
        other = self.client.get(f"/api/v2/orgs/{self.other_org.id}/rooms")
        self.assertEqual(other.status_code, 403)

    def test_member_cannot_manage_rooms_or_pin(self):
        self._auth(self.member_a)
        created = self.client.post(f"{self.base}/rooms", {"name": "Secret"}, format="json")
        self.assertEqual(created.status_code, 403)
        pinned = self.client.post(
            f"{self.base}/announcements",
            {"room": str(self.room_a.id), "body": "All hands"},
            format="json",
        )
        self.assertEqual(pinned.status_code, 403)
        self._auth(self.owner)
        ok = self.client.post(
            f"{self.base}/announcements",
            {"room": str(self.room_a.id), "body": "All hands"},
            format="json",
        )
        self.assertEqual(ok.status_code, 201, ok.content)

    def test_inactive_cannot_receive_new_dm_room(self):
        self._auth(self.owner)
        denied = self.client.post(f"{self.base}/rooms", {"user_id": str(self.inactive.id)}, format="json")
        self.assertEqual(denied.status_code, 404)

    def test_project_room_syncs_membership(self):
        self._auth(self.owner)
        created = self.client.post(f"/api/v2/orgs/{self.org.id}/projects", {"name": "Workspace V2"}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        project = Project.objects.get(pk=created.json()["id"])
        ProjectMembership.objects.create(project=project, user=self.member_a)
        room = ensure_project_room(project)
        self.assertEqual(room.kind, Room.KIND_PROJECT)
        self.assertTrue(RoomMember.objects.filter(room=room, user=self.member_a).exists())
        self._auth(self.member_a)
        listed = self.client.get(f"{self.base}/rooms")
        ids = {row["id"] for row in listed.json()}
        self.assertIn(str(room.id), ids)
        self._auth(self.member_b)
        listed_b = self.client.get(f"{self.base}/rooms")
        self.assertNotIn(str(room.id), {row["id"] for row in listed_b.json()})

    def test_leaving_a_team_removes_room_access(self):
        RoomMessage.objects.create(room=self.room_a, author=self.lead, body="team secret")
        self._auth(self.member_a)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_a.id}/messages").status_code, 200)
        TeamMembership.objects.filter(team=self.team_a, user=self.member_a).delete()
        self.assertFalse(RoomMember.objects.filter(room=self.room_a, user=self.member_a).exists())
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_a.id}/messages").status_code, 404)
        self.assertTrue(RoomMember.objects.filter(room=self.room_a, user=self.lead).exists())

    def test_leaving_a_project_removes_project_room_access(self):
        project = Project.objects.create(org=self.org, name="Gamma")
        ProjectMembership.objects.create(project=project, user=self.member_b)
        room = ensure_project_room(project)
        self.assertTrue(RoomMember.objects.filter(room=room, user=self.member_b).exists())
        ProjectMembership.objects.filter(project=project, user=self.member_b).delete()
        self.assertFalse(RoomMember.objects.filter(room=room, user=self.member_b).exists())

    def test_project_access_through_a_team_ends_when_the_team_is_detached(self):
        project = Project.objects.create(org=self.org, name="Delta")
        project.teams.add(self.team_b)
        room = ensure_project_room(project)
        self.assertTrue(RoomMember.objects.filter(room=room, user=self.member_b).exists())
        project.teams.remove(self.team_b)
        self.assertFalse(RoomMember.objects.filter(room=room, user=self.member_b).exists())

    def test_deleting_a_team_does_not_fail(self):
        self.team_b.delete()
        self.assertFalse(TeamMembership.objects.filter(user=self.member_b).exists())

    def test_deleting_a_team_removes_its_members_from_project_rooms(self):
        project = Project.objects.create(org=self.org, name="Echo")
        project.teams.add(self.team_b)
        room = ensure_project_room(project)
        self.assertTrue(RoomMember.objects.filter(room=room, user=self.member_b).exists())
        self.team_b.delete()
        self.assertFalse(RoomMember.objects.filter(room=room, user=self.member_b).exists())
        self._auth(self.member_b)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{room.id}/messages").status_code, 404)

    def test_moving_a_membership_to_another_team_leaves_the_old_room(self):
        row = TeamMembership.objects.get(team=self.team_b, user=self.member_b)
        row.team = self.team_a
        row.save()
        self.assertFalse(RoomMember.objects.filter(room=self.room_b, user=self.member_b).exists())
        self.assertTrue(RoomMember.objects.filter(room=self.room_a, user=self.member_b).exists())

    def test_stale_room_member_row_grants_nothing(self):
        # A row left behind by a race or a missed signal: live team membership decides.
        TeamMembership.objects.filter(team=self.team_b, user=self.member_b).delete()
        RoomMember.objects.create(room=self.room_b, user=self.member_b)
        self._auth(self.member_b)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room_b.id}/messages").status_code, 404)
        listed = {row["id"] for row in self.client.get(f"{self.base}/rooms").json()}
        self.assertNotIn(str(self.room_b.id), listed)

    def test_owner_cannot_read_a_dm_they_are_not_in(self):
        from rooms.services import pair_key_for

        dm = Room.objects.create(
            org=self.org, name="dm", kind=Room.KIND_DIRECT, pair_key=pair_key_for(self.member_a, self.member_b)
        )
        RoomMember.objects.create(room=dm, user=self.member_a)
        RoomMember.objects.create(room=dm, user=self.member_b)
        RoomMessage.objects.create(room=dm, author=self.member_a, body="private between a and b")
        self._auth(self.owner)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{dm.id}/messages").status_code, 404)
        listed = {row["id"] for row in self.client.get(f"{self.base}/rooms").json()}
        self.assertNotIn(str(dm.id), listed)
        self.assertIn(str(self.room_b.id), listed, "owners still see team rooms")
        found = self.client.get(f"{self.base}/search?q=private").json()["results"]
        self.assertFalse([r for r in found if r["id"] == str(dm.id)])
        self._auth(self.member_a)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{dm.id}/messages").status_code, 200)

    def test_realtime_ticket_unavailable(self):
        self._auth(self.owner)
        res = self.client.post("/api/v2/realtime/ticket", {"org_id": str(self.org.id)}, format="json")
        self.assertEqual(res.status_code, 503)
        self.org.settings = {"flags": {"realtime": True}}
        self.org.save(update_fields=["settings"])
        unimplemented = self.client.post("/api/v2/realtime/ticket", {"org_id": str(self.org.id)}, format="json")
        self.assertEqual(unimplemented.status_code, 501)
