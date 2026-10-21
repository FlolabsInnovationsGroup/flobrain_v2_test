import json
import time
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from actions import service as actions_service
from actions.models import ActionProposal
from automations import engine, schedule, triggers
from automations.models import AutomationSettings, BriefOptOut, RunApproval, Workflow, WorkflowRun
from automations.schema import MAX_STEPS, WorkflowError, clean_steps, clean_trigger, clean_workflow
from automations.views import sign
from notifications.models import Notification
from organizations.models import AuditEvent, OrgMembership, Organization, Team, TeamMembership
from rooms.models import Room, RoomMessage
from rooms.services import ensure_team_room, post_message
from tasks.models import Task, TaskAssignment
from tasks.services import create_task, set_blocked
from users.jwt_utils import make_access_token
from users.models import User

KEY = "ab" * 32


def _ai(text="Two tasks are blocked."):
    return patch("automations.ai._complete", return_value=text)


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="Acme", slug="acme-auto", settings={"flags": {"automations": True, "ai_actions": True}})
        self.users = {}
        for name, role in (("owner", "owner"), ("admin", "admin"), ("lead", "member"), ("member", "member"), ("outsider", "member")):
            user = User.objects.create(email=f"{name}@acme.test", username=name.title(), password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status="active")
            self.users[name] = user
        self.team = Team.objects.create(org=self.org, name="Launch")
        TeamMembership.objects.create(team=self.team, user=self.users["lead"], team_role=TeamMembership.ROLE_LEAD)
        TeamMembership.objects.create(team=self.team, user=self.users["member"])
        self.room = ensure_team_room(self.team)
        self.private = Room.objects.create(org=self.org, name="Secret", kind=Room.KIND_GROUP)
        self.base = f"/api/v2/orgs/{self.org.id}/automations"

    def _as(self, name):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return client

    def wf(self, trigger, steps, enabled=True, owner="admin", name="Test"):
        trig = clean_trigger(trigger)
        return Workflow.objects.create(
            org=self.org, name=name, trigger=trig, trigger_type=trig["type"], steps=clean_steps(steps, trig["type"]),
            enabled=enabled, created_by=self.users[owner], run_as=self.users[owner],
        )

    def run_now(self, workflow, payload=None):
        with self.captureOnCommitCallbacks(execute=True):
            run = engine.start_run(workflow, "manual", payload or {})
        run.refresh_from_db()
        return run

    def approve(self, run, name="admin", decision="approve"):
        approval = RunApproval.objects.get(run=run, state=RunApproval.PENDING)
        with self.captureOnCommitCallbacks(execute=True):
            if decision == "approve":
                actions_service.approve(approval.proposal_id, self.users[name], self.org)
            else:
                actions_service.reject(approval.proposal_id, self.users[name], self.org)
        run.refresh_from_db()
        return run


class ValidationTests(Base):
    def test_trigger_shapes(self):
        self.assertEqual(clean_trigger({"type": "schedule", "every": "day", "at": "08:30"})["at"], "08:30")
        for bad in (
            {"type": "cron", "expr": "* * * * *"},
            {"type": "schedule", "every": "day", "at": "25:00"},
            {"type": "schedule", "every": "week", "at": "09:00"},
            {"type": "schedule", "every": "day", "at": "09:00", "timezone": "Mars/Base"},
            {"type": "schedule", "every": "day", "at": "09:00", "cron": "* * * * *"},
            {"type": "room_message", "room": str(self.room.id)},
        ):
            with self.assertRaises(WorkflowError, msg=bad):
                clean_trigger(bad)

    def test_step_shapes(self):
        ok = clean_steps([{"type": "ai_prompt", "prompt": "Hi"}, {"type": "notify", "roles": ["owner"], "text": "{{steps.1.output}}"}], "manual")
        self.assertEqual(len(ok), 2)
        for bad in (
            [{"type": "shell", "cmd": "rm -rf /"}],
            [{"type": "ai_prompt", "prompt": "x", "extra": 1}],
            [{"type": "notify", "text": "nobody"}],
            [{"type": "notify", "roles": ["owner"], "text": "{{steps.2.output}}"}, {"type": "ai_prompt", "prompt": "x"}],
            [{"type": "call_webhook", "url": "http://hooks.example.com/x"}],
            [{"type": "post_to_room", "room": "trigger", "text": "x"}],
            [{"type": "ai_prompt", "prompt": "x"}] * (MAX_STEPS + 1),
            [],
        ):
            with self.assertRaises(WorkflowError, msg=bad):
                clean_steps(bad, "schedule")
        self.assertEqual(clean_steps([{"type": "post_to_room", "room": "trigger", "text": "x"}], "room_message")[0]["room"], "trigger")

    def test_references_use_the_editors_access(self):
        data = {"trigger": {"type": "manual"}, "steps": [{"type": "post_to_room", "room": str(self.private.id), "text": "x"}]}
        with self.assertRaises(WorkflowError):
            clean_workflow(self.org, self.users["admin"], data)
        data["steps"][0]["room"] = str(self.room.id)
        clean_workflow(self.org, self.users["admin"], data)
        with self.assertRaises(WorkflowError):
            clean_workflow(self.org, self.users["outsider"], data)
        hook = {"trigger": {"type": "manual"}, "steps": [{"type": "call_webhook", "url": "https://hooks.example.com/x"}]}
        with self.assertRaises(WorkflowError, msg="host not allowed"):
            clean_workflow(self.org, self.users["admin"], hook)
        settings_row = AutomationSettings.objects.create(org=self.org, webhook_hosts=["hooks.example.com"])
        clean_workflow(self.org, self.users["admin"], hook, settings_row)

    def test_schedule_math(self):
        now = datetime(2026, 10, 21, 10, 0, tzinfo=dt_timezone.utc)  # a Wednesday, 13:00 in Cairo
        weekly = schedule.next_run({"every": "week", "weekday": 0, "at": "09:00", "timezone": "Africa/Cairo"}, self.org, now)
        self.assertEqual(weekly.astimezone(dt_timezone.utc).weekday(), 0)
        self.assertEqual(weekly.date().isoformat(), "2026-10-26")
        daily = schedule.next_run({"every": "day", "at": "09:00"}, self.org, now)
        self.assertEqual(daily, datetime(2026, 10, 22, 9, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(schedule.next_run({"every": "hours", "hours": 6}, self.org, now), now + timedelta(hours=6))
        self.assertEqual(schedule.next_run({"every": "month", "day": 1, "at": "09:00"}, self.org, now).date().isoformat(), "2026-11-01")


class ApiTests(Base):
    def body(self, **extra):
        return {
            "name": "Blocked digest",
            "trigger": {"type": "schedule", "every": "week", "weekday": 0, "at": "09:00"},
            "steps": [
                {"type": "ai_prompt", "prompt": "Summarise", "context": "blocked_tasks"},
                {"type": "post_to_room", "room": str(self.room.id), "text": "{{steps.1.output}}"},
            ],
            **extra,
        }

    def test_permissions_and_audit(self):
        self.assertEqual(self._as("member").post(self.base, self.body(), format="json").status_code, 403)
        made = self._as("admin").post(self.base, self.body(enabled=True), format="json")
        self.assertEqual(made.status_code, 201, made.content)
        wid = made.json()["id"]
        self.assertIsNotNone(made.json()["next_run_at"])
        self.assertEqual(made.json()["run_as"]["id"], str(self.users["admin"].id))
        listed = self._as("member").get(self.base)
        self.assertEqual(listed.status_code, 200)
        self.assertFalse(listed.json()[0]["can_manage"])
        self.assertEqual(self._as("member").patch(f"{self.base}/{wid}", {"name": "x"}, format="json").status_code, 403)
        self.assertEqual(self._as("member").post(f"{self.base}/{wid}/enable", {"enabled": False}, format="json").status_code, 403)
        self.assertEqual(self._as("member").delete(f"{self.base}/{wid}").status_code, 403)
        self.assertEqual(self._as("owner").patch(f"{self.base}/{wid}", {"steps": self.body()["steps"][:1]}, format="json").status_code, 200)
        self.assertEqual(Workflow.objects.get(pk=wid).run_as, self.users["owner"], "the last editor runs it")
        self.assertEqual(self._as("admin").post(f"{self.base}/{wid}/enable", {"enabled": False}, format="json").json()["enabled"], False)
        self.assertEqual(self._as("member").post(f"{self.base}/{wid}/run").status_code, 403, "members can't run a disabled workflow")
        bad = self._as("admin").post(self.base, {**self.body(), "steps": [{"type": "nope"}]}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(bad.json()["problems"])
        self.assertEqual(self._as("admin").delete(f"{self.base}/{wid}").status_code, 204)
        actions = set(AuditEvent.objects.filter(org=self.org, action__startswith="automation.").values_list("action", flat=True))
        self.assertTrue({"automation.create", "automation.update", "automation.disable", "automation.delete"} <= actions)

    def test_flag_off_and_other_orgs(self):
        self.org.settings = {"flags": {}}
        self.org.save()
        for path in ("", "/templates", "/runs", "/settings", "/me"):
            self.assertEqual(self._as("admin").get(self.base + path).status_code, 501, path)
        self.assertEqual(self._as("admin").post(self.base, self.body(), format="json").status_code, 501)
        other = Organization.objects.create(name="Other", slug="other-auto", settings={"flags": {"automations": True}})
        self.assertEqual(self._as("admin").get(f"/api/v2/orgs/{other.id}/automations").status_code, 403)

    def test_run_now_and_output_visibility(self):
        workflow = self.wf({"type": "manual"}, [{"type": "ai_prompt", "prompt": "Summarise"}])
        with _ai("Secret summary"), self.captureOnCommitCallbacks(execute=True):
            made = self._as("member").post(f"{self.base}/{workflow.id}/run")
        self.assertEqual(made.status_code, 201, made.content)
        run = WorkflowRun.objects.get(pk=made.json()["id"])
        self.assertEqual(run.status, WorkflowRun.DONE)
        self.assertEqual(run.triggered_by, self.users["member"])
        member_view = self._as("member").get(f"{self.base}/runs/{run.id}").json()
        self.assertIsNone(member_view["step_log"][0]["output"], "outputs use the run_as person's access")
        self.assertEqual(self._as("admin").get(f"{self.base}/runs/{run.id}").json()["step_log"][0]["output"], "Secret summary")
        self.assertEqual(len(self._as("member").get(f"{self.base}/{workflow.id}/runs").json()), 1)

    def test_settings_and_opt_out(self):
        self.assertEqual(self._as("member").put(f"{self.base}/settings", {"webhook_hosts": ["a.example.com"]}, format="json").status_code, 403)
        bad = self._as("admin").put(f"{self.base}/settings", {"webhook_hosts": ["a.example.com"], "trusted_hosts": ["b.example.com"]}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self._as("admin").put(f"{self.base}/settings", {"webhook_hosts": ["http://x/"]}, format="json").status_code, 400)
        ok = self._as("admin").put(f"{self.base}/settings", {"webhook_hosts": ["A.example.com"], "trusted_hosts": ["a.example.com"]}, format="json")
        self.assertEqual(ok.json(), {"webhook_hosts": ["a.example.com"], "trusted_hosts": ["a.example.com"]})
        mine = self._as("member").put(f"{self.base}/me", {"daily_brief": False}, format="json")
        self.assertEqual(mine.json()["daily_brief"], False)
        self.assertTrue(BriefOptOut.objects.filter(user=self.users["member"], kind="daily_brief").exists())
        self.assertEqual(self._as("member").put(f"{self.base}/me", {"daily_brief": True}, format="json").json()["daily_brief"], True)


class TriggerTests(Base):
    def notify_lead(self, trigger):
        return self.wf(trigger, [{"type": "notify", "roles": ["team_leads"], "text": "{{trigger.title}} is blocked: {{trigger.reason}}"}])

    def test_task_blocked_fires_once_and_notifies_the_lead(self):
        self.notify_lead({"type": "task_blocked"})
        task, _ = create_task(self.users["member"], self.org, "Fix login", team_id=self.team.id)
        with self.captureOnCommitCallbacks(execute=True):
            set_blocked(task, self.users["member"], True, "No device")
            set_blocked(task, self.users["member"], True, "Still no device")
        run = WorkflowRun.objects.get(reason="task_blocked")
        self.assertEqual(run.status, WorkflowRun.DONE, run.error)
        note = Notification.objects.get(user=self.users["lead"], kind="automation.notice")
        self.assertEqual(note.payload["text"], "Fix login is blocked: No device")

    def test_task_created_with_team_filter(self):
        self.wf({"type": "task_created", "team": str(self.team.id)}, [{"type": "notify", "roles": ["owner"], "text": "New: {{trigger.title}}"}])
        with self.captureOnCommitCallbacks(execute=True):
            create_task(self.users["admin"], self.org, "No team task")
            create_task(self.users["member"], self.org, "Team task", team_id=self.team.id)
        self.assertEqual(WorkflowRun.objects.filter(reason="task_created").count(), 1)
        self.assertEqual(Notification.objects.get(user=self.users["admin"]).payload["text"], "New: Team task")

    def test_room_message_keyword_whole_word(self):
        self.wf({"type": "room_message", "room": str(self.room.id), "keyword": "deploy"}, [{"type": "post_to_room", "room": "trigger", "text": "Saw deploy: {{trigger.text}}"}])
        with self.captureOnCommitCallbacks(execute=True):
            post_message(self.room, self.users["member"], "redeployment soon")
            post_message(self.room, self.users["member"], "Can we DEPLOY today?")
        run = WorkflowRun.objects.get(reason="room_message")
        self.assertEqual(run.status, WorkflowRun.DONE, run.error)
        self.assertEqual(WorkflowRun.objects.count(), 1, "its own post never fires it again")
        self.assertTrue(RoomMessage.objects.filter(room=self.room, body="Saw deploy: Can we DEPLOY today?").exists())

    def test_meeting_ended(self):
        from meetings.models import Meeting

        self.wf({"type": "meeting_ended"}, [{"type": "post_to_room", "room": "trigger", "text": "Follow up on {{trigger.title}}"}])
        meeting = Meeting.objects.create(org=self.org, room=self.room, title="Sync")
        with self.captureOnCommitCallbacks(execute=True):
            meeting.ended_at = timezone.now()
            meeting.save()
            meeting.save()
        self.assertEqual(WorkflowRun.objects.filter(reason="meeting_ended", status=WorkflowRun.DONE).count(), 1)

    def test_no_fire_when_disabled_flag_off_or_hidden(self):
        workflow = self.notify_lead({"type": "task_blocked"})
        hidden = self.wf({"type": "room_message", "room": str(self.room.id), "keyword": "deploy"}, [{"type": "notify", "roles": ["owner"], "text": "x"}], owner="lead")
        task, _ = create_task(self.users["member"], self.org, "A", team_id=self.team.id)
        Workflow.objects.filter(pk=workflow.pk).update(enabled=False)
        set_blocked(task, self.users["member"], True, "x")
        self.assertFalse(WorkflowRun.objects.exists())
        TeamMembership.objects.filter(user=self.users["lead"]).delete()  # the lead leaves the team room
        ensure_team_room(self.team)
        post_message(self.room, self.users["member"], "deploy now")
        self.assertFalse(WorkflowRun.objects.filter(workflow=hidden).exists(), "run_as must be able to read the room")
        self.org.settings = {"flags": {}}
        self.org.save()
        Workflow.objects.filter(pk=workflow.pk).update(enabled=True)
        set_blocked(task, self.users["member"], False)
        set_blocked(task, self.users["member"], True, "y")
        self.assertFalse(WorkflowRun.objects.exists())

    def test_schedule_tick_fires_once(self):
        workflow = self.wf({"type": "schedule", "every": "day", "at": "09:00"}, [{"type": "notify", "roles": ["owner"], "text": "Morning"}])
        Workflow.objects.filter(pk=workflow.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))
        call_command("tick_automations", stdout=open("/dev/null", "w"))
        call_command("tick_automations", stdout=open("/dev/null", "w"))
        self.assertEqual(WorkflowRun.objects.filter(reason="schedule").count(), 1)
        self.assertEqual(WorkflowRun.objects.get().status, WorkflowRun.DONE)
        workflow.refresh_from_db()
        self.assertGreater(workflow.next_run_at, timezone.now())


class RunnerTests(Base):
    def test_ai_then_post_with_templating(self):
        workflow = self.wf({"type": "manual"}, [
            {"type": "ai_prompt", "prompt": "Summarise", "context": "blocked_tasks", "room": str(self.room.id)},
            {"type": "post_to_room", "room": str(self.room.id), "text": "Digest\n{{steps.1.output}} {{trigger.nope}}{{ __import__ }}"},
            {"type": "create_task", "title": "Review {{workflow.name}}", "room": str(self.room.id), "due_in_days": 2},
        ])
        with _ai("All good") as ai:
            run = self.run_now(workflow)
        self.assertEqual(run.status, WorkflowRun.DONE, run.error)
        self.assertIn("<data>", ai.call_args[0][2][1]["content"])
        self.assertTrue(RoomMessage.objects.filter(room=self.room, body="Digest\nAll good {{ __import__ }}").exists())
        task = Task.objects.get(title="Review Test")
        self.assertEqual(task.due_on, timezone.localdate() + timedelta(days=2))
        self.assertEqual([e["status"] for e in run.step_log], ["done", "done", "done"])
        self.assertIsNone(engine.process_run(run.id), "a finished run is never processed again")

    def test_failure_stops_the_run(self):
        workflow = self.wf({"type": "manual"}, [{"type": "notify", "roles": ["owner"], "text": "first"}, {"type": "post_to_room", "room": str(self.room.id), "text": "x"}, {"type": "notify", "roles": ["owner"], "text": "never"}])
        TeamMembership.objects.filter(team=self.team).delete()
        ensure_team_room(self.team)
        OrgMembership.objects.filter(user=self.users["admin"]).update(org_role="member")  # loses room access
        run = self.run_now(workflow)
        self.assertEqual(run.status, WorkflowRun.FAILED)
        self.assertEqual([e["status"] for e in run.step_log], ["done", "failed"])
        self.assertFalse(Notification.objects.filter(payload__text="never").exists())

    def test_ai_policy_and_budget_respected(self):
        workflow = self.wf({"type": "manual"}, [{"type": "ai_prompt", "prompt": "x"}])
        with patch("brain.llm.direct.is_configured", return_value=True), patch("brain.llm.policy.check_ai", return_value="private_only"):
            run = self.run_now(workflow)
        self.assertEqual(run.status, WorkflowRun.FAILED)
        self.assertIn("private_only", run.error)
        with patch("brain.llm.direct.is_configured", return_value=True), patch("telemetry.pricing.platform_budget_blocks", return_value="budget_exceeded"):
            run = self.run_now(workflow)
        self.assertIn("budget_exceeded", run.error)

    def test_inactive_owner_fails(self):
        workflow = self.wf({"type": "manual"}, [{"type": "notify", "roles": ["owner"], "text": "x"}])
        OrgMembership.objects.filter(user=self.users["admin"]).update(employment_status="inactive")
        self.assertEqual(self.run_now(workflow).status, WorkflowRun.FAILED)

    def test_daily_brief_and_nudges_respect_opt_out(self):
        yesterday = timezone.localdate() - timedelta(days=2)
        for who in ("member", "lead"):
            task = Task.objects.create(org=self.org, title=f"Late {who}", team=self.team, due_on=yesterday, created_by=self.users["admin"])
            TaskAssignment.objects.create(task=task, user=self.users[who])
        Task.objects.create(org=self.org, title="Today", team=self.team, due_on=timezone.localdate(), created_by=self.users["member"])
        BriefOptOut.objects.create(org=self.org, user=self.users["lead"], kind="nudges")
        BriefOptOut.objects.create(org=self.org, user=self.users["lead"], kind="daily_brief")
        workflow = self.wf({"type": "manual"}, [{"type": "daily_brief"}, {"type": "nudge_overdue", "min_days_overdue": 1}])
        run = self.run_now(workflow)
        self.assertEqual(run.status, WorkflowRun.DONE, run.error)
        brief = Notification.objects.get(user=self.users["member"], kind="automation.daily_brief")
        self.assertIn("1 task(s) due today", brief.payload["text"])
        self.assertTrue(Notification.objects.filter(user=self.users["member"], kind="automation.nudge").exists())
        self.assertFalse(Notification.objects.filter(user=self.users["lead"], kind__in=["automation.nudge", "automation.daily_brief"]).exists())

    def test_budget_check_stops_quietly(self):
        workflow = self.wf({"type": "manual"}, [{"type": "check_budget", "threshold_pct": 80}, {"type": "notify", "roles": ["admins"], "text": "{{steps.1.output}}"}])
        run = self.run_now(workflow)
        self.assertEqual(run.status, WorkflowRun.DONE)
        self.assertTrue(run.step_log[0]["detail"]["stopped"])
        self.assertFalse(Notification.objects.exists())


class ApprovalGatingTests(Base):
    def test_email_never_sent_without_approval(self):
        workflow = self.wf({"type": "manual"}, [
            {"type": "send_email", "to": ["boss@example.com"], "subject": "Report", "body": "Hello"},
            {"type": "notify", "roles": ["owner"], "text": "sent"},
        ])
        run = self.run_now(workflow)
        self.assertEqual(run.status, WorkflowRun.WAITING)
        self.assertEqual(len(mail.outbox), 0)
        proposal = ActionProposal.objects.get(tool_key="automations.send_email")
        self.assertEqual(proposal.user, self.users["admin"])
        with self.assertRaises(actions_service.ActionDenied):
            actions_service.approve(proposal.id, self.users["member"], self.org)  # only run_as decides
        run = self.approve(run)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["boss@example.com"])
        self.assertEqual(run.status, WorkflowRun.DONE, run.error)
        self.assertEqual([e["status"] for e in run.step_log], ["done", "done"])

    def test_declined_email_cancels(self):
        workflow = self.wf({"type": "manual"}, [{"type": "send_email", "to": ["boss@example.com"], "subject": "Report", "body": "Hello"}])
        run = self.approve(self.run_now(workflow), decision="reject")
        self.assertEqual(run.status, WorkflowRun.CANCELLED)
        self.assertEqual(len(mail.outbox), 0)

    def test_webhook_needs_approval_unless_trusted(self):
        AutomationSettings.objects.create(org=self.org, webhook_hosts=["hooks.example.com"])
        workflow = self.wf({"type": "manual"}, [{"type": "call_webhook", "url": "https://hooks.example.com/in", "body": "hi"}])
        with patch("platform_api.net.fetch", return_value=(200, b"ok")) as fetch:
            run = self.run_now(workflow)
            self.assertEqual(run.status, WorkflowRun.WAITING)
            fetch.assert_not_called()
            run = self.approve(run)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(json.loads(fetch.call_args[0][2])["text"], "hi")
        self.assertEqual(run.status, WorkflowRun.DONE, run.error)
        AutomationSettings.objects.filter(org=self.org).update(trusted_hosts=["hooks.example.com"])
        with patch("platform_api.net.fetch", return_value=(200, b"ok")) as fetch:
            run = self.run_now(workflow)
        self.assertEqual(run.status, WorkflowRun.DONE)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(ActionProposal.objects.count(), 1, "trusted host: no new approval")

    def test_removed_host_fails_at_run_time(self):
        AutomationSettings.objects.create(org=self.org, webhook_hosts=["hooks.example.com"])
        workflow = self.wf({"type": "manual"}, [{"type": "call_webhook", "url": "https://hooks.example.com/in"}])
        AutomationSettings.objects.filter(org=self.org).update(webhook_hosts=[])
        with patch("platform_api.net.fetch") as fetch:
            run = self.run_now(workflow)
        self.assertEqual(run.status, WorkflowRun.FAILED)
        fetch.assert_not_called()

    def test_ssrf_guard_on_private_addresses(self):
        from actions.service import ActionDenied
        from automations import tools

        with patch("platform_api.net.resolve", return_value=["10.0.0.7"]), self.assertRaises(ActionDenied):
            tools.call(self.org, "r", "w", "https://hooks.example.com/in", "POST", "x")
        with self.assertRaises(ActionDenied):
            tools.call(self.org, "r", "w", "https://127.0.0.1/in", "POST", "x")

    def test_wait_for_approval_and_expiry(self):
        workflow = self.wf({"type": "manual"}, [{"type": "wait_for_approval", "message": "OK to post?"}, {"type": "notify", "roles": ["owner"], "text": "went on"}])
        run = self.approve(self.run_now(workflow))
        self.assertEqual(run.status, WorkflowRun.DONE, run.error)
        self.assertTrue(Notification.objects.filter(payload__text="went on").exists())
        later = self.run_now(workflow)
        ActionProposal.objects.filter(status="proposed").update(expires_at=timezone.now() - timedelta(minutes=1))
        call_command("tick_automations", stdout=open("/dev/null", "w"))
        later.refresh_from_db()
        self.assertEqual(later.status, WorkflowRun.CANCELLED)
        self.assertEqual(Notification.objects.filter(payload__text="went on").count(), 1)


@override_settings(CREDENTIALS_ENCRYPTION_KEY=KEY)
class InboundHookTests(Base):
    def setUp(self):
        super().setUp()
        self.workflow = self.wf({"type": "webhook"}, [{"type": "create_task", "title": "{{trigger.title}}", "room": str(self.room.id)}])
        made = self._as("admin").post(f"{self.base}/{self.workflow.id}/hook")
        self.assertEqual(made.status_code, 201, made.content)
        self.secret = made.json()["secret"]
        self.url = f"/api/v2/hooks/automations/{self.workflow.id}"
        listed = self._as("admin").get(f"{self.base}/{self.workflow.id}").json()
        self.assertNotIn(self.secret, json.dumps(listed))
        self.assertEqual(listed["hook"]["secret_hint"], "…" + self.secret[-4:])

    def call(self, body=b'{"title": "From CRM"}', secret=None, ts=None, signature=None):
        ts = str(int(time.time())) if ts is None else ts
        sig = signature or sign(secret or self.secret, ts, body)
        with self.captureOnCommitCallbacks(execute=True):
            return APIClient().post(self.url, body, content_type="application/json", HTTP_X_FLOBRAIN_TIMESTAMP=ts, HTTP_X_FLOBRAIN_SIGNATURE=sig)

    def test_signed_call_starts_a_run(self):
        response = self.call()
        self.assertEqual(response.status_code, 202, response.content)
        self.assertTrue(Task.objects.filter(title="From CRM").exists())
        self.assertEqual(self.call(ts=response.wsgi_request.META["HTTP_X_FLOBRAIN_TIMESTAMP"]).json()["status"], "ignored", "replay is deduplicated")

    def test_bad_signatures(self):
        self.assertEqual(self.call(secret="whsec_wrong").status_code, 401)
        self.assertEqual(self.call(signature="sha256=00").status_code, 401)
        self.assertEqual(self.call(ts=str(int(time.time()) - 3600)).status_code, 401)
        self.assertEqual(self.call(ts="soon").status_code, 401)
        self.assertEqual(self.call(body=b"[1, 2]").status_code, 400)
        self.assertEqual(self.call(body=b"{" + b" " * 70000 + b"}").status_code, 413)
        self.assertFalse(WorkflowRun.objects.exists())

    def test_disabled_and_flag_off_look_missing(self):
        Workflow.objects.filter(pk=self.workflow.pk).update(enabled=False)
        self.assertEqual(self.call().status_code, 404)
        Workflow.objects.filter(pk=self.workflow.pk).update(enabled=True)
        self.org.settings = {"flags": {}}
        self.org.save()
        self.assertEqual(self.call().status_code, 404)

    def test_rate_limit(self):
        codes = [self.call(body=json.dumps({"title": f"t{i}"}).encode()).status_code for i in range(32)]
        self.assertEqual(codes.count(429), 2)


class DraftAndTemplateTests(Base):
    def test_draft_validates_model_output(self):
        good = {"name": "Digest", "trigger": {"type": "schedule", "every": "week", "weekday": 0, "at": "09:00"}, "steps": [{"type": "ai_prompt", "prompt": "Summarise"}]}
        with patch("automations.ai._complete", return_value=json.dumps(good)):
            response = self._as("member").post(f"{self.base}/draft", {"text": "every monday summarise"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["valid"])
        self.assertFalse(Workflow.objects.exists(), "a draft is never saved")
        evil = {**good, "steps": [{"type": "run_shell", "cmd": "x"}]}
        with patch("automations.ai._complete", return_value=json.dumps(evil)):
            response = self._as("member").post(f"{self.base}/draft", {"text": "x"}, format="json")
        self.assertFalse(response.json()["valid"])
        self.assertTrue(response.json()["problems"])
        with patch("automations.ai._complete", return_value="not json"):
            self.assertEqual(self._as("member").post(f"{self.base}/draft", {"text": "x"}, format="json").status_code, 502)
        self.assertEqual(self._as("member").post(f"{self.base}/draft", {"text": ""}, format="json").status_code, 400)

    @override_settings(DEMO_MODE=True, DEMO_AI=True)
    def test_demo_drafts(self):
        first = self._as("admin").post(f"{self.base}/draft", {"text": "every Monday at 9 summarise last week's blocked tasks in Launch room"}, format="json").json()
        self.assertTrue(first["valid"], first)
        self.assertEqual(first["draft"]["trigger"], {"type": "schedule", "every": "week", "weekday": 0, "at": "09:00"})
        self.assertEqual([s["type"] for s in first["draft"]["steps"]], ["ai_prompt", "post_to_room"])
        self.assertEqual(first["draft"]["steps"][1]["room"], str(self.room.id))
        second = self._as("admin").post(f"{self.base}/draft", {"text": "when a task is blocked notify the lead"}, format="json").json()
        self.assertTrue(second["valid"], second)
        self.assertEqual(second["draft"]["trigger"]["type"], "task_blocked")
        self.assertEqual(second["draft"]["steps"][0]["roles"], ["team_leads"])
        saved = self._as("admin").post(self.base, second["draft"], format="json")
        self.assertEqual(saved.status_code, 201, saved.content)

    def test_templates_install(self):
        listed = self._as("member").get(f"{self.base}/templates").json()
        self.assertGreaterEqual(len(listed), 8)
        self.assertEqual(self._as("member").post(f"{self.base}/templates/daily_brief/install").status_code, 403)
        self.assertEqual(self._as("admin").post(f"{self.base}/templates/weekly_blocked_digest/install").status_code, 400, "needs a room")
        self.assertEqual(self._as("admin").post(f"{self.base}/templates/nope/install").status_code, 404)
        brief = self._as("admin").post(f"{self.base}/templates/daily_brief/install", {"enabled": True}, format="json")
        self.assertEqual(brief.status_code, 201, brief.content)
        self.assertTrue(brief.json()["enabled"])
        self.assertIsNotNone(brief.json()["next_run_at"])
        extra = {"room": str(self.room.id), "emails": ["boss@example.com"]}
        for template in listed:
            if template["key"] == "daily_brief":
                continue
            made = self._as("admin").post(f"{self.base}/templates/{template['key']}/install", extra, format="json")
            self.assertEqual(made.status_code, 201, (template["key"], made.content))
            self.assertFalse(made.json()["enabled"])
        self.assertTrue(all(t["installed"] for t in self._as("admin").get(f"{self.base}/templates").json()))
        self.assertTrue(AuditEvent.objects.filter(action="automation.install").exists())


class DemoSeedTests(Base):
    """Runs only this workstream's demo extras (the full demo reset also runs other areas' extras)."""

    def test_demo_seed(self):
        import importlib

        from organizations.models import Project
        from rooms.services import ensure_project_room

        project = Project.objects.create(org=self.org, name="Mobile app launch", lead=self.users["lead"])
        project.teams.add(self.team)
        ensure_project_room(project)
        Task.objects.create(org=self.org, title="Fix login", team=self.team, is_blocked=True, blocked_reason="Device", created_by=self.users["lead"])
        importlib.import_module("demo.extras.91_automations").seed(self.org, self.users, timezone.now())
        org = self.org
        self.assertEqual(Workflow.objects.filter(org=org).count(), 4)
        self.assertEqual(Workflow.objects.filter(org=org, enabled=True).count(), 2)
        self.assertEqual(WorkflowRun.objects.filter(org=org).count(), 10)
        self.assertEqual(WorkflowRun.objects.filter(org=org, status=WorkflowRun.WAITING).count(), 1)
        approval = RunApproval.objects.get(run__org=org, state="pending")
        self.assertEqual(approval.proposal.user, self.users["admin"])
        self.assertEqual(triggers.tick()["fired"], 0)
        listed = self._as("admin").get(self.base).json()
        self.assertEqual(sum(w["waiting_runs"] for w in listed), 1)
        waiting = self._as("admin").get(f"{self.base}/runs?status=waiting_approval").json()
        self.assertEqual(waiting[0]["waiting_approval"], str(approval.proposal_id))
