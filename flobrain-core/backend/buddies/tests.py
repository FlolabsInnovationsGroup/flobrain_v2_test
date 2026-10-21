import json
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from brain.models import Chat
from buddies.models import Buddy, BuddyPin
from buddies.seeds import BUILTIN_BUDDIES, seed_org
from docs_app.models import Document
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.services import ensure_team_room
from telemetry.models import AITrace
from users.jwt_utils import make_access_token
from users.models import User

DIRECT = {
    "AI_DIRECT_BASE_URL": "https://provider.example",
    "AI_DIRECT_API_KEY": "test-key-not-live",
    "AI_DIRECT_MODEL_ALLOWLIST": "qwen",
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
            "model": "qwen",
            "choices": [{"message": {"role": "assistant", "content": "buddy says hi"}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12},
        })

    def text(self):
        return json.dumps(self.bodies[-1]["messages"]) if self.bodies else ""


def _user(email):
    return User.objects.create(email=email, password_hash=make_password("x"))


class BuddyBase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="Bud Org", slug="bud-org", settings={"flags": {"buddies": True, "memory_search": True}}
        )
        self.owner = _user("bd-owner@example.com")
        self.member_a = _user("bd-a@example.com")
        self.member_b = _user("bd-b@example.com")
        self.outsider = _user("bd-out@example.com")
        for user, role in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER),
            (self.member_a, OrgMembership.ORG_ROLE_MEMBER),
            (self.member_b, OrgMembership.ORG_ROLE_MEMBER),
        ):
            OrgMembership.objects.create(
                org=self.org, user=user, org_role=role, employment_status=OrgMembership.STATUS_ACTIVE
            )
        self.team_a = Team.objects.create(org=self.org, name="Alpha")
        self.team_b = Team.objects.create(org=self.org, name="Beta")
        TeamMembership.objects.create(team=self.team_a, user=self.member_a)
        TeamMembership.objects.create(team=self.team_b, user=self.member_b)
        self.room_a = ensure_team_room(self.team_a)
        self.room_b = ensure_team_room(self.team_b)
        Document.objects.create(org=self.org, room=self.room_a, title="A doc", content_text="ALPHA-FACT one")
        Document.objects.create(org=self.org, room=self.room_b, title="B doc", content_text="BETA-FACT two")
        self.builtin = Buddy.objects.create(
            org=self.org,
            slug="space",
            name="Space Buddy",
            is_builtin=True,
            visibility=Buddy.VIS_ORG,
            share_status=Buddy.SHARE_APPROVED,
            system_prompt="BUILTIN-PROMPT",
            allowed_sources={"mode": "accessible"},
        )
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _visible_ids(self, user):
        self._auth(user)
        response = self.client.get(f"{self.base}/buddies")
        self.assertEqual(response.status_code, 200, response.content)
        return {row["id"] for row in response.json()}

    def _thread(self, user, buddy):
        self._auth(user)
        response = self.client.post(f"{self.base}/buddies/{buddy.id}/threads", {}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["id"]

    def _send(self, user, thread_id, text="what do we know?", **extra):
        self._auth(user)
        capture = _Capture()
        with patch("urllib.request.urlopen", side_effect=capture):
            response = self.client.post(
                f"{self.base}/buddies/threads/{thread_id}/send", {"text": text, **extra}, format="json"
            )
        return response, capture


class BuddyVisibilityTests(BuddyBase):
    def test_flag_off_is_501_and_outsider_403(self):
        self.org.settings = {"flags": {}}
        self.org.save(update_fields=["settings"])
        self._auth(self.member_a)
        self.assertEqual(self.client.get(f"{self.base}/buddies").status_code, 501)
        self._auth(self.outsider)
        self.assertEqual(self.client.get(f"{self.base}/buddies").status_code, 403)

    def test_private_team_org_and_pending(self):
        private = Buddy.objects.create(org=self.org, slug="p", name="P", created_by=self.member_a)
        team = Buddy.objects.create(
            org=self.org,
            slug="t",
            name="T",
            created_by=self.member_b,
            visibility=Buddy.VIS_TEAM,
            team=self.team_b,
            share_status=Buddy.SHARE_APPROVED,
        )
        pending = Buddy.objects.create(
            org=self.org,
            slug="q",
            name="Q",
            created_by=self.member_b,
            visibility=Buddy.VIS_ORG,
            share_status=Buddy.SHARE_PENDING,
        )
        disabled = Buddy.objects.create(
            org=self.org, slug="d", name="D", is_builtin=True, visibility=Buddy.VIS_ORG, is_enabled=False
        )
        a = self._visible_ids(self.member_a)
        b = self._visible_ids(self.member_b)
        owner = self._visible_ids(self.owner)
        self.assertIn(str(self.builtin.id), a & b & owner)
        self.assertIn(str(private.id), a)
        self.assertNotIn(str(private.id), b | owner, "private means the creator only")
        self.assertIn(str(team.id), b)
        self.assertIn(str(team.id), owner)
        self.assertNotIn(str(team.id), a)
        self.assertNotIn(str(pending.id), a, "a pending share is not shared yet")
        self.assertIn(str(pending.id), b)
        self.assertNotIn(str(disabled.id), a | b | owner)

    def test_pins_are_per_user_and_only_visible_buddies(self):
        hidden = Buddy.objects.create(org=self.org, slug="h", name="H", created_by=self.member_b)
        self._auth(self.member_a)
        self.assertEqual(
            self.client.put(f"{self.base}/buddies/pins", {"buddies": [str(hidden.id)]}, format="json").status_code,
            404,
        )
        ok = self.client.put(f"{self.base}/buddies/pins", {"buddies": [str(self.builtin.id)]}, format="json")
        self.assertEqual(ok.status_code, 200)
        listed = self.client.get(f"{self.base}/buddies").json()
        self.assertTrue(listed[0]["pinned"])
        self.assertEqual(BuddyPin.objects.filter(user=self.member_b).count(), 0)
        self._auth(self.member_b)
        self.assertFalse(any(row["pinned"] for row in self.client.get(f"{self.base}/buddies").json()))


class BuddyThreadTests(BuddyBase):
    def test_threads_are_private_and_v1_cannot_open_them(self):
        thread_id = self._thread(self.member_a, self.builtin)
        self._auth(self.member_b)
        self.assertEqual(self.client.get(f"{self.base}/buddies/threads/{thread_id}").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/buddies/{self.builtin.id}/threads").json(), [])
        self._auth(self.member_a)
        self.assertEqual(self.client.get(f"/api/brain/chats/{thread_id}/").status_code, 404)
        v1 = self.client.get("/api/brain/chats/")
        self.assertNotIn(thread_id, [row.get("id") for row in v1.json()] if v1.status_code == 200 else [])

    def test_unshared_buddy_closes_its_threads(self):
        mine = Buddy.objects.create(
            org=self.org,
            slug="m",
            name="M",
            created_by=self.member_b,
            visibility=Buddy.VIS_ORG,
            share_status=Buddy.SHARE_APPROVED,
        )
        thread_id = self._thread(self.member_a, mine)
        Buddy.objects.filter(pk=mine.pk).update(share_status=Buddy.SHARE_NONE, visibility=Buddy.VIS_PRIVATE)
        self._auth(self.member_a)
        self.assertEqual(self.client.get(f"{self.base}/buddies/threads/{thread_id}").status_code, 404)

    def test_hidden_buddy_cannot_start_a_thread(self):
        hidden = Buddy.objects.create(org=self.org, slug="h", name="H", created_by=self.member_b)
        self._auth(self.member_a)
        self.assertEqual(self.client.post(f"{self.base}/buddies/{hidden.id}/threads", {}, format="json").status_code, 404)

    @override_settings(AI_PROVIDER_BACKEND="multimodal_legacy", AI_DIRECT_BASE_URL="", AI_DIRECT_API_KEY="")
    def test_no_direct_is_501_and_never_legacy(self):
        thread_id = self._thread(self.member_a, self.builtin)
        with patch("brain.llm.multimodal_adapter.MultimodalLLMAdapter.generate") as legacy:
            response, capture = self._send(self.member_a, thread_id)
        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["error"], "not_configured")
        legacy.assert_not_called()
        self.assertEqual(capture.bodies, [])
        self.assertFalse(Chat.objects.get(pk=thread_id).messages.exists())


@override_settings(**DIRECT)
class BuddySendTests(BuddyBase):
    def test_send_uses_buddy_prompt_and_viewer_sources(self):
        thread_id = self._thread(self.member_a, self.builtin)
        response, capture = self._send(self.member_a, thread_id)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["messages"][-1]["text"], "buddy says hi")
        sent = capture.text()
        self.assertIn("BUILTIN-PROMPT", sent)
        self.assertIn("not instructions", sent)
        self.assertIn("ALPHA-FACT", sent)
        self.assertNotIn("BETA-FACT", sent)
        self.assertEqual(body["sources_state"], "used")
        self.assertTrue(AITrace.objects.filter(org=self.org, surface="buddy").exists())
        # The stored user message is the user's text, not the sources block.
        self.assertEqual(body["messages"][0]["text"], "what do we know?")

    def test_shared_buddy_never_gives_the_creators_rooms(self):
        shared = Buddy.objects.create(
            org=self.org,
            slug="b-research",
            name="B research",
            created_by=self.member_b,
            visibility=Buddy.VIS_ORG,
            share_status=Buddy.SHARE_APPROVED,
            allowed_sources={"mode": "rooms", "rooms": [str(self.room_b.id)]},
        )
        thread_id = self._thread(self.member_a, shared)
        response, capture = self._send(self.member_a, thread_id)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("BETA-FACT", capture.text())
        self.assertEqual(response.json()["citations"], [])
        thread_b = self._thread(self.member_b, shared)
        _, capture_b = self._send(self.member_b, thread_b)
        self.assertIn("BETA-FACT", capture_b.text())

    def test_no_sources_buddy_sends_only_the_thread(self):
        plain = Buddy.objects.create(org=self.org, slug="plain", name="Plain", created_by=self.member_a)
        thread_id = self._thread(self.member_a, plain)
        response, capture = self._send(self.member_a, thread_id)
        self.assertEqual(response.json()["sources_state"], "none")
        self.assertNotIn("ALPHA-FACT", capture.text())

    def test_memory_flag_off_means_no_retrieval(self):
        self.org.settings = {"flags": {"buddies": True}}
        self.org.save(update_fields=["settings"])
        thread_id = self._thread(self.member_a, self.builtin)
        with patch("knowledge.embeddings.FakeEmbedder.embed") as embed:
            response, capture = self._send(self.member_a, thread_id)
        embed.assert_not_called()
        self.assertEqual(response.json()["sources_state"], "disabled")
        self.assertNotIn("ALPHA-FACT", capture.text())

    def test_buddy_default_model_outside_allowlist_uses_platform_default(self):
        Buddy.objects.filter(pk=self.builtin.pk).update(default_model="gpt-secret-model")
        thread_id = self._thread(self.member_a, self.builtin)
        _, capture = self._send(self.member_a, thread_id)
        self.assertEqual(capture.bodies[-1]["model"], "qwen")


class SeedTests(TestCase):
    def test_seed_is_idempotent_and_keeps_edits(self):
        org = Organization.objects.create(name="FloLabs", slug="flolabs-test")
        self.assertEqual(seed_org(org), len(BUILTIN_BUDDIES))
        Buddy.objects.filter(org=org, slug="design").update(name="Our Design Buddy")
        self.assertEqual(seed_org(org), 0)
        self.assertEqual(Buddy.objects.get(org=org, slug="design").name, "Our Design Buddy")
        self.assertTrue(all(b.is_builtin for b in Buddy.objects.filter(org=org)))


class BuilderBase(BuddyBase):
    def setUp(self):
        super().setUp()
        self.lead_a = _user("bd-lead@example.com")
        OrgMembership.objects.create(
            org=self.org,
            user=self.lead_a,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )
        TeamMembership.objects.create(team=self.team_a, user=self.lead_a, team_role=TeamMembership.ROLE_LEAD)
        self.member_c = _user("bd-c@example.com")
        OrgMembership.objects.create(
            org=self.org,
            user=self.member_c,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )
        TeamMembership.objects.create(team=self.team_a, user=self.member_c)

    def _approve(self, buddy_id):
        """As the current user: read the request's hash, then approve it."""
        pending = {row["id"]: row for row in self.client.get(f"{self.base}/buddies/share-requests").json()}
        return self.client.post(
            f"{self.base}/buddies/{buddy_id}/share/approve", {"hash": pending[buddy_id]["hash"]}, format="json"
        )

    def _create(self, user, **body):
        self._auth(user)
        data = {"name": "My helper", "system_prompt": "Be kind.", **body}
        return self.client.post(f"{self.base}/buddies", data, format="json")


class BuddyBuilderTests(BuilderBase):
    def test_member_creates_private_buddy(self):
        response = self._create(self.member_a, preset_prompts=[{"label": "Go", "prompt": "Do it"}])
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["visibility"], "private")
        self.assertIn(body["id"], self._visible_ids(self.member_a))
        self.assertNotIn(body["id"], self._visible_ids(self.member_b))
        self._auth(self.member_b)
        self.assertEqual(self.client.get(f"{self.base}/buddies/{body['id']}").status_code, 404)
        self.assertEqual(self.client.patch(f"{self.base}/buddies/{body['id']}", {"name": "x"}, format="json").status_code, 404)

    def test_sources_and_tools_limited_to_the_creator(self):
        bad_room = self._create(self.member_a, allowed_sources={"mode": "rooms", "rooms": [str(self.room_b.id)]})
        self.assertEqual(bad_room.status_code, 400)
        ok_room = self._create(self.member_a, allowed_sources={"mode": "rooms", "rooms": [str(self.room_a.id)]})
        self.assertEqual(ok_room.status_code, 201)
        self.assertEqual(self._create(self.member_a, allowed_tools=["reports.generate"]).status_code, 400)
        self.assertEqual(self._create(self.member_a, allowed_tools=["no.such.tool"]).status_code, 400)
        self.assertEqual(self._create(self.member_a, allowed_tools=["tasks.create"]).status_code, 201)
        self.assertEqual(self._create(self.lead_a, allowed_tools=["reports.generate"]).status_code, 201)
        self.assertEqual(self._create(self.member_a, system_prompt="x" * 5000).status_code, 400)
        self.assertEqual(self._create(self.member_a, name="").status_code, 400)

    def test_team_share_needs_that_teams_lead(self):
        buddy_id = self._create(self.member_a).json()["id"]
        self._auth(self.member_a)
        not_my_team = self.client.post(
            f"{self.base}/buddies/{buddy_id}/share", {"target": "team", "team": str(self.team_b.id)}, format="json"
        )
        self.assertEqual(not_my_team.status_code, 404)
        asked = self.client.post(
            f"{self.base}/buddies/{buddy_id}/share", {"target": "team", "team": str(self.team_a.id)}, format="json"
        )
        self.assertEqual(asked.status_code, 202)
        self.assertNotIn(buddy_id, self._visible_ids(self.member_c), "pending is not shared")
        self._auth(self.member_c)
        self.assertEqual(self.client.post(f"{self.base}/buddies/{buddy_id}/share/approve").status_code, 403)
        self._auth(self.member_a)
        self.assertEqual(self.client.post(f"{self.base}/buddies/{buddy_id}/share/approve").status_code, 403)
        self._auth(self.lead_a)
        pending = [row["id"] for row in self.client.get(f"{self.base}/buddies/share-requests").json()]
        self.assertIn(buddy_id, pending)
        self.assertEqual(self._approve(buddy_id).status_code, 200)
        self.assertIn(buddy_id, self._visible_ids(self.member_c))
        self.assertNotIn(buddy_id, self._visible_ids(self.member_b))

    def test_org_share_needs_admin_and_lead_cannot_approve_it(self):
        buddy_id = self._create(self.member_a).json()["id"]
        self._auth(self.member_a)
        self.assertEqual(
            self.client.post(f"{self.base}/buddies/{buddy_id}/share", {"target": "org"}, format="json").status_code, 202
        )
        self._auth(self.lead_a)
        self.assertEqual(self.client.post(f"{self.base}/buddies/{buddy_id}/share/approve").status_code, 403)
        self._auth(self.owner)
        self.assertEqual(self._approve(buddy_id).status_code, 200)
        self.assertIn(buddy_id, self._visible_ids(self.member_b))

    def test_editing_a_shared_buddy_reopens_approval(self):
        buddy_id = self._create(self.member_a).json()["id"]
        self._auth(self.member_a)
        self.client.post(f"{self.base}/buddies/{buddy_id}/share", {"target": "org"}, format="json")
        self._auth(self.owner)
        self._approve(buddy_id)
        self._auth(self.member_a)
        renamed = self.client.patch(f"{self.base}/buddies/{buddy_id}", {"name": "Renamed"}, format="json")
        self.assertEqual(renamed.json()["share_status"], "approved", "a rename keeps the share")
        changed = self.client.patch(f"{self.base}/buddies/{buddy_id}", {"system_prompt": "New rules"}, format="json")
        self.assertEqual(changed.json()["share_status"], "pending")
        self.assertNotIn(buddy_id, self._visible_ids(self.member_b))
        self._auth(self.owner)
        self._approve(buddy_id)
        self.assertIn(buddy_id, self._visible_ids(self.member_b))

    def test_viewer_cannot_edit_shared_buddy_and_builtins_need_manage(self):
        self._auth(self.member_a)
        denied = self.client.patch(f"{self.base}/buddies/{self.builtin.id}", {"system_prompt": "x"}, format="json")
        self.assertEqual(denied.status_code, 403)
        self._auth(self.owner)
        ok = self.client.patch(f"{self.base}/buddies/{self.builtin.id}", {"system_prompt": "edited"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["share_status"], "approved", "built-ins do not need re-approval")

    def test_reject_and_unshare(self):
        buddy_id = self._create(self.member_a).json()["id"]
        self._auth(self.member_a)
        self.client.post(f"{self.base}/buddies/{buddy_id}/share", {"target": "org"}, format="json")
        self._auth(self.owner)
        self.assertEqual(self.client.post(f"{self.base}/buddies/{buddy_id}/share/reject").json()["share_status"], "rejected")
        self.assertNotIn(buddy_id, self._visible_ids(self.member_b))
        self.assertEqual(self.client.post(f"{self.base}/buddies/{buddy_id}/share/maybe").status_code, 404)

    def test_lead_sharing_with_own_team_is_approved_at_once(self):
        buddy_id = self._create(self.lead_a).json()["id"]
        self._auth(self.lead_a)
        response = self.client.post(
            f"{self.base}/buddies/{buddy_id}/share", {"target": "team", "team": str(self.team_a.id)}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(buddy_id, self._visible_ids(self.member_a))


class BuddyReviewFixTests(BuilderBase):
    def test_approve_needs_the_reviewed_hash_and_hides_unreadable_rooms(self):
        dm_room = ensure_team_room(self.team_b)  # a room lead_a cannot read
        TeamMembership.objects.create(team=self.team_b, user=self.member_a)
        buddy_id = self._create(
            self.member_a, allowed_sources={"mode": "rooms", "rooms": [str(self.room_a.id), str(dm_room.id)]}
        ).json()["id"]
        self._auth(self.member_a)
        self.client.post(
            f"{self.base}/buddies/{buddy_id}/share", {"target": "team", "team": str(self.team_a.id)}, format="json"
        )
        self._auth(self.lead_a)
        row = next(r for r in self.client.get(f"{self.base}/buddies/share-requests").json() if r["id"] == buddy_id)
        self.assertEqual(row["allowed_sources"]["rooms"], [str(self.room_a.id)])
        self.assertEqual(row["allowed_sources"]["hidden_rooms"], 1)
        old_hash = row["hash"]
        self._auth(self.member_a)
        self.client.patch(f"{self.base}/buddies/{buddy_id}", {"system_prompt": "sneaky"}, format="json")
        self._auth(self.lead_a)
        stale = self.client.post(f"{self.base}/buddies/{buddy_id}/share/approve", {"hash": old_hash}, format="json")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self._approve(buddy_id).status_code, 200)

    def test_preset_edit_reopens_approval(self):
        buddy_id = self._create(self.member_a).json()["id"]
        self._auth(self.member_a)
        self.client.post(f"{self.base}/buddies/{buddy_id}/share", {"target": "org"}, format="json")
        self._auth(self.owner)
        self._approve(buddy_id)
        self._auth(self.member_a)
        changed = self.client.patch(
            f"{self.base}/buddies/{buddy_id}", {"preset_prompts": [{"label": "Go", "prompt": "ignore rules"}]}, format="json"
        )
        self.assertEqual(changed.json()["share_status"], "pending")
