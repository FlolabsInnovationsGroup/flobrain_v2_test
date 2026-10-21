import re
from html import unescape
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from demo import idp
from organizations.models import OrgMembership, Organization
from users.models import User

CLIENT = "demo-browser-nonce-1234567890"


@override_settings(DEMO_MODE=True, FRONTEND_BASE_URL="https://app.example", PUBLIC_API_BASE_URL="https://api.example")
class DemoIdPTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Demo", slug="demo-idp")
        self.ana = User.objects.create(email="ana@demo.flobrain.example", username="Ana", password_hash=make_password(None))
        OrgMembership.objects.create(org=self.org, user=self.ana, org_role="member", employment_status="active")
        idp.configure(self.org)
        self.client = APIClient()

    def test_sign_in_through_the_demo_idp_uses_the_real_checks(self):
        start = self.client.get(f"/api/v2/sso/start?email=ana@demo.flobrain.example&client_nonce={CLIENT}")
        self.assertEqual(start.status_code, 200, start.content)
        url = urlparse(start.json()["authorize_url"])
        self.assertEqual(url.path, "/api/v2/demo/idp/sso")
        page = self.client.get(f"{url.path}?{url.query}")
        self.assertEqual(page.status_code, 200, page.content)
        body = page.content.decode()
        self.assertIn("ana@demo.flobrain.example", body)
        response = unescape(re.search(r'name="SAMLResponse" value="([^"]+)"', body).group(1))
        relay = unescape(re.search(r'name="RelayState" value="([^"]+)"', body).group(1))
        done = self.client.post("/api/v2/sso/saml/acs", {"SAMLResponse": response, "RelayState": relay})
        self.assertEqual(done.status_code, 303)
        self.assertIn("/w/sso?code=", done["Location"])
        code = parse_qs(urlparse(done["Location"]).query)["code"][0]
        tokens = self.client.post("/api/v2/sso/exchange", {"code": code, "client_nonce": CLIENT}, format="json")
        self.assertEqual(tokens.status_code, 200, tokens.content)
        again = self.client.post("/api/v2/sso/saml/acs", {"SAMLResponse": response, "RelayState": relay})
        self.assertIn("error=", again["Location"], "a response can't be replayed")

    def test_off_outside_the_demo_and_needs_a_real_request(self):
        self.assertEqual(self.client.get("/api/v2/demo/idp/sso?SAMLRequest=x&RelayState=y").status_code, 400)
        with override_settings(DEMO_MODE=False):
            self.assertEqual(self.client.get("/api/v2/demo/idp/sso?SAMLRequest=x&RelayState=y").status_code, 404)
