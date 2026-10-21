"""Checkout, billing portal and the demo checkout (Phase 17b follow-up)."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from billing_v2 import stripe
from billing_v2.models import Plan, Subscription, UsageInvoiceLine
from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


def _user(email, **extra):
    return User.objects.create(email=email, password_hash=make_password("x"), **extra)


class CheckoutTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="C", slug="c-bill")
        self.owner, self.admin, self.member = _user("c-o@example.com"), _user("c-a@example.com"), _user("c-m@example.com")
        for user, role in ((self.owner, "owner"), (self.admin, "admin"), (self.member, "member")):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status="active")
        self.plan = Plan.objects.create(code="team", name="Team", price_cents=1900, is_public=True, stripe_price_id="price_team", entitlements={"flags": []})
        Plan.objects.create(code="secret", name="Hidden", is_public=False)
        self.base = f"/api/v2/orgs/{self.org.id}/billing"

    def c(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return client

    def test_billing_shows_plans_lines_and_mode(self):
        sub = Subscription.objects.create(org=self.org, plan=self.plan, status="active", seats=3)
        UsageInvoiceLine.objects.create(org=self.org, subscription=sub, period="2026-10", metric="seats", quantity=Decimal(3), unit_price=Decimal("19"), amount=Decimal(57))
        data = self.c(self.admin).get(self.base).json()
        self.assertEqual([p["code"] for p in data["plans"]], ["team"], "only public plans")
        self.assertEqual(data["invoice_lines"][0]["amount"], "57.0000")
        self.assertEqual(data["checkout"], "off")
        self.assertFalse(data["can_manage"])
        self.assertTrue(self.c(self.owner).get(self.base).json()["can_manage"])
        self.assertEqual(self.c(self.member).get(self.base).status_code, 403)

    def test_owner_only_and_off_without_stripe_or_demo(self):
        self.assertEqual(self.c(self.admin).post(f"{self.base}/checkout", {"plan": "team"}, format="json").status_code, 403)
        self.assertEqual(self.c(self.member).post(f"{self.base}/checkout", {"plan": "team"}, format="json").status_code, 403)
        self.assertEqual(self.c(self.owner).post(f"{self.base}/checkout", {"plan": "team"}, format="json").status_code, 501)
        self.assertEqual(self.c(self.owner).post(f"{self.base}/checkout", {"plan": "secret"}, format="json").status_code, 404)
        self.assertEqual(self.c(self.owner).post(f"{self.base}/checkout", {"plan": "team", "seats": "many"}, format="json").status_code, 400)
        self.assertEqual(self.c(self.owner).post(f"{self.base}/portal").status_code, 501)
        self.assertEqual(self.c(self.owner).post(f"{self.base}/demo", {"action": "subscribe", "plan": "team"}, format="json").status_code, 404)

    @override_settings(STRIPE_SECRET_KEY="sk_test_x")
    def test_stripe_checkout_is_created_server_side(self):
        with patch("billing_v2.stripe._post", return_value={"url": "https://checkout.stripe.com/c/s1"}) as posted:
            made = self.c(self.owner).post(f"{self.base}/checkout", {"plan": "team", "seats": 4}, format="json")
        self.assertEqual(made.json(), {"mode": "stripe", "url": "https://checkout.stripe.com/c/s1"})
        path, params = posted.call_args[0]
        self.assertEqual(path, "/checkout/sessions")
        self.assertEqual(params["metadata"], {"org_id": str(self.org.id), "plan": "team"})
        self.assertEqual(params["line_items"], [{"price": "price_team", "quantity": 4}])
        self.assertEqual(dict(stripe._flatten({"line_items": [{"price": "p", "quantity": 2}]})), {"line_items[0][price]": "p", "line_items[0][quantity]": "2"})
        self.assertEqual(self.c(self.owner).post(f"{self.base}/portal").status_code, 409, "no customer yet")
        Subscription.objects.create(org=self.org, plan=self.plan, stripe_customer_id="cus_1")
        with patch("billing_v2.stripe._post", return_value={"url": "https://billing.stripe.com/p/1"}):
            self.assertEqual(self.c(self.owner).post(f"{self.base}/portal").json()["url"], "https://billing.stripe.com/p/1")
        with patch("billing_v2.stripe._post", side_effect=stripe.StripeAPIError("down")):
            self.assertEqual(self.c(self.owner).post(f"{self.base}/checkout", {"plan": "team"}, format="json").status_code, 502)

    @override_settings(DEMO_MODE=True)
    def test_demo_checkout_sets_the_subscription_without_payment(self):
        started = self.c(self.owner).post(f"{self.base}/checkout", {"plan": "team", "seats": 5}, format="json").json()
        self.assertEqual(started["mode"], "demo")
        self.assertIn("/settings/billing/checkout?plan=team&seats=5", started["url"])
        self.assertEqual(self.c(self.admin).post(f"{self.base}/demo", {"action": "subscribe", "plan": "team"}, format="json").status_code, 403)
        self.assertEqual(self.c(self.owner).post(f"{self.base}/demo", {"action": "pay"}, format="json").status_code, 400)
        done = self.c(self.owner).post(f"{self.base}/demo", {"action": "subscribe", "plan": "team", "seats": 5}, format="json").json()
        self.assertEqual((done["status"], done["seats"], done["demo"]), ("active", 5, True))
        sub = Subscription.objects.get(org=self.org)
        self.assertEqual((sub.plan.code, sub.stripe_customer_id), ("team", ""))
        self.assertEqual(self.c(self.owner).post(f"{self.base}/demo", {"action": "cancel"}, format="json").json()["status"], "canceled")

    def test_platform_assigns_seats(self):
        staff = _user("c-staff@example.com", is_platform_admin=True)
        res = self.c(staff).put(f"/api/v2/platform/orgs/{self.org.id}/subscription", {"plan": "team", "seats": 7}, format="json")
        self.assertEqual(res.json()["seats"], 7)
        self.assertEqual(self.c(staff).put(f"/api/v2/platform/orgs/{self.org.id}/subscription", {"plan": "team", "seats": "x"}, format="json").status_code, 400)
