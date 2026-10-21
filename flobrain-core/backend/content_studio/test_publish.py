from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from content_studio.models import MediaAsset, OAuthState, PublishJob, SocialAccount
from content_studio.publishing import publish_due
from content_studio.tests import StudioBase
from workers.models import WorkerToken

KEY = "cd" * 32


@override_settings(SOCIAL_SANDBOX_ENABLED=True, CREDENTIALS_ENCRYPTION_KEY=KEY, FRONTEND_BASE_URL="https://app.example")
class PublishBase(StudioBase):
    def setUp(self):
        super().setUp()
        self.org.settings = {"flags": {"content_studio": True, "social_publishing": True}}
        self.org.save(update_fields=["settings"])
        self.asset = self._ready_asset(self.m1)
        self.pid = self.client.post(f"{self.base}/projects", {"title": "P", "source_assets": [self.asset]}, format="json").json()["id"]
        self.render = self._finished_render()
        self.root = f"/api/v2/orgs/{self.org.id}"

    def _finished_render(self):
        self._auth(self.m1)
        job_id = self.client.post(f"{self.base}/projects/{self.pid}/render", {"preset": "9x16_1080"}, format="json").json()["id"]
        _, raw = WorkerToken.issue("w")
        w = APIClient()
        w.credentials(HTTP_AUTHORIZATION=f"Worker {raw}")
        w.post("/api/v2/workers/claim")
        w.post(
            f"/api/v2/workers/jobs/{job_id}/complete",
            {"width": 1080, "height": 1920, "duration_seconds": 20, "codec": "h264", "gpu_seconds": 3},
            format="json",
        )
        return job_id

    def _connect(self, user=None):
        self._auth(user or self.owner)
        start = self.client.post(f"{self.root}/social-accounts/sandbox/connect")
        self.assertEqual(start.status_code, 200, start.content)
        state = parse_qs(urlparse(start.json()["authorize_url"]).query)["state"][0]
        callback = APIClient().get(f"/api/v2/oauth/callback/sandbox?state={state}&code=good-code")
        self.assertEqual(callback.status_code, 302)
        location = callback["Location"]
        code = parse_qs(urlparse(location).query)["confirm"][0]
        confirmed = self.client.post(f"{self.root}/social-accounts/confirm", {"code": code}, format="json")
        self.assertEqual(confirmed.status_code, 201, confirmed.content)
        return state, location

    def _submit(self, **extra):
        account = SocialAccount.objects.get(org=self.org)
        self._auth(self.m1)
        response = self.client.post(
            f"{self.root}/publish-jobs",
            {"project": self.pid, "render": self.render, "social_account": str(account.id), "title": "Clip", **extra},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def _approve(self, job, user=None):
        self._auth(user or self.owner)
        return self.client.post(f"{self.root}/publish-jobs/{job['id']}/approve", {"hash": job["hash"]}, format="json")


class PublishFlowTests(PublishBase):
    def test_end_to_end_with_approval(self):
        state, location = self._connect()
        self.assertIn("result=confirm", location)
        listed = self.client.get(f"{self.root}/social-accounts").json()
        self.assertNotIn("sandbox-token", str(listed))
        self.assertNotIn(b"sandbox-token", bytes(SocialAccount.objects.get().token_ciphertext))
        reused = APIClient().get(f"/api/v2/oauth/callback/sandbox?state={state}&code=good-code")
        self.assertTrue(reused["Location"].endswith("invalid_state"), "state is single-use")
        job = self._submit()
        self.assertEqual(job["status"], "awaiting_approval")
        self.assertEqual(self._approve(job, self.m1).status_code, 403, "a member cannot approve")
        approved = self._approve(job)
        self.assertEqual(approved.status_code, 200, approved.content)
        self.assertEqual(approved.json()["status"], "published")
        self.assertTrue(approved.json()["external_url"].startswith("https://sandbox.invalid/"))

    def test_consent_blocks_at_approval_and_again_at_publish(self):
        self._connect()
        self._auth(self.m1)
        self.client.put(f"{self.base}/assets/{self.asset}/people", {"people": [{"user_id": str(self.m2.id)}]}, format="json")
        job = self._submit()
        blocked = self._approve(job)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["problems"][0]["problem"], "missing_consent")
        self._auth(self.m2)
        given = self.client.post(f"{self.base}/consents", {"scope": "public_social"}, format="json")
        self.assertEqual(given.status_code, 201)
        later = (timezone.now() + timedelta(hours=1)).isoformat()
        self._auth(self.m1)
        job = self.client.patch(f"{self.root}/publish-jobs/{job['id']}", {"scheduled_at": later}, format="json").json()
        self.assertEqual(self._approve(job).json()["status"], "scheduled")
        self._auth(self.m2)
        self.client.post(f"{self.base}/consents/{given.json()['id']}/revoke")
        future = timezone.now() + timedelta(hours=2)
        with patch("django.utils.timezone.now", return_value=future):
            publish_due()
        row = PublishJob.objects.get(pk=job["id"])
        self.assertEqual(row.status, "awaiting_approval")
        self.assertEqual(row.error, "consent_missing")
        self.assertEqual(row.external_url, "")

    def test_untagged_faces_block(self):
        self._connect()
        MediaAsset.objects.filter(pk=self.asset).update(face_count=2)
        job = self._submit()
        response = self._approve(job)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["problems"][0]["problem"], "untagged_faces")

    def test_edit_resets_approval_and_stale_hash_is_refused(self):
        self._connect()
        later = (timezone.now() + timedelta(days=1)).isoformat()
        job = self._submit(scheduled_at=later)
        approved = self._approve(job).json()
        self.assertEqual(approved["status"], "scheduled")
        self._auth(self.m1)
        edited = self.client.patch(f"{self.root}/publish-jobs/{job['id']}", {"title": "Changed"}, format="json").json()
        self.assertEqual(edited["status"], "awaiting_approval")
        self.assertIsNone(edited["approved_by"])
        self.assertEqual(self._approve(job).status_code, 409, "the old hash no longer matches")
        PublishJob.objects.filter(pk=job["id"]).update(status="scheduled", approval_hash="tampered", scheduled_at=timezone.now())
        publish_due()
        self.assertEqual(PublishJob.objects.get(pk=job["id"]).error, "changed_after_approval")

    def test_oauth_state_rules_and_not_configured(self):
        self._auth(self.m1)
        self.assertEqual(self.client.post(f"{self.root}/social-accounts/sandbox/connect").status_code, 403)
        self._auth(self.owner)
        self.assertEqual(self.client.post(f"{self.root}/social-accounts/youtube/connect").status_code, 501)
        start = self.client.post(f"{self.root}/social-accounts/sandbox/connect").json()
        state = parse_qs(urlparse(start["authorize_url"]).query)["state"][0]
        OAuthState.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        expired = APIClient().get(f"/api/v2/oauth/callback/sandbox?state={state}&code=good-code")
        self.assertTrue(expired["Location"].endswith("invalid_state"))
        wrong = APIClient().get("/api/v2/oauth/callback/sandbox?state=guess&code=good-code")
        self.assertTrue(wrong["Location"].endswith("invalid_state"))
        self.assertFalse(SocialAccount.objects.exists())
        platforms = {p["platform"]: p for p in self.client.get(f"{self.root}/social-accounts/platforms").json()}
        self.assertFalse(platforms["youtube"]["configured"])
        self.assertTrue(platforms["youtube"]["posts_private_until_audit"])

    def test_flag_off_and_visibility(self):
        self._connect()
        job = self._submit()
        self._auth(self.m2)
        self.assertEqual(self.client.patch(f"{self.root}/publish-jobs/{job['id']}", {"title": "x"}, format="json").status_code, 404)
        self.assertEqual(self.client.get(f"{self.root}/publish-jobs").json(), [])
        self.org.settings = {"flags": {"content_studio": True}}
        self.org.save(update_fields=["settings"])
        self._auth(self.owner)
        self.assertEqual(self.client.get(f"{self.root}/publish-jobs").status_code, 501)


@override_settings(
    SOCIAL_SANDBOX_ENABLED=True,
    CREDENTIALS_ENCRYPTION_KEY=KEY,
    FRONTEND_BASE_URL="https://app.example",
    AI_DIRECT_BASE_URL="https://provider.example",
    AI_DIRECT_API_KEY="test-key-not-live",
    AI_DIRECT_MODEL_ALLOWLIST="qwen",
)
class PublishToolTests(PublishBase):
    def test_approved_tool_call_only_submits(self):
        import json as _json

        from actions.service import approve, propose_from_calls
        from buddies.models import Buddy

        self._connect()
        self.org.settings = {"flags": {"content_studio": True, "social_publishing": True, "ai_actions": True}}
        self.org.save(update_fields=["settings"])
        buddy = Buddy.objects.create(org=self.org, slug="cs", name="CS", created_by=self.m1, allowed_tools=["content.publish"])
        account = SocialAccount.objects.get(org=self.org)
        args = {"project": self.pid, "render": self.render, "social_account": str(account.id), "title": "AI post"}
        proposals, errors = propose_from_calls(
            self.m1, self.org, None, buddy, [{"name": "content__publish", "arguments": _json.dumps(args)}], ["content.publish"]
        )
        self.assertEqual(errors, [])
        done = approve(proposals[0].id, self.m1, self.org)
        self.assertEqual(done.status, "executed")
        job = PublishJob.objects.get(title="AI post")
        self.assertEqual(job.status, "awaiting_approval", "approving the AI proposal does not approve the post")
        self.assertEqual(job.external_url, "")



@override_settings(SOCIAL_SANDBOX_ENABLED=True, CREDENTIALS_ENCRYPTION_KEY=KEY, FRONTEND_BASE_URL="https://app.example")
class PublishReviewFixTests(PublishBase):
    def test_link_sent_to_someone_else_cannot_attach_their_channel(self):
        self._auth(self.owner)
        start = self.client.post(f"{self.root}/social-accounts/sandbox/connect").json()
        state = parse_qs(urlparse(start["authorize_url"]).query)["state"][0]
        victim_browser = APIClient().get(f"/api/v2/oauth/callback/sandbox?state={state}&code=good-code")
        code = parse_qs(urlparse(victim_browser["Location"]).query)["confirm"][0]
        self.assertFalse(SocialAccount.objects.exists(), "the callback alone connects nothing")
        # The attacker knows the state but never sees the victim's confirm code.
        self.assertEqual(self.client.post(f"{self.root}/social-accounts/confirm", {"code": "guess"}, format="json").status_code, 404)
        self._auth(self.m1)  # someone else signed in cannot use the code either
        self.assertIn(self.client.post(f"{self.root}/social-accounts/confirm", {"code": code}, format="json").status_code, (403, 404))
        self.assertFalse(SocialAccount.objects.exists())

    def test_consent_follows_the_render_not_the_current_project(self):
        self._connect()
        self._auth(self.m1)
        self.client.put(f"{self.base}/assets/{self.asset}/people", {"people": [{"user_id": str(self.m2.id)}]}, format="json")
        self.client.patch(f"{self.base}/projects/{self.pid}", {"source_assets": []}, format="json")
        job = self._submit()
        self.assertEqual(self._approve(job).status_code, 409, "the rendered footage still shows m2")

    def test_members_cannot_remove_tags_or_pad_faces(self):
        self._auth(self.owner)
        self.client.put(f"{self.base}/assets/{self.asset}/people", {"people": [{"user_id": str(self.m2.id)}]}, format="json")
        self._auth(self.m1)
        removed = self.client.put(f"{self.base}/assets/{self.asset}/people", {"people": []}, format="json")
        self.assertEqual(removed.status_code, 403)
        MediaAsset.objects.filter(pk=self.asset).update(face_count=3)
        padded = self.client.put(
            f"{self.base}/assets/{self.asset}/people",
            {"people": [{"user_id": str(self.m2.id)}, {"user_id": str(self.m1.id)}, {"user_id": str(self.m1.id)}]},
            format="json",
        )
        self.assertEqual(padded.json()["people"], 2, "duplicates do not count as extra people")

    def test_output_swapped_after_approval_is_not_published(self):
        self._connect()
        later = (timezone.now() + timedelta(hours=1)).isoformat()
        job = self._submit(scheduled_at=later)
        self.assertEqual(self._approve(job).json()["status"], "scheduled")
        with patch("content_studio.storage.head", return_value={"size": 1, "content_type": "video/mp4", "etag": "different"}), patch(
            "django.utils.timezone.now", return_value=timezone.now() + timedelta(hours=2)
        ):
            publish_due()
        row = PublishJob.objects.get(pk=job["id"])
        self.assertEqual((row.status, row.error), ("awaiting_approval", "output_changed"))

    def test_cancel_then_approve_is_refused(self):
        self._connect()
        job = self._submit()
        self._auth(self.m1)
        self.client.post(f"{self.root}/publish-jobs/{job['id']}/cancel")
        self.assertEqual(self._approve(job).status_code, 409)
        self.assertEqual(PublishJob.objects.get(pk=job["id"]).status, "cancelled")

    def test_bad_ids_are_4xx_not_500(self):
        self._connect()
        self._auth(self.m1)
        self.assertEqual(self.client.post(f"{self.root}/publish-jobs", {"project": "x", "render": "y", "social_account": "z", "title": "t"}, format="json").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/calendar?from=2026-02-30T00:00:00Z").status_code, 200)
        self.assertEqual(self.client.put(f"{self.base}/assets/{self.asset}/people", {"people": [{"user_id": "nope"}]}, format="json").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/projects/{self.pid}/captions.srt?asset=nope").status_code, 409)
        self.assertEqual(self.client.post(f"{self.base}/projects/{self.pid}/edl/revert", {"version": "x"}, format="json").status_code, 400)
        self.assertEqual(self.client.put(f"{self.base}/projects/{self.pid}/edl", {"operations": [], "base_version": "x"}, format="json").status_code, 400)
