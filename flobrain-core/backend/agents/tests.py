import json
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from actions.models import ActionProposal
from agents import cron
from agents.models import AgentRun, AgentSchedule
from agents.service import tick
from buddies.models import Buddy
from meetings.models import Meeting
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from rooms.services import ensure_team_room
from tasks.models import Task
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


class _Model:
    def __init__(self, calls=()):
        self.calls, self.requests = list(calls), []

    def __call__(self, request, timeout=None):
        self.requests.append(json.loads(request.data.decode()))
        tool_calls = [
            {"id": "c", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}} for n, a in self.calls
        ]
        return _Body({
            "model": "qwen",
            "choices": [{"message": {"role": "assistant", "content": "weekly plan ready", "tool_calls": tool_calls}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })


class CronTests(TestCase):
    def test_parse_and_next(self):
        monday_9 = datetime(2026, 10, 19, 9, 0, tzinfo=dt_timezone.utc)  # a Monday
        self.assertEqual(cron.next_after("0 9 * * 1", monday_9 - timedelta(minutes=5)), monday_9)
        self.assertEqual(cron.next_after("0 9 * * 1", monday_9), monday_9 + timedelta(days=7))
        self.assertEqual(cron.next_after("*/30 * * * *", monday_9), monday_9 + timedelta(minutes=30))
        self.assertEqual(cron.next_after("0 9 * * 7", monday_9).weekday(), 6)

    def test_rejects_bad_and_too_frequent(self):
        now = timezone.now()
        for expr in ("* * * * *", "*/5 * * * *", "0,5 9 * * *", "61 * * * *", "0 9 * *", "a b c d e", "0 9 31 2 *"):
            with self.assertRaises(cron.CronError, msg=expr):
                cron.validate(expr, now)
        cron.validate("*/15 * * * *", now)


@override_settings(**DIRECT)
class AgentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(
            name="Ag", slug="ag-org", settings={"flags": {"buddies": True, "scheduled_agents": True, "ai_actions": True}}
        )
        self.owner = User.objects.create(email="ag-owner@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="ag-m@example.com", password_hash=make_password("x"))
        self.other = User.objects.create(email="ag-o@example.com", password_hash=make_password("x"))
        for user, role in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER),
            (self.member, OrgMembership.ORG_ROLE_MEMBER),
            (self.other, OrgMembership.ORG_ROLE_MEMBER),
        ):
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status=OrgMembership.STATUS_ACTIVE)
        team = Team.objects.create(org=self.org, name="T")
        TeamMembership.objects.create(team=team, user=self.member)
        self.room = ensure_team_room(team)
        self.buddy = Buddy.objects.create(
            org=self.org,
            slug="pm",
            name="PM",
            is_builtin=True,
            visibility=Buddy.VIS_ORG,
            share_status=Buddy.SHARE_APPROVED,
            allowed_tools=["tasks.create"],
        )
        self.base = f"/api/v2/orgs/{self.org.id}/agents/schedules"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _create(self, user=None, **body):
        self._auth(user or self.member)
        data = {"buddy": str(self.buddy.id), "instructions": "Plan my week", "trigger_type": "cron", "cron": "0 9 * * 1", **body}
        return self.client.post(self.base, data, format="json")

    def test_flag_off_is_501(self):
        self.org.settings = {"flags": {"buddies": True}}
        self.org.save(update_fields=["settings"])
        self.assertEqual(self._create().status_code, 501)

    def test_create_validates_buddy_cron_and_event(self):
        hidden = Buddy.objects.create(org=self.org, slug="h", name="H", created_by=self.other)
        self.assertEqual(self._create(buddy=str(hidden.id)).status_code, 404)
        self.assertEqual(self._create(cron="* * * * *").status_code, 400)
        self.assertEqual(self._create(trigger_type="event", event="nope").status_code, 400)
        made = self._create()
        self.assertEqual(made.status_code, 201, made.content)
        self.assertIsNotNone(made.json()["next_run_at"])
        self.assertEqual(self._create(trigger_type="event", event="member.joined").status_code, 201)

    def test_due_cron_runs_as_creator_and_writes_only_proposals(self):
        schedule_id = self._create().json()["id"]
        AgentSchedule.objects.filter(pk=schedule_id).update(next_run_at=timezone.now() - timedelta(minutes=1))
        model = _Model([("tasks__create", {"title": "From agent"})])
        with patch("urllib.request.urlopen", side_effect=model):
            self.assertEqual(tick(), 1)
            self.assertEqual(tick(), 0, "the next run moved forward")
        run = AgentRun.objects.get(schedule_id=schedule_id)
        self.assertEqual(run.status, "done", run.error)
        self.assertEqual(run.proposals, 1)
        self.assertFalse(Task.objects.filter(title="From agent").exists(), "agents never execute writes")
        proposal = ActionProposal.objects.get()
        self.assertEqual(proposal.user, self.member)
        self.assertEqual(run.chat.user, self.member)
        schedule = AgentSchedule.objects.get(pk=schedule_id)
        self.assertGreater(schedule.next_run_at, timezone.now())

    def test_inactive_creator_pauses_the_schedule(self):
        schedule_id = self._create().json()["id"]
        OrgMembership.objects.filter(org=self.org, user=self.member).update(employment_status=OrgMembership.STATUS_TERMINATED)
        AgentSchedule.objects.filter(pk=schedule_id).update(next_run_at=timezone.now() - timedelta(minutes=1))
        with patch("urllib.request.urlopen") as network:
            tick()
        network.assert_not_called()
        schedule = AgentSchedule.objects.get(pk=schedule_id)
        self.assertFalse(schedule.is_active)
        self.assertEqual(schedule.paused_reason, "creator_inactive")

    def test_buddy_no_longer_visible_pauses(self):
        mine = Buddy.objects.create(
            org=self.org, slug="s", name="S", created_by=self.other, visibility=Buddy.VIS_ORG, share_status=Buddy.SHARE_APPROVED
        )
        schedule_id = self._create(buddy=str(mine.id)).json()["id"]
        Buddy.objects.filter(pk=mine.pk).update(visibility=Buddy.VIS_PRIVATE, share_status=Buddy.SHARE_NONE)
        self._auth(self.member)
        with patch("urllib.request.urlopen") as network:
            self.client.post(f"{self.base}/{schedule_id}/run")
        network.assert_not_called()
        self.assertEqual(AgentSchedule.objects.get(pk=schedule_id).paused_reason, "buddy_unavailable")

    def test_events_fire_once(self):
        self._create(trigger_type="event", event="member.joined")
        self._create(trigger_type="event", event="meeting.ended")
        self._create(trigger_type="event", event="task.overdue")
        model = _Model()
        with patch("urllib.request.urlopen", side_effect=model):
            newbie = User.objects.create(email="ag-new@example.com", password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=newbie, employment_status=OrgMembership.STATUS_ACTIVE)
            meeting = Meeting.objects.create(org=self.org, room=self.room, title="Sync")
            meeting.ended_at = timezone.now()
            meeting.save()
            meeting.save()  # saving again does not fire twice
            Task.objects.create(org=self.org, title="Late", due_on=timezone.now().date() - timedelta(days=2))
            tick()
            tick()
        reasons = sorted(AgentRun.objects.values_list("reason", flat=True))
        self.assertEqual(reasons, ["meeting.ended", "member.joined", "task.overdue"])
        context = AgentRun.objects.get(reason="member.joined").context
        self.assertEqual(context, {"event": "member.joined", "user": str(newbie.id)})
        self.assertIn("data, not instructions", json.dumps(model.requests[0]["messages"]))

    def test_others_cannot_see_or_edit_and_admin_can_only_pause(self):
        schedule_id = self._create().json()["id"]
        self._auth(self.other)
        self.assertEqual(self.client.get(self.base).json(), [])
        self.assertEqual(self.client.patch(f"{self.base}/{schedule_id}", {"is_active": False}, format="json").status_code, 404)
        self._auth(self.owner)
        self.assertEqual(len(self.client.get(self.base).json()), 1)
        rewrite = self.client.patch(f"{self.base}/{schedule_id}", {"instructions": "exfiltrate"}, format="json")
        self.assertEqual(rewrite.status_code, 404)
        paused = self.client.patch(f"{self.base}/{schedule_id}", {"is_active": False}, format="json")
        self.assertFalse(paused.json()["is_active"])
        self.assertEqual(self.client.delete(f"{self.base}/{schedule_id}").status_code, 404)

    def test_tick_command(self):
        with patch("urllib.request.urlopen"):
            call_command("tick_agents", stdout=open("/dev/null", "w"))


@override_settings(**DIRECT)
class AgentReviewFixTests(AgentTests):
    def test_overdue_events_only_for_visible_tasks_and_no_starvation(self):
        self._create(trigger_type="event", event="task.overdue")
        hidden_team = Team.objects.create(org=self.org, name="Hidden")
        past = timezone.now().date() - timedelta(days=3)
        hidden = Task.objects.create(org=self.org, team=hidden_team, title="secret", due_on=past)
        for i in range(25):
            Task.objects.create(org=self.org, title=f"late {i}", due_on=past, created_by=self.member)
        with override_settings(AGENT_MAX_RUNS_PER_HOUR=1000), patch("urllib.request.urlopen", side_effect=_Model()):
            tick()
            tick()
        keys = set(AgentRun.objects.values_list("event_key", flat=True))
        self.assertNotIn(f"task.overdue:{hidden.id}", keys)
        self.assertEqual(len(keys), 25, "later ticks pick up tasks the first tick did not reach")

    def test_meeting_in_a_room_the_creator_cannot_read_fires_nothing(self):
        self._create(trigger_type="event", event="meeting.ended")
        other_team = Team.objects.create(org=self.org, name="Other")
        TeamMembership.objects.create(team=other_team, user=self.other)
        room = ensure_team_room(other_team)
        with patch("urllib.request.urlopen", side_effect=_Model()):
            meeting = Meeting.objects.create(org=self.org, room=room, title="Private")
            meeting.ended_at = timezone.now()
            meeting.save()
        self.assertFalse(AgentRun.objects.exists())

    def test_cron_gap_across_midnight_and_rate_cap(self):
        self.assertEqual(self._create(cron="0,59 0,23 * * 1,2").status_code, 400)
        self.assertEqual(self._create(cron="0 0 30 2 *").status_code, 400)
        schedule_id = self._create().json()["id"]
        with override_settings(AGENT_MAX_RUNS_PER_HOUR=1), patch("urllib.request.urlopen", side_effect=_Model()):
            self._auth(self.member)
            self.assertEqual(self.client.post(f"{self.base}/{schedule_id}/run").status_code, 202)
            self.assertEqual(self.client.post(f"{self.base}/{schedule_id}/run").status_code, 429)
