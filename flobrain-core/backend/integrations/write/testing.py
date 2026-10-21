"""Test helpers for write-back connectors: a fake network boundary and a ready org. Tests only."""

import json
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User

TEST_KEY = "cd" * 32  # test-only encryption key, never a real one
OAUTH_ENV = {}
for _p in ("GOOGLE_WORKSPACE", "MICROSOFT_365", "JIRA", "HUBSPOT", "ZOHO"):
    OAUTH_ENV[f"FLOBRAIN_OAUTH_{_p}_CLIENT_ID"] = f"test-{_p.lower()}-client"
    OAUTH_ENV[f"FLOBRAIN_OAUTH_{_p}_CLIENT_SECRET"] = f"test-{_p.lower()}-secret-NOT-REAL"


class FakeNet:
    """Replaces ``transport._send``. ``routes`` maps (method, url prefix) to a list of responses
    (status, dict|bytes) used in order; the last one repeats."""

    def __init__(self, routes=None):
        self.routes = {k: list(v) for k, v in (routes or {}).items()}
        self.calls = []

    def __call__(self, method, url, body, headers):
        self.calls.append({"method": method, "url": url, "body": body, "headers": dict(headers)})
        for (m, prefix), responses in self.routes.items():
            if m == method and url.startswith(prefix):
                status, payload = responses.pop(0) if len(responses) > 1 else responses[0]
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                return status, data
        raise AssertionError(f"unexpected call {method} {url}")

    def json(self, index):
        return json.loads(self.calls[index]["body"].decode())

    def patch(self):
        return patch("integrations.write.transport._send", self)


@override_settings(CREDENTIALS_ENCRYPTION_KEY=TEST_KEY, DEMO_MODE=False, **OAUTH_ENV)
class WriteBase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="W Org", slug="w-org", settings={"flags": {"write_integrations": True, "ai_actions": True, "buddies": True}}
        )
        self.owner = self._user("w-owner", OrgMembership.ORG_ROLE_OWNER)
        self.admin = self._user("w-admin", OrgMembership.ORG_ROLE_ADMIN)
        self.member = self._user("w-member", OrgMembership.ORG_ROLE_MEMBER)
        self.other = self._user("w-other", OrgMembership.ORG_ROLE_MEMBER)
        self.base = f"/api/v2/orgs/{self.org.id}/integrations/write"

    def _user(self, name, role):
        user = User.objects.create(email=f"{name}@example.com", username=name, password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status=OrgMembership.STATUS_ACTIVE)
        return user

    def auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def connect(self, provider, token="tok-ACCESS-NOT-REAL-1234", refresh="tok-REFRESH-NOT-REAL-5678", owner=None, config=None, scopes=None, demo=False, expires_at=None):
        from integrations.write import registry
        from integrations.write.models import WriteConnection

        prov = registry.get(provider)
        conn = WriteConnection(
            org=self.org, owner=owner, provider=provider, account_label=f"{provider} test",
            scopes=prov.scopes() if scopes is None else scopes, config=config or {}, demo=demo, connected_by=self.admin,
            expires_at=expires_at,
        )
        if not demo:
            conn.set_secrets(token, refresh)
        conn.save()
        return conn
