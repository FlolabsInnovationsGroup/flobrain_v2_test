"""Workspace pricing (M8): calculator math, seat cap on every add path, plan switching, webhook,
config-only prices. The calculator vectors here are the same as in
flobrain-website/src/components/v2/billing/pricing.test.ts."""

import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from billing_v2 import pricing, sample_plans, stripe
from billing_v2.entitlements import ai_allowance, seat_blocked, seat_error, seat_limit
from billing_v2.models import Invoice, Plan, Subscription
from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User

SECRET = "whsec_test_not_live"
FLAGS = {"workspace_pricing": True}

# (team, interval) -> (fleet per month, fleet per year, studio per month, studio per year, cheaper)
VECTORS = {
    (1, "month"): (1200, 14400, 19900, 238800, "fleet"),
    (10, "month"): (12000, 144000, 19900, 238800, "fleet"),
    (16, "month"): (19200, 230400, 19900, 238800, "fleet"),
    (17, "month"): (20400, 244800, 19900, 238800, "studio"),
    (25, "month"): (30000, 360000, 19900, 238800, "studio"),
    (26, "month"): (31200, 374400, None, None, "fleet"),
    (1, "year"): (1000, 12000, 16500, 198000, "fleet"),
    (16, "year"): (16000, 192000, 16500, 198000, "fleet"),
    (17, "year"): (17000, 204000, 16500, 198000, "studio"),
    (25, "year"): (25000, 300000, 16500, 198000, "studio"),
    (26, "year"): (26000, 312000, None, None, "fleet"),
}


def _user(email, **extra):
    return User.objects.create(email=email, password_hash=make_password("x"), **extra)


def _sign(body: bytes, secret=SECRET):
    ts = int(time.time())
    return f"t={ts},v1={hmac.new(secret.encode(), f'{ts}.'.encode() + body, hashlib.sha256).hexdigest()}"


class CalculatorMathTests(TestCase):
    def setUp(self):
        self.plans = sample_plans.ensure()

    def test_vectors_match_the_frontend(self):
        plans = [self.plans["fleet"], self.plans["studio"]]
        for (team, interval), (fm, fy, sm, sy, cheaper) in VECTORS.items():
            out = pricing.calculate(plans, team, interval)
            rows = {r["code"]: r for r in out["plans"]}
            self.assertEqual((rows["fleet"]["per_month_cents"], rows["fleet"]["per_year_cents"]), (fm, fy), (team, interval))
            self.assertEqual((rows["studio"]["per_month_cents"], rows["studio"]["per_year_cents"]), (sm, sy), (team, interval))
            self.assertEqual(out["cheaper"], cheaper, (team, interval))
            self.assertTrue(out["sample"])

    def test_edge_at_the_cap_and_break_even(self):
        plans = [self.plans["fleet"], self.plans["studio"]]
        at_cap = pricing.calculate(plans, 25, "month")
        self.assertTrue({r["code"]: r for r in at_cap["plans"]}["studio"]["available"])
        over = pricing.calculate(plans, 26, "month")
        studio = {r["code"]: r for r in over["plans"]}["studio"]
        self.assertEqual((studio["available"], studio["reason"]), (False, "over_cap"))
        self.assertEqual(over["comparisons"][0]["savings_per_year_cents"], 0)
        self.assertEqual(at_cap["comparisons"][0]["break_even"], 17)
        self.assertEqual(pricing.calculate(plans, 3, "year")["comparisons"][0]["break_even"], 17)
        self.assertEqual(pricing.calculate(plans, 17, "month")["comparisons"][0]["savings_per_year_cents"], 244800 - 238800)

    def test_prices_come_from_plan_rows(self):
        Plan.objects.filter(code="studio").update(price_cents=50000, price_yearly_cents=0)
        plans = list(Plan.objects.filter(code__in=["fleet", "studio"]))
        rows = {r["code"]: r for r in pricing.calculate(plans, 20, "year")["plans"]}
        self.assertEqual(rows["studio"]["per_year_cents"], 600000, "0 yearly = 12 x monthly")
        self.assertEqual(pricing.calculate(plans, 20, "month")["cheaper"], "fleet")
        with override_settings(BILLING_PRICES_CONFIRMED=True):
            self.assertFalse(pricing.calculate(plans, 20, "month")["sample"])

    def test_no_price_or_stripe_id_written_in_code_paths(self):
        here = Path(__file__).resolve().parent
        for name in ("pricing.py", "views.py", "stripe.py", "entitlements.py", "switching.py"):
            source = (here / name).read_text()
            self.assertIsNone(re.search(r"price_[A-Za-z0-9]{8,}", source), f"Stripe price id in {name}")
            for cents in ("1200", "12000", "19900", "198000"):
                self.assertNotIn(cents, source, f"sample price in {name}")


@override_settings(STRIPE_WEBHOOK_SECRET=SECRET)
class WorkspacePlanTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="W", slug="w-price", settings={"flags": dict(FLAGS)})
        self.owner, self.admin, self.member = _user("w-o@example.com"), _user("w-a@example.com"), _user("w-m@example.com")
        for user, role in ((self.owner, "owner"), (self.admin, "admin"), (self.member, "member")):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status="active")
        self.plans = sample_plans.ensure()
        self.studio, self.fleet = self.plans["studio"], self.plans["fleet"]
        Plan.objects.filter(pk=self.studio.pk).update(included_seats=4)
        self.studio.refresh_from_db()
        self.base = f"/api/v2/orgs/{self.org.id}/billing"

    def c(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return client

    def _on_studio(self, **extra):
        return Subscription.objects.create(org=self.org, plan=self.studio, status="active", seats=4, **extra)

    # --- seat cap -------------------------------------------------------------------------
    def test_workspace_cap_is_enforced_even_without_global_enforcement(self):
        self.assertIsNone(seat_limit(self.org), "no subscription: today's behaviour")
        self._on_studio()
        self.assertEqual(seat_limit(self.org), 4)
        self.assertIsNone(seat_blocked(self.org, email="new1@example.com"), "3 of 4 used")
        OrgMembership.objects.create(org=self.org, user=_user("w-4@example.com"), org_role="member", employment_status="active")
        self.assertEqual(seat_blocked(self.org, email="new2@example.com"), 4)
        self.assertIsNone(seat_blocked(self.org, adding_user_id=self.member.id), "already holds a seat")
        body = seat_error(self.org, 4)
        self.assertEqual(body["error"], "seat_limit")
        self.assertIn("up to 4 people", body["details"])
        self.assertEqual(body["upgrade"]["plan"], "fleet", "prompt_upgrade suggests the per-person plan")
        Plan.objects.filter(pk=self.studio.pk).update(overage_policy="block")
        self.assertNotIn("upgrade", seat_error(self.org, 4))

    def test_cap_blocks_register_reactivate_and_scim_paths(self):
        self._on_studio()
        OrgMembership.objects.create(org=self.org, user=_user("w-4@example.com"), org_role="member", employment_status="active")
        gone = OrgMembership.objects.create(org=self.org, user=_user("w-gone@example.com"), org_role="member", employment_status="terminated")
        res = self.c(self.owner).post(f"/api/v2/orgs/{self.org.id}/members", {"email": "extra@example.com"}, format="json")
        self.assertEqual((res.status_code, res.json().get("error")), (409, "seat_limit"), res.content)
        back = self.c(self.owner).patch(f"/api/v2/orgs/{self.org.id}/members/{gone.user_id}", {"employment_status": "active"}, format="json")
        self.assertEqual((back.status_code, back.json().get("error")), (409, "seat_limit"), back.content)
        Subscription.objects.filter(org=self.org).update(status="canceled")
        self.assertIsNone(seat_limit(self.org), "canceled workspace plan: back to today's rule")

    def test_ai_allowance_is_per_workspace(self):
        self.assertIsNone(ai_allowance(self.org))
        self._on_studio()
        self.assertEqual(ai_allowance(self.org), 30000)
        data = self.c(self.owner).get(self.base).json()["workspace_pricing"]
        self.assertEqual((data["ai"]["basis"], data["ai"]["total"]), ("per_workspace", 30000))
        self.assertEqual((data["seat_status"]["limit"], data["seat_status"]["used"]), (4, 3))
        self.assertTrue(data["sample"])

    # --- flag and permissions -------------------------------------------------------------
    def test_flag_off_hides_workspace_plans_and_endpoints(self):
        self.org.settings = {"flags": {}}
        self.org.save()
        data = self.c(self.owner).get(self.base).json()
        self.assertNotIn("workspace_pricing", data)
        self.assertNotIn("studio", [p["code"] for p in data["plans"]])
        self.assertEqual(self.c(self.owner).post(f"{self.base}/switch", {"plan": "studio"}, format="json").status_code, 501)
        self.assertEqual(self.c(self.owner).get(f"{self.base}/invoices").status_code, 501)
        with override_settings(DEMO_MODE=True):
            self.assertEqual(self.c(self.owner).post(f"{self.base}/checkout", {"plan": "studio"}, format="json").status_code, 501)

    def test_only_the_owner_switches_and_members_cannot_see_invoices(self):
        self.assertEqual(self.c(self.admin).post(f"{self.base}/switch", {"plan": "studio"}, format="json").status_code, 403)
        self.assertEqual(self.c(self.member).post(f"{self.base}/switch", {"plan": "studio"}, format="json").status_code, 403)
        self.assertEqual(self.c(self.member).get(f"{self.base}/invoices").status_code, 403)
        self.assertEqual(self.c(self.admin).get(f"{self.base}/invoices").status_code, 200)

    # --- switching --------------------------------------------------------------------------
    def test_switch_validation(self):
        owner = self.c(self.owner)
        Subscription.objects.create(org=self.org, plan=self.fleet, status="active", seats=3)
        self.assertEqual(owner.post(f"{self.base}/switch", {"plan": "nope"}, format="json").status_code, 404)
        self.assertEqual(owner.post(f"{self.base}/switch", {"plan": "studio", "interval": "week"}, format="json").status_code, 400)
        self.assertEqual(owner.post(f"{self.base}/switch", {"plan": "fleet", "seats": 2}, format="json").json()["details"], "You have 3 people. Choose at least 3 seats.")
        self.assertEqual(owner.post(f"{self.base}/switch", {"plan": "fleet", "seats": "x"}, format="json").status_code, 400)
        self.assertEqual(owner.post(f"{self.base}/switch", {"plan": "fleet", "seats": 3}, format="json").json()["error"], "no_change")
        for i in range(2):
            OrgMembership.objects.create(org=self.org, user=_user(f"w-x{i}@example.com"), org_role="member", employment_status="active")
        full = owner.post(f"{self.base}/switch", {"plan": "studio"}, format="json")
        self.assertEqual((full.status_code, full.json()["error"], full.json()["used"]), (409, "seat_limit", 5))

    def test_preview_states_exactly_what_changes(self):
        Subscription.objects.create(org=self.org, plan=self.fleet, status="active", seats=3, interval="month")
        preview = self.c(self.owner).post(f"{self.base}/switch", {"plan": "studio", "interval": "year"}, format="json").json()
        self.assertTrue(preview["preview"])
        self.assertEqual((preview["from"]["charge_cents"], preview["to"]["charge_cents"]), (3600, 198000))
        keys = {c["key"]: c for c in preview["changes"]}
        self.assertEqual(set(keys), {"plan", "billing_unit", "interval", "seats", "charge_cents", "ai", "seat_cap"})
        self.assertEqual(keys["seats"]["to"], 4)
        self.assertEqual(keys["ai"]["to"]["basis"], "per_workspace")
        self.assertEqual(preview["proration"], "stripe")
        self.assertEqual(Subscription.objects.get(org=self.org).plan.code, "fleet", "a preview changes nothing")

    @override_settings(DEMO_MODE=True)
    def test_demo_switch_applies_and_back(self):
        Subscription.objects.create(org=self.org, plan=self.fleet, status="active", seats=3)
        done = self.c(self.owner).post(f"{self.base}/switch", {"plan": "studio", "confirm": True}, format="json").json()
        self.assertEqual((done["mode"], done["status"]), ("demo", "applied"))
        sub = Subscription.objects.get(org=self.org)
        self.assertEqual((sub.plan.code, sub.seats), ("studio", 4))
        back = self.c(self.owner).post(f"{self.base}/switch", {"plan": "fleet", "seats": 5, "interval": "year", "confirm": True}, format="json").json()
        self.assertEqual(back["status"], "applied")
        sub.refresh_from_db()
        self.assertEqual((sub.plan.code, sub.seats, sub.interval), ("fleet", 5, "year"))

    @override_settings(STRIPE_SECRET_KEY="sk_test_x")
    def test_stripe_switch_prorates_and_waits_for_the_webhook(self):
        sub = Subscription.objects.create(org=self.org, plan=self.fleet, status="active", seats=3, stripe_customer_id="cus_1", stripe_subscription_id="sub_live1")
        calls = []

        def fake(method, path, params):
            calls.append((method, path, params))
            return {"items": {"data": [{"id": "si_1"}]}} if method == "GET" else {"id": "sub_live1", "status": "active"}

        with patch.dict("os.environ", {"STRIPE_PRICE_STUDIO_MONTH": "price_env_studio_m"}), patch("billing_v2.stripe._request", side_effect=fake):
            res = self.c(self.owner).post(f"{self.base}/switch", {"plan": "studio", "confirm": True}, format="json")
        self.assertEqual(res.json()["status"], "pending", res.content)
        self.assertEqual(calls[0][:2], ("GET", "/subscriptions/sub_live1"))
        posted = calls[1][2]
        self.assertEqual(posted["proration_behavior"], "create_prorations")
        self.assertEqual(posted["items"], [{"id": "si_1", "price": "price_env_studio_m", "quantity": 1}])
        sub.refresh_from_db()
        self.assertEqual(sub.plan.code, "fleet", "changes only when Stripe confirms")
        with patch("billing_v2.stripe._request", side_effect=fake):
            self.assertEqual(self.c(self.owner).post(f"{self.base}/switch", {"plan": "studio", "interval": "year", "confirm": True}, format="json").status_code, 501, "no price id in env")
        with self.assertRaises(stripe.StripeAPIError):
            stripe.change_subscription("sub_../../x", self.studio, "month", 1)

    def test_price_ids_come_from_the_environment(self):
        self.assertEqual(stripe.price_id(self.studio, "year"), "")
        with patch.dict("os.environ", {"STRIPE_PRICE_STUDIO_YEAR": "price_env_y"}):
            self.assertEqual(stripe.price_id(self.studio, "year"), "price_env_y")
            self.assertEqual(stripe.plan_for_price("price_env_y")[0].code, "studio")
        with override_settings(STRIPE_PRICE_IDS={"fleet": {"month": "price_set_m"}}):
            self.assertEqual(stripe.plan_for_price("price_set_m"), (Plan.objects.get(code="fleet"), "month"))

    # --- webhook ---------------------------------------------------------------------------
    def _hook(self, event, header=None):
        body = json.dumps(event).encode()
        return APIClient().post("/api/v2/billing/stripe/webhook", data=body, content_type="application/json", HTTP_STRIPE_SIGNATURE=header or _sign(body))

    def test_webhook_still_verified_and_applies_workspace_plan(self):
        sub = Subscription.objects.create(org=self.org, plan=self.fleet, status="active", seats=3, stripe_subscription_id="sub_w1", stripe_customer_id="cus_w")
        event = {
            "id": "evt_w1",
            "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_w1", "status": "active", "items": {"data": [{"price": {"id": "price_env_sy", "recurring": {"interval": "year"}}, "quantity": 1}]}}},
        }
        body = json.dumps(event).encode()
        self.assertEqual(self._hook(event, header=_sign(body, secret="wrong")).status_code, 400)
        with patch.dict("os.environ", {"STRIPE_PRICE_STUDIO_YEAR": "price_env_sy"}):
            self.assertEqual(self._hook(event).json()["result"], "applied")
        sub.refresh_from_db()
        self.assertEqual((sub.plan.code, sub.interval, sub.seats), ("studio", "year", 4), "seats follow the plan's cap, not quantity 1")
        invoice = {
            "id": "evt_i1",
            "type": "invoice.paid",
            "data": {"object": {"id": "in_1", "subscription": "sub_w1", "number": "FB-1", "amount_paid": 198000, "currency": "usd", "hosted_invoice_url": "https://evil.example.com/x"}},
        }
        self.assertEqual(self._hook(invoice).json()["result"], "applied")
        row = Invoice.objects.get(stripe_invoice_id="in_1")
        self.assertEqual((row.amount_cents, row.status, row.hosted_url), (198000, "paid", ""), "only Stripe invoice hosts are kept")
        stranger = {"id": "evt_i2", "type": "invoice.paid", "data": {"object": {"id": "in_2", "subscription": "sub_unknown"}}}
        self.assertEqual(self._hook(stranger).json()["result"], "ignored")

    # --- platform plan fields --------------------------------------------------------------
    def test_platform_admin_sets_workspace_fields(self):
        staff = self.c(_user("w-staff@example.com", is_platform_admin=True))
        bad = staff.post("/api/v2/platform/plans", {"code": "hub", "entitlements": {"flags": []}, "billing_unit": "per_workspace"}, format="json")
        self.assertEqual(bad.status_code, 400, "a workspace plan needs a cap")
        made = staff.post(
            "/api/v2/platform/plans",
            {"code": "hub", "entitlements": {"flags": []}, "billing_unit": "per_workspace", "included_seats": 50, "price_cents": 100, "ai_allowance_per_workspace": 9, "overage_policy": "prompt_upgrade", "tier": "x"},
            format="json",
        ).json()
        self.assertEqual((made["billing_unit"], made["included_seats"], made["price_yearly_cents"]), ("per_workspace", 50, 1200))
        self.assertEqual(staff.post("/api/v2/platform/plans", {"code": "hub", "entitlements": {"flags": []}, "overage_policy": "charge"}, format="json").status_code, 400)


class CalculatorEndpointTests(TestCase):
    url = "/api/v2/pricing/calculator"

    def setUp(self):
        cache.clear()
        sample_plans.ensure()

    def test_off_by_default(self):
        self.assertEqual(APIClient().get(self.url, {"team": 5}).status_code, 501)

    @override_settings(WORKSPACE_PRICING_PUBLIC=True)
    def test_public_validated_and_rate_limited(self):
        client = APIClient()
        data = client.get(self.url, {"team": 17, "interval": "year"}).json()
        self.assertEqual((data["cheaper"], data["interval"], data["sample"]), ("studio", "year", True))
        self.assertEqual(client.get(self.url, {"team": 0}).status_code, 400)
        self.assertEqual(client.get(self.url, {"team": "a"}).status_code, 400)
        self.assertEqual(client.get(self.url, {"team": 3, "interval": "week"}).status_code, 400)
        codes = [client.get(self.url, {"team": 3}).status_code for _ in range(40)]
        self.assertIn(429, codes)


class DemoSeedTests(TestCase):
    def test_demo_org_is_on_the_workspace_plan_with_8_of_25(self):
        import importlib

        from django.utils import timezone

        module = importlib.import_module("demo.extras.a8_pricing")
        org = Organization.objects.create(name="Demo", slug="demo-m8", settings={"demo": True, "flags": dict(FLAGS)})
        owner = _user("owner@demo-m8.example.com")
        OrgMembership.objects.create(org=org, user=owner, org_role="owner", employment_status="active")
        sub = module.seed(org, {"owner": owner}, timezone.now())
        self.assertEqual((sub.plan.code, sub.plan.billing_unit), ("studio", "per_workspace"))
        self.assertEqual((seat_limit(org), OrgMembership.objects.filter(org=org).count()), (25, 7), "1 + 6 demo people: all it has")
        invoices = list(Invoice.objects.filter(org=org).order_by("created_at"))
        self.assertEqual([i.status for i in invoices], ["paid", "paid", "paid", "draft"])
        self.assertEqual(invoices[-1].amount_cents, Plan.objects.get(code="studio").price_cents, "amounts come from the plan rows")
        self.assertTrue(all(i.demo and not i.hosted_url for i in invoices))
        module.seed(org, {"owner": owner}, timezone.now())
        self.assertEqual(Invoice.objects.filter(org=org).count(), 4, "seeding twice does not duplicate")

    def test_demo_tops_up_to_eight(self):
        import importlib

        from django.utils import timezone

        module = importlib.import_module("demo.extras.a8_pricing")
        org = Organization.objects.create(name="Demo", slug="demo-m8b", settings={"demo": True})
        for i in range(5):
            OrgMembership.objects.create(org=org, user=_user(f"d{i}@demo-m8.example.com"), org_role="member", employment_status="active")
        module.seed(org, {}, timezone.now())
        self.assertEqual(OrgMembership.objects.filter(org=org).count(), 8)
