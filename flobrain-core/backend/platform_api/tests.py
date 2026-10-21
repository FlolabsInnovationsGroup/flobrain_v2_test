import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from actions.models import ActionProposal
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from platform_api import net, webhooks
from platform_api.models import Incident, PersonalAccessToken, WebhookDelivery, WebhookEndpoint
from rooms.models import Room, RoomMember, RoomMessage
from rooms.services import ensure_team_room, pair_key_for
from tasks.models import Task
from users.jwt_utils import make_access_token
from users.models import User

KEY = "ef" * 32


def _user(email):
    return User.objects.create(email=email, username=email.split("@")[0], password_hash=make_password("x"))


@override_settings(CREDENTIALS_ENCRYPTION_KEY=KEY)
class PlatformBase(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(
            name="PA", slug="pa-org", settings={"flags": {"api_access": True, "webhooks": True, "ai_actions": True, "status_page": True}}
        )
        self.owner = _user("pa-owner@example.com")
        self.member = _user("pa-m@example.com")
        self.other = _user("pa-o@example.com")
        for user, role in ((self.owner, OrgMembership.ORG_ROLE_OWNER), (self.member, OrgMembership.ORG_ROLE_MEMBER), (self.other, OrgMembership.ORG_ROLE_MEMBER)):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status=OrgMembership.STATUS_ACTIVE)
        self.team = Team.objects.create(org=self.org, name="T")
        TeamMembership.objects.create(team=self.team, user=self.member)
        self.room = ensure_team_room(self.team)
        hidden_team = Team.objects.create(org=self.org, name="Hidden")
        TeamMembership.objects.create(team=hidden_team, user=self.other)
        self.hidden_room = ensure_team_room(hidden_team)
        self.web = APIClient()

    def _session(self, user):
        self.web.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _token(self, user, scopes, **extra):
        self._session(user)
        response = self.web.post("/api/v2/me/tokens", {"org": str(self.org.id), "name": "cli", "scopes": scopes, **extra}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def _pat(self, raw):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        return client


class TokenTests(PlatformBase):
    def test_token_shown_once_hashed_and_scoped(self):
        made = self._token(self.member, ["tasks:read"])
        self.assertTrue(made["token"].startswith("fbp_"))
        listed = self.web.get("/api/v2/me/tokens").json()
        self.assertNotIn(made["token"], json.dumps(listed))
        self.assertNotIn(made["token"], json.dumps(list(PersonalAccessToken.objects.values()), default=str), "only the hash is stored")
        api = self._pat(made["token"])
        self.assertEqual(api.get("/api/public/v1/tasks").status_code, 200)
        self.assertEqual(api.get("/api/public/v1/rooms").status_code, 403, "missing scope")

    def test_revoked_password_change_inactive_and_flag(self):
        raw = self._token(self.member, ["tasks:read"])["token"]
        api = self._pat(raw)
        self.assertEqual(api.get("/api/public/v1/me").status_code, 200)
        token_id = PersonalAccessToken.objects.get().id
        self._session(self.member)
        self.web.delete(f"/api/v2/me/tokens/{token_id}")
        self.assertEqual(api.get("/api/public/v1/me").status_code, 401, "revocation is immediate")

        raw = self._token(self.member, ["tasks:read"])["token"]
        User.objects.filter(pk=self.member.pk).update(password_changed_at=timezone.now() + timedelta(seconds=1))
        self.assertEqual(self._pat(raw).get("/api/public/v1/me").status_code, 401)
        User.objects.filter(pk=self.member.pk).update(password_changed_at=None)

        raw = self._token(self.member, ["tasks:read"])["token"]
        OrgMembership.objects.filter(user=self.member).update(employment_status=OrgMembership.STATUS_TERMINATED)
        self.assertEqual(self._pat(raw).get("/api/public/v1/me").status_code, 401)
        self.assertIsNotNone(PersonalAccessToken.objects.filter(revoked_at__isnull=False).count())
        OrgMembership.objects.filter(user=self.member).update(employment_status=OrgMembership.STATUS_ACTIVE)

        raw = self._token(self.member, ["tasks:read"])["token"]
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        self.assertEqual(self._pat(raw).get("/api/public/v1/me").status_code, 403)

    def test_pat_is_not_a_session_and_jwt_is_not_a_pat(self):
        raw = self._token(self.member, ["tasks:read"])["token"]
        self.assertEqual(self._pat(raw).get(f"/api/v2/orgs/{self.org.id}/rooms").status_code, 401)
        jwt = APIClient()
        jwt.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.member.id))}")
        self.assertEqual(jwt.get("/api/public/v1/me").status_code, 401)

    def test_expired_token(self):
        raw = self._token(self.member, ["tasks:read"], expires_in_days=1)["token"]
        PersonalAccessToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self._pat(raw).get("/api/public/v1/me").status_code, 401)


class PublicApiTests(PlatformBase):
    def test_same_visibility_as_the_app(self):
        mine = Task.objects.create(org=self.org, team=self.team, title="Mine", created_by=self.member)
        hidden = Task.objects.create(org=self.org, team=self.hidden_room.team, title="Hidden")
        RoomMessage.objects.create(room=self.hidden_room, author=self.other, body="secret")
        dm = Room.objects.create(org=self.org, name="dm", kind=Room.KIND_DIRECT, pair_key=pair_key_for(self.owner, self.other))
        RoomMember.objects.create(room=dm, user=self.owner)
        RoomMember.objects.create(room=dm, user=self.other)
        api = self._pat(self._token(self.member, ["tasks:read", "rooms:read", "tasks:write"])["token"])
        ids = {t["id"] for t in api.get("/api/public/v1/tasks").json()["results"]}
        self.assertIn(str(mine.id), ids)
        self.assertNotIn(str(hidden.id), ids)
        self.assertEqual(api.get(f"/api/public/v1/tasks/{hidden.id}").status_code, 404)
        rooms = {r["id"] for r in api.get("/api/public/v1/rooms").json()["results"]}
        self.assertEqual(rooms, {str(self.room.id)})
        self.assertEqual(api.get(f"/api/public/v1/rooms/{self.hidden_room.id}/messages").status_code, 404)
        owner_api = self._pat(self._token(self.owner, ["rooms:read"])["token"])
        self.assertEqual(owner_api.get(f"/api/public/v1/rooms/{dm.id}/messages").status_code, 200)
        self.assertNotIn(str(dm.id), {r["id"] for r in api.get("/api/public/v1/rooms").json()["results"]})
        created = api.post("/api/public/v1/tasks", {"title": "From CLI", "team": str(self.hidden_room.team_id)}, format="json")
        self.assertEqual(created.status_code, 404)
        self.assertEqual(api.post("/api/public/v1/tasks", {"title": "From CLI"}, format="json").status_code, 201)


class MCPTests(PlatformBase):
    def _rpc(self, api, method, params=None, rid=1):
        return api.post("/api/mcp", {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}, format="json")

    def test_initialize_list_and_read_tools(self):
        api = self._pat(self._token(self.member, ["mcp", "tasks:read", "rooms:read"])["token"])
        init = self._rpc(api, "initialize").json()
        self.assertEqual(init["result"]["serverInfo"]["name"], "flobrain")
        names = {t["name"] for t in self._rpc(api, "tools/list").json()["result"]["tools"]}
        self.assertIn("tasks_list", names)
        self.assertNotIn("time_report", names, "only tools the token's scopes allow")
        Task.objects.create(org=self.org, team=self.team, title="Visible", created_by=self.member)
        Task.objects.create(org=self.org, team=self.hidden_room.team, title="Hidden")
        result = self._rpc(api, "tools/call", {"name": "tasks_list", "arguments": {}}).json()["result"]
        self.assertEqual([t["title"] for t in result["structuredContent"]["tasks"]], ["Visible"])
        bad = self._rpc(api, "tools/call", {"name": "tasks_list", "arguments": {"evil": 1}}).json()["result"]
        self.assertTrue(bad["isError"])

    def test_write_tools_only_propose(self):
        api = self._pat(self._token(self.member, ["mcp", "tasks:write", "rooms:read"])["token"])
        result = self._rpc(api, "tools/call", {"name": "tasks_create", "arguments": {"title": "From agent"}}).json()["result"]
        self.assertFalse(result["isError"], result)
        self.assertEqual(result["structuredContent"]["proposal"]["status"], "proposed")
        self.assertFalse(Task.objects.filter(title="From agent").exists())
        self.assertEqual(ActionProposal.objects.get().user, self.member)
        hidden = self._rpc(api, "tools/call", {"name": "rooms_post_message", "arguments": {"room": str(self.hidden_room.id), "body": "x"}}).json()
        self.assertTrue(hidden["result"]["isError"])

    def test_scope_and_auth(self):
        api = self._pat(self._token(self.member, ["tasks:read"])["token"])
        self.assertEqual(self._rpc(api, "tools/list").status_code, 403)
        self.assertEqual(APIClient().post("/api/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize"}, format="json").status_code, 401)


class WebhookTests(PlatformBase):
    def _create(self, url="https://hooks.example.com/in", events=("task.created",)):
        self._session(self.owner)
        with patch("platform_api.net.resolve", return_value=["93.184.216.34"]):
            return self.web.post(f"/api/v2/orgs/{self.org.id}/webhooks", {"url": url, "events": list(events)}, format="json")

    def test_ssrf_guard_at_save(self):
        for url, addr in (
            ("http://hooks.example.com/x", "93.184.216.34"),
            ("https://10.0.0.5/x", "10.0.0.5"),
            ("https://internal.example.com/x", "10.0.0.5"),
            ("https://meta.example.com/x", "169.254.169.254"),
            ("https://local.example.com/x", "127.0.0.1"),
            ("https://v6.example.com/x", "::ffff:127.0.0.1"),
            ("https://user:pw@hooks.example.com/x", "93.184.216.34"),
        ):
            self._session(self.owner)
            with patch("platform_api.net.resolve", return_value=[addr]):
                response = self.web.post(f"/api/v2/orgs/{self.org.id}/webhooks", {"url": url, "events": ["task.created"]}, format="json")
            self.assertEqual(response.status_code, 400, url)
        self._session(self.member)
        self.assertEqual(self.web.get(f"/api/v2/orgs/{self.org.id}/webhooks").status_code, 403)

    def test_signed_delivery_retry_and_rebinding(self):
        made = self._create()
        self.assertEqual(made.status_code, 201, made.content)
        secret = made.json()["secret"]
        self.assertNotIn(secret, json.dumps(self.web.get(f"/api/v2/orgs/{self.org.id}/webhooks").json()))
        sent = {}

        def fake_post(url, body, headers, timeout=10):
            sent.update(url=url, body=body, headers=headers)
            return 200

        with patch("platform_api.net.post", side_effect=fake_post), self.captureOnCommitCallbacks(execute=True):
            Task.objects.create(org=self.org, team=self.team, title="Hooked")
        delivery = WebhookDelivery.objects.get()
        self.assertEqual(delivery.status, "delivered")
        ts = sent["headers"]["FloBrain-Signature"].split(",")[0][2:]
        self.assertEqual(sent["headers"]["FloBrain-Signature"], webhooks.sign(secret, int(ts), sent["body"]))
        self.assertNotIn("Hooked", sent["body"].decode(), "ids only, no titles or bodies")

        with patch("platform_api.net.post", return_value=500), self.captureOnCommitCallbacks(execute=True):
            Task.objects.create(org=self.org, team=self.team, title="Retry")
        retry = WebhookDelivery.objects.filter(status="pending").get()
        self.assertEqual(retry.attempts, 1)
        self.assertGreater(retry.next_attempt_at, timezone.now())

        with patch("platform_api.net.resolve", return_value=["10.1.2.3"]):
            WebhookDelivery.objects.filter(pk=retry.pk).update(next_attempt_at=timezone.now())
            webhooks.deliver(retry.pk)
        retry.refresh_from_db()
        self.assertEqual(retry.status, "failed", "a host that now resolves privately is never contacted")

    def test_dm_meetings_never_emit(self):
        from meetings.models import Meeting

        self._create(events=("meeting.ended",))
        dm = Room.objects.create(org=self.org, name="dm", kind=Room.KIND_DIRECT, pair_key="a:b")
        with patch("platform_api.net.post", return_value=200) as posted, self.captureOnCommitCallbacks(execute=True):
            meeting = Meeting.objects.create(org=self.org, room=dm, title="Private")
            meeting.ended_at = timezone.now()
            meeting.save()
        posted.assert_not_called()

    def test_redirects_are_not_followed(self):
        self.assertFalse(hasattr(net, "HTTPRedirectHandler"))
        with patch("platform_api.net.resolve", return_value=["93.184.216.34"]), patch.object(net._PinnedHTTPS, "connect"), patch.object(
            net._PinnedHTTPS, "request"
        ), patch.object(net._PinnedHTTPS, "getresponse") as response:
            response.return_value.status = 302
            response.return_value.read.return_value = b""
            self.assertEqual(net.post("https://hooks.example.com/x", b"{}", {}), 302)


class IncidentStatusTests(PlatformBase):
    def test_org_incidents_private_and_export_sanitized(self):
        self._session(self.owner)
        made = self.web.post(f"/api/v2/orgs/{self.org.id}/incidents", {"title": "Org outage", "components": ["API"]}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        denied = self.web.patch(f"/api/v2/orgs/{self.org.id}/incidents/{made.json()['id']}", {"is_public": True}, format="json")
        self.assertEqual(denied.status_code, 403, "only platform admins publish")
        Incident.objects.create(title="Platform AI slow", severity="major", components=["AI"], is_public=True)
        import os
        import tempfile

        path = os.path.join(tempfile.mkdtemp(), "status.json")
        call_command("export_status", "--out", path, stdout=open(os.devnull, "w"))
        data = json.load(open(path))
        self.assertEqual([i["title"] for i in data["incidents"]], ["Platform AI slow"])
        self.assertEqual({c["name"]: c["status"] for c in data["components"]}["AI"], "partial_outage")
        self.assertNotIn("Org outage", json.dumps(data))



class Review14FixTests(PlatformBase):
    def _rpc(self, api, method, params=None):
        return api.post("/api/mcp", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, format="json")

    def test_read_only_scope_cannot_propose_room_messages(self):
        api = self._pat(self._token(self.member, ["mcp", "rooms:read"])["token"])
        names = {t["name"] for t in self._rpc(api, "tools/list").json()["result"]["tools"]}
        self.assertNotIn("rooms_post_message", names)
        call = self._rpc(api, "tools/call", {"name": "rooms_post_message", "arguments": {"room": str(self.room.id), "body": "x"}})
        self.assertTrue(call.json()["result"]["isError"])
        self.assertFalse(ActionProposal.objects.exists())

    def test_ip_literals_bad_ports_and_long_labels_are_400(self):
        self._session(self.owner)
        for url in ("https://8.8.8.8/x", "https://[2606:4700::1111]/x", "https://h.com:abc/", "https://h.com:99999/", "https://" + "a" * 70 + ".com/x"):
            response = self.web.post(f"/api/v2/orgs/{self.org.id}/webhooks", {"url": url, "events": ["task.created"]}, format="json")
            self.assertEqual(response.status_code, 400, url)
        self.assertFalse(net._public("fec0::1"))

    def test_bad_input_is_4xx(self):
        self._session(self.member)
        self.assertEqual(self.web.post("/api/v2/me/tokens", {"org": "nope", "name": "x", "scopes": ["tasks:read"]}, format="json").status_code, 404)
        self.assertEqual(
            self.web.post("/api/v2/me/tokens", {"org": str(self.org.id), "name": "x", "scopes": [["a"]]}, format="json").status_code, 400
        )
        api = self._pat(self._token(self.member, ["tasks:write"])["token"])
        self.assertEqual(api.post("/api/public/v1/tasks", [1, 2], format="json").status_code, 400)
        self.assertEqual(api.post("/api/public/v1/tasks", {"title": 5}, format="json").status_code, 400)

    def test_deactivation_revokes_tokens_at_once(self):
        raw = self._token(self.member, ["tasks:read"])["token"]
        membership = OrgMembership.objects.get(org=self.org, user=self.member)
        membership.employment_status = OrgMembership.STATUS_TERMINATED
        membership.save()
        membership.employment_status = OrgMembership.STATUS_ACTIVE
        membership.save()
        self.assertEqual(self._pat(raw).get("/api/public/v1/me").status_code, 401, "reactivation does not revive old tokens")

    def test_delivery_is_claimed_once(self):
        self._session(self.owner)
        with patch("platform_api.net.resolve", return_value=["93.184.216.34"]):
            self.web.post(f"/api/v2/orgs/{self.org.id}/webhooks", {"url": "https://hooks.example.com/in", "events": ["task.created"]}, format="json")
        Task.objects.create(org=self.org, team=self.team, title="Once")  # on_commit not run: still pending
        delivery = WebhookDelivery.objects.get()
        calls = []
        with patch("platform_api.net.post", side_effect=lambda *a, **k: calls.append(1) or 200):
            webhooks.deliver(delivery.id)
            webhooks.deliver(delivery.id)
            webhooks.retry_due()
        self.assertEqual(len(calls), 1)

    def test_pending_invite_is_not_member_joined_and_webhook_cap(self):
        self._session(self.owner)
        with patch("platform_api.net.resolve", return_value=["93.184.216.34"]):
            for i in range(20):
                self.web.post(f"/api/v2/orgs/{self.org.id}/webhooks", {"url": f"https://h{i}.example.com/", "events": ["member.joined"]}, format="json")
            over = self.web.post(f"/api/v2/orgs/{self.org.id}/webhooks", {"url": "https://x.example.com/", "events": ["member.joined"]}, format="json")
        self.assertEqual(over.status_code, 400)
        invited = _user("pa-invite@example.com")
        OrgMembership.objects.create(org=self.org, user=invited, employment_status=OrgMembership.STATUS_PENDING)
        self.assertFalse(WebhookDelivery.objects.filter(event="member.joined").exists())

    def test_deadline_closes_a_trickling_receiver(self):
        import time

        def slow_response(*args, **kwargs):
            time.sleep(0.5)
            raise AttributeError("closed")

        with patch("platform_api.net.resolve", return_value=["93.184.216.34"]), patch.object(net, "DEADLINE_SECONDS", 0.1), patch.object(
            net._PinnedHTTPS, "connect"
        ), patch.object(net._PinnedHTTPS, "request"), patch.object(net._PinnedHTTPS, "getresponse", side_effect=slow_response):
            with self.assertRaises(OSError):
                net.post("https://hooks.example.com/x", b"{}", {})
