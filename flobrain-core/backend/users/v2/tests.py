from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from users.jwt_utils import make_access_token
from users.models import User
from users.v2.serializers import normalize_phone


class PhoneTests(TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_phone("+20 100 123-4567"), "+201001234567")
        self.assertEqual(normalize_phone("0044 (20) 7946 0958"), "+442079460958")
        for bad in ("12345", "0100 123 4567", "+0 123 456 789", "+20abc1234567", "", "+1234567890123456"):
            with self.assertRaises(Exception, msg=bad):
                normalize_phone(bad)


class FirstLoginPhoneTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="fl@example.com", password_hash=make_password("Temp-pass-1"), must_change_password=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.user.id))}")

    def test_phone_required_and_validated(self):
        url = "/api/v2/auth/first-login"
        self.assertEqual(self.client.post(url, {"password": "Brand-new-pass-77"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"password": "Brand-new-pass-77", "phone": "123"}, format="json").status_code, 400)
        ok = self.client.post(url, {"password": "Brand-new-pass-77", "phone": "+216 20 123 456"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "+21620123456")
        self.assertFalse(self.user.must_change_password)

    def test_phone_on_file_is_enough(self):
        self.user.phone = "+201001234567"
        self.user.save(update_fields=["phone"])
        res = self.client.post("/api/v2/auth/first-login", {"password": "Brand-new-pass-77"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)


class MePatchTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(email="me@example.com", username="Me", password_hash=make_password("x"))

    def as_(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return self.client

    def test_updates_profile(self):
        res = self.as_(self.user).patch(
            "/api/v2/me",
            {"username": "  Mona  Said ", "phone": "+20 100 123 4567", "timezone": "Africa/Cairo", "locale": "ar", "about_me": "Hi", "linkedin_url": "https://linkedin.com/in/mona"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["username"], "Mona Said")
        self.assertEqual(body["phone"], "+201001234567")
        self.assertEqual(body["timezone"], "Africa/Cairo")
        self.assertEqual(body["locale"], "ar")

    def test_bad_input_is_400(self):
        c = self.as_(self.user)
        for payload in (
            {"phone": "call me"},
            {"timezone": "Mars/Olympus"},
            {"locale": "xx"},
            {"username": "   "},
            {"about_me": "x" * 2001},
            {"linkedin_url": "javascript:alert(1)"},
            {},
            {"email": "new@example.com"},
        ):
            self.assertEqual(c.patch("/api/v2/me", payload, format="json").status_code, 400, payload)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "me@example.com")

    def test_demo_profile_is_locked(self):
        demo = User.objects.create(email="demo@demo.flobrain.example", username="Demo", password_hash=make_password(None), provider="demo")
        self.assertEqual(self.as_(demo).patch("/api/v2/me", {"username": "Changed"}, format="json").status_code, 403)

    def test_needs_sign_in(self):
        self.client.credentials()
        self.assertEqual(self.client.patch("/api/v2/me", {"username": "x"}, format="json").status_code, 401)
