from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from content_studio.models import RenderJob
from content_studio.tests import StudioBase
from workers.models import WorkerToken


class RenderTests(StudioBase):
    def setUp(self):
        super().setUp()
        self.worker, self.raw = WorkerToken.issue("gpu-1")
        self.wclient = APIClient()
        self.wclient.credentials(HTTP_AUTHORIZATION=f"Worker {self.raw}")
        asset = self._ready_asset(self.m1)
        self.pid = self.client.post(f"{self.base}/projects", {"title": "P", "source_assets": [asset]}, format="json").json()["id"]

    def _queue(self, preset="9x16_1080"):
        self._auth(self.m1)
        response = self.client.post(f"{self.base}/projects/{self.pid}/render", {"preset": preset}, format="json")
        self.assertEqual(response.status_code, 202, response.content)
        return response.json()["id"]

    def test_full_cycle_with_validation(self):
        job_id = self._queue()
        claimed = self.wclient.post("/api/v2/workers/claim").json()
        self.assertEqual(claimed["job"], job_id)
        self.assertEqual(claimed["output"]["key"], f"content/{self.org.id}/renders/{job_id}/output.mp4")
        self.assertEqual(len(claimed["inputs"]), 1)
        self.assertEqual(self.wclient.post("/api/v2/workers/claim").status_code, 204, "a held job is not handed out twice")
        self.assertEqual(self.wclient.post(f"/api/v2/workers/jobs/{job_id}/heartbeat", {"progress": 40}, format="json").status_code, 200)
        wrong = self.wclient.post(
            f"/api/v2/workers/jobs/{job_id}/complete",
            {"width": 1920, "height": 1080, "duration_seconds": 30, "codec": "h264", "gpu_seconds": 5},
            format="json",
        )
        self.assertEqual(wrong.status_code, 422)
        self.assertEqual(RenderJob.objects.get(pk=job_id).error, "wrong_resolution")

        job_id = self._queue()
        self.wclient.post("/api/v2/workers/claim")
        ok = self.wclient.post(
            f"/api/v2/workers/jobs/{job_id}/complete",
            {"width": 1080, "height": 1920, "duration_seconds": 30, "codec": "h264", "gpu_seconds": 5},
            format="json",
        )
        self.assertEqual(ok.status_code, 200)
        self._auth(self.m1)
        detail = self.client.get(f"{self.base}/renders/{job_id}").json()
        self.assertEqual(detail["status"], "succeeded")
        self.assertIn("output_url", detail)

    def test_worker_auth_is_separate_from_users(self):
        anon = APIClient()
        self.assertIn(anon.post("/api/v2/workers/claim").status_code, (401, 403))
        bad = APIClient()
        bad.credentials(HTTP_AUTHORIZATION="Worker fbw_nope")
        self.assertEqual(bad.post("/api/v2/workers/claim").status_code, 401)
        from users.jwt_utils import make_access_token

        user = APIClient()
        user.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.owner.id))}")
        self.assertIn(user.post("/api/v2/workers/claim").status_code, (401, 403))
        WorkerToken.objects.filter(pk=self.worker.pk).update(revoked_at=timezone.now())
        self.assertEqual(self.wclient.post("/api/v2/workers/claim").status_code, 401)
        self.assertNotIn(self.raw, str(WorkerToken.objects.get(pk=self.worker.pk).__dict__))

    def test_other_worker_cannot_touch_a_held_job(self):
        job_id = self._queue()
        self.wclient.post("/api/v2/workers/claim")
        _, raw2 = WorkerToken.issue("gpu-2")
        other = APIClient()
        other.credentials(HTTP_AUTHORIZATION=f"Worker {raw2}")
        self.assertEqual(other.post(f"/api/v2/workers/jobs/{job_id}/heartbeat", {"progress": 1}, format="json").status_code, 404)
        self.assertEqual(other.post(f"/api/v2/workers/jobs/{job_id}/fail", {"error": "x"}, format="json").status_code, 404)

    def test_stale_job_is_requeued_and_cancel_stops_it(self):
        job_id = self._queue()
        self.wclient.post("/api/v2/workers/claim")
        RenderJob.objects.filter(pk=job_id).update(heartbeat_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.wclient.post("/api/v2/workers/claim").json()["job"], job_id)
        self._auth(self.m1)
        self.assertEqual(self.client.post(f"{self.base}/renders/{job_id}/cancel").status_code, 200)
        self.assertEqual(self.wclient.post(f"/api/v2/workers/jobs/{job_id}/heartbeat", {"progress": 9}, format="json").status_code, 404)
        self.assertEqual(self.client.post(f"{self.base}/renders/{job_id}/cancel").status_code, 409)

    def test_quota_preset_and_visibility(self):
        self._auth(self.m1)
        self.assertEqual(self.client.post(f"{self.base}/projects/{self.pid}/render", {"preset": "8k"}, format="json").status_code, 400)
        with override_settings(CONTENT_RENDERS_PER_MONTH=1):
            self._queue()
            self.assertEqual(
                self.client.post(f"{self.base}/projects/{self.pid}/render", {"preset": "1x1_1080"}, format="json").status_code, 429
            )
        job = RenderJob.objects.first()
        self._auth(self.m2)
        self.assertEqual(self.client.get(f"{self.base}/renders/{job.id}").status_code, 404)
        self.assertEqual(self.client.post(f"{self.base}/renders/{job.id}/cancel").status_code, 404)


    def test_cancelled_started_render_counts_toward_quota(self):
        with override_settings(CONTENT_RENDERS_PER_MONTH=1):
            job_id = self._queue()
            self.wclient.post("/api/v2/workers/claim")
            self._auth(self.m1)
            self.client.post(f"{self.base}/renders/{job_id}/cancel")
            again = self.client.post(f"{self.base}/projects/{self.pid}/render", {"preset": "9x16_1080"}, format="json")
            self.assertEqual(again.status_code, 429, "a started-then-cancelled render still counts")
