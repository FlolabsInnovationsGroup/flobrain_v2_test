"""Buddy feedback and the quality numbers (growth round W5)."""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from actions.models import ActionProposal
from brain.models import Chat, Message
from buddies import quality
from buddies.models import Buddy, BuddyAnswer, BuddyFeedback, BuddyRoute, BuddyRouteHop
from buddies.test_router import CrewBase, _RouterCapture
from buddies.tests import DIRECT
from telemetry.models import PriceTable, UsageEvent

SECRET_TEXT = "SECRET-ANSWER-TEXT"


class FeedbackTests(CrewBase):
    def setUp(self):
        super().setUp()
        self.chat = Chat.objects.create(user=self.member_a, org=self.org, buddy=self.builtin, title="t")
        Message.objects.create(chat=self.chat, role=Message.ROLE_USER, text="q")
        self.reply = Message.objects.create(chat=self.chat, role=Message.ROLE_ASSISTANT, text=SECRET_TEXT)
        self.url = f"{self.base}/buddies/feedback"

    def _post(self, user, **body):
        self._auth(user)
        return self.client.post(self.url, {"message": self.reply.id, **body}, format="json")

    def test_rate_then_change_keeps_one_row(self):
        first = self._post(self.member_a, rating="up")
        self.assertEqual(first.status_code, 201, first.content)
        second = self._post(self.member_a, rating="down", reason="incomplete", note="missed the date")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(BuddyFeedback.objects.filter(message=self.reply).count(), 1)
        row = BuddyFeedback.objects.get(message=self.reply)
        self.assertEqual((row.rating, row.reason, row.buddy_id), (BuddyFeedback.DOWN, "incomplete", self.builtin.id))
        listed = self.client.get(self.url, {"thread": self.chat.id}).json()
        self.assertEqual(listed[0]["rating"], "down")
        self.assertEqual(self.client.delete(f"{self.url}/{self.reply.id}").status_code, 204)
        self.assertEqual(self.client.delete(f"{self.url}/{self.reply.id}").status_code, 404)

    def test_validation(self):
        self.assertEqual(self._post(self.member_a, rating="meh").status_code, 400)
        self.assertEqual(self._post(self.member_a, rating="down", reason="because").status_code, 400)
        self.assertEqual(self._post(self.member_a, rating="down", note="x" * 301).status_code, 400)
        self.assertEqual(self._post(self.member_a, rating="up", note=["x"]).status_code, 400)
        self._auth(self.member_a)
        self.assertEqual(self.client.post(self.url, {"message": "abc", "rating": "up"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"message": True, "rating": "up"}, format="json").status_code, 400)
        # A reason only counts for "not helpful".
        self.assertEqual(self._post(self.member_a, rating="up", reason="wrong").status_code, 201)
        self.assertEqual(BuddyFeedback.objects.get(message=self.reply).reason, "")

    def test_only_your_own_buddy_replies(self):
        self.assertEqual(self._post(self.member_b, rating="up").status_code, 404, "someone else's thread")
        question = self.chat.messages.get(role=Message.ROLE_USER)
        self._auth(self.member_a)
        self.assertEqual(self.client.post(self.url, {"message": question.id, "rating": "up"}, format="json").status_code, 404)
        plain = Chat.objects.create(user=self.member_a, org=self.org, title="not a buddy")
        other = Message.objects.create(chat=plain, role=Message.ROLE_ASSISTANT, text="x")
        self.assertEqual(self.client.post(self.url, {"message": other.id, "rating": "up"}, format="json").status_code, 404)
        self.builtin.is_enabled = False
        self.builtin.save()
        self.assertEqual(self._post(self.member_a, rating="up").status_code, 404, "a buddy you can no longer use")
        self._auth(self.member_a)
        self.assertEqual(self.client.get(self.url, {"thread": "x"}).status_code, 400)

    def test_flag_off(self):
        self.org.settings = {"flags": {"buddies": True}}
        self.org.save(update_fields=["settings"])
        self.assertEqual(self._post(self.member_a, rating="up").status_code, 501)

    @override_settings(**DIRECT)
    def test_flo_reply_is_rated_for_the_buddy_that_answered(self):
        capture = _RouterCapture(lambda ids: {"buddy_ids": [str(self.finance.id), str(self.builtin.id)]})
        body = self._flo_send(self.member_a, "budget and workspace", capture)[0].json()
        reply_id = body["messages"][-1]["id"]
        self._auth(self.member_a)
        made = self.client.post(self.url, {"message": reply_id, "rating": "up"}, format="json")
        self.assertEqual(made.json()["buddy"], str(self.finance.id), "first answering buddy by default")
        chosen = self.client.post(self.url, {"message": reply_id, "rating": "up", "buddy": str(self.builtin.id)}, format="json")
        self.assertEqual(chosen.json()["buddy"], str(self.builtin.id))
        bad = self.client.post(self.url, {"message": reply_id, "rating": "up", "buddy": str(self.private_b.id)}, format="json")
        self.assertEqual(bad.status_code, 400)


class QualityStatsTests(CrewBase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        PriceTable.objects.create(provider="demo", model="m", input_price=Decimal("1"), output_price=Decimal("2"), valid_from=now - timedelta(days=90))
        self.chat = Chat.objects.create(user=self.member_a, org=self.org, buddy=self.builtin, title="t")
        replies = []
        for i in range(4):
            Message.objects.create(chat=self.chat, role=Message.ROLE_USER, text="question")
            replies.append(Message.objects.create(chat=self.chat, role=Message.ROLE_ASSISTANT, text=SECRET_TEXT))
        old = Message.objects.create(chat=self.chat, role=Message.ROLE_ASSISTANT, text="old")
        Message.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=20))
        b_chat = Chat.objects.create(user=self.member_b, org=self.org, buddy=self.builtin, title="t")
        b_reply = Message.objects.create(chat=b_chat, role=Message.ROLE_ASSISTANT, text=SECRET_TEXT)
        for msg, user, rating, reason in (
            (replies[0], self.member_a, 1, ""),
            (replies[1], self.member_a, 1, ""),
            (replies[2], self.member_a, -1, "wrong"),
            (b_reply, self.member_b, -1, "wrong"),
        ):
            BuddyFeedback.objects.create(org=self.org, buddy=self.builtin, user=user, message=msg, rating=rating, reason=reason, note="NOTE-TEXT")
        for msg, latency, cited in ((replies[0], 1000, True), (replies[1], 3000, False), (replies[2], 2000, True)):
            BuddyAnswer.objects.create(org=self.org, buddy=self.builtin, message=msg, latency_ms=latency, cited=cited)
        for status in ("executed", "approved", "rejected", "proposed", "expired"):
            ActionProposal.objects.create(org=self.org, user=self.member_a, buddy=self.builtin, tool_key="tasks.create", status=status)
        UsageEvent.objects.create(org=self.org, user=self.member_a, chat=self.chat, provider="demo", model="m",
                                  input_tokens=1_000_000, output_tokens=500_000, total_tokens=1_500_000)
        for slugs in ([self.builtin], [self.builtin, self.finance], [self.finance]):
            route = BuddyRoute.objects.create(org=self.org, user=self.member_a, surface=BuddyRoute.SURFACE_BUDDY, method="llm")
            for i, b in enumerate(slugs):
                BuddyRouteHop.objects.create(route=route, buddy=b, position=i)
        hint = BuddyRoute.objects.create(org=self.org, user=self.member_a, surface=BuddyRoute.SURFACE_HINT, method="llm")
        BuddyRouteHop.objects.create(route=hint, buddy=self.builtin, status=0)

    def _get(self, user, days="7"):
        self._auth(user)
        return self.client.get(f"{self.base}/buddies/quality", {"days": days})

    def test_aggregates(self):
        response = self._get(self.owner)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        row = next(r for r in data["buddies"] if r["slug"] == "space")
        self.assertEqual(row["answers"], 5, "four of A's and one of B's, not the 20-day-old one")
        self.assertEqual((row["helpful"], row["not_helpful"], row["ratings"]), (2, 2, 4))
        self.assertEqual(row["helpful_rate"], 0.5)
        self.assertEqual(row["approvals"], {"proposed": 5, "approved": 2, "rejected": 1, "waiting": 1})
        self.assertEqual(row["median_latency_ms"], 2000)
        self.assertEqual(row["measured"], 3)
        self.assertEqual(row["with_sources_rate"], round(2 / 3, 4))
        self.assertEqual(row["tokens"], 1_500_000)
        self.assertEqual(row["cost"], "2.0000")
        self.assertEqual(row["routed"], 2)
        self.assertEqual(row["routing_share"], round(2 / 3, 4), "hints are not counted")
        self.assertEqual(row["top_reasons"], [{"reason": "wrong", "count": 2}])
        self.assertEqual(data["routing"], {"decisions": 3, "by_method": {"llm": 3}})
        self.assertEqual(sum(d["answers"] for d in data["trend"]), data["totals"]["answers"])
        self.assertEqual(len(data["trend"]), 7)
        self.assertEqual(self._get(self.owner, "30").json()["buddies"][0]["answers"], 6)

    def test_numbers_only(self):
        raw = json.dumps(self._get(self.owner).json())
        for secret in (SECRET_TEXT, "NOTE-TEXT", "question", str(self.member_a.id), self.member_a.email):
            self.assertNotIn(secret, raw)

    def test_permissions_scope_and_validation(self):
        self.assertEqual(self._get(self.owner, "14").status_code, 400)
        self.assertEqual(self._get(self.outsider).status_code, 403)
        member_rows = {r["slug"] for r in self._get(self.member_a).json()["buddies"]}
        self.assertNotIn("b-secret", member_rows, "members see buddies they can use")
        self.assertIn("b-secret", {r["slug"] for r in self._get(self.owner).json()["buddies"]})
        with patch("buddies.views_quality.can", return_value=False):
            self.assertEqual(self._get(self.member_a).status_code, 403)

    def test_quality_module_matches_endpoint(self):
        direct = quality.stats(self.org, self.owner, 7)
        self.assertEqual(direct["totals"]["ratings"], 4)
        self.assertEqual(direct["reasons"], [{"reason": "wrong", "count": 2}])
        self.assertTrue(all(isinstance(r["cost"], str) for r in direct["buddies"]))
        self.assertIsInstance(Buddy.objects.get(slug="space"), Buddy)
