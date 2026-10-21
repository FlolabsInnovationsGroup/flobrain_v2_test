"""Flo router and specialist templates (growth round W5)."""

import json
from unittest.mock import patch

from django.test import override_settings

from brain.models import Chat, Message
from buddies import router
from buddies.models import Buddy, BuddyAnswer, BuddyRoute
from buddies.templates_extra import TEMPLATES, context_for, ensure_flo, install
from buddies.tests import DIRECT, BuddyBase, _Body


class _RouterCapture:
    """Answers the routing call with ``route`` (a callable of the buddy ids listed) and buddy turns
    with a fixed text. ``fail`` makes the routing call fail."""

    def __init__(self, route=None, fail=None):
        self.route, self.fail = route, fail
        self.router_calls, self.buddy_bodies = [], []

    def __call__(self, request, timeout=None):
        body = json.loads(request.data.decode())
        system = body["messages"][0]["content"]
        if router.ROUTER_MARK in system:
            self.router_calls.append(body)
            if self.fail == "error":
                import urllib.error

                raise urllib.error.HTTPError(request.full_url, 500, "boom", {}, None)
            ids = [line.split(" | ")[0][len("- id: "):] for line in system.splitlines() if line.startswith("- id: ")]
            content = self.fail if isinstance(self.fail, str) and self.fail != "error" else json.dumps(self.route(ids))
            return _Body({"model": "qwen", "choices": [{"message": {"role": "assistant", "content": content}}], "usage": {"total_tokens": 20}})
        self.buddy_bodies.append(body)
        name = system.split("Buddy instructions:\n", 1)[-1][:20]
        return _Body({
            "model": "qwen",
            "choices": [{"message": {"role": "assistant", "content": f"specialist answer ({name})"}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12},
        })

    def sent(self):
        return json.dumps([b["messages"] for b in self.buddy_bodies])


class CrewBase(BuddyBase):
    def setUp(self):
        super().setUp()
        self.org.settings = {"flags": {"buddies": True, "memory_search": True, "flo_router": True, "ai_actions": True}}
        self.org.save(update_fields=["settings"])
        self.finance = Buddy.objects.create(
            org=self.org, slug="finance", name="Finance Buddy", description="Budgets, costs and invoices.",
            is_builtin=True, visibility=Buddy.VIS_ORG, share_status=Buddy.SHARE_APPROVED, system_prompt="FINANCE-PROMPT",
        )
        self.private_b = Buddy.objects.create(
            org=self.org, slug="b-secret", name="B secret budget helper", description="budget budget budget",
            created_by=self.member_b, system_prompt="SECRET-PROMPT",
        )
        self.team_b_buddy = Buddy.objects.create(
            org=self.org, slug="beta-team", name="Beta budget buddy", description="budget", created_by=self.member_b,
            visibility=Buddy.VIS_TEAM, team=self.team_b, share_status=Buddy.SHARE_APPROVED,
        )
        self.flo = ensure_flo(self.org)

    def _route(self, user, text, capture, **extra):
        self._auth(user)
        with patch("urllib.request.urlopen", side_effect=capture):
            return self.client.post(f"{self.base}/buddies/route", {"text": text, **extra}, format="json")

    def _flo_send(self, user, text, capture, thread_id=None):
        thread_id = thread_id or self._thread(user, self.flo)
        self._auth(user)
        with patch("urllib.request.urlopen", side_effect=capture):
            response = self.client.post(f"{self.base}/buddies/threads/{thread_id}/send", {"text": text}, format="json")
        return response, thread_id


@override_settings(**DIRECT)
class RoutingTests(CrewBase):
    def test_flag_off_hides_flo_and_routing(self):
        self.org.settings = {"flags": {"buddies": True}}
        self.org.save(update_fields=["settings"])
        self._auth(self.member_a)
        ids = {row["slug"] for row in self.client.get(f"{self.base}/buddies").json()}
        self.assertNotIn("flo", ids)
        self.assertEqual(self.client.post(f"{self.base}/buddies/route", {"text": "budget"}, format="json").status_code, 501)
        self.assertEqual(self.client.post(f"{self.base}/buddies/{self.flo.id}/threads", {}, format="json").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/buddies/{self.flo.id}").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/buddies/quality").status_code, 501)
        self.assertEqual(self.client.get(f"{self.base}/buddies/templates").status_code, 501)

    def test_flo_thread_closes_when_flag_turns_off(self):
        thread_id = self._thread(self.member_a, self.flo)
        self.org.settings = {"flags": {"buddies": True}}
        self.org.save(update_fields=["settings"])
        response, _ = self._flo_send(self.member_a, "budget?", _RouterCapture(lambda ids: {"buddy_ids": ids[:1]}), thread_id)
        self.assertEqual(response.status_code, 404)

    def test_flo_is_listed_when_on_and_members_can_open_it(self):
        Buddy.objects.filter(slug="flo").delete()
        self._auth(self.member_a)
        slugs = [row["slug"] for row in self.client.get(f"{self.base}/buddies").json()]
        self.assertIn("flo", slugs)
        flo = Buddy.objects.get(org=self.org, slug="flo")
        card = self.client.get(f"{self.base}/buddies/{flo.id}")
        self.assertEqual(card.status_code, 200)
        self.assertNotIn("system_prompt", card.json(), "viewers get the public card, not the builder view")
        self.assertTrue(card.json()["preset_prompts"])

    def test_candidates_are_only_buddies_the_user_can_use(self):
        install(self.org, "customer")
        names = {b.slug for b in router.candidates(self.member_a, self.org)}
        self.assertIn("finance", names)
        self.assertIn("space", names)
        self.assertNotIn("b-secret", names)
        self.assertNotIn("beta-team", names)
        self.assertNotIn("flo", names)
        self.assertNotIn("customer", names, "the customer persona is never routed to")

    def test_model_pick_is_used_when_it_names_an_allowed_buddy(self):
        capture = _RouterCapture(lambda ids: {"buddy_ids": [str(self.finance.id)], "reason": "Budget question."})
        response = self._route(self.member_a, "how much budget is left?", capture)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["method"], "llm")
        self.assertEqual([b["slug"] for b in body["buddies"]], ["finance"])
        listed = capture.router_calls[0]["messages"][0]["content"]
        self.assertNotIn(str(self.private_b.id), listed, "a buddy you can't use is never offered to the model")
        self.assertNotIn(str(self.team_b_buddy.id), listed)
        self.assertNotIn("FINANCE-PROMPT", listed, "buddy prompts are not sent to the router")
        self.assertEqual(BuddyRoute.objects.filter(surface="hint").count(), 1)

    def test_model_naming_a_forbidden_buddy_is_ignored(self):
        capture = _RouterCapture(lambda ids: {"buddy_ids": [str(self.private_b.id)], "reason": "x"})
        body = self._route(self.member_a, "how much budget is left?", capture).json()
        self.assertEqual(body["method"], "keywords")
        self.assertEqual([b["slug"] for b in body["buddies"]], ["finance"])

    def test_fallback_to_keywords_when_the_model_fails_or_rambles(self):
        for fail in ("error", "Sure! The finance buddy.", '{"buddy_ids": [], "reason": ""}'):
            body = self._route(self.member_a, "Which invoices are overdue on the budget?", _RouterCapture(fail=fail)).json()
            self.assertEqual(body["method"], "keywords", fail)
            self.assertEqual(body["buddies"][0]["slug"], "finance", fail)

    def test_no_provider_means_keywords_and_no_call(self):
        with override_settings(AI_DIRECT_BASE_URL="", AI_DIRECT_API_KEY=""):
            capture = _RouterCapture(lambda ids: {"buddy_ids": ids[:1]})
            body = self._route(self.member_a, "budget", capture).json()
        self.assertEqual(body["method"], "keywords")
        self.assertEqual(capture.router_calls, [])

    def test_nothing_matches_means_no_buddy(self):
        body = self._route(self.member_a, "zzz qqq", _RouterCapture(fail="error")).json()
        self.assertEqual(body["buddies"], [])
        self.assertEqual(body["method"], "none")

    def test_room_must_be_readable(self):
        capture = _RouterCapture(lambda ids: {"buddy_ids": ids[:1]})
        self.assertEqual(self._route(self.member_a, "budget", capture, room=str(self.room_b.id)).status_code, 404)
        self.assertEqual(self._route(self.member_a, "budget", capture, room=str(self.room_a.id)).status_code, 200)

    def test_validation(self):
        self._auth(self.member_a)
        self.assertEqual(self.client.post(f"{self.base}/buddies/route", {"text": ""}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{self.base}/buddies/route", {"text": "x" * 4001}, format="json").status_code, 400)
        self._auth(self.outsider)
        self.assertEqual(self.client.post(f"{self.base}/buddies/route", {"text": "x"}, format="json").status_code, 403)

    def test_parse_decision_is_strict(self):
        ok = {"a", "b", "c"}
        self.assertEqual(router.parse_decision('{"buddy_ids": ["a"], "reason": "r"}', ok), (["a"], "r"))
        self.assertEqual(router.parse_decision('```json\n{"buddy_ids": ["a", "b"]}\n```', ok), (["a", "b"], ""))
        for bad in (
            '{"buddy_ids": ["a", "b", "c"]}',
            '{"buddy_ids": ["a"], "reason": "r", "extra": 1}',
            '{"buddy_ids": "a"}',
            '{"buddy_ids": ["a", "zzz"]}',
            '["a"]',
            "not json",
            '{"buddy_ids": [1]}',
            '{"reason": "r"}',
        ):
            self.assertIsNone(router.parse_decision(bad, ok), bad)


@override_settings(**DIRECT)
class FloTurnTests(CrewBase):
    def test_flo_answers_with_attribution_and_viewer_sources(self):
        capture = _RouterCapture(lambda ids: {"buddy_ids": [str(self.builtin.id)], "reason": "Workspace question."})
        response, thread_id = self._flo_send(self.member_a, "what do we know?", capture)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        reply = body["messages"][-1]
        self.assertTrue(reply["text"].startswith("Answered by Space Buddy"))
        self.assertIn("specialist answer", reply["text"])
        self.assertEqual(body["answered_by"][str(reply["id"])][0]["slug"], "space")
        self.assertEqual(body["routing"]["method"], "llm")
        # The specialist read only what member A can open.
        self.assertIn("BUILTIN-PROMPT", capture.sent())
        self.assertIn("ALPHA-FACT", capture.sent())
        self.assertNotIn("BETA-FACT", capture.sent())
        sub = Chat.objects.get(user=self.member_a, buddy=self.builtin)
        self.assertEqual(sub.messages.filter(role=Message.ROLE_ASSISTANT).count(), 1)
        self.assertTrue(BuddyAnswer.objects.get(buddy=self.builtin).via_flo)
        route = BuddyRoute.objects.get(surface="buddy")
        self.assertEqual(route.reply_id, reply["id"])
        self.assertEqual([h.buddy_id for h in route.hops.all()], [self.builtin.id])
        # A second message reuses the same specialist thread.
        self._flo_send(self.member_a, "and more?", capture, thread_id)
        self.assertEqual(Chat.objects.filter(user=self.member_a, buddy=self.builtin).count(), 1)

    def test_two_buddies_each_get_attribution(self):
        capture = _RouterCapture(lambda ids: {"buddy_ids": [str(self.finance.id), str(self.builtin.id)], "reason": "Both."})
        body = self._flo_send(self.member_a, "budget and workspace", capture)[0].json()
        text = body["messages"][-1]["text"]
        self.assertIn("Answered by Finance Buddy", text)
        self.assertIn("Answered by Space Buddy", text)
        self.assertEqual(len(body["answers"]), 2)
        self.assertEqual(len(capture.buddy_bodies), 2)

    def test_member_b_routing_never_reaches_member_a_private_buddy(self):
        mine = Buddy.objects.create(org=self.org, slug="a-mine", name="A budget", description="budget", created_by=self.member_a)
        capture = _RouterCapture(lambda ids: {"buddy_ids": [str(mine.id)], "reason": "x"})
        body = self._flo_send(self.member_b, "budget", capture)[0].json()
        self.assertNotIn("Answered by A budget", body["messages"][-1]["text"])
        self.assertFalse(Chat.objects.filter(user=self.member_b, buddy=mine).exists())

    def test_specialist_failure_is_returned_and_nothing_is_stored(self):
        capture = _RouterCapture(lambda ids: {"buddy_ids": [str(self.finance.id)]})
        with override_settings(AI_DIRECT_BASE_URL="", AI_DIRECT_API_KEY=""):
            response, thread_id = self._flo_send(self.member_a, "budget", capture)
        self.assertEqual(response.status_code, 501)
        self.assertFalse(Message.objects.filter(chat_id=thread_id).exists())

    def test_no_match_gives_a_helpful_reply(self):
        body = self._flo_send(self.member_a, "zzz qqq", _RouterCapture(fail="error"))[0].json()
        self.assertIn("couldn't tell which buddy", body["messages"][-1]["text"])
        self.assertEqual(body["routing"]["buddies"], [])

    def test_direct_buddy_send_measures_the_reply(self):
        thread_id = self._thread(self.member_a, self.builtin)
        response, _ = self._send(self.member_a, thread_id)
        self.assertEqual(response.status_code, 200)
        fact = BuddyAnswer.objects.get(buddy=self.builtin)
        self.assertFalse(fact.via_flo)
        self.assertTrue(fact.cited)
        self.assertIsNotNone(fact.latency_ms)
        self.assertTrue(all("id" in m for m in response.json()["messages"]))


@override_settings(**DIRECT)
class TemplateTests(CrewBase):
    def test_install_needs_buddy_manage_and_is_idempotent(self):
        self._auth(self.member_a)
        listing = self.client.get(f"{self.base}/buddies/templates").json()
        self.assertFalse(listing["can_install"])
        self.assertEqual({t["key"] for t in listing["templates"]}, set(TEMPLATES))
        self.assertEqual(self.client.post(f"{self.base}/buddies/templates/sales/install").status_code, 403)
        self._auth(self.owner)
        first = self.client.post(f"{self.base}/buddies/templates/sales/install")
        self.assertEqual(first.status_code, 201, first.content)
        self.assertTrue(first.json()["installed"])
        self.assertEqual(self.client.post(f"{self.base}/buddies/templates/sales/install").status_code, 200)
        self.assertEqual(Buddy.objects.filter(org=self.org, slug="sales").count(), 1)
        self.assertEqual(self.client.post(f"{self.base}/buddies/templates/nope/install").status_code, 404)
        sales = Buddy.objects.get(org=self.org, slug="sales")
        self.assertTrue(sales.is_builtin)
        self.assertEqual(sales.visibility, Buddy.VIS_ORG)
        self.assertEqual(sales.allowed_tools[0], "email.draft")
        self.assertTrue(all(t.startswith("hubspot.") for t in sales.allowed_tools[1:]), "only registered write-back tools")
        self.assertIn(str(sales.id), self._visible_ids(self.member_a))

    def test_disabled_template_is_switched_back_on_not_overwritten(self):
        buddy, _ = install(self.org, "meeting")
        buddy.system_prompt = "EDITED"
        buddy.is_enabled = False
        buddy.save()
        again, created = install(self.org, "meeting")
        self.assertFalse(created)
        self.assertTrue(again.is_enabled)
        self.assertEqual(again.system_prompt, "EDITED")

    def test_write_back_tools_are_added_only_when_registered(self):
        from actions.registry import TOOLS

        spec = {"perm_key": "integrations.act", "risk": "external", "label": "x", "description": "x", "schema": {"type": "object"}}
        with patch.dict(TOOLS, {"hubspot.create_note": spec}):
            sales, _ = install(self.org, "sales")
        self.assertIn("hubspot.create_note", sales.allowed_tools)

    def test_customer_template_is_public_only(self):
        spec = TEMPLATES["customer"]
        self.assertEqual(spec["allowed_sources"], {"mode": "none"})
        self.assertEqual(spec["allowed_tools"], [])
        self.assertIn("public", spec["system_prompt"])

    def test_sales_facts_show_only_the_viewers_leads(self):
        from commissions.models import Lead

        self.org.settings["flags"]["commissions"] = True
        self.org.save(update_fields=["settings"])
        Lead.objects.create(org=self.org, owner_user=self.member_a, project_or_product="App", contact_name="Mine Co", stage="won")
        Lead.objects.create(org=self.org, owner_user=self.member_b, project_or_product="App", contact_name="Theirs Co", stage="won")
        sales, _ = install(self.org, "sales")
        facts = context_for(sales, self.member_a, self.org)
        self.assertIn("Mine Co", facts)
        self.assertNotIn("Theirs Co", facts)
        self.assertIn("not instructions", facts)
        self.assertEqual(context_for(self.finance, self.member_a, self.org), "")

    def test_meeting_facts_reach_the_specialist_turn(self):
        from datetime import timedelta

        from django.utils import timezone

        from meetings.models import Meeting

        Meeting.objects.create(org=self.org, room=self.room_a, title="Alpha sync", started_at=timezone.now() + timedelta(hours=2))
        Meeting.objects.create(org=self.org, room=self.room_b, title="Beta secret sync", started_at=timezone.now() + timedelta(hours=2))
        meeting, _ = install(self.org, "meeting")
        thread_id = self._thread(self.member_a, meeting)
        _, capture = self._send(self.member_a, thread_id, "Prepare me for my next meeting.")
        self.assertIn("Alpha sync", capture.text())
        self.assertNotIn("Beta secret sync", capture.text())
