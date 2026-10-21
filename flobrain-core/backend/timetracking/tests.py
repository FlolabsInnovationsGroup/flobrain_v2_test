from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class TimerApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Time Org", slug="time-org")
        self.user = User.objects.create(email="time@example.com", password_hash=make_password("x"))
        OrgMembership.objects.create(
            org=self.org,
            user=self.user,
            org_role=OrgMembership.ORG_ROLE_MEMBER,
            employment_status=OrgMembership.STATUS_ACTIVE,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.user.id))}")

    def test_start_stop_and_one_open_timer(self):
        start = self.client.post(f"/api/v2/orgs/{self.org.id}/timer/start", {"description": "work"}, format="json")
        self.assertEqual(start.status_code, 201, start.content)
        again = self.client.post(f"/api/v2/orgs/{self.org.id}/timer/start", {}, format="json")
        self.assertEqual(again.status_code, 409)
        running = self.client.get(f"/api/v2/orgs/{self.org.id}/timer")
        self.assertIsNotNone(running.json()["running"])
        stop = self.client.post(f"/api/v2/orgs/{self.org.id}/timer/stop", {}, format="json")
        self.assertEqual(stop.status_code, 200)
        self.assertIsNotNone(stop.json()["ended_at"])
        report = self.client.get(f"/api/v2/orgs/{self.org.id}/time-reports/me")
        self.assertEqual(report.status_code, 200)
        self.assertGreaterEqual(report.json()["entries"], 1)
        calendar = self.client.get(f"/api/v2/orgs/{self.org.id}/calendar")
        self.assertEqual(calendar.status_code, 200)
        dashboard = self.client.get(f"/api/v2/orgs/{self.org.id}/dashboard/me")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIsNone(dashboard.json()["impact_score"])


from datetime import timedelta  # noqa: E402

from django.utils import timezone  # noqa: E402

from organizations.models import Project, Team, TeamMembership  # noqa: E402
from privacy.models import PrivacySettings  # noqa: E402
from rooms.models import Room, RoomMember  # noqa: E402
from tasks.models import Task, TaskAssignment  # noqa: E402
from timetracking.models import TimeEntry  # noqa: E402
from timetracking.reports import parse_week  # noqa: E402


def _person(email, org, role=OrgMembership.ORG_ROLE_MEMBER):
    user = User.objects.create(email=email, password_hash=make_password("x"), username=email.split("@")[0])
    OrgMembership.objects.create(org=org, user=user, org_role=role, employment_status=OrgMembership.STATUS_ACTIVE)
    return user


class ChronosTests(TestCase):
    """Decision 16: categories, links, manual entries, approval, reports and privacy."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Chronos Org", slug="chronos-org")
        self.admin = _person("c-admin@example.com", self.org, OrgMembership.ORG_ROLE_ADMIN)
        self.lead = _person("c-lead@example.com", self.org)
        self.member = _person("c-member@example.com", self.org)
        self.mate = _person("c-mate@example.com", self.org)
        self.outsider = _person("c-out@example.com", self.org)
        self.team = Team.objects.create(org=self.org, name="Eng")
        TeamMembership.objects.create(team=self.team, user=self.lead, team_role=TeamMembership.ROLE_LEAD)
        TeamMembership.objects.create(team=self.team, user=self.member, weekly_target_hours=20)
        TeamMembership.objects.create(team=self.team, user=self.mate)
        self.project = Project.objects.create(org=self.org, name="Launch")
        self.project.teams.add(self.team)
        self.task = Task.objects.create(org=self.org, team=self.team, project=self.project, title="Fix login")
        TaskAssignment.objects.create(task=self.task, user=self.member)
        self.room = Room.objects.filter(org=self.org, kind="team", team=self.team).first() or Room.objects.create(
            org=self.org, name="Eng", kind="team", team=self.team
        )
        RoomMember.objects.get_or_create(room=self.room, user=self.member)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _as(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return self.client

    def _manual(self, user, hours=2, days_ago=1, **extra):
        end = timezone.now() - timedelta(days=days_ago)
        body = {"started_at": (end - timedelta(hours=hours)).isoformat(), "ended_at": end.isoformat(), **extra}
        return self._as(user).post(f"{self.base}/time-entries", body, format="json")

    def test_timer_with_links_and_conflict_details(self):
        c = self._as(self.member)
        start = c.post(
            f"{self.base}/timer/start",
            {"description": "debug", "task": str(self.task.id), "room": str(self.room.id), "category": "projects", "tags": ["bug"]},
            format="json",
        )
        self.assertEqual(start.status_code, 201, start.content)
        body = start.json()
        self.assertEqual((body["task_title"], body["project"], body["room"], body["source"], body["tags"]), ("Fix login", str(self.project.id), str(self.room.id), "timer", ["bug"]))
        again = c.post(f"{self.base}/timer/start", {}, format="json")
        self.assertEqual((again.status_code, again.json()["error"], again.json()["details"]["id"]), (409, "timer_already_running", body["id"]))
        patched = c.patch(f"{self.base}/timer", {"category": "masterclass", "description": "class"}, format="json")
        self.assertEqual(patched.json()["category"], "masterclass")
        self.assertEqual(c.patch(f"{self.base}/timer", {"category": "fun"}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/timer/stop", {}, format="json").status_code, 200)

    def test_timer_link_validation(self):
        c = self._as(self.outsider)
        self.assertEqual(c.post(f"{self.base}/timer/start", {"task": str(self.task.id)}, format="json").status_code, 404)
        self.assertEqual(c.post(f"{self.base}/timer/start", {"room": str(self.room.id)}, format="json").status_code, 404)
        self.assertEqual(c.post(f"{self.base}/timer/start", {"project": str(self.project.id)}, format="json").status_code, 404)
        self.assertEqual(c.post(f"{self.base}/timer/start", {"task": "garbage"}, format="json").status_code, 404)
        self.assertEqual(c.post(f"{self.base}/timer/start", {"category": "x"}, format="json").status_code, 400)
        self.assertFalse(TimeEntry.objects.filter(user=self.outsider).exists())

    def test_manual_entries_rules(self):
        res = self._manual(self.member, category="onboarding", project=str(self.project.id))
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["source"], res.json()["category"], res.json()["seconds"]), ("manual", "onboarding", 7200))
        now = timezone.now()
        c = self._as(self.member)
        bad = [
            {},
            {"started_at": now.isoformat()},
            {"started_at": "x", "ended_at": now.isoformat()},
            {"started_at": now.isoformat(), "ended_at": (now - timedelta(hours=1)).isoformat()},
            {"started_at": (now + timedelta(hours=1)).isoformat(), "ended_at": (now + timedelta(hours=2)).isoformat()},
            {"started_at": (now - timedelta(hours=30)).isoformat(), "ended_at": now.isoformat()},
        ]
        for body in bad:
            self.assertEqual(c.post(f"{self.base}/time-entries", body, format="json").status_code, 400, body)
        self.assertEqual(c.post(f"{self.base}/time-entries", [1], format="json").status_code, 400)

    def test_edit_delete_own_only_and_approved_locked(self):
        entry_id = self._manual(self.member).json()["id"]
        url = f"{self.base}/time-entries/{entry_id}"
        self.assertEqual(self._as(self.mate).patch(url, {"description": "x"}, format="json").status_code, 404)
        self.assertEqual(self._as(self.mate).delete(url).status_code, 404)
        edited = self._as(self.member).patch(url, {"description": "Notes", "category": "masterclass"}, format="json")
        self.assertEqual((edited.json()["description"], edited.json()["category"]), ("Notes", "masterclass"))
        end = timezone.now() - timedelta(hours=1)
        moved = self.client.patch(url, {"started_at": (end - timedelta(minutes=30)).isoformat(), "ended_at": end.isoformat()}, format="json")
        self.assertEqual(moved.json()["seconds"], 1800)
        TimeEntry.objects.filter(pk=entry_id).update(approval_status=TimeEntry.APPROVAL_APPROVED)
        self.assertEqual(self.client.patch(url, {"description": "y"}, format="json").status_code, 409)
        self.assertEqual(self.client.delete(url).status_code, 409)

    def test_running_entry_times_not_editable(self):
        c = self._as(self.member)
        entry_id = c.post(f"{self.base}/timer/start", {}, format="json").json()["id"]
        res = c.patch(f"{self.base}/time-entries/{entry_id}", {"started_at": timezone.now().isoformat()}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_submit_and_review(self):
        entry_id = self._manual(self.member).json()["id"]
        c = self._as(self.member)
        self.assertEqual(c.post(f"{self.base}/time-entries/submit", {}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/time-entries/submit", {"week": "bad"}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/time-entries/submit", {"ids": [entry_id]}, format="json").json()["submitted"], 1)
        queue = self._as(self.lead).get(f"{self.base}/time-entries/approvals").json()
        self.assertEqual([(r["id"], r["user_name"]) for r in queue], [(entry_id, "c-member")])
        self.assertEqual(self._as(self.mate).get(f"{self.base}/time-entries/approvals").json(), [])
        approve = f"{self.base}/time-entries/{entry_id}/approve"
        reject = f"{self.base}/time-entries/{entry_id}/reject"
        self.assertEqual(self._as(self.member).post(approve, {}, format="json").status_code, 403, "not your own")
        self.assertEqual(self._as(self.mate).post(approve, {}, format="json").status_code, 403, "teammates can't")
        self.assertEqual(self._as(self.outsider).post(approve, {}, format="json").status_code, 404)
        self.assertEqual(self._as(self.lead).post(reject, {}, format="json").status_code, 400, "needs a reason")
        rejected = self._as(self.lead).post(reject, {"note": "Split by task please"}, format="json").json()
        self.assertEqual((rejected["approval_status"], rejected["approval_note"]), ("rejected", "Split by task please"))
        self.assertEqual(self._as(self.lead).post(approve, {}, format="json").status_code, 409)
        self._as(self.member).post(f"{self.base}/time-entries/submit", {"ids": [entry_id]}, format="json")
        approved = self._as(self.admin).post(approve, {}, format="json").json()
        self.assertEqual((approved["approval_status"], approved["approved_by"]), ("approved", str(self.admin.id)))

    def test_editing_submitted_entry_returns_it_to_draft(self):
        entry_id = self._manual(self.member).json()["id"]
        self._as(self.member).post(f"{self.base}/time-entries/submit", {"ids": [entry_id]}, format="json")
        res = self.client.patch(f"{self.base}/time-entries/{entry_id}", {"description": "more"}, format="json")
        self.assertEqual(res.json()["approval_status"], "draft")

    def test_reports_by_category_project_task_and_week(self):
        week = parse_week(None)
        start = timezone.make_aware(timezone.datetime.combine(week, timezone.datetime.min.time())) + timedelta(hours=9)
        for hours, cat, task in ((2, "projects", self.task), (1, "onboarding", None), (3, "projects", None)):
            TimeEntry.objects.create(
                org=self.org, user=self.member, started_at=start, ended_at=start + timedelta(hours=hours),
                category=cat, task=task, project=self.project if task else None, source="manual",
            )
        TimeEntry.objects.create(org=self.org, user=self.member, started_at=start - timedelta(days=7), ended_at=start - timedelta(days=7, hours=-5))
        me = self._as(self.member).get(f"{self.base}/time-reports/me?week={week.isoformat()}").json()
        self.assertEqual((me["seconds"], me["entries"]), (6 * 3600, 3))
        cats = {r["key"]: r["seconds"] for r in me["by_category"]}
        self.assertEqual(cats, {"projects": 5 * 3600, "onboarding": 3600, "masterclass": 0})
        tasks = {r["name"]: r["seconds"] for r in me["by_task"]}
        self.assertEqual(tasks["Fix login"], 7200)
        self.assertEqual({r["name"]: r["seconds"] for r in me["by_project"]}["Launch"], 7200)
        self.assertEqual(sum(r["seconds"] for r in me["by_day"]), me["seconds"])
        label = me["week"]
        self.assertEqual(self._as(self.member).get(f"{self.base}/time-reports/me?week={label}").json()["seconds"], 6 * 3600)
        self.assertEqual(self._as(self.member).get(f"{self.base}/time-reports/me?week=nope").status_code, 400)
        team = self._as(self.lead).get(f"{self.base}/time-reports/team/{self.team.id}?week={label}").json()
        row = next(r for r in team["by_member"] if r["user_id"] == str(self.member.id))
        self.assertEqual((row["seconds"], row["capacity_seconds"]), (6 * 3600, 14 * 3600))
        self.assertEqual(team["seconds"], 6 * 3600)
        self.assertEqual(self._as(self.mate).get(f"{self.base}/time-reports/team/{self.team.id}").status_code, 403)
        self.assertEqual(self._as(self.outsider).get(f"{self.base}/time-reports/team/{self.team.id}").status_code, 404)
        dash = self._as(self.member).get(f"{self.base}/dashboard/me").json()
        self.assertIn("by_category", dash)

    def test_privacy_hides_descriptions_in_approval_queue(self):
        entry_id = self._manual(self.member, description="doctor visit").json()["id"]
        self._as(self.member).post(f"{self.base}/time-entries/submit", {"ids": [entry_id]}, format="json")
        PrivacySettings.objects.create(org=self.org, user=self.member, share_time_details_with_org=False)
        row = self._as(self.lead).get(f"{self.base}/time-entries/approvals").json()[0]
        self.assertEqual((row["description"], row["description_hidden"]), ("", True))
        listed = self._as(self.lead).get(f"{self.base}/time-entries?team={self.team.id}&status=submitted").json()["results"]
        self.assertEqual(listed[0]["description"], "")
        self.assertEqual(self._as(self.lead).get(f"{self.base}/time-entries?status=nope").status_code, 400)

    def test_private_room_names_and_hidden_details_never_reach_teammates(self):
        """Review finding 3: a time entry must not reveal a private room's name or, with sharing off, tags."""
        secret = Room.objects.create(org=self.org, name="Secret HR talk", kind="group")
        RoomMember.objects.create(room=secret, user=self.member)
        self._manual(self.member, room=str(secret.id))
        self._manual(self.member, room=str(self.room.id), days_ago=2)
        rows = self._as(self.mate).get(f"{self.base}/time-entries?team={self.team.id}").json()["results"]
        names = {r["room_name"] for r in rows}
        self.assertNotIn("Secret HR talk", names)
        self.assertIn(self.room.name, names, "rooms the viewer can open still show")
        mine = self._as(self.member).get(f"{self.base}/time-entries").json()["results"]
        self.assertIn("Secret HR talk", {r["room_name"] for r in mine}, "your own entries keep their names")
        report = self._as(self.lead).get(f"{self.base}/time-reports/team/{self.team.id}").json()
        self.assertNotIn("Secret HR talk", {r["name"] for r in report["by_room"]})
        self.assertTrue(any(r.get("private") for r in report["by_room"]))
        PrivacySettings.objects.create(org=self.org, user=self.member, share_time_details_with_org=False)
        rows = self._as(self.mate).get(f"{self.base}/time-entries?team={self.team.id}").json()["results"]
        self.assertTrue(all(r["room_name"] == "" and r["tags"] == [] and r["task_title"] == "" for r in rows))

    def test_calendar_room_and_range(self):
        today = timezone.localdate()
        Task.objects.filter(pk=self.task.pk).update(due_on=today + timedelta(days=2))
        Task.objects.create(org=self.org, title="Elsewhere", due_on=today + timedelta(days=2))
        c = self._as(self.member)
        everything = [i["title"] for i in c.get(f"{self.base}/calendar").json()]
        self.assertEqual(sorted(everything), ["Elsewhere", "Fix login"])
        in_room = [i["title"] for i in c.get(f"{self.base}/calendar?room={self.room.id}").json()]
        self.assertEqual(in_room, ["Fix login"])
        self.assertEqual(c.get(f"{self.base}/calendar?from={(today + timedelta(days=3)).isoformat()}").json(), [])
        self.assertEqual(c.get(f"{self.base}/calendar?from=2026-02-30").status_code, 400)
        self.assertEqual(self._as(self.outsider).get(f"{self.base}/calendar?room={self.room.id}").status_code, 404)

    def test_cross_org(self):
        other = Organization.objects.create(name="Other", slug="chronos-other")
        stranger = _person("c-stranger@example.com", other, OrgMembership.ORG_ROLE_OWNER)
        entry_id = self._manual(self.member).json()["id"]
        self._as(self.member).post(f"{self.base}/time-entries/submit", {"ids": [entry_id]}, format="json")
        c = self._as(stranger)
        self.assertEqual(c.post(f"/api/v2/orgs/{other.id}/time-entries/{entry_id}/approve", {}, format="json").status_code, 404)
        self.assertEqual(c.post(f"/api/v2/orgs/{other.id}/timer/start", {"task": str(self.task.id)}, format="json").status_code, 404)
        self.assertEqual(c.get(f"/api/v2/orgs/{other.id}/time-entries/approvals").json(), [])
