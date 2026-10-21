import json

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from demo import seed
from demo.models import DemoAccount
from organizations.models import OrgMembership, Organization
from users.models import User


class DemoOffTests(TestCase):
    def test_everything_is_hidden_when_off(self):
        client = APIClient()
        self.assertEqual(client.get("/api/v2/demo").json(), {"enabled": False})
        self.assertEqual(client.post("/api/v2/demo/signin", {"role": "owner"}, format="json").status_code, 404)
        self.assertFalse(Organization.objects.filter(slug="demo").exists())


@override_settings(DEMO_MODE=True, DEMO_AI=True)
class DemoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def _signin(self, role):
        res = self.client.post("/api/v2/demo/signin", {"role": role}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.json()['access']}")
        return res.json()

    def test_roles_and_signin(self):
        info = self.client.get("/api/v2/demo").json()
        self.assertEqual([r["key"] for r in info["roles"]], ["owner", "admin", "lead", "member"])
        self.assertEqual(self.client.post("/api/v2/demo/signin", {"role": "platform"}, format="json").status_code, 400)
        data = self._signin("member")
        self.assertEqual(data["org_slug"], "demo")
        org = Organization.objects.get(slug="demo")
        self.assertEqual(self.client.get(f"/api/v2/orgs/{org.id}/tasks").status_code, 200)
        roles = dict(OrgMembership.objects.filter(org=org, user__demo_account__isnull=False).values_list("user__demo_account__role", "org_role"))
        self.assertEqual(roles, {"owner": "owner", "admin": "admin", "lead": "member", "member": "member"})
        # Demo users cannot sign in with a password.
        res = APIClient().post("/api/v2/auth/signin", {"email": seed.email_for("owner"), "password": ""}, format="json")
        self.assertNotEqual(res.status_code, 200)

    def test_reset_rebuilds_and_is_limited(self):
        self._signin("owner")
        first = Organization.objects.get(slug="demo").id
        self.assertEqual(self.client.post("/api/v2/demo/reset").status_code, 200)
        self.assertEqual(self.client.post("/api/v2/demo/reset").status_code, 401, "old tokens belong to deleted users")
        self.assertNotEqual(Organization.objects.get(slug="demo").id, first)
        self.assertEqual(DemoAccount.objects.count(), 4)
        outsider = User.objects.create(email="real@example.com", password_hash="x")
        from users.jwt_utils import make_access_token

        other = APIClient()
        other.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(outsider.id))}")
        self.assertEqual(other.post("/api/v2/demo/reset").status_code, 403)

    def test_demo_ai_answers_and_proposes(self):
        self._signin("member")
        org = Organization.objects.get(slug="demo")
        ask = self.client.post(f"/api/v2/orgs/{org.id}/knowledge/ask", {"question": "What is the launch plan?"}, format="json")
        self.assertEqual(ask.status_code, 200, ask.content)
        from brain.llm import demo_ai

        tools = [{"type": "function", "function": {"name": "tasks__create", "parameters": {}}}]
        result = demo_ai.reply([{"role": "user", "content": "Sources:\n<source id=\"1\">x</source>\n\nMessage: create a task to call the store"}], tools)
        self.assertEqual(result.tool_calls[0]["name"], "tasks__create")
        self.assertEqual(json.loads(result.tool_calls[0]["arguments"])["title"], "call the store")
        access = self.client.get(f"/api/v2/orgs/{org.id}/me/access").json()
        self.assertEqual((access["org_role"], access["demo_role"], access["flags"]["buddies"]), ("member", "member", True))
        self.assertNotIn("exports.memory", access["permissions"])


@override_settings(DEMO_MODE=True)
class DemoSafetyTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_real_org_on_demo_slug_is_never_touched(self):
        real = Organization.objects.create(name="Real", slug="demo")
        res = APIClient().post("/api/v2/demo/signin", {"role": "owner"}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertTrue(Organization.objects.filter(pk=real.pk).exists())

    def test_demo_accounts_cannot_change_identity_and_reset_survives(self):
        res = APIClient().post("/api/v2/demo/signin", {"role": "owner"}, format="json").json()
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {res['access']}")
        self.assertEqual(c.patch("/api/profile/", {"email": "me@evil.test"}, format="json").status_code, 403)
        User.objects.filter(email=seed.email_for("owner")).update(email="moved@elsewhere.test")  # even if it happened
        self.assertEqual(c.post("/api/v2/demo/reset").status_code, 200)
        self.assertFalse(User.objects.filter(email="moved@elsewhere.test").exists())
        self.assertEqual(DemoAccount.objects.count(), 4)
        keep = User.objects.create(email="someone@demo.flobrain.example", password_hash="x")
        seed.wipe()
        self.assertTrue(User.objects.filter(pk=keep.pk).exists(), "only provider=demo users are removed")
