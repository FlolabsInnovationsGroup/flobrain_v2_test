from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from brain.models import Chat, Message
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.models import RoomMessage
from rooms.services import ensure_team_room
from telemetry.models import UsageEvent
from users.jwt_utils import make_access_token
from users.models import User


class RoomThreadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(name="Thread Org", slug="thread-org", settings={"flags": {}})
        self.owner = User.objects.create(email="th-owner@example.com", password_hash=make_password("x"))
        self.member_a = User.objects.create(email="th-a@example.com", password_hash=make_password("x"))
        self.member_b = User.objects.create(email="th-b@example.com", password_hash=make_password("x"))
        self.same = User.objects.create(email="th-same@example.com", password_hash=make_password("x"))
        self.inactive = User.objects.create(email="th-off@example.com", password_hash=make_password("x"))
        self.outsider = User.objects.create(email="th-out@example.com", password_hash=make_password("x"))
        for user, role, status in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER, OrgMembership.STATUS_ACTIVE),
            (self.member_a, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.member_b, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.same, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_ACTIVE),
            (self.inactive, OrgMembership.ORG_ROLE_MEMBER, OrgMembership.STATUS_TERMINATED),
        ):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status=status)
        self.team_a = Team.objects.create(org=self.org, name="Alpha")
        self.team_b = Team.objects.create(org=self.org, name="Beta")
        TeamMembership.objects.create(team=self.team_a, user=self.member_a)
        TeamMembership.objects.create(team=self.team_a, user=self.same)
        TeamMembership.objects.create(team=self.team_b, user=self.member_b)
        self.room = ensure_team_room(self.team_a)
        self.other_room = ensure_team_room(self.team_b)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _enable(self):
        self.org.settings = {"flags": {"room_ai": True}}
        self.org.save(update_fields=["settings"])

    def test_flag_off_is_501_and_does_not_call_the_provider(self):
        self._auth(self.member_a)
        with patch("urllib.request.urlopen") as opened:
            response = self.client.get(f"{self.base}/rooms/{self.room.id}/ai/threads")
        opened.assert_not_called()
        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["error"], "not_implemented")

    def test_outsider_inactive_and_other_team(self):
        self._enable()
        self._auth(self.outsider)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room.id}/ai/threads").status_code, 403)
        self._auth(self.inactive)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room.id}/ai/threads").status_code, 403)
        self._auth(self.member_a)
        hidden = self.client.get(f"{self.base}/rooms/{self.other_room.id}/ai/threads")
        self.assertEqual(hidden.status_code, 404)

    def test_same_room_member_and_owner_cannot_read_a_private_thread(self):
        self._enable()
        self._auth(self.member_a)
        created = self.client.post(
            f"{self.base}/rooms/{self.room.id}/ai/threads",
            {"title": "mine"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        thread_id = created.json()["id"]
        self._auth(self.same)
        listed = self.client.get(f"{self.base}/rooms/{self.room.id}/ai/threads")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json(), [])
        self.assertEqual(self.client.get(f"{self.base}/ai/threads/{thread_id}").status_code, 404)
        denied = self.client.post(f"{self.base}/ai/threads/{thread_id}/send", {"text": "no"}, format="json")
        self.assertEqual(denied.status_code, 404)
        self._auth(self.owner)
        self.assertEqual(self.client.get(f"{self.base}/ai/threads/{thread_id}").status_code, 404)
        owner_send = self.client.post(f"{self.base}/ai/threads/{thread_id}/send", {"text": "no"}, format="json")
        self.assertEqual(owner_send.status_code, 404)
        owner_list = self.client.get(f"{self.base}/rooms/{self.room.id}/ai/threads")
        self.assertNotIn(thread_id, [row["id"] for row in owner_list.json()])

    def test_send_uses_only_the_users_text_and_stores_unknown_tokens(self):
        self._enable()
        self._auth(self.member_a)
        RoomMessage.objects.create(room=self.room, author=self.same, body="ROOM_SECRET_PHRASE")
        RoomMessage.objects.create(room=self.room, author=self.member_a, body="MY_ROOM_LINE")
        created = self.client.post(f"{self.base}/rooms/{self.room.id}/ai/threads", {}, format="json")
        thread_id = created.json()["id"]
        captured = {}

        def _complete(messages, model=None):
            captured["messages"] = messages
            from brain.llm.providers import ProviderResult

            return ProviderResult(text="answer", model="legacy", total_tokens=None)

        with patch("brain.v2_views.get_provider") as get_provider:
            get_provider.return_value.complete.side_effect = _complete
            sent = self.client.post(
                f"{self.base}/ai/threads/{thread_id}/send",
                {"text": "my own question"},
                format="json",
            )
        self.assertEqual(sent.status_code, 200, sent.content)
        blob = " ".join(row["content"] for row in captured["messages"])
        self.assertIn("my own question", blob)
        self.assertNotIn("ROOM_SECRET_PHRASE", blob)
        self.assertNotIn("MY_ROOM_LINE", blob)
        self.assertIsNotNone(sent.json()["usage"]["total_tokens"])
        self.assertNotEqual(sent.json()["usage"]["total_tokens"], 0)
        self.assertEqual(sent.json()["usage"]["token_state"], "estimated")
        self.assertEqual(Message.objects.filter(chat_id=thread_id, role="assistant").count(), 1)
        stored = UsageEvent.objects.get(chat_id=thread_id)
        self.assertTrue(stored.estimated)
        self.assertIsNotNone(stored.total_tokens)
        v1 = self.client.get("/api/brain/chats/")
        self.assertEqual(v1.status_code, 200)
        self.assertNotIn(thread_id, [row["id"] for row in v1.json()])

    def test_echo_is_not_stored(self):
        self._enable()
        self._auth(self.member_a)
        created = self.client.post(f"{self.base}/rooms/{self.room.id}/ai/threads", {}, format="json")
        thread_id = created.json()["id"]
        from brain.llm.providers import ProviderResult

        echo = ProviderResult(text=None, model="legacy", error_code="provider_error")
        with patch("brain.v2_views.get_provider") as get_provider:
            get_provider.return_value.complete.return_value = echo
            sent = self.client.post(f"{self.base}/ai/threads/{thread_id}/send", {"text": "hi"}, format="json")
        self.assertEqual(sent.status_code, 502)
        self.assertEqual(sent.json()["error"], "provider_error")
        self.assertFalse(Message.objects.filter(chat_id=thread_id, role="assistant").exists())
        stored = " ".join(Message.objects.filter(chat_id=thread_id).values_list("text", flat=True))
        self.assertNotIn("Echoing", stored)

    @override_settings(FLOBRAIN_V2={"AI_SEND_RATE": "1/min"})
    def test_send_is_throttled_per_user(self):
        self._enable()
        self._auth(self.member_a)
        created = self.client.post(f"{self.base}/rooms/{self.room.id}/ai/threads", {}, format="json")
        thread_id = created.json()["id"]
        from brain.llm.providers import ProviderResult

        ok = ProviderResult(text="ok", model="legacy", total_tokens=1)
        with patch("brain.v2_views.get_provider") as get_provider:
            get_provider.return_value.complete.return_value = ok
            first = self.client.post(f"{self.base}/ai/threads/{thread_id}/send", {"text": "one"}, format="json")
            second = self.client.post(f"{self.base}/ai/threads/{thread_id}/send", {"text": "two"}, format="json")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 429)


class RoomThreadLimitTests(RoomThreadTests):
    def _thread(self):
        self._enable()
        self._auth(self.member_a)
        res = self.client.post(f"{self.base}/rooms/{self.room.id}/ai/threads", {}, format="json")
        return res.json()["id"]

    @override_settings(FLOBRAIN_V2={"AI_SEND_RATE": "1000/min", "AI_MAX_INPUT_CHARS": 10, "AI_THREAD_HISTORY_MESSAGES": 40})
    def test_overlong_text_is_rejected_before_the_provider(self):
        thread_id = self._thread()
        with patch("brain.v2_views.get_provider") as get_provider:
            res = self.client.post(f"{self.base}/ai/threads/{thread_id}/send", {"text": "x" * 11}, format="json")
        self.assertEqual(res.status_code, 400)
        get_provider.assert_not_called()

    @override_settings(FLOBRAIN_V2={"AI_SEND_RATE": "1000/min", "AI_MAX_INPUT_CHARS": 8000, "AI_THREAD_HISTORY_MESSAGES": 4})
    def test_history_sent_to_the_provider_is_bounded(self):
        from brain.llm.providers import ProviderResult

        thread_id = self._thread()
        chat = Chat.objects.get(pk=thread_id)
        for i in range(10):
            Message.objects.create(chat=chat, role=Message.ROLE_USER, text=f"old {i}")
        with patch("brain.v2_views.get_provider") as get_provider:
            get_provider.return_value.complete.return_value = ProviderResult(
                text="ok", model="m", total_tokens=3, provider="openai"
            )
            res = self.client.post(f"{self.base}/ai/threads/{thread_id}/send", {"text": "newest"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        sent = get_provider.return_value.complete.call_args.args[0]
        self.assertEqual(sent[0]["role"], "system")
        self.assertEqual(len(sent), 1 + 4)
        self.assertEqual(sent[-1]["content"], "newest")
        self.assertEqual(UsageEvent.objects.filter(chat=chat).latest("created_at").provider, "openai")
