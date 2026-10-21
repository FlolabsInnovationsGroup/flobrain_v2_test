from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import Notification
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from telemetry.models import Budget, PriceTable, UsageEvent
from telemetry.pricing import (
    budget_decision,
    check_alerts,
    money_for_render,
    platform_budget_blocks,
    scope_spend,
)
from users.jwt_utils import make_access_token
from users.models import User

PLATFORM = UsageEvent.CREDENTIAL_PLATFORM


def _member(org, email, role=OrgMembership.ORG_ROLE_MEMBER, status=OrgMembership.STATUS_ACTIVE):
    user = User.objects.create(email=email, username=email.split("@")[0], password_hash=make_password("x"))
    OrgMembership.objects.create(org=org, user=user, org_role=role, employment_status=status)
    return user


class ScopedBudgetBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Scope Org", slug="scope-org", settings={"flags": {"budgets": True}})
        self.other = Organization.objects.create(name="Other", slug="scope-other", settings={"flags": {"budgets": True}})
        self.owner = _member(self.org, "s-owner@example.com", OrgMembership.ORG_ROLE_OWNER)
        self.admin = _member(self.org, "s-admin@example.com", OrgMembership.ORG_ROLE_ADMIN)
        self.lead = _member(self.org, "s-lead@example.com")
        self.member = _member(self.org, "s-member@example.com")
        self.peer = _member(self.org, "s-peer@example.com")
        self.outsider = _member(self.other, "s-out@example.com", OrgMembership.ORG_ROLE_OWNER)
        self.team = Team.objects.create(org=self.org, name="Eng")
        self.other_team = Team.objects.create(org=self.other, name="Elsewhere")
        TeamMembership.objects.create(team=self.team, user=self.lead, team_role=TeamMembership.ROLE_LEAD)
        TeamMembership.objects.create(team=self.team, user=self.member)
        # 1 token = 1.00 at this price
        PriceTable.objects.create(provider="p", model="m", input_price=Decimal("1000000"), output_price=Decimal("1000000"))
        self.base = f"/api/v2/orgs/{self.org.id}/budgets"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _spend(self, user, tokens, source=PLATFORM, team=None, org=None):
        UsageEvent.objects.create(
            org=org or self.org, user=user, provider="p", model="m", total_tokens=tokens, credential_source=source, team=team
        )


class ScopeSpendTests(ScopedBudgetBase):
    def test_spend_per_scope(self):
        self._spend(self.member, 3)
        self._spend(self.peer, 2)
        self._spend(self.member, 50, source=UsageEvent.CREDENTIAL_CUSTOMER)  # own key: never metered
        self._spend(self.member, 7, org=self.other)  # other org
        self._spend(self.peer, 4, team=self.team)  # tagged with the team although not a member
        self.assertEqual(scope_spend(self.org), Decimal("9"))
        self.assertEqual(scope_spend(self.org, Budget.SCOPE_USER, self.member.id), Decimal("3"))
        self.assertEqual(scope_spend(self.org, Budget.SCOPE_TEAM, self.team.id), Decimal("7"))

    def test_last_month_does_not_count(self):
        UsageEvent.objects.create(
            org=self.org, user=self.member, provider="p", model="m", total_tokens=9, credential_source=PLATFORM,
            created_at=timezone.now().replace(day=1) - timedelta(days=2),
        )
        self.assertEqual(scope_spend(self.org), Decimal("0"))

    def test_gpu_render_seconds_count_when_priced(self):
        from content_studio.models import ContentProject, RenderJob

        project = ContentProject.objects.create(org=self.org, owner=self.member, title="Clip")
        job = RenderJob.objects.create(org=self.org, project=project, requested_by=self.member, preset="9x16_1080", gpu_seconds=10)
        self.assertIsNone(money_for_render(job), "no GPU price yet: not counted")
        self.assertEqual(scope_spend(self.org), Decimal("0"))
        PriceTable.objects.create(
            provider=PriceTable.GPU_PROVIDER, model=PriceTable.GPU_MODEL, unit=PriceTable.UNIT_GPU_SECOND,
            input_price=Decimal("0.5"), output_price=Decimal("0"), valid_from=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(scope_spend(self.org), Decimal("5.0"))
        self.assertEqual(scope_spend(self.org, Budget.SCOPE_USER, self.member.id), Decimal("5.0"))
        self.assertEqual(scope_spend(self.org, Budget.SCOPE_USER, self.peer.id), Decimal("0"))
        self.assertEqual(scope_spend(self.org, Budget.SCOPE_TEAM, self.team.id), Decimal("5.0"))


class BudgetBehaviourTests(ScopedBudgetBase):
    def test_user_budget_blocks_only_that_user(self):
        Budget.objects.create(org=self.org, scope_type="user", scope_id=self.member.id, cap_amount=Decimal("2"))
        self._spend(self.member, 3)
        self.assertEqual(platform_budget_blocks(self.org, self.member, PLATFORM), "budget_exceeded")
        self.assertEqual(platform_budget_blocks(self.org, self.peer, PLATFORM), "")
        self.assertEqual(platform_budget_blocks(self.org, self.member, UsageEvent.CREDENTIAL_CUSTOMER), "")

    def test_team_budget_applies_to_its_members(self):
        Budget.objects.create(org=self.org, scope_type="team", scope_id=self.team.id, cap_amount=Decimal("2"))
        self._spend(self.lead, 3)
        self.assertEqual(platform_budget_blocks(self.org, self.member, PLATFORM), "budget_exceeded")
        self.assertEqual(platform_budget_blocks(self.org, self.peer, PLATFORM), "")

    def test_downgrade_and_alert_only_do_not_block(self):
        budget = Budget.objects.create(
            org=self.org, scope_type="user", scope_id=self.member.id, cap_amount=Decimal("1"),
            on_exceed=Budget.ON_DOWNGRADE, downgrade_model="small",
        )
        self._spend(self.member, 2)
        decision = budget_decision(self.org, self.member, PLATFORM)
        self.assertEqual(decision.code, "")
        self.assertEqual(decision.downgrade_model, "small")
        self.assertEqual(platform_budget_blocks(self.org, self.member, PLATFORM), "", "existing callers only see blocks")
        self.assertEqual(budget_decision(self.org, self.member, UsageEvent.CREDENTIAL_CUSTOMER).downgrade_model, "", "BYOK is never downgraded")
        budget.on_exceed, budget.downgrade_model = Budget.ON_ALERT, ""
        budget.save()
        decision = budget_decision(self.org, self.member, PLATFORM)
        self.assertEqual((decision.code, decision.downgrade_model), ("", ""))

    def test_block_wins_over_downgrade(self):
        Budget.objects.create(
            org=self.org, scope_type="user", scope_id=self.member.id, cap_amount=Decimal("1"),
            on_exceed=Budget.ON_DOWNGRADE, downgrade_model="small",
        )
        Budget.objects.create(org=self.org, cap_amount=Decimal("1"))
        self._spend(self.member, 2)
        self.assertEqual(budget_decision(self.org, self.member, PLATFORM).code, "budget_exceeded")

    def test_flag_off_never_blocks(self):
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        Budget.objects.create(org=self.org, cap_amount=Decimal("0"))
        self.assertEqual(platform_budget_blocks(self.org, self.member, PLATFORM), "")


class BudgetAlertTests(ScopedBudgetBase):
    def test_alert_at_threshold_once_per_period_to_owners_and_admins(self):
        Budget.objects.create(org=self.org, scope_type="team", scope_id=self.team.id, cap_amount=Decimal("10"))
        self._spend(self.member, 7)
        self.assertEqual(check_alerts(self.org), 0, "70% is below the 80% threshold")
        self._spend(self.member, 2)
        self.assertEqual(check_alerts(self.org), 1)
        self.assertEqual(check_alerts(self.org), 0, "one alert per period")
        budget_decision(self.org, self.member, PLATFORM)
        alerts = Notification.objects.filter(org=self.org, kind="budget_alert")
        self.assertEqual({n.user_id for n in alerts}, {self.owner.id, self.admin.id})
        payload = alerts.first().payload
        self.assertEqual(payload["percent"], 90)
        self.assertEqual(payload["scope"], "Eng")
        self.assertEqual(payload["link"], "settings/budgets")
        self.assertFalse(Notification.objects.filter(kind="budget_alert", user=self.outsider).exists())

    def test_new_limit_re_arms_the_alert(self):
        self._auth(self.owner)
        created = self.client.post(self.base, {"scope_type": "user", "scope_id": str(self.member.id), "cap_amount": "10"}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self._spend(self.member, 9)
        self.assertEqual(check_alerts(self.org), 1)
        self.client.patch(f"{self.base}/{created.json()['id']}", {"cap_amount": "11"}, format="json")
        self.assertEqual(check_alerts(self.org), 1)


class BudgetApiScopeTests(ScopedBudgetBase):
    def test_create_list_update_delete(self):
        self._auth(self.admin)
        team = self.client.post(
            self.base,
            {"scope_type": "team", "scope_id": str(self.team.id), "cap_amount": "20", "on_exceed": "alert_only"},
            format="json",
        )
        self.assertEqual(team.status_code, 201, team.content)
        self.assertEqual(team.json()["scope_name"], "Eng")
        user = self.client.post(
            self.base, {"scope_type": "user", "scope_id": str(self.member.id), "limit_amount": "5", "alert_threshold": "0.5"}, format="json"
        )
        self.assertEqual(user.status_code, 201, user.content)
        self.assertEqual(user.json()["on_exceed"], "block")
        dup = self.client.post(self.base, {"scope_type": "user", "scope_id": str(self.member.id), "cap_amount": "5"}, format="json")
        self.assertEqual(dup.status_code, 409)
        put = self.client.put(self.base, {"cap_amount": "100"}, format="json")
        self.assertEqual(put.status_code, 200)
        listed = self.client.get(self.base).json()
        self.assertEqual(listed["cap_amount"], "100.0000", "the old single-budget shape still works")
        self.assertEqual([r["scope_type"] for r in listed["results"]], ["org", "team", "user"])
        self._spend(self.member, 4)
        status = self.client.get(f"{self.base}/status").json()
        by_scope = {r["scope_type"]: r for r in status["results"]}
        self.assertEqual(by_scope["user"]["state"], "alert")
        self.assertEqual(by_scope["user"]["spent"], "4.0000")
        self.assertEqual(status["spent"], "4.0000")
        patched = self.client.patch(f"{self.base}/{user.json()['id']}", {"on_exceed": "alert_only"}, format="json")
        self.assertEqual(patched.json()["on_exceed"], "alert_only")
        self.assertEqual(self.client.delete(f"{self.base}/{team.json()['id']}").status_code, 204)
        self.assertFalse(Budget.objects.filter(pk=team.json()["id"]).exists())

    def test_bad_input_is_400_and_unknown_targets_404(self):
        self._auth(self.owner)
        for body in (
            {"scope_type": "galaxy", "cap_amount": "1"},
            {"scope_type": "user", "scope_id": str(self.member.id), "cap_amount": "-1"},
            {"scope_type": "user", "scope_id": str(self.member.id), "cap_amount": "1", "on_exceed": "explode"},
            {"scope_type": "user", "scope_id": str(self.member.id), "cap_amount": "1", "on_exceed": "downgrade"},
            {"scope_type": "user", "scope_id": str(self.member.id), "cap_amount": "1", "on_exceed": "downgrade", "downgrade_model": "not-a-platform-model"},
            {"scope_type": "user", "scope_id": str(self.member.id), "cap_amount": "1", "alert_threshold": "2"},
            {"scope_type": "user", "scope_id": str(self.member.id), "cap_amount": "1", "currency": "dollars"},
        ):
            res = self.client.post(self.base, body, format="json")
            self.assertEqual(res.status_code, 400, (body, res.content))
        self.assertEqual(
            self.client.post(self.base, {"scope_type": "team", "scope_id": str(self.other_team.id), "cap_amount": "1"}, format="json").status_code, 404
        )
        self.assertEqual(
            self.client.post(self.base, {"scope_type": "user", "scope_id": str(self.outsider.id), "cap_amount": "1"}, format="json").status_code, 404
        )
        self.assertEqual(self.client.post(self.base, {"scope_type": "user", "scope_id": "nope", "cap_amount": "1"}, format="json").status_code, 404)

    @override_settings(AI_DIRECT_MODEL_ALLOWLIST="big,small")
    def test_downgrade_model_must_be_a_platform_model(self):
        self._auth(self.owner)
        ok = self.client.post(
            self.base,
            {"scope_type": "user", "scope_id": str(self.member.id), "cap_amount": "1", "on_exceed": "downgrade", "downgrade_model": "small"},
            format="json",
        )
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(ok.json()["downgrade_model"], "small")

    def test_members_and_other_orgs_cannot_manage(self):
        budget = Budget.objects.create(org=self.org, scope_type="user", scope_id=self.member.id, cap_amount=Decimal("1"))
        self._auth(self.member)
        self.assertEqual(self.client.post(self.base, {"scope_type": "org", "cap_amount": "1"}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"{self.base}/{budget.id}", {"cap_amount": "9"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"{self.base}/{budget.id}").status_code, 403)
        self.assertEqual(self.client.get(f"{self.base}/status").status_code, 403)
        self._auth(self.outsider)
        self.assertEqual(self.client.patch(f"{self.base}/{budget.id}", {"cap_amount": "9"}, format="json").status_code, 403)
        other_base = f"/api/v2/orgs/{self.other.id}/budgets"
        self.assertEqual(self.client.patch(f"{other_base}/{budget.id}", {"cap_amount": "9"}, format="json").status_code, 404)
        budget.refresh_from_db()
        self.assertEqual(budget.cap_amount, Decimal("1"))

    def test_mine_shows_own_and_led_team_budgets_only(self):
        own = Budget.objects.create(org=self.org, scope_type="user", scope_id=self.member.id, cap_amount=Decimal("5"))
        peer = Budget.objects.create(org=self.org, scope_type="user", scope_id=self.peer.id, cap_amount=Decimal("5"))
        team = Budget.objects.create(org=self.org, scope_type="team", scope_id=self.team.id, cap_amount=Decimal("5"))
        Budget.objects.create(org=self.org, cap_amount=Decimal("50"))
        self._auth(self.member)
        ids = {row["id"] for row in self.client.get(f"{self.base}/mine").json()}
        self.assertEqual(ids, {str(own.id)})
        self._auth(self.lead)
        ids = {row["id"] for row in self.client.get(f"{self.base}/mine").json()}
        self.assertEqual(ids, {str(team.id)})
        self.assertNotIn(str(peer.id), ids)
