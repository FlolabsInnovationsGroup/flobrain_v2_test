from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from meetings.models import Meeting, MeetingBotSession, MeetingSummary, Recording
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.services import ensure_team_room
from tasks.models import Task
from users.jwt_utils import make_access_token
from users.models import User

DEMO = dict(DEMO_MODE=True, LIVEKIT_URL="", ASR_BACKEND="", MEETING_BOT_VENDOR="")


@override_settings(**DEMO)
class DemoMeetingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="D", slug="demo-meet", settings={"flags": {"voice_video": True, "meeting_bot": True}})
        self.users = {}
        for name, role in (("owner", "owner"), ("ana", "member"), ("ben", "member")):
            u = User.objects.create(email=f"{name}@d.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            self.users[name] = u
        team = Team.objects.create(org=self.org, name="T")
        for n in ("ana", "ben"):
            TeamMembership.objects.create(team=team, user=self.users[n])
        self.room = ensure_team_room(team)
        self.meeting = Meeting.objects.create(org=self.org, room=self.room, title="Standup", created_by=self.users["owner"])
        self.base = f"/api/v2/orgs/{self.org.id}/meetings/{self.meeting.id}"

    def _as(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return c

    def test_demo_call_records_and_transcribes_by_speaker(self):
        res = self._as("owner").post(f"{self.base}/join").json()
        self.assertTrue(res["demo"])
        self.assertIn("owner", res["participants"])
        self.assertNotIn("token", res, "no call server, no token")
        c = self._as("owner")
        self.assertEqual(c.post(f"{self.base}/recording", {"action": "start"}, format="json").json(), {"recording": True})
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(c.post(f"{self.base}/recording", {"action": "stop"}, format="json").json(), {"recording": False})
        recs = Recording.objects.filter(meeting=self.meeting)
        self.assertGreaterEqual(recs.count(), 2, "one recording per speaker")
        self.assertTrue(all(r.storage_key.startswith("demo/") for r in recs))
        self.assertTrue(all(r.transcript_status == "done" for r in recs))
        rows = c.get(f"{self.base}/transcript").json()
        lines = rows.get("segments", rows) if isinstance(rows, dict) else rows
        self.assertTrue(any(line.get("speaker") == "owner" for line in lines))

    @override_settings(DEMO_MODE=False)
    def test_demo_audio_is_refused_outside_the_demo(self):
        from meetings import pipeline

        rec = Recording.objects.create(org=self.org, meeting=self.meeting, storage_key="demo/x/speaker-0.ogg", transcript_status="queued")
        self.assertEqual(pipeline.transcribe_recording({"recording_id": str(rec.id)})["reason"], "audio_missing")
        self.assertEqual(self._as("owner").post(f"{self.base}/join").status_code, 501)

    def test_demo_assistant_walks_through_its_steps(self):
        url = f"/api/v2/orgs/{self.org.id}/rooms/{self.room.id}/meetings/{self.meeting.id}/bot"
        res = self._as("owner").post(url, {"platform": "zoom", "meeting_url": "https://example.zoom.us/j/123456789", "host_consent": True}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        session = MeetingBotSession.objects.get(pk=res.json()["id"])
        MeetingBotSession.objects.filter(pk=session.pk).update(created_at=timezone.now() - timedelta(seconds=10))
        statuses = self._as("owner").get(f"{self.base}/bot-sessions").json()
        self.assertEqual(statuses[0]["status"], "waiting_admission")
        MeetingBotSession.objects.filter(pk=session.pk).update(created_at=timezone.now() - timedelta(minutes=2))
        with self.captureOnCommitCallbacks(execute=True):
            statuses = self._as("owner").get(f"{self.base}/bot-sessions").json()
        self.assertEqual(statuses[0]["status"], "done")
        session.refresh_from_db()
        self.assertEqual(session.recording.transcript_status, "done")

    def test_action_item_becomes_one_task_for_the_chosen_person(self):
        MeetingSummary.objects.create(meeting=self.meeting, text="s", action_items=[{"id": "a1", "text": "Order a phone"}])
        url = f"{self.base}/action-items/a1/to-task"
        c = self._as("owner")
        self.assertEqual(c.post(url, {}, format="json").status_code, 400, "needs a confirm")
        bad = c.post(url, {"confirm": True, "assignee_id": str(User.objects.create(email="x@x.test", username="x").id)}, format="json")
        self.assertEqual(bad.status_code, 400, "not a member")
        res = c.post(url, {"confirm": True, "assignee_id": str(self.users["ana"].id), "due_on": "2026-11-02"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        task = Task.objects.get(pk=res.json()["id"])
        self.assertEqual((str(task.due_on), list(task.assignments.values_list("user__username", flat=True))), ("2026-11-02", ["ana"]))
        self.assertEqual(MeetingSummary.objects.get(meeting=self.meeting).action_items[0]["task_id"], str(task.id))
        again = c.post(url, {"confirm": True}, format="json")
        self.assertEqual((again.status_code, again.json()["id"]), (409, str(task.id)))
        self.assertEqual(Task.objects.filter(org=self.org).count(), 1)
