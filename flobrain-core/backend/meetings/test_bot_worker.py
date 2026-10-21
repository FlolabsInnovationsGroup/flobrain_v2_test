from datetime import timedelta
from unittest import mock

from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from meetings.models import Meeting, MeetingBotSession, Recording
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.services import ensure_team_room
from users.jwt_utils import make_access_token
from users.models import User
from workers.models import WorkerToken


@override_settings(MEETING_BOT_VENDOR="self_hosted", CONTENT_STORAGE="local", ASR_BACKEND="")
class BotWorkerTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="B", slug="bot-org", settings={"flags": {"meeting_bot": True}})
        self.owner = User.objects.create(email="o@b.test", username="o", password_hash=make_password("x"))
        OrgMembership.objects.create(org=self.org, user=self.owner, org_role="owner", employment_status="active")
        team = Team.objects.create(org=self.org, name="T")
        TeamMembership.objects.create(team=team, user=self.owner)
        self.room = ensure_team_room(team)
        self.meeting = Meeting.objects.create(org=self.org, room=self.room, title="Client call", created_by=self.owner)
        _, self.raw = WorkerToken.issue("bot-1", "meeting_bot")
        _, self.render_raw = WorkerToken.issue("gpu-1", "render")
        self.user = APIClient()
        self.user.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.owner.id))}")

    def _worker(self, raw=None):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Worker {raw or self.raw}")
        return c

    def _invite(self):
        url = f"/api/v2/orgs/{self.org.id}/rooms/{self.room.id}/meetings/{self.meeting.id}/bot"
        return self.user.post(url, {"platform": "meet", "meeting_url": "https://meet.google.com/abc-defg-hij", "host_consent": True}, format="json")

    def test_full_session_and_token_kinds(self):
        self.assertEqual(self._invite().status_code, 201)
        self.assertEqual(self._worker(self.render_raw).post("/api/v2/workers/meeting-bots/claim").status_code, 403, "a render token can't claim bots")
        self.assertEqual(self._worker().post("/api/v2/workers/claim").status_code, 403, "a bot token can't claim renders")
        job = self._worker().post("/api/v2/workers/meeting-bots/claim").json()
        self.assertEqual((job["platform"], job["bot_name"]), ("meet", "FloBrain assistant"))
        self.assertEqual(self._worker().post("/api/v2/workers/meeting-bots/claim").status_code, 204)
        sid = job["session"]
        res = self._worker().post(f"/api/v2/workers/meeting-bots/{sid}/status", {"status": "in_call"}, format="json").json()
        self.assertFalse(res["leave"])
        audio = SimpleUploadedFile("a.ogg", b"OggS", content_type="audio/ogg")
        self.assertEqual(self._worker().post(f"/api/v2/workers/meeting-bots/{sid}/audio", {"file": audio}, format="multipart").status_code, 201)
        session = MeetingBotSession.objects.get(pk=sid)
        self.assertEqual((session.status, Recording.objects.get(pk=session.recording_id).source), ("done", "bot"))

    def test_cancel_and_stale(self):
        self._invite()
        sid = self._worker().post("/api/v2/workers/meeting-bots/claim").json()["session"]
        other = WorkerToken.issue("bot-2", "meeting_bot")[1]
        self.assertEqual(self._worker(other).post(f"/api/v2/workers/meeting-bots/{sid}/status", {"status": "in_call"}, format="json").status_code, 404)
        cancel = f"/api/v2/orgs/{self.org.id}/meetings/{self.meeting.id}/bot-sessions/{sid}/cancel"
        self.assertEqual(self.user.post(cancel).json(), {"cancelled": True})
        self.assertTrue(self._worker().post(f"/api/v2/workers/meeting-bots/{sid}/status", {"status": "in_call"}, format="json").json()["leave"])
        self._invite()
        sid2 = self._worker().post("/api/v2/workers/meeting-bots/claim").json()["session"]
        MeetingBotSession.objects.filter(pk=sid2).update(heartbeat_at=timezone.now() - timedelta(minutes=10))
        self._worker().post("/api/v2/workers/meeting-bots/claim")
        self.assertEqual(MeetingBotSession.objects.get(pk=sid2).status, "joining", "waiting in the lobby is not lost")
        MeetingBotSession.objects.filter(pk=sid2).update(heartbeat_at=timezone.now() - timedelta(minutes=20))
        self._worker().post("/api/v2/workers/meeting-bots/claim")
        self.assertEqual(MeetingBotSession.objects.get(pk=sid2).error, "worker_lost")

    def test_old_requests_expire_and_audio_needs_a_real_join(self):
        self._invite()
        old = MeetingBotSession.objects.get()
        MeetingBotSession.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=3))
        self.assertEqual(self._worker().post("/api/v2/workers/meeting-bots/claim").status_code, 204)
        self.assertEqual(MeetingBotSession.objects.get(pk=old.pk).error, "expired")
        self._invite()
        sid = self._worker().post("/api/v2/workers/meeting-bots/claim").json()["session"]
        audio = SimpleUploadedFile("a.ogg", b"OggS", content_type="audio/ogg")
        self.assertEqual(self._worker().post(f"/api/v2/workers/meeting-bots/{sid}/audio", {"file": audio}, format="multipart").status_code, 409, "never joined")
        MeetingBotSession.objects.filter(pk=sid).update(status="failed", joined_at=timezone.now())
        audio = SimpleUploadedFile("a.ogg", b"OggS", content_type="audio/ogg")
        self.assertEqual(self._worker().post(f"/api/v2/workers/meeting-bots/{sid}/audio", {"file": audio}, format="multipart").status_code, 409, "failed sessions take no audio")



class StatusLengthTests(TestCase):
    def test_every_status_fits_the_column(self):
        from meetings.models import MeetingBotSession
        from meetings.views_bot_worker import FROM_WORKER, LIVE

        width = MeetingBotSession._meta.get_field("status").max_length
        for status in {*LIVE, *FROM_WORKER, "requested", "cancelled", "expired"}:
            self.assertLessEqual(len(status), width, status)
