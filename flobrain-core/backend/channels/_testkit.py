"""Shared setup for the channels tests (not a test module)."""

import hashlib
import hmac
import json

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from channels import vault
from channels.models import ChannelConnection
from organizations.models import Organization, OrgMembership
from users.jwt_utils import make_access_token
from users.models import User

KEY = "ab" * 32
APP_SECRET = "a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6"
ACCESS_TOKEN = "EAAGtestaccesstoken1234567890XYZ"
VERIFY_TOKEN = "verify-me-please"
BOT_TOKEN = "123456789:AAH-testbottokenabcdefghijklmnopqrstu"
TG_SECRET = "tg-secret-token-0123456789"
PHONE_ID = "100200300400500"
ALL_SECRETS = (APP_SECRET, ACCESS_TOKEN, VERIFY_TOKEN, BOT_TOKEN, TG_SECRET)
FLAGS = {"channels": True, "customer_buddy": True, "buddies": True, "ai_actions": True}


def wa_payload(msg_id="wamid.1", sender="201001112222", text="hello", phone=PHONE_ID, name="Mona"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "999",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": phone},
                            "contacts": [{"wa_id": sender, "profile": {"name": name}}],
                            "messages": [{"from": sender, "id": msg_id, "type": "text", "text": {"body": text}}],
                        },
                    }
                ],
            }
        ],
    }


def tg_payload(update_id=1, chat_id=555111, text="hello", name="Hana"):
    return {
        "update_id": update_id,
        "message": {"message_id": update_id, "from": {"id": chat_id, "first_name": name}, "chat": {"id": chat_id, "type": "private"}, "text": text},
    }


def sign(body: bytes, secret=APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class Sent:
    """Records outbound provider calls instead of reaching the network."""

    def __init__(self, status=200, body=b'{"ok": true}'):
        self.calls = []
        self.status = status
        self.body = body

    def __call__(self, method, url, body=b"", headers=None, timeout=10, max_bytes=4096):
        self.calls.append({"method": method, "url": url, "body": json.loads(body or b"{}"), "headers": headers or {}})
        return self.status, self.body

    def texts(self):
        out = []
        for call in self.calls:
            body = call["body"]
            out.append(body.get("text") if isinstance(body.get("text"), str) else (body.get("text") or {}).get("body"))
        return out


@override_settings(CREDENTIALS_ENCRYPTION_KEY=KEY, DEMO_MODE=False, DEMO_AI=False, CHANNELS_LIMITS={})
class ChannelsTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="Acme", slug="acme-ch", settings={"flags": dict(FLAGS)})
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

    def whatsapp(self, serve_team=True, serve_customers=True, **extra):
        conn = ChannelConnection(
            org=self.org, kind="whatsapp", label="WA", status="active", config={"phone_number_id": PHONE_ID},
            serve_team=serve_team, serve_customers=serve_customers, **extra,
        )
        vault.store(conn, {"access_token": ACCESS_TOKEN, "app_secret": APP_SECRET, "verify_token": VERIFY_TOKEN})
        conn.save()
        return conn

    def telegram(self, serve_team=True, serve_customers=False):
        conn = ChannelConnection(org=self.org, kind="telegram", label="TG", status="active", serve_team=serve_team, serve_customers=serve_customers)
        vault.store(conn, {"bot_token": BOT_TOKEN, "secret_token": TG_SECRET})
        conn.save()
        return conn

    def website(self, origins=("https://shop.example",)):
        return ChannelConnection.objects.create(
            org=self.org, kind="website", label="Web", status="active", site_key="site-key-123", config={"allowed_origins": list(origins)},
            serve_team=False, serve_customers=True,
        )

    def post_wa(self, conn, payload, signature="good"):
        body = json.dumps(payload).encode()
        headers = {}
        if signature == "good":
            headers["HTTP_X_HUB_SIGNATURE_256"] = sign(body)
        elif signature:
            headers["HTTP_X_HUB_SIGNATURE_256"] = signature
        return self.client.post(f"/api/v2/hooks/whatsapp/{conn.id}", data=body, content_type="application/json", **headers)

    def post_tg(self, conn, payload, secret=TG_SECRET):
        headers = {"HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN": secret} if secret else {}
        return self.client.post(f"/api/v2/hooks/telegram/{conn.id}", data=json.dumps(payload), content_type="application/json", **headers)
