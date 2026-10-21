import hashlib

from django.contrib.auth.hashers import make_password
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .jwt_utils import decode_token, make_access_token, make_refresh_token
from .models import PasswordResetToken, User


class ProfileAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            username="Jane Doe",
            email="jane@example.com",
            password_hash="unused",
        )
        self.token = make_access_token(str(self.user.id))

    def test_get_profile_requires_auth(self):
        response = self.client.get("/api/profile/")
        self.assertEqual(response.status_code, 401)

    def test_get_profile_returns_user_data(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        response = self.client.get("/api/profile/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["email"], "jane@example.com")
        self.assertEqual(data["fullName"], "Jane Doe")
        self.assertEqual(data["id"], str(self.user.id))

    def test_patch_profile_requires_auth(self):
        response = self.client.patch(
            "/api/profile/",
            {"fullName": "Jane Smith", "email": "jane@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_patch_profile_updates_user(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        response = self.client.patch(
            "/api/profile/",
            {"fullName": "Jane Smith", "email": "jane.new@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["fullName"], "Jane Smith")
        self.assertEqual(data["email"], "jane.new@example.com")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "Jane Smith")
        self.assertEqual(self.user.email, "jane.new@example.com")


class V2AuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            email="v2@example.com",
            username="V2 User",
            password_hash=make_password("correct-horse"),
        )

    def test_signin_refresh_me_signout(self):
        res = self.client.post(
            "/api/v2/auth/signin",
            {"email": "v2@example.com", "password": "correct-horse"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertIn("access", body)
        self.assertIn("refresh", body)
        payload = decode_token(body["access"])
        self.assertIsNotNone(payload)
        self.assertIn("jti", payload)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        me = self.client.get("/api/v2/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "v2@example.com")

        refresh = self.client.post(
            "/api/v2/auth/refresh",
            {"refresh": body["refresh"]},
            format="json",
        )
        self.assertEqual(refresh.status_code, 200)
        self.assertIn("access", refresh.json())

        out = self.client.post(
            "/api/v2/auth/signout",
            {"refresh": body["refresh"]},
            format="json",
        )
        self.assertEqual(out.status_code, 200)
        again = self.client.post(
            "/api/v2/auth/refresh",
            {"refresh": body["refresh"]},
            format="json",
        )
        self.assertEqual(again.status_code, 401)

    def test_signin_rejects_bad_password(self):
        res = self.client.post(
            "/api/v2/auth/signin",
            {"email": "v2@example.com", "password": "wrong"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_signout_requires_bearer(self):
        refresh = make_refresh_token(str(self.user.id))
        res = self.client.post("/api/v2/auth/signout", {"refresh": refresh}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_me_requires_bearer(self):
        res = self.client.get("/api/v2/me")
        self.assertEqual(res.status_code, 401)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_forgot_and_reset_password(self):
        res = self.client.post(
            "/api/v2/auth/password/forgot",
            {"email": "v2@example.com"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        token_row = PasswordResetToken.objects.get(user=self.user)
        raw = mail.outbox[0].body.split("token=")[1].strip()
        self.assertEqual(token_row.token_hash, hashlib.sha256(raw.encode()).hexdigest())
        reset = self.client.post(
            "/api/v2/auth/password/reset",
            {"token": raw, "password": "NewHorseBattery1"},
            format="json",
        )
        self.assertEqual(reset.status_code, 200, reset.content)
        signin = self.client.post(
            "/api/v2/auth/signin",
            {"email": "v2@example.com", "password": "NewHorseBattery1"},
            format="json",
        )
        self.assertEqual(signin.status_code, 200)

    def test_password_change_rejects_old_access_token(self):
        old = make_access_token(str(self.user.id))
        self.user.must_change_password = True
        self.user.save(update_fields=["must_change_password"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {old}")
        res = self.client.post(
            "/api/v2/auth/first-login",
            {"password": "BrandNewPass99"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        stale = self.client.get("/api/v2/me")
        self.assertEqual(stale.status_code, 401)
        self.client.credentials()
        fresh = self.client.post(
            "/api/v2/auth/signin",
            {"email": "v2@example.com", "password": "BrandNewPass99"},
            format="json",
        )
        self.assertEqual(fresh.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {fresh.json()['access']}")
        me = self.client.get("/api/v2/me")
        self.assertEqual(me.status_code, 200)
        self.assertFalse(me.json()["must_change_password"])

    def test_v1_signin_still_works(self):
        res = self.client.post(
            "/api/auth/signin/",
            {"email": "v2@example.com", "password": "correct-horse"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("access_token", res.json())
        self.assertIn("userId", res.json())
