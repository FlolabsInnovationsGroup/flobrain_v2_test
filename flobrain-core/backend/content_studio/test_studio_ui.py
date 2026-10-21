"""Backend behind the Studio UI: local storage URLs, voiceover (TTS interface), transcripts,
people/consent checks, the render queue, the demo render worker, demo AI answers and demo seed."""

import os
import shutil
import tempfile
import time
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from content_studio import storage, tts
from content_studio.models import AssetPerson, ConsentRecord, ContentProject, MediaAsset, PublishJob, RenderJob, SocialAccount
from content_studio.test_publish import KEY, PublishBase
from content_studio.tests import StudioBase


class LocalDirMixin:
    def setUp(self):
        super().setUp()
        self.media_dir = tempfile.mkdtemp(prefix="cs-test-")
        self.addCleanup(shutil.rmtree, self.media_dir, True)
        override = override_settings(CONTENT_STORAGE="local", CONTENT_LOCAL_DIR=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)

    def _path_of(self, url):
        parsed = urlparse(url)
        return parsed.path, {k: v[0] for k, v in parse_qs(parsed.query).items()}


class LocalStorageTests(LocalDirMixin, StudioBase):
    def test_signed_put_then_get_with_ranges(self):
        self._auth(self.m1)
        made = self.client.post(
            f"{self.base}/assets", {"kind": "video", "content_type": "video/mp4", "size_bytes": 10, "name": "a.mp4"}, format="json"
        ).json()
        path, query = self._path_of(made["upload_url"])
        self.assertTrue(path.startswith("/api/v2/content/local/content/"))
        anon = APIClient()
        # The asset cannot complete before the bytes exist.
        self.assertEqual(self.client.post(f"{self.base}/assets/{made['id']}/complete", {"duration_seconds": 5}, format="json").status_code, 409)
        wrong_type = anon.generic("PUT", made["upload_url"], b"0123456789", content_type="text/html")
        self.assertEqual(wrong_type.status_code, 400)
        bad_sig = anon.generic("PUT", made["upload_url"].replace(query["sig"], "0" * 64), b"x", content_type="video/mp4")
        self.assertEqual(bad_sig.status_code, 403)
        ok = anon.generic("PUT", made["upload_url"], b"0123456789", content_type="video/mp4")
        self.assertEqual(ok.status_code, 200, ok.content)
        done = self.client.post(f"{self.base}/assets/{made['id']}/complete", {"duration_seconds": 5}, format="json")
        self.assertEqual(done.status_code, 200, done.content)
        self.assertTrue(MediaAsset.objects.get(pk=made["id"]).source_etag)
        url = self.client.get(f"{self.base}/assets/{made['id']}").json()["url"]
        whole = anon.get(url)
        self.assertEqual(whole.status_code, 200)
        self.assertEqual(b"".join(whole.streaming_content), b"0123456789")
        part = anon.get(url, HTTP_RANGE="bytes=2-4")
        self.assertEqual(part.status_code, 206)
        self.assertEqual(b"".join(part.streaming_content), b"234")
        self.assertEqual(part["Content-Range"], "bytes 2-4/10")
        self.assertEqual(anon.get(url, HTTP_RANGE="bytes=50-").status_code, 416)
        # A GET signature does not allow a PUT, and the reverse.
        self.assertEqual(anon.generic("PUT", url, b"x", content_type="video/mp4").status_code, 403)
        self.assertEqual(anon.get(made["upload_url"]).status_code, 403)

    def test_expired_traversal_and_disabled(self):
        url = storage.presign_get("content/x/y/file.mp4", expires=-5)
        self.assertEqual(APIClient().get(url).status_code, 403)
        exp = int(time.time()) + 60
        sig = storage.sign_local("GET", "../../etc/passwd", exp)
        self.assertIn(APIClient().get(f"/api/v2/content/local/../../etc/passwd?exp={exp}&sig={sig}").status_code, (400, 403, 404))
        self.assertEqual(storage.local_path("../outside"), "")
        with override_settings(CONTENT_LOCAL_DIR=""):
            self.assertEqual(APIClient().get(storage.presign_get("content/a/b/c.mp4")).status_code, 404)
        with override_settings(CONTENT_STORAGE="s3", CONTENT_S3_BUCKET=""):
            self.assertEqual(APIClient().get("/api/v2/content/local/content/a?exp=1&sig=x").status_code, 404)

    def test_put_file_and_head(self):
        import io

        self.assertIsNone(storage.head("content/o/a/missing.mp4"))
        self.assertTrue(storage.put_file("content/o/a/x.mp4", io.BytesIO(b"abc"), "video/mp4"))
        meta = storage.head("content/o/a/x.mp4")
        self.assertEqual(meta["size"], 3)
        self.assertTrue(meta["etag"])
        self.assertFalse(storage.put_file("../escape.mp4", io.BytesIO(b"abc"), "video/mp4"))


class FakeTTS(tts.TTSProvider):
    name, label = "fake", "Fake voice"
    fail = False

    def configured(self):
        return True

    def voices(self):
        return [tts.Voice("narrator", "Narrator", "en"), tts.Voice("rawi", "Rawi", "ar")]

    def synthesize(self, text, voice, language):
        if FakeTTS.fail:
            raise tts.TTSError("vendor_down", transient=True)
        return tts.Speech(b"ID3fake-audio", "audio/mpeg", 4.2)


class VoiceoverTests(LocalDirMixin, StudioBase):
    def setUp(self):
        super().setUp()
        tts.register(FakeTTS)
        self.addCleanup(tts.REGISTRY.pop, "fake", None)
        FakeTTS.fail = False

    def test_not_configured_by_default(self):
        self.assertIsNone(tts.get_tts())
        with override_settings(TTS_PROVIDER="nobody"):
            self.assertIsNone(tts.get_tts())
        with override_settings(TTS_PROVIDER="demo", DEMO_MODE=False):
            self.assertIsNone(tts.get_tts(), "the demo voice only exists in demo mode")
        self._auth(self.m1)
        self.assertEqual(self.client.get(f"{self.base}/voiceover").status_code, 501)
        self.assertEqual(self.client.post(f"{self.base}/voiceover", {"text": "Hi"}, format="json").status_code, 501)

    @override_settings(TTS_PROVIDER="fake")
    def test_provider_makes_an_audio_asset(self):
        self._auth(self.m1)
        info = self.client.get(f"{self.base}/voiceover").json()
        self.assertEqual([v["id"] for v in info["voices"]], ["narrator", "rawi"])
        project = self.client.post(f"{self.base}/projects", {"title": "VO"}, format="json").json()
        made = self.client.post(f"{self.base}/voiceover", {"text": "Welcome to launch day.", "voice": "rawi", "project": project["id"]}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        body = made.json()
        self.assertEqual((body["kind"], body["status"], body["duration_seconds"]), ("audio", "ready", 4.2))
        self.assertTrue(body["url"])
        asset = MediaAsset.objects.get(pk=body["id"])
        self.assertTrue(asset.storage_key.endswith("voiceover.mp3"))
        self.assertTrue(os.path.isfile(storage.local_path(asset.storage_key)))
        self.assertIn(body["id"], self.client.get(f"{self.base}/projects/{project['id']}").json()["source_assets"])

    @override_settings(TTS_PROVIDER="fake")
    def test_bad_input_other_people_and_vendor_errors(self):
        self._auth(self.m1)
        for body in ({}, {"text": ""}, {"text": "x" * 5001}, {"text": "Hi", "voice": "someone-else"}, []):
            self.assertEqual(self.client.post(f"{self.base}/voiceover", body, format="json").status_code, 400, body)
        theirs = ContentProject.objects.create(org=self.org, owner=self.m2, title="Theirs")
        self.assertEqual(self.client.post(f"{self.base}/voiceover", {"text": "Hi", "project": str(theirs.id)}, format="json").status_code, 404)
        self.assertEqual(self.client.post(f"{self.base}/voiceover", {"text": "Hi", "project": "nope"}, format="json").status_code, 404)
        FakeTTS.fail = True
        self.assertEqual(self.client.post(f"{self.base}/voiceover", {"text": "Hi"}, format="json").status_code, 502)
        self.assertFalse(MediaAsset.objects.filter(kind="audio").exists())
        self._auth(self.outsider)
        self.assertEqual(self.client.post(f"{self.base}/voiceover", {"text": "Hi"}, format="json").status_code, 403)

    @override_settings(DEMO_MODE=True, TTS_PROVIDER="")
    def test_demo_voice_is_labelled(self):
        provider = tts.get_tts()
        self.assertIsInstance(provider, tts.DemoTTS)
        self._auth(self.m1)
        made = self.client.post(f"{self.base}/voiceover", {"text": "Hello"}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        self.assertTrue(made.json()["demo"])
        self.assertTrue(made.json()["name"].startswith("Demo voiceover"))
        self.assertEqual(made.json()["content_type"], "audio/mp4")


class TranscriptTests(StudioBase):
    def test_get_words_and_visibility(self):
        asset = self._ready_asset(self.m1)
        self._auth(self.m1)
        words = [{"w": "hello", "start": 0.1, "end": 0.4}, {"w": "world", "start": 0.5, "end": 0.9}]
        self.assertEqual(self.client.put(f"{self.base}/assets/{asset}/transcript", {"words": words}, format="json").status_code, 200)
        got = self.client.get(f"{self.base}/assets/{asset}/transcript").json()
        self.assertEqual((got["status"], len(got["words"])), ("done", 2))
        self._auth(self.m2)
        self.assertEqual(self.client.get(f"{self.base}/assets/{asset}/transcript").status_code, 404)
        self._auth(self.outsider)
        self.assertEqual(self.client.get(f"{self.base}/assets/{asset}/transcript").status_code, 403)

    def test_transcribe_not_configured_and_bad_input(self):
        asset = self._ready_asset(self.m1)
        image = self._ready_asset(self.m1, kind="image", content_type="image/png")
        self._auth(self.m1)
        self.assertEqual(self.client.post(f"{self.base}/assets/{asset}/transcribe").status_code, 501)
        self.assertEqual(self.client.post(f"{self.base}/assets/{image}/transcribe").status_code, 400)
        self.assertEqual(self.client.post(f"{self.base}/assets/{asset}/transcribe", {"language": "a$"}, format="json").status_code, 400)
        self._auth(self.m2)
        self.assertEqual(self.client.post(f"{self.base}/assets/{asset}/transcribe").status_code, 404)

    @override_settings(ASR_BACKEND="http", ASR_BASE_URL="http://whisper.local")
    def test_transcribe_with_speech_to_text(self):
        asset = self._ready_asset(self.m1)
        self._auth(self.m1)
        segments = {"text": "x", "segments": [{"start": 0.0, "end": 2.0, "text": "Hello there"}, {"start": 2.5, "end": 4.0, "text": "um okay"}]}
        with patch("content_studio.storage.download_to", return_value=True), patch("meetings.asr.transcribe_file", return_value=segments):
            res = self.client.post(f"{self.base}/assets/{asset}/transcribe", {"language": "en"}, format="json")
        self.assertEqual(res.status_code, 202, res.content)
        row = MediaAsset.objects.get(pk=asset)
        self.assertEqual(row.transcript_status, "done")
        self.assertEqual([w["w"] for w in row.transcript_words], ["Hello", "there", "um", "okay"])
        self.assertTrue(all(w["start"] < w["end"] for w in row.transcript_words))
        from meetings.asr import ASRError

        with patch("content_studio.storage.download_to", return_value=True), patch("meetings.asr.transcribe_file", side_effect=ASRError("unavailable")):
            self.client.post(f"{self.base}/assets/{asset}/transcribe", format="json")
        self.assertEqual(MediaAsset.objects.get(pk=asset).transcript_status, "failed")

    @override_settings(DEMO_MODE=True)
    def test_demo_transcript_fits_the_asset(self):
        asset = self._ready_asset(self.m1)  # 60 s
        short = MediaAsset.objects.create(
            org=self.org, uploaded_by=self.m1, kind="video", name="s.mp4", content_type="video/mp4", storage_key="k", status="ready", duration_seconds=12
        )
        self._auth(self.m1)
        for pk, limit in ((asset, 60), (str(short.id), 12)):
            res = self.client.post(f"{self.base}/assets/{pk}/transcribe")
            self.assertEqual(res.status_code, 202, res.content)
            self.assertTrue(res.json()["demo"])
            words = MediaAsset.objects.get(pk=pk).transcript_words
            self.assertGreater(len(words), 50)
            self.assertLessEqual(words[-1]["end"], limit)


class ConsentCheckTests(StudioBase):
    def setUp(self):
        super().setUp()
        self.asset = self._ready_asset(self.m1)
        self._auth(self.m1)
        self.pid = self.client.post(f"{self.base}/projects", {"title": "P", "source_assets": [self.asset]}, format="json").json()["id"]
        self.client.put(
            f"{self.base}/assets/{self.asset}/people", {"people": [{"user_id": str(self.m1.id)}, {"user_id": str(self.m2.id)}]}, format="json"
        )
        ConsentRecord.objects.create(org=self.org, person_user=self.m1, scope="public_social")

    def test_people_list_shows_consent(self):
        got = self.client.get(f"{self.base}/assets/{self.asset}/people").json()
        consented = {p["user_id"]: p["consented"] for p in got["tagged"]}
        self.assertEqual(consented, {str(self.m1.id): True, str(self.m2.id): False})
        self.assertFalse(got["can_remove"])
        self._auth(self.m2)
        self.assertEqual(self.client.get(f"{self.base}/assets/{self.asset}/people").status_code, 404)

    def test_project_check_names_who_is_missing(self):
        res = self.client.get(f"{self.base}/projects/{self.pid}/consent").json()
        self.assertFalse(res["ok"])
        self.assertEqual([(p["problem"], p["person"]) for p in res["problems"]], [("missing_consent", str(self.m2.id))])
        self.assertEqual(res["problems"][0]["asset_name"], "a.mp4")
        ConsentRecord.objects.create(org=self.org, person_user=self.m2, scope="marketing")
        self.assertTrue(self.client.get(f"{self.base}/projects/{self.pid}/consent").json()["ok"])
        self._auth(self.m2)
        self.assertEqual(self.client.get(f"{self.base}/projects/{self.pid}/consent").status_code, 404)

    def test_render_check(self):
        job = RenderJob.objects.create(
            org=self.org, project_id=self.pid, preset="9x16_1080", spec={"sources": [{"asset": self.asset, "key": "k"}]}
        )
        res = self.client.get(f"{self.base}/renders/{job.id}/consent").json()
        self.assertEqual(len(res["problems"]), 1)
        self._auth(self.m2)
        self.assertEqual(self.client.get(f"{self.base}/renders/{job.id}/consent").status_code, 404)
        self._auth(self.owner)
        self.assertEqual(self.client.get(f"{self.base}/renders/00000000-0000-0000-0000-000000000000/consent").status_code, 404)


class RenderQueueTests(LocalDirMixin, StudioBase):
    def _queue(self, user, preset="9x16_1080"):
        asset = self._ready_asset_local(user)
        self._auth(user)
        pid = self.client.post(f"{self.base}/projects", {"title": "Q", "source_assets": [asset]}, format="json").json()["id"]
        res = self.client.post(f"{self.base}/projects/{pid}/render", {"preset": preset}, format="json")
        self.assertEqual(res.status_code, 202, res.content)
        return pid, res.json()["id"]

    def _ready_asset_local(self, user):
        import io

        self._auth(user)
        made = self.client.post(
            f"{self.base}/assets", {"kind": "video", "content_type": "video/mp4", "size_bytes": 10, "name": "a.mp4"}, format="json"
        ).json()
        storage.put_file(MediaAsset.objects.get(pk=made["id"]).storage_key, io.BytesIO(b"0123456789"), "video/mp4")
        self.assertEqual(self.client.post(f"{self.base}/assets/{made['id']}/complete", {"duration_seconds": 30}, format="json").status_code, 200)
        return made["id"]

    def test_queue_lists_visible_renders_only(self):
        _, mine = self._queue(self.m1)
        _, theirs = self._queue(self.m2)
        self._auth(self.m1)
        ids = [r["id"] for r in self.client.get(f"{self.base}/renders").json()]
        self.assertEqual(ids, [mine])
        self.assertEqual(self.client.get(f"{self.base}/renders", {"status": "succeeded"}).json(), [])
        self._auth(self.owner)
        rows = self.client.get(f"{self.base}/renders").json()
        self.assertEqual({r["id"] for r in rows}, {mine, theirs})
        self.assertEqual(rows[0]["project_title"], "Q")
        self.assertEqual(RenderJob.objects.get(pk=mine).status, "queued", "no demo worker outside demo mode")

    @override_settings(DEMO_MODE=True)
    def test_demo_worker_renders_with_a_sample(self):
        from workers import demo_render

        pid, job_id = self._queue(self.m1)
        self._auth(self.m1)
        first = self.client.get(f"{self.base}/renders/{job_id}").json()
        self.assertEqual(first["status"], "running")
        later = timezone.now() + timedelta(seconds=demo_render.RUN_SECONDS + 1)
        demo_render.tick(self.org, now=timezone.now() + timedelta(seconds=3))
        self.assertGreater(RenderJob.objects.get(pk=job_id).progress, 0)
        with patch("django.utils.timezone.now", return_value=later):
            demo_render.tick(self.org)
        done = self.client.get(f"{self.base}/renders/{job_id}").json()
        self.assertEqual(done["status"], "succeeded", done)
        self.assertTrue(done["demo"])
        self.assertGreater(done["gpu_seconds"], 1)
        self.assertEqual((done["output"]["width"], done["output"]["height"]), (1080, 1920))
        job = RenderJob.objects.get(pk=job_id)
        self.assertEqual(job.worker.name, demo_render.WORKER_NAME)
        self.assertTrue(os.path.getsize(storage.local_path(job.output_key)) > 1000)
        # Other orgs' queued jobs are left alone.
        other = ContentProject.objects.create(org=self.other_org, owner=self.outsider, title="x")
        foreign = RenderJob.objects.create(org=self.other_org, project=other, preset="9x16_1080", spec={"resolution": [1080, 1920]})
        demo_render.tick(self.org)
        self.assertEqual(RenderJob.objects.get(pk=foreign.pk).status, "queued")

    @override_settings(DEMO_MODE=True)
    def test_demo_worker_fails_clearly_without_a_sample(self):
        from workers import demo_render

        project = ContentProject.objects.create(org=self.org, owner=self.m1, title="odd")
        job = RenderJob.objects.create(org=self.org, project=project, preset="custom", spec={"resolution": [640, 480], "template": {"duration_seconds": 3}})
        demo_render.tick(self.org)
        with patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(seconds=30)):
            demo_render.tick(self.org)
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIn("640x480", job.error)


@override_settings(DEMO_MODE=True, DEMO_AI=True)
class DemoAITests(StudioBase):
    def setUp(self):
        super().setUp()
        from content_studio import demo_media

        self.asset = MediaAsset.objects.create(
            org=self.org, uploaded_by=self.m1, kind="video", name="rec.mp4", content_type="video/mp4", storage_key="k",
            status="ready", duration_seconds=demo_media.manifest()["source"]["duration_seconds"], transcript_words=demo_media.source_words(),
        )
        self._auth(self.m1)
        self.pid = self.client.post(f"{self.base}/projects", {"title": "Launch", "source_assets": [str(self.asset.id)]}, format="json").json()["id"]

    def test_clips_cuts_and_copy_pass_validation(self):
        clips = self.client.post(f"{self.base}/projects/{self.pid}/suggest-clips", format="json")
        self.assertEqual(clips.status_code, 200, clips.content)
        body = clips.json()
        self.assertGreaterEqual(len(body["clips"]), 2)
        self.assertEqual(body["rejected"], [])
        self.assertTrue(all(c["hook_text"].startswith("(Demo)") for c in body["clips"]))
        cuts = self.client.post(f"{self.base}/projects/{self.pid}/auto-edit", format="json")
        self.assertEqual(cuts.status_code, 201, cuts.content)
        reasons = sorted({o.get("reason") for o in cuts.json()["operations"] if o["op"] == "cut"})
        self.assertEqual(reasons, ["filler", "silence"])
        self.assertEqual(cuts.json()["rejected"], [])
        fillers = [o for o in cuts.json()["operations"] if o.get("reason") == "filler"]
        self.assertEqual(len(fillers), 3)  # um, uh, like
        copy = self.client.post(f"{self.base}/projects/{self.pid}/copy", {"platforms": ["youtube", "tiktok"]}, format="json").json()["copy"]
        self.assertEqual(set(copy), {"youtube", "tiktok"})
        self.assertIn("(Demo copy)", copy["tiktok"]["description"])
        self.assertNotEqual(copy["youtube"]["title"], copy["tiktok"]["title"])


@override_settings(SOCIAL_SANDBOX_ENABLED=False)
class DemoPublishingTests(PublishBase):
    def test_sandbox_in_demo_and_unique_urls(self):
        from content_studio import connectors

        self.assertFalse(connectors.get("sandbox").configured())
        with override_settings(DEMO_MODE=True):
            self.assertTrue(connectors.get("sandbox").configured())
            self.assertEqual(connectors.get("sandbox").label, "Sandbox (demo)")
            a = connectors.get("sandbox").create_post({"access_token": "sandbox-token"}, "u", "t", "", [], False)
            b = connectors.get("sandbox").create_post({"access_token": "sandbox-token"}, "u", "t", "", [], False)
        self.assertNotEqual(a["url"], b["url"])
        self.assertTrue(a["url"].startswith("https://sandbox.invalid/post/"))

    @override_settings(SOCIAL_SANDBOX_ENABLED=True)
    def test_callback_returns_to_the_org_studio(self):
        _, location = self._connect()
        self.assertIn(f"/w/{self.org.slug}/studio?tab=accounts&result=confirm", location)
        bad = APIClient().get("/api/v2/oauth/callback/sandbox?state=unknown&code=x")
        self.assertEqual(bad["Location"], "https://app.example/?result=invalid_state")

    @override_settings(SOCIAL_SANDBOX_ENABLED=True)
    def test_calendar_and_demo_scheduler(self):
        self._connect()
        job = self._submit(scheduled_at=(timezone.now() + timedelta(days=2)).isoformat())
        self.assertEqual(self._approve(job).json()["status"], "scheduled")
        now_job = self._submit()
        self.assertEqual(self._approve(now_job).json()["status"], "published")
        self._auth(self.m1)
        rows = self.client.get(f"{self.root}/content/calendar").json()
        self.assertEqual({r["id"] for r in rows}, {job["id"], now_job["id"]}, "published-now posts show on the calendar too")
        later = timezone.now() + timedelta(days=3)
        with patch("django.utils.timezone.now", return_value=later):
            self.client.get(f"{self.root}/publish-jobs")
        self.assertEqual(PublishJob.objects.get(pk=job["id"]).status, "scheduled", "outside demo mode only the scheduler publishes")
        with override_settings(DEMO_MODE=True), patch("django.utils.timezone.now", return_value=later):
            self.client.get(f"{self.root}/publish-jobs")
        self.assertEqual(PublishJob.objects.get(pk=job["id"]).status, "published")
        bad = self.client.get(f"{self.root}/content/calendar", {"from": "2026-13-45T00:00"})
        self.assertEqual(bad.status_code, 200)


@override_settings(DEMO_MODE=True, CREDENTIALS_ENCRYPTION_KEY=KEY)
class DemoSeedTests(StudioBase):
    def test_seed_builds_a_blocked_and_a_published_story(self):
        import importlib

        from content_studio.models import BrandKit
        from content_studio import publishing

        BrandKit.objects.create(org=self.org, name="Kit")
        ContentProject.objects.create(org=self.org, owner=self.owner, title="Launch teaser (30 s)")
        users = {"member": self.m1, "admin": self.owner, "designer": self.m2, "owner": self.owner, "lead": self.lead}
        importlib.import_module("demo.extras.60_studio").seed(self.org, users, timezone.now())
        asset = MediaAsset.objects.get(org=self.org, name__startswith="Launch update recording")
        self.assertGreater(len(asset.transcript_words), 50)
        self.assertEqual(AssetPerson.objects.filter(asset=asset).count(), 2)
        self.assertEqual(ConsentRecord.objects.filter(org=self.org, revoked_at__isnull=True).count(), 1)
        account = SocialAccount.objects.get(org=self.org)
        self.assertEqual((account.platform, account.display_name), ("sandbox", "Sandbox (demo)"))
        jobs = {j.status: j for j in PublishJob.objects.filter(org=self.org)}
        self.assertEqual(set(jobs), {"published", "scheduled", "awaiting_approval"})
        blocked = publishing.consent_problems(jobs["awaiting_approval"].render)
        self.assertEqual([p["person"] for p in blocked], [str(self.m2.id)])
        self.assertEqual(publishing.consent_problems(jobs["scheduled"].render), [])
        self.assertTrue(all(r.output_meta.get("demo") for r in RenderJob.objects.filter(org=self.org)))
        # The pending post can be approved once Sara consents.
        ConsentRecord.objects.create(org=self.org, person_user=self.m2, scope="public_social")
        pending = jobs["awaiting_approval"]
        self._auth(self.owner)
        self.org.settings = {"flags": {"content_studio": True, "social_publishing": True}}
        self.org.save(update_fields=["settings"])
        approved = self.client.post(
            f"/api/v2/orgs/{self.org.id}/publish-jobs/{pending.id}/approve", {"hash": publishing.approval_hash(pending)}, format="json"
        )
        self.assertEqual(approved.status_code, 200, approved.content)
        self.assertEqual(approved.json()["status"], "scheduled")


class EditorBackendTests(StudioBase):
    def test_keeps_play_in_listed_order_for_captions(self):
        from content_studio.edl import captions, kept_ranges

        asset = MediaAsset.objects.create(
            org=self.org, uploaded_by=self.m1, kind="video", name="a.mp4", content_type="video/mp4", storage_key="k", status="ready",
            duration_seconds=10,
            transcript_words=[{"w": "first", "start": 1.0, "end": 1.5}, {"w": "second", "start": 6.0, "end": 6.5}],
        )
        ops = [{"op": "keep", "asset": str(asset.id), "start": 5.0, "end": 7.0}, {"op": "keep", "asset": str(asset.id), "start": 0.5, "end": 2.0}]
        self.assertEqual(kept_ranges(asset, ops), [(5.0, 7.0), (0.5, 2.0)])
        srt = captions(asset, ops, "srt")
        self.assertLess(srt.index("second"), srt.index("first"), "the second segment plays first")
        self.assertIn("00:00:01,000 --> 00:00:03,000\nsecond first", srt)

    def test_clip_list(self):
        from content_studio.models import ClipSuggestion

        asset = self._ready_asset(self.m1)
        self._auth(self.m1)
        pid = self.client.post(f"{self.base}/projects", {"title": "P", "source_assets": [asset]}, format="json").json()["id"]
        ClipSuggestion.objects.create(org=self.org, project_id=pid, asset_id=asset, start=1, end=20, hook_text="Hook", score=0.5)
        rows = self.client.get(f"{self.base}/projects/{pid}/suggest-clips").json()
        self.assertEqual([(r["hook_text"], r["accepted"]) for r in rows], [("Hook", False)])
        self._auth(self.m2)
        self.assertEqual(self.client.get(f"{self.base}/projects/{pid}/suggest-clips").status_code, 404)


class RenderNotificationTests(StudioBase):
    def test_requester_is_told_when_a_render_finishes(self):
        from notifications.models import Notification
        from workers.models import WorkerToken

        asset = self._ready_asset(self.m1)
        self._auth(self.m1)
        pid = self.client.post(f"{self.base}/projects", {"title": "Teaser", "source_assets": [asset]}, format="json").json()["id"]
        job_id = self.client.post(f"{self.base}/projects/{pid}/render", {"preset": "1x1_1080"}, format="json").json()["id"]
        _, raw = WorkerToken.issue("w")
        worker = APIClient()
        worker.credentials(HTTP_AUTHORIZATION=f"Worker {raw}")
        worker.post("/api/v2/workers/claim")
        worker.post(
            f"/api/v2/workers/jobs/{job_id}/complete",
            {"width": 1080, "height": 1080, "duration_seconds": 12, "codec": "h264", "gpu_seconds": 4},
            format="json",
        )
        row = Notification.objects.get(user=self.m1, kind="render_finished")
        self.assertEqual((row.payload["title"], row.payload["link"]), ("Teaser", f"studio/{pid}"))
        self.assertFalse(Notification.objects.filter(kind="render_finished").exclude(user=self.m1).exists())


@override_settings(DEMO_MODE=True, DEMO_AI=True, CREDENTIALS_ENCRYPTION_KEY=KEY, TTS_PROVIDER="")
class DemoJourneyTests(LocalDirMixin, StudioBase):
    """The spec's Content Studio journey, end to end on demo data (acceptance 10)."""

    def test_recording_to_published_clip(self):
        import importlib

        from content_studio.models import BrandKit
        from workers import demo_render

        self.org.settings = {"flags": {"content_studio": True, "social_publishing": True}}
        self.org.save(update_fields=["settings"])
        BrandKit.objects.create(org=self.org, name="Kit")
        users = {"member": self.m1, "admin": self.owner, "designer": self.m2, "owner": self.owner, "lead": self.lead}
        importlib.import_module("demo.extras.60_studio").seed(self.org, users, timezone.now())
        root = f"/api/v2/orgs/{self.org.id}"
        self._auth(self.m1)
        project = next(p for p in self.client.get(f"{self.base}/projects").json() if p["title"].startswith("Launch update"))
        pid, asset = project["id"], project["source_assets"][0]
        # The recording plays from local storage.
        url = self.client.get(f"{self.base}/assets/{asset}").json()["url"]
        media = APIClient().get(url, HTTP_RANGE="bytes=0-11")
        self.assertEqual(media.status_code, 206)
        self.assertIn(b"ftyp", b"".join(media.streaming_content))
        # Suggested clips, filler removal, accept a clip, captions in Arabic, 9:16.
        clips = self.client.post(f"{self.base}/projects/{pid}/suggest-clips", format="json").json()["clips"]
        edl = self.client.post(f"{self.base}/projects/{pid}/auto-edit", format="json").json()
        self.client.post(f"{self.base}/clips/{clips[0]['id']}/accept", format="json")
        current = self.client.get(f"{self.base}/projects/{pid}/edl").json()
        ops = [o for o in current["operations"] if o["op"] != "captions"] + [{"op": "captions", "language": "ar", "burn_in": True}]
        saved = self.client.put(f"{self.base}/projects/{pid}/edl", {"operations": ops, "base_version": current["version"]}, format="json")
        self.assertEqual(saved.status_code, 201, saved.content)
        self.assertGreater(saved.json()["version"], edl["version"])
        self.assertIn("-->", self.client.get(f"{self.base}/projects/{pid}/captions.srt").content.decode())
        # Render on the (demo) worker.
        job = self.client.post(f"{self.base}/projects/{pid}/render", {"preset": "9x16_1080"}, format="json").json()
        self.client.get(f"{self.base}/renders")
        with patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(seconds=demo_render.RUN_SECONDS + 1)):
            demo_render.tick(self.org)
        done = self.client.get(f"{self.base}/renders/{job['id']}").json()
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(APIClient().get(done["output_url"]).status_code, 200)
        # Copy, submit; approval is blocked until Sara consents.
        copy = self.client.post(f"{self.base}/projects/{pid}/copy", format="json").json()["copy"]
        account = SocialAccount.objects.get(org=self.org, platform="sandbox")
        post = self.client.post(
            f"{root}/publish-jobs",
            {"project": pid, "render": job["id"], "social_account": str(account.id), **copy["youtube"]},
            format="json",
        ).json()
        self.assertEqual(post["status"], "awaiting_approval")
        self.assertEqual(self._approve_as_owner(root, post).json()["error"], "consent_missing")
        self._auth(self.owner)
        self.client.post(f"{self.base}/consents", {"scope": "public_social", "person_user": str(self.m2.id)}, format="json")
        published = self._approve_as_owner(root, post).json()
        self.assertEqual(published["status"], "published")
        self.assertTrue(published["external_url"].startswith("https://sandbox.invalid/post/"))
        self.assertIn(post["id"], [r["id"] for r in self.client.get(f"{root}/content/calendar").json()])

    def _approve_as_owner(self, root, post):
        self._auth(self.owner)
        return self.client.post(f"{root}/publish-jobs/{post['id']}/approve", {"hash": post["hash"]}, format="json")
