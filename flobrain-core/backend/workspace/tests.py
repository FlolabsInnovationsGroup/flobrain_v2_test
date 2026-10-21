from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from notifications.models import PushSubscription
from organizations.models import OrgMembership, Organization
from rooms.models import Room, RoomMember, RoomMessage
from users.jwt_utils import make_access_token
from users.models import User

FCM = "https://fcm.googleapis.com/fcm/send/abc123"
KEYS = {"p256dh": "B" * 87, "auth": "a" * 22}


class WorkspaceTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="W", slug="w-org")
        self.a = User.objects.create(email="a@w.test", username="Ana", password_hash=make_password("x"))
        self.b = User.objects.create(email="b@w.test", username="Ben", password_hash=make_password("x"))
        for u in (self.a, self.b):
            OrgMembership.objects.create(org=self.org, user=u, employment_status="active")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.a.id))}")

    def test_layout_round_trip_and_validation(self):
        self.assertEqual(self.client.get("/api/v2/me/cockpit-layout").json()["mode"], "default")
        saved = self.client.put(
            "/api/v2/me/cockpit-layout",
            {"mode": "custom", "layout": {"panels": {"video": True}, "widgets": ["tasks", "impact"], "accent": "#7c3aed"}, "low_bandwidth": True},
            format="json",
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["layout"]["widgets"], ["tasks", "impact"])
        self.assertTrue(saved.json()["layout"]["panels"]["rooms"], "unset panels keep their default")
        for bad in (
            {"mode": "chaos"},
            {"layout": {"widgets": ["<script>"]}},
            {"layout": {"accent": "red; background:url(x)"}},
            {"layout": {"panels": {"admin": True}}},
            {"low_bandwidth": "yes"},
        ):
            self.assertEqual(self.client.put("/api/v2/me/cockpit-layout", bad, format="json").status_code, 400, bad)

    def test_presence(self):
        url = f"/api/v2/orgs/{self.org.id}/me/presence"
        self.assertEqual(self.client.patch(url, {"presence": "away"}, format="json").status_code, 200)
        self.assertEqual(OrgMembership.objects.get(org=self.org, user=self.a).presence, "away")
        self.assertEqual(self.client.patch(url, {"presence": "invisible"}, format="json").status_code, 400)

    def test_push_subscriptions_only_for_real_push_services(self):
        url = "/api/v2/me/push-subscriptions"
        self.assertEqual(self.client.post(url, {"endpoint": "https://169.254.169.254/latest", "keys": KEYS}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"endpoint": "http://fcm.googleapis.com/x", "keys": KEYS}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"endpoint": "https://fcm.googleapis.com.evil.test/x", "keys": KEYS}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"endpoint": FCM, "keys": KEYS}, format="json").status_code, 201)
        self.assertEqual(PushSubscription.objects.get().user, self.a)

    @override_settings(VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv")
    def test_dm_push_has_no_message_text(self):
        PushSubscription.objects.create(user=self.b, endpoint=FCM, p256dh=KEYS["p256dh"], auth=KEYS["auth"])
        dm = Room.objects.create(org=self.org, name="dm", kind=Room.KIND_DIRECT, pair_key="ab")
        RoomMember.objects.create(room=dm, user=self.a)
        RoomMember.objects.create(room=dm, user=self.b)
        team = Room.objects.create(org=self.org, name="team", kind=Room.KIND_TEAM)
        with patch("pywebpush.webpush") as push, self.captureOnCommitCallbacks(execute=True):
            RoomMessage.objects.create(room=dm, author=self.a, body="the secret plan")
            RoomMessage.objects.create(room=team, author=self.a, body="team chatter")
        self.assertEqual(push.call_count, 1)
        sent = push.call_args.kwargs["data"]
        self.assertIn("New message from Ana", sent)
        self.assertNotIn("secret", sent)

    def test_preferences(self):
        rows = self.client.get("/api/v2/me/notification-preferences").json()
        self.assertTrue(all(r["enabled"] for r in rows))
        self.assertEqual(self.client.put("/api/v2/me/notification-preferences", {"type": "direct_message", "sound": "pop", "push": False}, format="json").status_code, 200)
        self.assertEqual(self.client.put("/api/v2/me/notification-preferences", {"type": "direct_message", "sound": "../../x"}, format="json").status_code, 400)

    def test_disabled_types_are_hidden_but_support_access_stays(self):
        from notifications.models import Notification

        Notification.objects.create(org=self.org, user=self.a, kind="room_message", payload={})
        Notification.objects.create(org=self.org, user=self.a, kind="impersonation.started", payload={})
        put = lambda body: self.client.put("/api/v2/me/notification-preferences", body, format="json")  # noqa: E731
        self.assertEqual(put({"type": "impersonation_started", "enabled": False}).status_code, 400)
        put({"type": "team_chat_message", "enabled": False})
        kinds = [n["kind"] for n in self.client.get(f"/api/v2/orgs/{self.org.id}/notifications").json()["results"]]
        self.assertIn("impersonation.started", kinds)
