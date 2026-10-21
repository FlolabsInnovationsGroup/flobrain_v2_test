import base64
import hashlib
import json
import time
from unittest import mock

import jwt
from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from meetings.models import Meeting, MeetingSummary, Recording, Transcript
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.models import RoomMessage
from rooms.services import ensure_team_room
from users.jwt_utils import make_access_token
from users.models import User

LK = dict(LIVEKIT_URL="wss://calls.example.test", LIVEKIT_API_KEY="lk_key", LIVEKIT_API_SECRET="lk_secret_that_is_long_enough_123")


@override_settings(**LK)
class CallTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="C", slug="calls-org", settings={"flags": {"voice_video": True}})
        self.other = Organization.objects.create(name="O", slug="calls-other", settings={"flags": {"voice_video": True}})
        self.users = {}
        for name, role in (("owner", "owner"), ("ana", "member"), ("ben", "member")):
            u = User.objects.create(email=f"{name}@c.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            self.users[name] = u
        team = Team.objects.create(org=self.org, name="T")
        TeamMembership.objects.create(team=team, user=self.users["ana"])
        self.room = ensure_team_room(team)
        self.meeting = Meeting.objects.create(org=self.org, room=self.room, title="Standup", created_by=self.users["owner"])
        self.base = f"/api/v2/orgs/{self.org.id}/meetings/{self.meeting.id}"

    def _as(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return c

    def test_join_token_is_scoped_to_the_call_and_person(self):
        with mock.patch("meetings.livekit._api", return_value={}) as api:
            res = self._as("ana").post(f"{self.base}/join").json()
        self.assertEqual(api.call_args[0][:2], ("RoomService", "CreateRoom"), "FloBrain creates the room; tokens alone can't")
        claims = jwt.decode(res["token"], LK["LIVEKIT_API_SECRET"], algorithms=["HS256"])
        self.assertEqual((claims["sub"], claims["video"]["room"], claims["iss"]), (str(self.users["ana"].id), f"fb-{self.meeting.id}", "lk_key"))
        self.assertLessEqual(claims["exp"] - time.time(), 10 * 60 + 5)
        self.assertFalse(res["can_manage"])
        self.assertEqual(self._as("ben").post(f"{self.base}/join").status_code, 404, "not in the room")
        from meetings.livekit import LiveKitError

        with mock.patch("meetings.livekit._api", side_effect=LiveKitError("URLError")):
            self.assertEqual(self._as("ana").post(f"{self.base}/join").status_code, 502)
        with override_settings(LIVEKIT_URL=""):
            self.assertEqual(self._as("ana").post(f"{self.base}/join").status_code, 501)

    def test_recording_needs_manage_and_posts_a_notice_first(self):
        self.assertEqual(self._as("ana").post(f"{self.base}/recording", {"action": "start"}, format="json").status_code, 403)
        calls = []

        def api(service, method, body, grants):
            calls.append((service, method))
            if method == "ListParticipants":
                return {"participants": [{"identity": str(self.users["ana"].id), "name": "ana", "tracks": [{"sid": "TR_a", "type": "AUDIO"}, {"sid": "TR_v", "type": "VIDEO"}]}]}
            if method == "StartTrackEgress":
                return {"egress_id": f"EG_{body['track_id']}"}
            return {}

        with mock.patch("meetings.livekit._api", side_effect=api):
            res = self._as("owner").post(f"{self.base}/recording", {"action": "start"}, format="json")
        self.assertEqual(res.json(), {"recording": True})
        self.assertEqual(calls, [("RoomService", "ListParticipants"), ("Egress", "StartTrackEgress")], "one recording per microphone, none for video")
        self.assertTrue(RoomMessage.objects.filter(room=self.room, body__startswith="Recording started by owner").exists())
        self.assertTrue(self._as("ana").get(f"{self.base}/state").json()["recording"])
        with mock.patch("meetings.livekit._api", side_effect=api):
            self.assertEqual(self._as("owner").post(f"{self.base}/recording", {"action": "start"}, format="json").status_code, 409, "one recording at a time")
        # Someone starts speaking later: the webhook records their track too, once.
        event = {"event": "track_published", "room": {"name": f"fb-{self.meeting.id}"}, "participant": {"identity": str(self.users["owner"].id), "name": "owner"}, "track": {"sid": "TR_o", "type": "AUDIO"}}
        with mock.patch("meetings.livekit._api", side_effect=api):
            self.assertTrue(self._webhook(event).json().get("recording_track"))
            self._webhook(event)
        from meetings.models import TrackEgress

        self.assertEqual(TrackEgress.objects.filter(meeting=self.meeting).count(), 2)
        # While recording is still being switched on ("starting"), a new microphone is recorded too.
        Meeting.objects.filter(pk=self.meeting.pk).update(recording_egress_id="starting")
        late = {**event, "track": {"sid": "TR_late", "type": "AUDIO"}}
        with mock.patch("meetings.livekit._api", side_effect=api):
            self.assertTrue(self._webhook(late).json().get("recording_track"))
        Meeting.objects.filter(pk=self.meeting.pk).update(recording_egress_id="tracks")
        self.assertEqual(TrackEgress.objects.filter(meeting=self.meeting).count(), 3)
        from meetings.livekit import LiveKitError

        with mock.patch("meetings.livekit._api", side_effect=LiveKitError("http_404", 404)):
            self.assertEqual(self._as("owner").post(f"{self.base}/recording", {"action": "stop"}, format="json").json(), {"recording": False}, "an egress that already ended counts as stopped")
        self.assertFalse(TrackEgress.objects.filter(meeting=self.meeting, stopped_at__isnull=True).exists())
        with mock.patch("meetings.livekit._api", side_effect=LiveKitError("http_500", 500)):
            self.assertEqual(self._as("owner").post(f"{self.base}/recording", {"action": "start"}, format="json").status_code, 502)
        self.assertEqual(Meeting.objects.get(pk=self.meeting.pk).recording_egress_id, "", "a failed start releases the claim")

    @override_settings(ASR_BACKEND="http", ASR_BASE_URL="http://whisper:8000", CONTENT_STORAGE="local")
    def test_speakers_are_known_and_merged_in_time_order(self):
        from datetime import timedelta

        from django.utils import timezone

        from meetings.models import TrackEgress

        t0 = timezone.now() - timedelta(minutes=5)
        Meeting.objects.filter(pk=self.meeting.pk).update(recording_egress_id="tracks", recording_started_at=t0)
        TrackEgress.objects.create(meeting=self.meeting, egress_id="EG_a", track_sid="TR_a", participant_identity=str(self.users["ana"].id), participant_name="Ana", started_at=t0)
        TrackEgress.objects.create(meeting=self.meeting, egress_id="EG_o", track_sid="TR_o", participant_identity=str(self.users["owner"].id), participant_name="Owner", started_at=t0 + timedelta(seconds=10))
        outputs = {
            "a": {"text": "Hello everyone.", "segments": [{"start": 1, "end": 2, "text": "Hello everyone."}, {"start": 20, "end": 21, "text": "Agreed."}], "language": "en"},
            "o": {"text": "Let's ship Friday.", "segments": [{"start": 2, "end": 4, "text": "Let's ship Friday."}], "language": "en"},
        }

        def fake_download(key, fileobj):
            fileobj.write(b"OggS")
            return True

        def fake_asr(path, file_name, content_type):
            return outputs["a" if "TR_a" in file_name else "o"]

        for who in ("a", "o"):
            key = f"meetings/{self.org.id}/{self.meeting.id}/{self.users['ana' if who == 'a' else 'owner'].id}-TR_{who}-2026.ogg"
            event = {"event": "egress_ended", "egressInfo": {"egressId": f"EG_{who}", "roomName": f"fb-{self.meeting.id}", "fileResults": [{"filename": key}]}}
            with mock.patch("content_studio.storage.download_to", fake_download), mock.patch("meetings.asr.transcribe_file", side_effect=fake_asr):
                with self.captureOnCommitCallbacks(execute=True):
                    self.assertEqual(self._webhook(event).json()["recordings"], 1)
        rec = Recording.objects.get(egress_id="EG_o")
        self.assertEqual((rec.speaker_id, rec.speaker_name, rec.offset_seconds), (self.users["owner"].id, "Owner", 10.0))
        merged = self._as("ana").get(f"/api/v2/orgs/{self.org.id}/meetings/{self.meeting.id}/transcript").json()
        self.assertEqual([(s["speaker"], s["text"]) for s in merged["segments"]], [("Ana", "Hello everyone."), ("Owner", "Let's ship Friday."), ("Ana", "Agreed.")])
        self.assertEqual(merged["speakers"], ["Ana", "Owner"])
        from meetings.pipeline import _labelled_text

        self.assertEqual(_labelled_text(self.meeting), "Ana: Hello everyone.\nOwner: Let's ship Friday.\nAna: Agreed.")
        self.assertEqual(self._as("ben").get(f"/api/v2/orgs/{self.org.id}/meetings/{self.meeting.id}/transcript").status_code, 404)

    def test_losing_access_removes_you_from_live_calls(self):
        removed = []
        with mock.patch("meetings.livekit._api", side_effect=lambda s, m, b, g: removed.append((m, b.get("identity"))) or {}):
            with self.captureOnCommitCallbacks(execute=True):
                TeamMembership.objects.filter(user=self.users["ana"]).delete()
        self.assertIn(("RemoveParticipant", str(self.users["ana"].id)), removed)
        removed.clear()
        with mock.patch("meetings.livekit._api", side_effect=lambda s, m, b, g: removed.append((m, b.get("identity"))) or {}):
            with self.captureOnCommitCallbacks(execute=True):
                OrgMembership.objects.filter(org=self.org, user=self.users["owner"]).update(employment_status="active")  # update() sends no signal
                m = OrgMembership.objects.get(org=self.org, user=self.users["owner"])
                m.employment_status = "active"
                m.save()
        self.assertEqual(removed, [], "still a member: nobody is removed")

    def _webhook(self, event, secret=LK["LIVEKIT_API_SECRET"]):
        body = json.dumps(event).encode()
        token = jwt.encode({"iss": "lk_key", "sha256": base64.b64encode(hashlib.sha256(body).digest()).decode(), "exp": int(time.time()) + 60}, secret, algorithm="HS256")
        return APIClient().post("/api/v2/livekit/webhook", data=body, content_type="application/webhook+json", HTTP_AUTHORIZATION=token)

    @override_settings(ASR_BACKEND="http", ASR_BASE_URL="http://whisper:8000", CONTENT_STORAGE="local", DEMO_MODE=True, DEMO_AI=True)
    def test_webhook_recording_to_transcript_to_summary(self):
        key = f"meetings/{self.org.id}/{self.meeting.id}/2026.ogg"
        event = {"event": "egress_ended", "egressInfo": {"egressId": "EG_1", "roomName": f"fb-{self.meeting.id}", "fileResults": [{"filename": key, "duration": "65000000000"}]}}
        self.assertEqual(self._webhook(event, secret="wrong").status_code, 401)
        bad = {"event": "egress_ended", "egressInfo": {"roomName": f"fb-{self.meeting.id}", "fileResults": [{"filename": "elsewhere/x.ogg"}]}}
        self.assertEqual(self._webhook(bad).json()["recordings"], 0, "keys outside our prefix are ignored")
        asr_out = {"text": "We release next month. Youssef fixes the login bug.", "segments": [{"start": 0, "end": 65, "text": "We release next month."}], "language": "en"}
        def fake_download(key, fileobj):
            fileobj.write(b"OggS")
            return True

        sneaky = {"event": "egress_ended", "egressInfo": {"roomName": f"fb-{self.meeting.id}", "fileResults": [{"filename": f"meetings/{self.org.id}/{self.meeting.id}/../../x/y.ogg"}]}}
        self.assertEqual(self._webhook(sneaky).json()["recordings"], 0, "no path tricks after our prefix")
        self.assertEqual(self._webhook({"event": "egress_ended", "egressInfo": "junk"}).status_code, 200)
        with mock.patch("content_studio.storage.download_to", fake_download), mock.patch("meetings.asr.transcribe_file", return_value=asr_out):
            with self.captureOnCommitCallbacks(execute=True):
                res = self._webhook(event)
        self.assertEqual(res.json()["recordings"], 1)
        rec = Recording.objects.get(meeting=self.meeting)
        self.assertEqual((rec.source, rec.transcript_status, rec.duration_seconds), ("livekit", "done", 65))
        self.assertEqual(Transcript.objects.get(recording=rec).language, "en")
        summary = MeetingSummary.objects.get(meeting=self.meeting)
        self.assertEqual(summary.action_items[0]["id"], "a1")
        task = self._as("owner").post(f"/api/v2/orgs/{self.org.id}/meetings/{self.meeting.id}/action-items/a1/to-task", {"confirm": True}, format="json").json()
        self.assertEqual(task["title"], "Fix the Android login timeout")

    @override_settings(ASR_BACKEND="http", ASR_BASE_URL="http://whisper:8000", CONTENT_STORAGE="local")
    def test_upload_checks_type_and_permission(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        url = f"{self.base}/recordings"
        audio = SimpleUploadedFile("a.ogg", b"OggS data", content_type="audio/ogg")
        self.assertEqual(self._as("ana").post(url, {"file": audio}, format="multipart").status_code, 403)
        exe = SimpleUploadedFile("a.exe", b"MZ", content_type="application/octet-stream")
        self.assertEqual(self._as("owner").post(url, {"file": exe}, format="multipart").status_code, 400)
        audio = SimpleUploadedFile("a.ogg", b"OggS data", content_type="audio/ogg")
        with mock.patch("jobs.queue.enqueue"):
            res = self._as("owner").post(url, {"file": audio}, format="multipart")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Recording.objects.get(pk=res.json()["id"]).storage_key.startswith(f"meetings/{self.org.id}/{self.meeting.id}/"))

    def test_calls_off_without_flag_and_end_needs_manage(self):
        Organization.objects.filter(pk=self.org.pk).update(settings={"flags": {}})
        self.assertEqual(self._as("ana").post(f"{self.base}/join").status_code, 501)
        Organization.objects.filter(pk=self.org.pk).update(settings={"flags": {"voice_video": True}})
        self.assertEqual(self._as("ana").post(f"{self.base}/end").status_code, 403)
        with mock.patch("meetings.livekit._api", return_value={}):
            self.assertEqual(self._as("owner").post(f"{self.base}/end").json(), {"ended": True})
        self.assertEqual(self._as("ana").post(f"{self.base}/join").status_code, 409)

    @override_settings(ASR_BACKEND="http", ASR_BASE_URL="http://whisper:8000", TESTING=False, JOBS_EAGER=False, JOBS_WORKER_ENABLED=False)
    def test_transcribe_without_a_worker_and_stuck_jobs(self):
        from datetime import timedelta

        from django.utils import timezone

        rec = Recording.objects.create(org=self.org, meeting=self.meeting, storage_key=f"meetings/{self.org.id}/{self.meeting.id}/a.ogg")
        url = f"/api/v2/orgs/{self.org.id}/recordings/{rec.id}/transcribe"
        self.assertEqual(self._as("owner").post(url).status_code, 501)
        self.assertEqual(Recording.objects.get(pk=rec.pk).transcript_status, "failed", "never left queued with nobody to run it")
        Recording.objects.filter(pk=rec.pk).update(transcript_status="running", transcript_updated_at=timezone.now())
        with override_settings(JOBS_WORKER_ENABLED=True):
            self.assertEqual(self._as("owner").post(url).status_code, 409)
            Recording.objects.filter(pk=rec.pk).update(transcript_updated_at=timezone.now() - timedelta(hours=3))
            with mock.patch("jobs.queue.enqueue"):
                self.assertEqual(self._as("owner").post(url).status_code, 202, "a stuck job can be started again")

    @override_settings(ASR_BACKEND="http", ASR_BASE_URL="http://whisper:8000")
    def test_unexpected_errors_fail_the_recording(self):
        from meetings import pipeline

        rec = Recording.objects.create(org=self.org, meeting=self.meeting, storage_key="k", transcript_status="queued")
        with mock.patch("content_studio.storage.download_to", side_effect=MemoryError()):
            with self.assertRaises(MemoryError):
                pipeline.transcribe_recording({"recording_id": str(rec.id)})
        self.assertEqual((Recording.objects.get(pk=rec.pk).transcript_status, Recording.objects.get(pk=rec.pk).transcript_error), ("failed", "MemoryError"))

