from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from brain.llm.providers import ProviderResult
from brain.models import Chat
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.services import ensure_team_room
from telemetry.models import Budget, PriceTable, UsageEvent
from telemetry.pricing import estimate_tokens, fill_missing_tokens, platform_budget_blocks
from users.jwt_utils import make_access_token
from users.models import User


class BudgetApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Budget Org", slug="budget-org", settings={"flags": {}})
        self.owner = User.objects.create(email="b-owner@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="b-member@example.com", password_hash=make_password("x"))
        self.outsider = User.objects.create(email="b-out@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(
            org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org, user=self.member, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        self.url = f"/api/v2/orgs/{self.org.id}/budgets"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_flag_off_is_501(self):
        self._auth(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 501)
        self.assertEqual(self.client.put(self.url, {"cap_amount": "1.00"}, format="json").status_code, 501)

    def test_member_cannot_view_or_manage(self):
        self.org.settings = {"flags": {"budgets": True}}
        self.org.save(update_fields=["settings"])
        self._auth(self.member)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.put(self.url, {"cap_amount": "1.00"}, format="json").status_code, 403)
        self._auth(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_owner_sets_cap_when_flag_on(self):
        self.org.settings = {"flags": {"budgets": True}}
        self.org.save(update_fields=["settings"])
        self._auth(self.owner)
        put = self.client.put(self.url, {"cap_amount": "5.00"}, format="json")
        self.assertEqual(put.status_code, 200, put.content)
        got = self.client.get(self.url)
        self.assertEqual(got.json()["cap_amount"], "5.0000")

    def test_invalid_cap_or_currency_is_400(self):
        self.org.settings = {"flags": {"budgets": True}}
        self.org.save(update_fields=["settings"])
        self._auth(self.owner)
        for body in (
            {"cap_amount": "abc"},
            {"cap_amount": "-1"},
            {"cap_amount": "NaN"},
            {},
            {"cap_amount": "5", "currency": "dollars"},
        ):
            res = self.client.put(self.url, body, format="json")
            self.assertEqual(res.status_code, 400, (body, res.content))


class BudgetEnforcementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="Cap Org", slug="cap-org", settings={"flags": {"budgets": True, "room_ai": True}}
        )
        self.owner = User.objects.create(email="c-owner@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="c-member@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(
            org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        OrgMembership.objects.create(
            org=self.org, user=self.member, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status=OrgMembership.STATUS_ACTIVE
        )
        team = Team.objects.create(org=self.org, name="Cap")
        TeamMembership.objects.create(team=team, user=self.member)
        self.room = ensure_team_room(team)
        PriceTable.objects.create(
            provider="platform",
            model="qwen",
            input_price=Decimal("1000000"),
            output_price=Decimal("1000000"),
        )
        Budget.objects.create(org=self.org, cap_amount=Decimal("1.00"))
        UsageEvent.objects.create(
            org=self.org,
            user=self.member,
            model="qwen",
            provider="platform",
            total_tokens=1,
            credential_source=UsageEvent.CREDENTIAL_PLATFORM,
        )

    def test_over_cap_platform_is_rejected_customer_is_not(self):
        self.assertEqual(
            platform_budget_blocks(self.org, self.member, UsageEvent.CREDENTIAL_PLATFORM),
            "budget_exceeded",
        )
        self.assertEqual(platform_budget_blocks(self.org, self.member, UsageEvent.CREDENTIAL_CUSTOMER), "")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.member.id))}")
        created = self.client.post(
            f"/api/v2/orgs/{self.org.id}/rooms/{self.room.id}/ai/threads",
            {},
            format="json",
        )
        thread_id = created.json()["id"]
        with patch("brain.v2_views.get_provider") as get_provider:
            get_provider.return_value.complete.return_value = ProviderResult(text="ok", model="qwen", total_tokens=1)
            sent = self.client.post(
                f"/api/v2/orgs/{self.org.id}/ai/threads/{thread_id}/send",
                {"text": "hi"},
                format="json",
            )
        self.assertEqual(sent.status_code, 429)
        self.assertEqual(sent.json()["error"], "budget_exceeded")

    def test_missing_tokens_become_an_estimate(self):
        result = ProviderResult(text="hello", model="legacy", total_tokens=None)
        filled, estimated = fill_missing_tokens(result, "hello there")
        self.assertTrue(estimated)
        self.assertIsNotNone(filled.total_tokens)
        self.assertNotEqual(filled.total_tokens, 0)
        self.assertGreaterEqual(estimate_tokens("hello there"), 1)


class PricingMathTests(TestCase):
    """Cost uses both input and output prices; a total without a split uses the higher price."""

    def setUp(self):
        self.org = Organization.objects.create(name="Price Org", slug="price-org", settings={"flags": {}})
        self.user = User.objects.create(email="price@example.com", password_hash=make_password("x"))
        PriceTable.objects.create(
            provider="openai", model="m1", input_price=Decimal("1.00"), output_price=Decimal("10.00")
        )

    def _event(self, **kw):
        from telemetry.pricing import money_for_event

        row = UsageEvent.objects.create(
            org=self.org, user=self.user, provider="openai", model="m1",
            credential_source=UsageEvent.CREDENTIAL_PLATFORM, **kw
        )
        return money_for_event(row)

    def test_input_and_output_are_priced_separately(self):
        cost = self._event(input_tokens=1_000_000, output_tokens=1_000_000, total_tokens=2_000_000)
        self.assertEqual(cost, Decimal("11.00"))

    def test_total_only_uses_the_higher_price(self):
        cost = self._event(input_tokens=None, output_tokens=None, total_tokens=1_000_000)
        self.assertEqual(cost, Decimal("10.00"))

    def test_customer_key_is_never_platform_spend(self):
        from telemetry.pricing import money_for_event

        row = UsageEvent.objects.create(
            org=self.org, user=self.user, provider="openai", model="m1", total_tokens=1000,
            credential_source=UsageEvent.CREDENTIAL_CUSTOMER,
        )
        self.assertIsNone(money_for_event(row))

    def test_unknown_provider_has_no_price(self):
        from telemetry.pricing import money_for_event

        row = UsageEvent.objects.create(
            org=self.org, user=self.user, provider="other", model="m1", total_tokens=1000,
            credential_source=UsageEvent.CREDENTIAL_PLATFORM,
        )
        self.assertIsNone(money_for_event(row))

    def test_estimate_covers_prompt_and_reply(self):
        result = ProviderResult(text="a reply with several words", model="legacy", total_tokens=None)
        filled, estimated = fill_missing_tokens(result, "system line\nuser history\nnew question", result.text)
        self.assertTrue(estimated)
        self.assertGreater(filled.input_tokens, 0)
        self.assertGreater(filled.output_tokens, 0)
        self.assertEqual(filled.total_tokens, filled.input_tokens + filled.output_tokens)

