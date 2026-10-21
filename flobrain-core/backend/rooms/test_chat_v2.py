"""Room chat polish (2026-10-21): names, edit/delete, notifications, group rooms, members, announcements."""

from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from notifications.models import Notification
from organizations.models import AuditEvent, OrgMembership, Organization, Team, TeamMembership
from rooms.models import Announcement, Room, RoomMember, RoomMessage
from rooms.services import ensure_team_room, mentioned_users, pair_key_for
from users.jwt_utils import make_access_token
from users.models import User


def _user(email, name):
    return User.objects.create(email=email, username=name, password_hash=make_password("x"))


class RoomChatBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Chat Org", slug="chat-org")
        self.other_org = Organization.objects.create(name="Other Chat", slug="other-chat")
        self.owner = _user("c-owner@example.com", "Nadia Owner")
        self.layla = _user("c-layla@example.com", "Layla Mansour")
        self.youssef = _user("c-youssef@example.com", "Youssef Adel")
        self.sara = _user("c-sara@example.com", "Sara Nabil")
        self.gone = _user("c-gone@example.com", "Gone Person")
        self.foreign = _user("c-foreign@example.com", "Far Away")
        for user, role, status in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER, OrgMembership.STATUS_ACTIVE),
            (self.layla, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.youssef, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.sara, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.gone, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_TERMINATED),
        ):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status=status)
        OrgMembership.objects.create(org=self.other_org, user=self.foreign, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status="active")
        self.eng = Team.objects.create(org=self.org, name="Engineering")
        self.design = Team.objects.create(org=self.org, name="Design")
        TeamMembership.objects.create(team=self.eng, user=self.layla, team_role=TeamMembership.ROLE_LEAD)
        TeamMembership.objects.create(team=self.eng, user=self.youssef)
        TeamMembership.objects.create(team=self.eng, user=self.gone)
        TeamMembership.objects.create(team=self.design, user=self.sara)
        self.room = ensure_team_room(self.eng)
        self.design_room = ensure_team_room(self.design)
        self.dm = Room.objects.create(org=self.org, name="dm", kind=Room.KIND_DIRECT, pair_key=pair_key_for(self.layla, self.youssef))
        RoomMember.objects.create(room=self.dm, user=self.layla)
        RoomMember.objects.create(room=self.dm, user=self.youssef)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _post(self, room, body, user):
        self._auth(user)
        return self.client.post(f"{self.base}/rooms/{room.id}/messages", {"body": body}, format="json")


class MessageTests(RoomChatBase):
    def test_messages_carry_sender_name_and_time_not_email(self):
        posted = self._post(self.room, "hello", self.layla)
        self.assertEqual(posted.status_code, 201, posted.content)
        row = self.client.get(f"{self.base}/rooms/{self.room.id}/messages").json()["results"][0]
        self.assertEqual(row["author_name"], "Layla Mansour")
        self.assertEqual(row["author"], str(self.layla.id))
        self.assertIsNone(row["edited_at"])
        self.assertTrue(row["created_at"])
        self.assertNotIn("c-layla@example.com", str(row))

    def test_author_edits_and_deletes_with_audit_and_no_text_in_the_log(self):
        msg_id = self._post(self.room, "first draft", self.layla).json()["id"]
        url = f"{self.base}/rooms/{self.room.id}/messages/{msg_id}"
        edited = self.client.patch(url, {"body": "second draft"}, format="json")
        self.assertEqual(edited.status_code, 200, edited.content)
        self.assertEqual(edited.json()["body"], "second draft")
        self.assertIsNotNone(edited.json()["edited_at"])
        event = AuditEvent.objects.get(org=self.org, action="room.message.edit")
        self.assertEqual(event.actor, self.layla)
        self.assertNotIn("draft", str(event.payload))
        self.assertEqual(self.client.patch(url, {"body": "   "}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertIsNotNone(RoomMessage.objects.get(pk=msg_id).deleted_at, "soft delete keeps the row")
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="room.message.delete", actor=self.layla).exists())
        self.assertEqual(self.client.patch(url, {"body": "again"}, format="json").status_code, 404)
        listed = self.client.get(f"{self.base}/rooms/{self.room.id}/messages").json()["results"]
        self.assertNotIn(msg_id, [r["id"] for r in listed])

    def test_others_and_owner_cannot_edit_or_delete(self):
        msg_id = self._post(self.room, "mine", self.layla).json()["id"]
        url = f"{self.base}/rooms/{self.room.id}/messages/{msg_id}"
        for user in (self.youssef, self.owner):
            self._auth(user)
            self.assertEqual(self.client.patch(url, {"body": "x"}, format="json").status_code, 403)
            self.assertEqual(self.client.delete(url).status_code, 403)
        self.assertEqual(RoomMessage.objects.get(pk=msg_id).body, "mine")

    def test_owner_cannot_reach_dm_messages(self):
        msg_id = self._post(self.dm, "private", self.layla).json()["id"]
        self._auth(self.owner)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.dm.id}/messages").status_code, 404)
        self.assertEqual(self.client.delete(f"{self.base}/rooms/{self.dm.id}/messages/{msg_id}").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.dm.id}/members").status_code, 404)

    def test_other_org_cannot_touch_a_message(self):
        msg_id = self._post(self.room, "mine", self.layla).json()["id"]
        self._auth(self.foreign)
        url = f"/api/v2/orgs/{self.other_org.id}/rooms/{self.room.id}/messages/{msg_id}"
        self.assertEqual(self.client.patch(url, {"body": "x"}, format="json").status_code, 404)


class NotificationTests(RoomChatBase):
    def test_team_room_message_creates_no_row_per_member(self):
        self._post(self.room, "plain update", self.layla)
        self.assertFalse(Notification.objects.exists())
        self._auth(self.youssef)
        rooms = {r["id"]: r for r in self.client.get(f"{self.base}/rooms").json()}
        self.assertEqual(rooms[str(self.room.id)]["unread"], 1, "unread comes from read markers")

    def test_mention_notifies_only_the_mentioned_member_who_can_read_the_room(self):
        self._post(self.room, "@Youssef Adel please review. Also @Sara Nabil and @Gone Person", self.layla)
        rows = list(Notification.objects.all())
        self.assertEqual([(r.user_id, r.kind) for r in rows], [(self.youssef.id, "mention")])
        self.assertEqual(rows[0].payload["by"], "Layla Mansour")
        self.assertEqual(rows[0].payload["link"], f"rooms/{self.room.id}")
        self.assertNotIn("please review", str(rows[0].payload), "no message text in the notification")

    def test_first_name_mention_and_no_self_mention(self):
        self._post(self.room, "thanks @youssef, and note to @Layla", self.layla)
        self.assertEqual(list(Notification.objects.values_list("user_id", flat=True)), [self.youssef.id])
        self.assertEqual(mentioned_users(self.room, "email me at a@youssef.example"), [])

    def test_dm_notifies_the_other_member_once(self):
        self._post(self.dm, "hi there", self.layla)
        self.assertEqual(list(Notification.objects.values_list("user_id", "kind")), [(self.youssef.id, "direct_message")])
        Notification.objects.all().delete()
        self._post(self.dm, "@Youssef look", self.layla)
        self.assertEqual(list(Notification.objects.values_list("user_id", "kind")), [(self.youssef.id, "mention")])


class RoomCreateTests(RoomChatBase):
    def test_group_room_needs_room_manage(self):
        self._auth(self.youssef)
        denied = self.client.post(f"{self.base}/rooms", {"name": "Lunch", "user_ids": [str(self.sara.id)]}, format="json")
        self.assertEqual(denied.status_code, 403)

    def test_owner_creates_group_with_active_members_only(self):
        self._auth(self.owner)
        bad = self.client.post(f"{self.base}/rooms", {"name": "G", "user_ids": [str(self.gone.id)]}, format="json")
        self.assertEqual(bad.status_code, 400)
        foreign = self.client.post(f"{self.base}/rooms", {"name": "G", "user_ids": [str(self.foreign.id)]}, format="json")
        self.assertEqual(foreign.status_code, 400)
        junk = self.client.post(f"{self.base}/rooms", {"name": "G", "user_ids": ["not-a-uuid"]}, format="json")
        self.assertEqual(junk.status_code, 400)
        ok = self.client.post(f"{self.base}/rooms", {"name": "Launch crew", "user_ids": [str(self.sara.id), str(self.youssef.id)]}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)
        room = Room.objects.get(pk=ok.json()["id"])
        self.assertEqual(room.kind, Room.KIND_GROUP)
        self.assertEqual(set(RoomMember.objects.filter(room=room).values_list("user_id", flat=True)), {self.owner.id, self.sara.id, self.youssef.id})
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="room.create").exists())

    def test_dm_with_yourself_is_400_and_dm_shows_the_other_name(self):
        self._auth(self.youssef)
        self.assertEqual(self.client.post(f"{self.base}/rooms", {"user_id": str(self.youssef.id)}, format="json").status_code, 400)
        created = self.client.post(f"{self.base}/rooms", {"user_id": str(self.sara.id)}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["other_name"], "Sara Nabil")
        again = self.client.post(f"{self.base}/rooms", {"user_id": str(self.sara.id)}, format="json")
        self.assertEqual(again.json()["id"], created.json()["id"], "one DM per pair")


class MemberListTests(RoomChatBase):
    def test_members_have_names_presence_and_active_state(self):
        OrgMembership.objects.filter(org=self.org, user=self.layla).update(presence="online")
        OrgMembership.objects.filter(org=self.org, user=self.gone).update(presence="online")
        self._auth(self.youssef)
        rows = {r["user_id"]: r for r in self.client.get(f"{self.base}/rooms/{self.room.id}/members").json()}
        self.assertEqual(rows[str(self.layla.id)]["presence"], "online")
        self.assertEqual(rows[str(self.layla.id)]["name"], "Layla Mansour")
        self.assertFalse(rows[str(self.gone.id)]["active"])
        self.assertEqual(rows[str(self.gone.id)]["presence"], "offline", "inactive people never show as online")
        self._auth(self.sara)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room.id}/members").status_code, 404)


class AnnouncementTests(RoomChatBase):
    def test_create_notifies_and_pin_unpin_are_audited(self):
        self._auth(self.owner)
        created = self.client.post(f"{self.base}/announcements", {"room": str(self.room.id), "body": "Freeze on Friday"}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        ann_id = created.json()["id"]
        self.assertEqual(created.json()["room_name"], "Engineering")
        notified = set(Notification.objects.filter(kind="announcement").values_list("user_id", flat=True))
        self.assertEqual(notified, {self.layla.id, self.youssef.id}, "active room members, not the author")
        self.assertEqual(self.client.post(f"{self.base}/announcements/{ann_id}/unpin").json()["pinned"], False)
        self.assertEqual(self.client.post(f"{self.base}/announcements/{ann_id}/pin").json()["pinned"], True)
        actions = set(AuditEvent.objects.filter(org=self.org).values_list("action", flat=True))
        self.assertTrue({"announcement.create", "announcement.pin", "announcement.unpin"} <= actions)

    def test_room_filter_and_unpinned_only_for_managers(self):
        pinned = Announcement.objects.create(org=self.org, room=self.room, body="pinned", created_by=self.owner)
        Announcement.objects.create(org=self.org, room=self.room, body="old", created_by=self.owner, pinned=False)
        Announcement.objects.create(org=self.org, room=self.design_room, body="design", created_by=self.owner)
        self._auth(self.youssef)
        rows = self.client.get(f"{self.base}/announcements?room={self.room.id}").json()
        self.assertEqual([r["id"] for r in rows], [str(pinned.id)])
        self.assertEqual(self.client.get(f"{self.base}/announcements?room=nope").status_code, 400)
        self.assertEqual(self.client.get(f"{self.base}/announcements?include_unpinned=1").status_code, 403)
        self.assertEqual(self.client.post(f"{self.base}/announcements/{pinned.id}/pin").status_code, 403)
        self.assertEqual(self.client.post(f"{self.base}/announcements/{pinned.id}/unpin").status_code, 403)
        self._auth(self.owner)
        everything = self.client.get(f"{self.base}/announcements?room={self.room.id}&include_unpinned=1").json()
        self.assertEqual(len(everything), 2)

    def test_other_org_cannot_pin(self):
        row = Announcement.objects.create(org=self.org, room=self.room, body="x", created_by=self.owner, pinned=False)
        self._auth(self.foreign)
        self.assertEqual(self.client.post(f"/api/v2/orgs/{self.other_org.id}/announcements/{row.id}/pin").status_code, 404)
        self.assertFalse(Announcement.objects.get(pk=row.id).pinned)
