"""Share-request notifications, the requests list for reviewers, and budget downgrade in buddy chat."""

from decimal import Decimal

from django.test import override_settings

from buddies.models import Buddy
from buddies.tests import DIRECT, BuddyBase, BuilderBase
from notifications.models import Notification
from organizations.models import OrgMembership
from telemetry.models import Budget, PriceTable, UsageEvent


class ShareNotificationTests(BuilderBase):
    def test_request_notifies_deciders_and_decision_notifies_requester(self):
        created = self._create(self.member_a).json()
        res = self.client.post(f"{self.base}/buddies/{created['id']}/share", {"target": "team", "team": str(self.team_a.id)}, format="json")
        self.assertEqual(res.status_code, 202)
        asked = Notification.objects.filter(org=self.org, kind="buddy_share_request")
        self.assertEqual({n.user_id for n in asked}, {self.owner.id, self.lead_a.id})
        self.assertEqual(asked.first().payload["link"], "buddies/requests")
        self.assertEqual(asked.first().payload["team"], "Alpha")

        self._auth(self.lead_a)
        row = next(r for r in self.client.get(f"{self.base}/buddies/share-requests").json() if r["id"] == created["id"])
        self.assertEqual(row["requested_by"]["name"], "bd-a@example.com")
        self.assertEqual(row["share_team_name"], "Alpha")
        decided = self.client.post(f"{self.base}/buddies/{created['id']}/share/reject", {"reason": "Too broad for now"}, format="json")
        self.assertEqual(decided.status_code, 200, decided.content)
        told = Notification.objects.get(org=self.org, kind="buddy_share_decided")
        self.assertEqual(told.user_id, self.member_a.id)
        self.assertEqual(told.payload["outcome"], "rejected")
        self.assertEqual(told.payload["reason"], "Too broad for now")
        self.assertEqual(told.payload["link"], f"buddies/{created['id']}")

    def test_org_share_goes_to_admins_only_and_approval_is_announced(self):
        created = self._create(self.member_a).json()
        self.client.post(f"{self.base}/buddies/{created['id']}/share", {"target": "org"}, format="json")
        asked = Notification.objects.filter(org=self.org, kind="buddy_share_request")
        self.assertEqual({n.user_id for n in asked}, {self.owner.id}, "a team lead cannot decide org shares")
        self._auth(self.owner)
        self.assertEqual(self._approve(created["id"]).status_code, 200)
        told = Notification.objects.get(kind="buddy_share_decided")
        self.assertEqual((told.user_id, told.payload["outcome"]), (self.member_a.id, "approved"))

    def test_auto_approved_share_sends_nothing(self):
        created = self._create(self.lead_a).json()
        res = self.client.post(f"{self.base}/buddies/{created['id']}/share", {"target": "team", "team": str(self.team_a.id)}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Notification.objects.filter(kind__startswith="buddy_share").exists())

    def test_bad_reason_is_400_and_member_cannot_decide(self):
        created = self._create(self.member_a).json()
        self.client.post(f"{self.base}/buddies/{created['id']}/share", {"target": "org"}, format="json")
        self._auth(self.member_b)
        self.assertEqual(self.client.get(f"{self.base}/buddies/share-requests").json(), [])
        self.assertEqual(self.client.post(f"{self.base}/buddies/{created['id']}/share/reject").status_code, 403)
        self._auth(self.owner)
        res = self.client.post(f"{self.base}/buddies/{created['id']}/share/reject", {"reason": ["x"]}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Buddy.objects.get(pk=created["id"]).share_status, Buddy.SHARE_PENDING)


@override_settings(**{**DIRECT, "AI_DIRECT_MODEL_ALLOWLIST": "qwen,qwen-small"})
class BuddyBudgetDowngradeTests(BuddyBase):
    def setUp(self):
        super().setUp()
        self.org.settings = {"flags": {"buddies": True, "budgets": True}}
        self.org.save(update_fields=["settings"])
        PriceTable.objects.create(provider="openai_compatible", model="qwen", input_price=Decimal("1000000"), output_price=Decimal("1000000"))
        UsageEvent.objects.create(org=self.org, user=self.member_a, provider="openai_compatible", model="qwen", total_tokens=5)

    def test_downgrade_budget_switches_model_and_says_so(self):
        Budget.objects.create(
            org=self.org, scope_type="user", scope_id=self.member_a.id, cap_amount=Decimal("1"),
            on_exceed=Budget.ON_DOWNGRADE, downgrade_model="qwen-small",
        )
        thread_id = self._thread(self.member_a, self.builtin)
        response, capture = self._send(self.member_a, thread_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(capture.bodies[-1]["model"], "qwen-small")
        self.assertTrue(response.json()["usage"]["downgraded"])

    def test_block_budget_refuses(self):
        Budget.objects.create(org=self.org, cap_amount=Decimal("1"))
        thread_id = self._thread(self.member_a, self.builtin)
        response, capture = self._send(self.member_a, thread_id)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(capture.bodies, [])

    def test_other_member_is_not_downgraded(self):
        Budget.objects.create(
            org=self.org, scope_type="user", scope_id=self.member_a.id, cap_amount=Decimal("1"),
            on_exceed=Budget.ON_DOWNGRADE, downgrade_model="qwen-small",
        )
        OrgMembership.objects.filter(org=self.org, user=self.member_b).update(employment_status="active")
        thread_id = self._thread(self.member_b, self.builtin)
        response, capture = self._send(self.member_b, thread_id)
        self.assertEqual(capture.bodies[-1]["model"], "qwen")
        self.assertNotIn("downgraded", response.json()["usage"])
