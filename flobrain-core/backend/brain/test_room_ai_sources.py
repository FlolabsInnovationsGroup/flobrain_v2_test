"""Room AI grounded in the room's readable sources, model choice, and the demo answers (2026-10-21)."""

import json
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from brain.models import Chat, Message
from brain.v2_views import OWN_TEXT_SYSTEM, ROOM_SOURCES_SYSTEM
from docs_app.models import Document
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.models import Room, RoomMember, RoomMessage
from rooms.services import ensure_team_room, pair_key_for
from users.jwt_utils import make_access_token
from users.models import User

DIRECT = {
    "AI_PROVIDER_BACKEND": "direct",
    "AI_DIRECT_BASE_URL": "https://provider.example",
    "AI_DIRECT_API_KEY": "test-key-not-live",
    "AI_DIRECT_MODEL_ALLOWLIST": "qwen,llama",
    "AI_DIRECT_DEFAULT_MODEL": "qwen",
}


class _Body:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Capture:
    def __init__(self):
        self.bodies = []

    def __call__(self, request, timeout=None):
        self.bodies.append(json.loads(request.data.decode()))
        return _Body({
            "model": self.bodies[-1].get("model", "qwen"),
            "choices": [{"message": {"role": "assistant", "content": "Friday [1]"}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 3, "total_tokens": 43},
        })

    def prompt(self):
        return "\n".join(m["content"] for m in self.bodies[-1]["messages"])


def _user(email):
    return User.objects.create(email=email, password_hash=make_password("x"))


@override_settings(**DIRECT)
class RoomAISourcesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="RA Org", slug="ra-org", settings={"flags": {"room_ai": True, "memory_search": True}}
        )
        self.a = _user("ra-a@example.com")
        self.b = _user("ra-b@example.com")
        for user in (self.a, self.b):
            OrgMembership.objects.create(org=self.org, user=user, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status="active")
        alpha = Team.objects.create(org=self.org, name="Alpha")
        beta = Team.objects.create(org=self.org, name="Beta")
        gamma = Team.objects.create(org=self.org, name="Gamma")
        TeamMembership.objects.create(team=alpha, user=self.a)
        TeamMembership.objects.create(team=gamma, user=self.a)
        TeamMembership.objects.create(team=beta, user=self.b)
        self.room = ensure_team_room(alpha)
        self.own_other_room = ensure_team_room(gamma)
        self.hidden_room = ensure_team_room(beta)
        Document.objects.create(org=self.org, room=self.room, title="Plan", content_text="ROOM-FACT code freeze is Friday.")
        RoomMessage.objects.create(room=self.room, author=self.a, body="ROOM-CHAT freeze reminder")
        Document.objects.create(org=self.org, room=self.own_other_room, title="Gamma", content_text="GAMMA-FACT other room")
        Document.objects.create(org=self.org, room=self.hidden_room, title="Beta", content_text="BETA-SECRET pricing")
        dm = Room.objects.create(org=self.org, name="dm", kind=Room.KIND_DIRECT, pair_key=pair_key_for(self.a, self.b))
        RoomMember.objects.create(room=dm, user=self.a)
        RoomMember.objects.create(room=dm, user=self.b)
        RoomMessage.objects.create(room=dm, author=self.b, body="DM-SECRET for a")
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _thread(self, user=None):
        self._auth(user or self.a)
        return self.client.post(f"{self.base}/rooms/{self.room.id}/ai/threads", {}, format="json").json()["id"]

    def _send(self, thread_id, body):
        capture = _Capture()
        with patch("urllib.request.urlopen", side_effect=capture):
            res = self.client.post(f"{self.base}/ai/threads/{thread_id}/send", body, format="json")
        return res, capture

    def test_answer_uses_only_this_rooms_sources_and_keeps_citations(self):
        thread_id = self._thread()
        res, capture = self._send(thread_id, {"text": "when is the code freeze?"})
        self.assertEqual(res.status_code, 200, res.content)
        prompt = capture.prompt()
        self.assertIn("ROOM-FACT", prompt)
        self.assertIn("Question: when is the code freeze?", prompt)
        for secret in ("GAMMA-FACT", "BETA-SECRET", "DM-SECRET"):
            self.assertNotIn(secret, prompt)
        self.assertEqual(capture.bodies[-1]["messages"][0]["content"], ROOM_SOURCES_SYSTEM)
        data = res.json()
        self.assertEqual(data["sources_state"], "used")
        self.assertTrue(data["citations"])
        self.assertEqual({c["room"] for c in data["citations"]}, {str(self.room.id)})
        stored = Message.objects.get(chat_id=thread_id, role="assistant")
        self.assertEqual(stored.sources, data["citations"])
        detail = self.client.get(f"{self.base}/ai/threads/{thread_id}").json()
        self.assertEqual(detail["messages"][-1]["sources"], data["citations"])
        self.assertEqual(detail["title"], "when is the code freeze?", "first question names the thread")
        self.assertEqual(Message.objects.get(chat_id=thread_id, role="user").text, "when is the code freeze?")

    def test_memory_search_off_sends_own_text_only(self):
        self.org.settings = {"flags": {"room_ai": True}}
        self.org.save(update_fields=["settings"])
        thread_id = self._thread()
        res, capture = self._send(thread_id, {"text": "when is the code freeze?"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertNotIn("ROOM-FACT", capture.prompt())
        self.assertEqual(capture.bodies[-1]["messages"][0]["content"], OWN_TEXT_SYSTEM)
        self.assertEqual(res.json()["sources_state"], "disabled")
        self.assertEqual(res.json()["citations"], [])

    @override_settings(AI_PROVIDER_BACKEND="multimodal_legacy")
    def test_legacy_backend_never_receives_room_sources(self):
        thread_id = self._thread()
        from brain.llm.providers import ProviderResult

        with patch("brain.v2_views.get_provider") as get_provider:
            get_provider.return_value.complete.return_value = ProviderResult(text="ok", model="legacy", total_tokens=2)
            res = self.client.post(f"{self.base}/ai/threads/{thread_id}/send", {"text": "code freeze?"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        sent = " ".join(m["content"] for m in get_provider.return_value.complete.call_args.args[0])
        self.assertNotIn("ROOM-FACT", sent)
        self.assertEqual(res.json()["sources_state"], "unavailable")

    def test_models_list_offers_the_direct_allowlist(self):
        self._auth(self.a)
        data = self.client.get(f"{self.base}/ai/models").json()
        self.assertEqual([m["name"] for m in data["direct"]], ["qwen", "llama"])
        self.assertEqual(data["default"], "qwen")

    def test_chosen_model_is_used_and_unknown_model_is_400(self):
        thread_id = self._thread()
        res, capture = self._send(thread_id, {"text": "hi", "model": "llama"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(capture.bodies[-1]["model"], "llama")
        bad, capture = self._send(thread_id, {"text": "hi", "model": "gpt-unknown"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(capture.bodies, [], "no provider call for a model that is not offered")
        junk, _ = self._send(thread_id, {"text": "hi", "model": ["llama"]})
        self.assertEqual(junk.status_code, 400)

    def test_non_text_input_is_400(self):
        thread_id = self._thread()
        res, capture = self._send(thread_id, {"text": {"x": 1}})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(capture.bodies, [])
        self.assertEqual(self.client.post(f"{self.base}/rooms/{self.room.id}/ai/threads", {"title": 5}, format="json").status_code, 400)

    def test_thread_list_is_private_and_dated(self):
        thread_id = self._thread()
        rows = self.client.get(f"{self.base}/rooms/{self.room.id}/ai/threads").json()
        self.assertEqual(rows[0]["id"], thread_id)
        self.assertIn("updated_at", rows[0])
        self._auth(self.b)
        self.assertEqual(self.client.get(f"{self.base}/rooms/{self.room.id}/ai/threads").status_code, 404)
        self.assertFalse(Chat.objects.filter(user=self.b).exists())

    def test_downgrade_budget_switches_the_model(self):
        """A used-up "switch to a cheaper model" budget switches room AI too (2026-10-21)."""
        from decimal import Decimal

        from telemetry.models import Budget, PriceTable, UsageEvent

        self.org.settings = {"flags": {"room_ai": True, "memory_search": True, "budgets": True}}
        self.org.save(update_fields=["settings"])
        PriceTable.objects.create(provider="p", model="m", input_price=Decimal("1000000"), output_price=Decimal("1000000"))
        Budget.objects.create(org=self.org, scope_type="user", scope_id=self.a.id, cap_amount=Decimal("1"), on_exceed=Budget.ON_DOWNGRADE, downgrade_model="llama")
        UsageEvent.objects.create(org=self.org, user=self.a, provider="p", model="m", total_tokens=5, credential_source=UsageEvent.CREDENTIAL_PLATFORM)
        thread_id = self._thread()
        res, capture = self._send(thread_id, {"text": "when is the code freeze?", "model": "qwen"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(capture.bodies[-1]["model"], "llama")
        self.assertTrue(res.json()["usage"]["downgraded"])


@override_settings(DEMO_MODE=True, DEMO_AI=True, AI_PROVIDER_BACKEND="direct")
class DemoRoomAnswersTests(TestCase):
    def test_demo_model_quotes_the_closest_source_with_a_citation(self):
        from brain.llm import demo_ai

        user = (
            'Sources:\n<source id="1" type="room message" title="Message in Engineering">\nMorning team.\n</source>\n\n'
            '<source id="2" type="document" title="Launch plan">\n# Launch plan\n\n1. Code freeze Friday.\n2. Store review: 5 days.\n</source>'
            "\n\nQuestion: When is the code freeze?"
        )
        result = demo_ai.reply([{"role": "system", "content": ROOM_SOURCES_SYSTEM}, {"role": "user", "content": user}])
        self.assertIn("[2]", result.text)
        self.assertIn("Code freeze Friday.", result.text)
        self.assertIn("demo model", result.text)

    def test_demo_translation_is_canned_for_seeded_messages(self):
        from brain.llm import demo_ai
        from rooms.translation import TRANSLATE_SYSTEM

        to_ar = demo_ai.reply([
            {"role": "system", "content": TRANSLATE_SYSTEM.format(language="ar")},
            {"role": "user", "content": "Launch date is confirmed for the end of next month."},
        ])
        self.assertEqual(to_ar.text, "تم تأكيد موعد الإطلاق في نهاية الشهر القادم.")
        to_en = demo_ai.reply([
            {"role": "system", "content": TRANSLATE_SYSTEM.format(language="en")},
            {"role": "user", "content": "تمام، سأراجعه اليوم."},
        ])
        self.assertEqual(to_en.text, "OK, I'll review it today.")
        unknown = demo_ai.reply([
            {"role": "system", "content": TRANSLATE_SYSTEM.format(language="ar")},
            {"role": "user", "content": "Something nobody seeded"},
        ])
        self.assertIn("demo translation", unknown.text)

    def test_seeded_demo_rooms_work_end_to_end(self):
        cache.clear()
        from demo import seed
        from notifications.models import Notification
        from rooms.models import Announcement

        org = seed.reset()
        member = User.objects.get(email=seed.email_for("member"))
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(member.id))}")
        base = f"/api/v2/orgs/{org.id}"
        project = Room.objects.get(org=org, kind=Room.KIND_PROJECT)
        threads = client.get(f"{base}/rooms/{project.id}/ai/threads").json()
        self.assertTrue(threads, "seeded room AI thread")
        detail = client.get(f"{base}/ai/threads/{threads[0]['id']}").json()
        self.assertTrue(detail["messages"][-1]["sources"])
        self.assertTrue(Announcement.objects.filter(org=org, pinned=True).count() >= 2)
        self.assertTrue(Notification.objects.filter(org=org, user=member, kind="mention").exists())
        self.assertTrue(Room.objects.filter(org=org, kind=Room.KIND_DIRECT, memberships__user=member).count() >= 2)
        translated = client.get(f"{base}/rooms/{project.id}/messages?translate_to=ar").json()["results"]
        launch = next(r for r in translated if r["body"].startswith("Launch date"))
        self.assertEqual(launch["translation"], "تم تأكيد موعد الإطلاق في نهاية الشهر القادم.")
        sent = client.post(f"{base}/ai/threads/{threads[0]['id']}/send", {"text": "Who owns the blog post?"}, format="json")
        self.assertEqual(sent.status_code, 200, sent.content)
        answer = sent.json()["messages"][-1]
        self.assertIn("demo model", answer["text"])
        if sent.json()["citations"]:
            self.assertIn("[", answer["text"])
