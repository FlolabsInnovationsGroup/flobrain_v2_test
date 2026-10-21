import hashlib
import hmac
import json
import time

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from billing_v2.models import Plan, Subscription
from organizations.flags import effective_flag
from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User

SECRET = "whsec_test_not_live"


def _sign(body: bytes, ts=None, secret=SECRET):
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


@override_settings(STRIPE_WEBHOOK_SECRET=SECRET, BILLING_ENFORCE_ENTITLEMENTS=True)
class BillingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="B", slug="b-bill", settings={"flags": {"buddies": True, "content_studio": True}})
        self.owner = User.objects.create(email="bill-o@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="bill-m@example.com", password_hash=make_password("x"))
        self.staff = User.objects.create(email="bill-staff@example.com", password_hash=make_password("x"), is_platform_admin=True)
        OrgMembership.objects.create(org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status="active")
        OrgMembership.objects.create(org=self.org, user=self.member, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status="active")
        self.basic = Plan.objects.create(code="basic", name="Basic", entitlements={"flags": ["buddies"], "limits": {"renders_per_month": 0}}, stripe_price_id="price_basic")
        self.pro = Plan.objects.create(code="pro", name="Pro", entitlements={"flags": ["buddies", "content_studio"]}, stripe_price_id="price_pro")

    def _fresh(self):
        return Organization.objects.get(pk=self.org.pk)

    def _hook(self, event, header=None):
        body = json.dumps(event).encode()
        return self.client.post(
            "/api/v2/billing/stripe/webhook", data=body, content_type="application/json", HTTP_STRIPE_SIGNATURE=header or _sign(body)
        )

    def test_plan_gates_flags_even_when_the_org_turns_them_on(self):
        self.assertTrue(effective_flag(self._fresh(), None, "content_studio"), "no subscription: today's behaviour")
        Subscription.objects.create(org=self.org, plan=self.basic, status="active")
        self.assertTrue(effective_flag(self._fresh(), None, "buddies"))
        self.assertFalse(effective_flag(self._fresh(), None, "content_studio"), "the plan does not include it")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.member.id))}")
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.org.id}/content/projects").status_code, 501)
        Subscription.objects.filter(org=self.org).update(status="canceled")
        self.assertFalse(effective_flag(self._fresh(), None, "buddies"))

    def test_stripe_signature_replay_and_idempotency(self):
        Subscription.objects.create(org=self.org, plan=self.basic, status="active", stripe_subscription_id="sub_1")
        event = {
            "id": "evt_1",
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_1", "status": "active", "items": {"data": [{"price": {"id": "price_pro"}, "quantity": 7}]}}},
        }
        body = json.dumps(event).encode()
        self.assertEqual(self._hook(event, header=_sign(body, secret="wrong")).status_code, 400)
        self.assertEqual(self._hook(event, header=_sign(body, ts=int(time.time()) - 3600)).status_code, 400, "old timestamps are refused")
        self.assertEqual(self._hook(event).json()["result"], "applied")
        self.assertEqual(self._hook(event).json()["result"], "duplicate")
        sub = Subscription.objects.get(org=self.org)
        self.assertEqual((sub.plan.code, sub.seats), ("pro", 7))
        deleted = {"id": "evt_2", "type": "customer.subscription.deleted", "data": {"object": {"id": "sub_1"}}}
        self._hook(deleted)
        self.assertEqual(Subscription.objects.get(org=self.org).status, "canceled")

    def test_checkout_creates_the_subscription(self):
        event = {"id": "evt_c", "type": "checkout.session.completed", "data": {"object": {"customer": "cus_1", "subscription": "sub_9", "payment_status": "paid", "metadata": {"org_id": str(self.org.id), "plan": "pro"}}}}
        self.assertEqual(self._hook(event).json()["result"], "applied")
        self.assertEqual(Subscription.objects.get(org=self.org).plan.code, "pro")
        junk = {"id": "evt_j", "type": "checkout.session.completed", "data": {"object": {"metadata": {"org_id": "nope", "plan": "pro"}}}}
        self.assertEqual(self._hook(junk).json()["result"], "ignored")

    def test_only_platform_admins_write_plans(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.owner.id))}")
        self.assertEqual(self.client.post("/api/v2/platform/plans", {"code": "x", "entitlements": {"flags": []}}, format="json").status_code, 403)
        self.assertEqual(self.client.put(f"/api/v2/platform/orgs/{self.org.id}/subscription", {"plan": "pro"}, format="json").status_code, 403)
        billing = self.client.get(f"/api/v2/orgs/{self.org.id}/billing")
        self.assertEqual(billing.status_code, 200)
        self.assertEqual(billing.json()["usage_this_month"]["byok_markup"], "0")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.member.id))}")
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.org.id}/billing").status_code, 403)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.staff.id))}")
        made = self.client.post("/api/v2/platform/plans", {"code": "team", "entitlements": {"flags": ["buddies"], "limits": {"seats": 10}}}, format="json")
        self.assertEqual(made.status_code, 201)
        self.assertEqual(self.client.put(f"/api/v2/platform/orgs/{self.org.id}/subscription", {"plan": "team"}, format="json").status_code, 200)

    def test_webhook_not_configured_is_refused(self):
        with override_settings(STRIPE_WEBHOOK_SECRET=""):
            self.assertEqual(self._hook({"id": "e", "type": "x"}).status_code, 400)

    def test_unpaid_checkout_ignored_and_ordering(self):
        unpaid = {"id": "evt_u", "type": "checkout.session.completed", "data": {"object": {"subscription": "sub_u", "payment_status": "unpaid", "metadata": {"org_id": str(self.org.id), "plan": "pro"}}}}
        self.assertEqual(self._hook(unpaid).json()["result"], "ignored")
        self.assertFalse(Subscription.objects.filter(org=self.org).exists())
        from billing_v2.models import StripeEvent

        self.assertFalse(StripeEvent.objects.filter(event_id="evt_u").exists(), "ignored events can be retried")
        now = int(time.time())
        Subscription.objects.create(org=self.org, plan=self.basic, status="active", stripe_subscription_id="sub_2")
        deleted = {"id": "evt_d", "created": now, "type": "customer.subscription.deleted", "data": {"object": {"id": "sub_2"}}}
        late = {"id": "evt_l", "created": now - 30, "type": "customer.subscription.updated", "data": {"object": {"id": "sub_2", "status": "active"}}}
        newer = {"id": "evt_n", "created": now + 30, "type": "customer.subscription.updated", "data": {"object": {"id": "sub_2", "status": "active"}}}
        self.assertEqual(self._hook(deleted).json()["result"], "applied")
        self.assertEqual(self._hook(late).json()["result"], "stale")
        self.assertEqual(self._hook(newer).json()["result"], "stale", "canceled is final")
        self.assertEqual(Subscription.objects.get(org=self.org).status, "canceled")
