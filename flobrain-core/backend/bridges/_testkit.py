"""Shared setup for the bridges tests (not a test module). Nothing here reaches the network."""

import json
import time
import urllib.parse

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from brain.models import Message
from bridges import slack
from bridges.models import SLACK, TEAMS, BridgeLink, BridgeWorkspace
from channels import vault
from organizations.models import Organization, OrgMembership
from users.jwt_utils import make_access_token
from users.models import User

KEY = "cd" * 32
SIGNING = "8f742231b10e8888abcd99yyyzzz85a5"
CLIENT_ID = "1111.2222"
CLIENT_SECRET = "slack-client-secret-value-123"
BOT_TOKEN = "xoxb-1234-5678-abcdefghijklmnopqrstuvwx"
TEAMS_APP = "11111111-2222-4333-8444-555555555555"
TEAMS_SECRET = "teams-app-secret-value-0987654321"
TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"
TEAM = "T0ACME"
ALL_SECRETS = (SIGNING, CLIENT_SECRET, BOT_TOKEN, TEAMS_SECRET)
FLAGS = {"bridges": True, "buddies": True, "ai_actions": True}
ENV = {
    "FLOBRAIN_SLACK_CLIENT_ID": CLIENT_ID,
    "FLOBRAIN_SLACK_CLIENT_SECRET": CLIENT_SECRET,
    "FLOBRAIN_SLACK_SIGNING_SECRET": SIGNING,
    "FLOBRAIN_TEAMS_APP_ID": TEAMS_APP,
    "FLOBRAIN_TEAMS_APP_SECRET": TEAMS_SECRET,
}


def fake_turn(user, org, chat, text, data, surface="buddy"):
    Message.objects.create(chat=chat, role=Message.ROLE_USER, text=text)
    Message.objects.create(chat=chat, role=Message.ROLE_ASSISTANT, text=f"Buddy says: {text}")
    return 200, {"usage": {}, "proposals": []}


class FakeNet:
    """Stands in for ``platform_api.net.fetch``: records calls, answers like Slack and Microsoft."""

    def __init__(self):
        self.calls = []
        self.profiles = {}  # Slack user id -> {"email", "real_name"}
        self.jwks = {"keys": []}
        self.teams_member = {}
        self.fail = set()

    def __call__(self, method, url, body=b"", headers=None, timeout=10, max_bytes=4096):
        parsed = urllib.parse.urlparse(url)
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            data = dict(urllib.parse.parse_qsl((body or b"").decode()))
        self.calls.append({"method": method, "url": url, "host": parsed.hostname, "path": parsed.path, "body": data, "headers": headers or {}})
        return self.answer(parsed, data)

    def _json(self, value, status=200):
        return status, json.dumps(value).encode()

    def answer(self, parsed, data):
        host, path = parsed.hostname, parsed.path
        if host == "slack.com":
            method = path.rsplit("/", 1)[-1]
            if method in self.fail:
                return self._json({"ok": False, "error": "channel_not_found"})
            query = dict(urllib.parse.parse_qsl(parsed.query))
            if method == "chat.postMessage":
                return self._json({"ok": True, "channel": data.get("channel"), "ts": f"1700000000.{len(self.calls):06d}"})
            if method == "conversations.open":
                return self._json({"ok": True, "channel": {"id": "D0DM" + data.get("users", "")[-3:]}})
            if method in ("users.info", "users.lookupByEmail"):
                for uid, prof in self.profiles.items():
                    if query.get("user") == uid or query.get("email") == prof.get("email"):
                        return self._json({"ok": True, "user": {"id": uid, "profile": {"email": prof.get("email"), "real_name": prof.get("real_name", "")}}})
                return self._json({"ok": False, "error": "users_not_found"})
            if method == "oauth.v2.access":
                return self._json({"ok": True, "access_token": BOT_TOKEN, "token_type": "bot", "scope": "chat:write", "bot_user_id": "U0BOT", "app_id": "A0APP", "team": {"id": TEAM, "name": "Acme Slack"}})
            if method == "auth.test":
                return self._json({"ok": True, "team_id": TEAM, "user_id": "U0BOT"})
            return self._json({"ok": True})
        if host == "hooks.slack.com":
            return 200, b"ok"
        if host == "login.microsoftonline.com":
            return self._json({"access_token": "ms-bot-access-token", "expires_in": 3600})
        if host == "login.botframework.com":
            if path.endswith("openidconfiguration"):
                return self._json({"issuer": "https://api.botframework.com", "jwks_uri": "https://login.botframework.com/v1/.well-known/keys"})
            return self._json(self.jwks)
        if "/members/" in path:
            return self._json(self.teams_member) if self.teams_member else self._json({}, 404)
        return self._json({"id": f"act-{len(self.calls)}"})

    def slack(self, method):
        return [c for c in self.calls if c["host"] == "slack.com" and c["path"].endswith("/" + method)]

    def texts(self):
        return [c["body"].get("text") for c in self.calls if isinstance(c["body"], dict) and c["body"].get("text")]


@override_settings(CREDENTIALS_ENCRYPTION_KEY=KEY, DEMO_MODE=False, DEMO_AI=False, BRIDGES_LIMITS={}, CHANNELS_LIMITS={}, **ENV)
class BridgesTestCase(TestCase):
    def setUp(self):
        cache.clear()
        from bridges import teams

        teams._token_cache.clear()
        teams._last_refresh["at"] = 0.0
        self.org = Organization.objects.create(name="Acme", slug="acme-br", settings={"flags": dict(FLAGS)})
        self.users = {}
        for name, role in (("owner", "owner"), ("admin", "admin"), ("member", "member"), ("other", "member")):
            u = User.objects.create(email=f"{name}@acme.test", username=name.title(), password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            self.users[name] = u
        self.base = f"/api/v2/orgs/{self.org.id}"

    def client_for(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return c

    def set_flag(self, key, value):
        flags = dict(self.org.settings.get("flags", {}))
        flags[key] = value
        self.org.settings = {**self.org.settings, "flags": flags}
        self.org.save()

    def slack_ws(self, **extra):
        ws = BridgeWorkspace(org=self.org, platform=SLACK, external_id=TEAM, name="Acme Slack", status="active", config={"bot_user_id": "U0BOT"}, **extra)
        vault.store(ws, {"bot_token": BOT_TOKEN})
        ws.save()
        return ws

    def teams_ws(self):
        return BridgeWorkspace.objects.create(org=self.org, platform=TEAMS, external_id=TENANT, name="Acme Teams", status="active")

    def link(self, who, ws, external_id, status="active", **extra):
        return BridgeLink.objects.create(org=self.org, user=self.users[who], workspace=ws, status=status, external_id=external_id, **extra)

    # --- Slack requests ---

    def slack_post(self, path, body: bytes, content_type, *, ts=None, secret=SIGNING, signature=None):
        ts = int(time.time()) if ts is None else ts
        headers = {"HTTP_X_SLACK_REQUEST_TIMESTAMP": str(ts)}
        if signature is not False:
            headers["HTTP_X_SLACK_SIGNATURE"] = signature or slack.sign(body, ts, secret)
        return self.client.post(f"/api/v2/hooks/slack/{path}", data=body, content_type=content_type, **headers)

    def slack_event(self, event, event_id="Ev001", team=TEAM, **kw):
        payload = {"type": "event_callback", "team_id": team, "event_id": event_id, "event": event}
        return self.slack_post("events", json.dumps(payload).encode(), "application/json", **kw)

    def mention(self, user="U0MEMBER", text="<@U0BOT> what is due today?", channel="C0LAUNCH", ts="1700000000.000100", **extra):
        return {"type": "app_mention", "user": user, "text": text, "channel": channel, "ts": ts, **extra}

    def dm(self, user="U0MEMBER", text="hello", channel="D0DMMEM", ts="1700000001.000100"):
        return {"type": "message", "channel_type": "im", "user": user, "text": text, "channel": channel, "ts": ts}

    def slack_command(self, text="what is due?", user="U0MEMBER", trigger="trig-1", **kw):
        form = urllib.parse.urlencode({
            "team_id": TEAM, "user_id": user, "user_name": "member", "command": "/flo", "text": text, "channel_id": "C0LAUNCH",
            "response_url": "https://hooks.slack.com/commands/T0ACME/123/abcdefghijk", "trigger_id": trigger,
        }).encode()
        return self.slack_post("commands", form, "application/x-www-form-urlencoded", **kw)

    def slack_action(self, card, decision="approve", user="U0MEMBER", action_ts="1700000099.1"):
        payload = {
            "type": "block_actions", "team": {"id": TEAM}, "user": {"id": user},
            "container": {"type": "message", "channel_id": card.channel, "message_ts": card.message_id},
            "actions": [{"action_id": f"flo_{decision}", "value": str(card.proposal_id), "action_ts": action_ts}],
        }
        body = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode()
        return self.slack_post("interactions", body, "application/x-www-form-urlencoded")
