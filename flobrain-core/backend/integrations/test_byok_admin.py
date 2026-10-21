"""AI keys page backend: private-only orgs, the meta endpoint and the demo provider."""

from unittest.mock import patch

from django.test import override_settings

from integrations.credentials import DEMO_BASE_URL
from integrations.models import AICredential
from integrations.test_byok import SECRET, ByokBase, _ok_models
from organizations.models import OrgPolicy


class PrivateOnlyKeyTests(ByokBase):
    def _private(self):
        OrgPolicy.objects.create(org=self.org, inference_scope=OrgPolicy.SCOPE_PRIVATE)

    def test_private_only_org_cannot_add_an_external_key(self):
        self._private()
        response, opened = self._create(self.member)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"], "private_only")
        self.assertFalse(opened.called, "the key is never sent anywhere")
        self.assertFalse(AICredential.objects.exists())

    @override_settings(AI_SELF_HOSTED_HOSTS="api.openai.com")
    def test_private_only_allows_a_self_hosted_host(self):
        self._private()
        response, _ = self._create(self.member)
        self.assertEqual(response.status_code, 201, response.content)

    def test_disabled_key_cannot_be_re_enabled_in_private_only(self):
        response, _ = self._create(self.member)
        key_id = response.json()["id"]
        self.client.patch(f"{self.url}/{key_id}", {"status": "disabled"}, format="json")
        self._private()
        res = self.client.patch(f"{self.url}/{key_id}", {"status": "enabled"}, format="json")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(AICredential.objects.get(pk=key_id).status, AICredential.STATUS_DISABLED)

    def test_bad_provider_type_is_400_not_500(self):
        self._auth(self.member)
        res = self.client.post(self.url, {"provider": ["x"], "secret": SECRET}, format="json")
        self.assertEqual(res.status_code, 400)


class CredentialMetaTests(ByokBase):
    def test_meta_for_member_and_admin(self):
        self._auth(self.member)
        body = self.client.get(f"{self.url}/meta").json()
        self.assertFalse(body["can_manage_org_keys"])
        self.assertIn("openai", body["providers"])
        self.assertNotIn("demo", body["providers"])
        self.assertFalse(body["private_only"])
        self.assertIn("api.openai.com", body["allowed_hosts"])
        self._auth(self.admin)
        self.assertTrue(self.client.get(f"{self.url}/meta").json()["can_manage_org_keys"])

    def test_meta_needs_membership_and_flag(self):
        self._auth(self.outsider)
        self.assertEqual(self.client.get(f"{self.url}/meta").status_code, 403)
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        self._auth(self.member)
        self.assertEqual(self.client.get(f"{self.url}/meta").status_code, 501)


class DemoProviderTests(ByokBase):
    def test_demo_provider_is_refused_outside_demo_mode(self):
        response, _ = self._create(self.member, provider="demo")
        self.assertEqual(response.status_code, 400)

    @override_settings(DEMO_MODE=True, DEMO_AI=True)
    def test_demo_provider_is_active_without_network(self):
        response, opened = self._create(self.member, provider="demo")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["status"], "active")
        self.assertTrue(body["demo"])
        self.assertEqual(body["base_url"], DEMO_BASE_URL)
        self.assertFalse(opened.called)
        self.assertNotIn(SECRET, response.content.decode())

    def test_existing_demo_key_is_not_active_after_demo_mode_ends(self):
        with override_settings(DEMO_MODE=True, DEMO_AI=True):
            response, _ = self._create(self.member, provider="demo")
        key_id = response.json()["id"]
        with patch("integrations.credentials.open_customer", side_effect=_ok_models) as opened:
            res = self.client.patch(f"{self.url}/{key_id}", {"recheck": True}, format="json")
        self.assertEqual(res.json()["status"], "rejected")
        self.assertFalse(opened.called)
