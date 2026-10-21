from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class TaskApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Task Org", slug="task-org")
        self.owner = User.objects.create(email="t-owner@example.com", password_hash=make_password("x"))
        self.member = User.objects.create(email="t-member@example.com", password_hash=make_password("x"))
        self.other = User.objects.create(email="t-other@example.com", password_hash=make_password("x"))
        for user, role in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER),
            (self.member, OrgMembership.ORG_ROLE_MEMBER),
            (self.other, OrgMembership.ORG_ROLE_MEMBER),
        ):
            OrgMembership.objects.create(
                org=self.org,
                user=user,
                org_role=role,
                employment_status=OrgMembership.STATUS_ACTIVE,
            )

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_member_creates_and_cannot_assign_others(self):
        self._auth(self.member)
        created = self.client.post(
            f"/api/v2/orgs/{self.org.id}/tasks",
            {"title": "Write tests"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        task_id = created.json()["id"]
        denied = self.client.post(
            f"/api/v2/orgs/{self.org.id}/tasks/{task_id}/assign",
            {"user_id": str(self.other.id)},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

    def test_owner_can_assign_others_and_member_can_move_own(self):
        self._auth(self.member)
        created = self.client.post(
            f"/api/v2/orgs/{self.org.id}/tasks",
            {"title": "Ship"},
            format="json",
        )
        task_id = created.json()["id"]
        moved = self.client.post(
            f"/api/v2/orgs/{self.org.id}/tasks/{task_id}/move",
            {"status": "in_progress"},
            format="json",
        )
        self.assertEqual(moved.status_code, 200, moved.content)
        self._auth(self.owner)
        assigned = self.client.post(
            f"/api/v2/orgs/{self.org.id}/tasks/{task_id}/assign",
            {"user_id": str(self.other.id)},
            format="json",
        )
        self.assertEqual(assigned.status_code, 200, assigned.content)
        self.assertIn(str(self.other.id), assigned.json()["assignees"])

    def test_mission_control(self):
        self._auth(self.owner)
        self.client.post(f"/api/v2/orgs/{self.org.id}/tasks", {"title": "A"}, format="json")
        res = self.client.get(f"/api/v2/orgs/{self.org.id}/mission-control")
        self.assertEqual(res.status_code, 200)
        self.assertIn("assigned_open", res.json())
        self.assertGreaterEqual(res.json()["assigned_open"], 1)
        self.assertIn("accomplishments", res.json())
        self.assertIn("blockers", res.json())
        self.assertIn("deadlines", res.json())
        self.assertIn("workload", res.json())

    def test_member_cannot_open_mission_control(self):
        self._auth(self.member)
        res = self.client.get(f"/api/v2/orgs/{self.org.id}/mission-control")
        self.assertEqual(res.status_code, 403)


from datetime import date, timedelta  # noqa: E402
from io import StringIO  # noqa: E402

from django.core.management import call_command  # noqa: E402
from django.utils import timezone  # noqa: E402

from notifications.models import Notification, NotificationPreference  # noqa: E402
from organizations.models import Project, Team, TeamMembership  # noqa: E402
from rooms.models import Room, RoomMember  # noqa: E402
from tasks.models import ProjectTemplate, Task, TaskAssignment, TaskReminder  # noqa: E402


def _person(email, org, role=OrgMembership.ORG_ROLE_MEMBER, status=OrgMembership.STATUS_ACTIVE):
    user = User.objects.create(email=email, password_hash=make_password("x"), username=email.split("@")[0])
    OrgMembership.objects.create(org=org, user=user, org_role=role, employment_status=status)
    return user


class TaskBoardTests(TestCase):
    """Priority, ordering, blocked reasons, filters, rooms, edit/delete rules and notifications."""

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Board Org", slug="board-org")
        self.admin = _person("b-admin@example.com", self.org, OrgMembership.ORG_ROLE_ADMIN)
        self.lead = _person("b-lead@example.com", self.org)
        self.member = _person("b-member@example.com", self.org)
        self.mate = _person("b-mate@example.com", self.org)
        self.outsider = _person("b-out@example.com", self.org)
        self.gone = _person("b-gone@example.com", self.org, status=OrgMembership.STATUS_TERMINATED)
        self.team = Team.objects.create(org=self.org, name="Eng")
        self.other_team = Team.objects.create(org=self.org, name="Ops")
        TeamMembership.objects.create(team=self.team, user=self.lead, team_role=TeamMembership.ROLE_LEAD)
        TeamMembership.objects.create(team=self.team, user=self.member)
        TeamMembership.objects.create(team=self.team, user=self.mate)
        TeamMembership.objects.create(team=self.other_team, user=self.outsider)
        self.base = f"/api/v2/orgs/{self.org.id}"
        self.room = Room.objects.filter(org=self.org, kind="team", team=self.team).first() or Room.objects.create(
            org=self.org, name="Eng", kind="team", team=self.team
        )
        for user in (self.lead, self.member, self.mate):
            RoomMember.objects.get_or_create(room=self.room, user=user)

    def _as(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return self.client

    def _create(self, user, **body):
        body.setdefault("title", "A task")
        body.setdefault("team", str(self.team.id))
        return self._as(user).post(f"{self.base}/tasks", body, format="json")

    def test_create_with_priority_due_and_assignees(self):
        res = self._create(
            self.lead, title="Ship it", priority="urgent", due_on="2030-01-02", assignees=[str(self.member.id)], description="Now"
        )
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual((body["priority"], body["due_on"], body["assignees"]), ("urgent", "2030-01-02", [str(self.member.id)]))
        self.assertEqual(body["people"][0]["name"], "b-member")
        row = TaskAssignment.objects.get(task_id=body["id"])
        self.assertEqual(row.assigned_by_id, self.lead.id)
        note = Notification.objects.get(user=self.member, kind="task.assigned")
        self.assertEqual((note.payload["title"], note.payload["link"]), ("Ship it", "tasks"))
        self.assertFalse(Notification.objects.filter(user=self.lead).exists())

    def test_create_validation(self):
        self.assertEqual(self._create(self.member, title=" ").status_code, 400)
        self.assertEqual(self._create(self.member, priority="huge").status_code, 400)
        self.assertEqual(self._create(self.member, due_on="tomorrow").status_code, 400)
        self.assertEqual(self._create(self.member, assignees="nope").status_code, 400)
        self.assertEqual(self._as(self.member).post(f"{self.base}/tasks", [1], format="json").status_code, 400)
        # Assigning someone else needs a due date (Decision 5), and members can't do it at all.
        self.assertEqual(self._create(self.lead, assignees=[str(self.member.id)]).status_code, 400)
        denied = self._create(self.member, assignees=[str(self.mate.id)], due_on="2030-01-01")
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(Task.objects.filter(title="A task").exists(), "nothing is half-created")
        self.assertEqual(self._create(self.lead, assignees=[str(self.gone.id)], due_on="2030-01-01").status_code, 404)
        self.assertEqual(self._create(self.lead, assignees=[str(self.outsider.id)], due_on="2030-01-01").status_code, 404)

    def test_member_can_assign_self_and_default_is_normal(self):
        res = self._create(self.member, assignees=[str(self.member.id)])
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["priority"], "normal")
        self.assertFalse(Notification.objects.exists(), "no notification for assigning yourself")

    def test_room_board_and_room_create(self):
        created = self._create(self.member, title="From the room", room=str(self.room.id), team=None)
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual((created.json()["room"], created.json()["team"]), (str(self.room.id), str(self.team.id)))
        Task.objects.create(org=self.org, title="Ops work", team=self.other_team)
        listed = self._as(self.member).get(f"{self.base}/tasks?room={self.room.id}").json()["results"]
        self.assertEqual([t["title"] for t in listed], ["From the room"])
        # Not a member of the room: 404 to list or file into it.
        self.assertEqual(self._as(self.outsider).get(f"{self.base}/tasks?room={self.room.id}").status_code, 404)
        self.assertEqual(self._create(self.outsider, room=str(self.room.id), team=None).status_code, 404)
        self.assertEqual(self._as(self.member).get(f"{self.base}/tasks?room=garbage").status_code, 404)

    def test_move_reorders_and_sets_completed_at(self):
        ids = [self._create(self.member, title=f"T{i}").json()["id"] for i in range(3)]
        url = lambda i: f"{self.base}/tasks/{i}/move"  # noqa: E731
        res = self._as(self.member).post(url(ids[2]), {"status": "to_do", "before": ids[0]}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        order = [t["title"] for t in self.client.get(f"{self.base}/tasks?status=to_do").json()["results"]]
        self.assertEqual(order, ["T2", "T0", "T1"])
        done = self.client.post(url(ids[0]), {"status": "done"}, format="json").json()
        self.assertIsNotNone(done["completed_at"])
        back = self.client.post(url(ids[0]), {"status": "in_progress", "position": 0}, format="json").json()
        self.assertIsNone(back["completed_at"])
        self.assertEqual(self.client.post(url(ids[1]), {"status": "nope"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url(ids[1]), {"status": "done", "before": ids[2]}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url(ids[1]), {"status": "done", "position": -1}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url(ids[1]), {"status": "done", "position": "x"}, format="json").status_code, 400)
        # A teammate who is neither creator nor assignee cannot move it.
        self.assertEqual(self._as(self.mate).post(url(ids[1]), {"status": "done"}, format="json").status_code, 403)
        # Someone outside the team cannot see it.
        self.assertEqual(self._as(self.outsider).post(url(ids[1]), {"status": "done"}, format="json").status_code, 404)

    def test_blocked_needs_reason_and_tracks_since(self):
        task_id = self._create(self.member).json()["id"]
        url = f"{self.base}/tasks/{task_id}"
        self.assertEqual(self._as(self.member).patch(url, {"is_blocked": True}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"is_blocked": "yes", "blocked_reason": "x"}, format="json").status_code, 400)
        res = self.client.patch(url, {"is_blocked": True, "blocked_reason": "Waiting for a device"}, format="json").json()
        self.assertEqual((res["is_blocked"], res["blocked_reason"]), (True, "Waiting for a device"))
        self.assertIsNotNone(res["blocked_since"])
        blocked = self.client.get(f"{self.base}/tasks?blocked=1").json()["results"]
        self.assertEqual([t["id"] for t in blocked], [task_id])
        cleared = self.client.patch(url, {"is_blocked": False}, format="json").json()
        self.assertEqual((cleared["is_blocked"], cleared["blocked_reason"], cleared["blocked_since"]), (False, "", None))

    def test_edit_rules(self):
        task_id = self._create(self.lead, assignees=[str(self.member.id)], due_on="2030-01-01").json()["id"]
        url = f"{self.base}/tasks/{task_id}"
        ok = self._as(self.member).patch(url, {"title": "Renamed", "priority": "high", "description": "d"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual((ok.json()["title"], ok.json()["priority"]), ("Renamed", "high"))
        self.assertEqual(self.client.patch(url, {"title": ""}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"priority": "x"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"due_on": "soon"}, format="json").status_code, 400)
        # The member is the assignee but the lead created it: due date stays the lead's call... for others' tasks.
        self._as(self.lead).post(f"{url}/assign", {"user_id": str(self.mate.id)}, format="json")
        self.assertEqual(self._as(self.member).patch(url, {"due_on": "2030-02-01"}, format="json").status_code, 403)
        self.assertEqual(self._as(self.lead).patch(url, {"due_on": "2030-02-01"}, format="json").status_code, 200)
        self.assertEqual(self._as(self.outsider).patch(url, {"title": "x"}, format="json").status_code, 404)
        self.assertEqual(self._as(self.member).patch(url, {"team": str(self.other_team.id)}, format="json").status_code, 404)

    def test_delete_rules(self):
        task_id = self._create(self.lead, assignees=[str(self.member.id)], due_on="2030-01-01").json()["id"]
        url = f"{self.base}/tasks/{task_id}"
        self.assertEqual(self._as(self.member).delete(url).status_code, 403, "assignees can't delete")
        self.assertEqual(self._as(self.outsider).delete(url).status_code, 404)
        self.assertEqual(self._as(self.admin).delete(url).status_code, 204)
        own = self._create(self.member).json()["id"]
        self.assertEqual(self._as(self.member).delete(f"{self.base}/tasks/{own}").status_code, 204)

    def test_filters(self):
        mine = self._create(self.lead, title="Mine", assignees=[str(self.lead.id)]).json()["id"]
        given = self._create(self.lead, title="Given", assignees=[str(self.member.id)], due_on=str(date.today() - timedelta(days=1))).json()["id"]
        self._as(self.member).post(f"{self.base}/tasks/{given}/move", {"status": "in_progress"}, format="json")
        lead = self._as(self.lead)
        titles = lambda q: sorted(t["title"] for t in lead.get(f"{self.base}/tasks?{q}").json()["results"])  # noqa: E731
        self.assertEqual(titles("filter=mine"), ["Mine"])
        self.assertEqual(titles("filter=assigned_by_me"), ["Given"])
        self.assertEqual(titles(f"assignee={self.member.id}"), ["Given"])
        self.assertEqual(titles("status=in_progress"), ["Given"])
        self.assertEqual(titles("due=overdue"), ["Given"])
        self.assertEqual(titles("due=none"), ["Mine"])
        self.assertEqual(titles(f"team={self.team.id}"), ["Given", "Mine"])
        self.assertEqual(titles("mine=1"), ["Mine"], "old mine=1 still works")
        lead.post(f"{self.base}/tasks/{mine}/move", {"status": "done"}, format="json")
        self.assertEqual(titles("filter=completed"), ["Mine"])
        for bad in ("filter=x", "status=x", "due=x", "team=x", "priority=x", "due_before=x"):
            self.assertEqual(lead.get(f"{self.base}/tasks?{bad}").status_code, 400, bad)

    def test_unassign(self):
        task_id = self._create(self.lead, assignees=[str(self.member.id), str(self.mate.id)], due_on="2030-01-01").json()["id"]
        url = f"{self.base}/tasks/{task_id}/unassign"
        self.assertEqual(self._as(self.member).post(url, {"user_id": str(self.mate.id)}, format="json").status_code, 403)
        self.assertEqual(self._as(self.member).post(url, {"user_id": str(self.member.id)}, format="json").status_code, 200)
        self.assertEqual(self._as(self.lead).post(url, {"user_id": str(self.member.id)}, format="json").status_code, 404)
        res = self._as(self.lead).post(url, {"user_id": str(self.mate.id)}, format="json")
        self.assertEqual(res.json()["assignees"], [])

    def test_assign_notifies_and_respects_muting(self):
        task_id = self._create(self.lead).json()["id"]
        NotificationPreference.objects.create(user=self.mate, type="task_assigned", enabled=False)
        lead = self._as(self.lead)
        self.assertEqual(lead.post(f"{self.base}/tasks/{task_id}/assign", {"user_id": str(self.member.id)}, format="json").status_code, 200)
        lead.post(f"{self.base}/tasks/{task_id}/assign", {"user_id": str(self.member.id)}, format="json")
        self.assertEqual(Notification.objects.filter(user=self.member, kind="task.assigned").count(), 1, "re-assigning is quiet")
        lead.post(f"{self.base}/tasks/{task_id}/assign", {"user_id": str(self.mate.id)}, format="json")
        self.assertFalse(Notification.objects.filter(user=self.mate).exists())
        self.assertEqual(lead.post(f"{self.base}/tasks/{task_id}/assign", {"user_id": "bad"}, format="json").status_code, 404)

    def test_cross_org_isolation(self):
        other = Organization.objects.create(name="Other", slug="other-board")
        stranger = _person("b-stranger@example.com", other, OrgMembership.ORG_ROLE_OWNER)
        task_id = self._create(self.member).json()["id"]
        client = self._as(stranger)
        self.assertEqual(client.get(f"/api/v2/orgs/{other.id}/tasks/{task_id}").status_code, 404)
        self.assertEqual(client.post(f"/api/v2/orgs/{other.id}/tasks/{task_id}/move", {"status": "done"}, format="json").status_code, 404)
        self.assertEqual(client.get(f"{self.base}/tasks").status_code, 403)
        self.assertEqual(
            client.post(f"/api/v2/orgs/{other.id}/tasks", {"title": "x", "room": str(self.room.id)}, format="json").status_code, 404
        )

    def test_list_payload_has_permissions_and_people(self):
        self._create(self.lead, title="Lead's", assignees=[str(self.member.id)], due_on="2030-01-01")
        row = self._as(self.mate).get(f"{self.base}/tasks").json()["results"][0]
        self.assertEqual((row["can_edit"], row["can_delete"]), (False, False))
        row = self._as(self.member).get(f"{self.base}/tasks").json()["results"][0]
        self.assertEqual((row["can_edit"], row["can_delete"]), (True, False))
        self.assertEqual(row["people"], [{"id": str(self.member.id), "name": "b-member"}])


class TaskRemindersTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Remind Org", slug="remind-org")
        self.member = _person("r-member@example.com", self.org)
        self.gone = _person("r-gone@example.com", self.org, status=OrgMembership.STATUS_TERMINATED)
        today = timezone.localdate()
        self.soon = Task.objects.create(org=self.org, title="Soon", due_on=today + timedelta(days=1))
        self.late = Task.objects.create(org=self.org, title="Late", due_on=today - timedelta(days=3))
        self.done = Task.objects.create(org=self.org, title="Done", due_on=today - timedelta(days=3), status=Task.STATUS_DONE)
        self.later = Task.objects.create(org=self.org, title="Later", due_on=today + timedelta(days=5))
        for task in (self.soon, self.late, self.done, self.later):
            TaskAssignment.objects.create(task=task, user=self.member)
            TaskAssignment.objects.create(task=task, user=self.gone)

    def test_tick_is_idempotent(self):
        out = StringIO()
        call_command("tick_tasks", stdout=out)
        self.assertIn("due_soon 1 overdue 1", out.getvalue())
        kinds = sorted(Notification.objects.filter(user=self.member).values_list("kind", "payload__title"))
        self.assertEqual(kinds, [("task.due_soon", "Soon"), ("task.overdue", "Late")])
        self.assertFalse(Notification.objects.filter(user=self.gone).exists(), "inactive people get nothing")
        call_command("tick_tasks", stdout=StringIO())
        self.assertEqual(Notification.objects.filter(user=self.member).count(), 2)
        self.assertEqual(TaskReminder.objects.count(), 2)

    def test_new_due_date_is_a_new_reminder_and_muting_works(self):
        call_command("tick_tasks", stdout=StringIO())
        self.late.due_on = timezone.localdate() - timedelta(days=1)
        self.late.save()
        NotificationPreference.objects.create(user=self.member, type="task_deadline_reached", enabled=False)
        call_command("tick_tasks", stdout=StringIO())
        self.assertEqual(Notification.objects.filter(user=self.member, kind="task.overdue").count(), 1)
        self.assertEqual(TaskReminder.objects.filter(task=self.late).count(), 2)


class ProjectTemplateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Tpl Org", slug="tpl-org")
        self.admin = _person("tpl-admin@example.com", self.org, OrgMembership.ORG_ROLE_ADMIN)
        self.member = _person("tpl-member@example.com", self.org)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _as(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return self.client

    def test_template_to_project(self):
        spec = {"description": "Launch", "tasks": [{"title": "Kickoff", "priority": "high", "due_in_days": 2}, {"title": "Retro"}]}
        created = self._as(self.admin).post(f"{self.base}/project-templates", {"name": "Launch", "spec": spec}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["task_count"], 2)
        listed = self._as(self.member).get(f"{self.base}/project-templates").json()
        self.assertEqual([t["name"] for t in listed], ["Launch"])
        self.assertEqual(
            self._as(self.member).post(f"{self.base}/projects/from-template", {"template_id": created.json()["id"]}, format="json").status_code,
            403,
        )
        res = self._as(self.admin).post(
            f"{self.base}/projects/from-template", {"template_id": created.json()["id"], "name": "Launch Q4"}, format="json"
        )
        self.assertEqual(res.status_code, 201, res.content)
        project = Project.objects.get(pk=res.json()["id"])
        self.assertEqual(project.name, "Launch Q4")
        kickoff = Task.objects.get(project=project, title="Kickoff")
        self.assertEqual((kickoff.priority, kickoff.due_on), ("high", timezone.localdate() + timedelta(days=2)))

    def test_template_validation(self):
        admin = self._as(self.admin)
        self.assertEqual(admin.post(f"{self.base}/project-templates", {"name": ""}, format="json").status_code, 400)
        self.assertEqual(admin.post(f"{self.base}/project-templates", {"name": "x", "spec": {"tasks": [{"title": ""}]}}, format="json").status_code, 400)
        self.assertEqual(
            admin.post(f"{self.base}/project-templates", {"name": "x", "spec": {"tasks": [{"title": "a", "due_in_days": "2"}]}}, format="json").status_code,
            400,
        )
        self.assertEqual(admin.post(f"{self.base}/projects/from-template", {"template_id": "nope"}, format="json").status_code, 404)
        other = Organization.objects.create(name="O2", slug="tpl-o2")
        foreign = ProjectTemplate.objects.create(org=other, name="Theirs")
        self.assertEqual(admin.post(f"{self.base}/projects/from-template", {"template_id": str(foreign.id)}, format="json").status_code, 404)


class MissionControlDrilldownTests(TestCase):
    def test_titles_names_and_capacity(self):
        client = APIClient()
        org = Organization.objects.create(name="MC Org", slug="mc-org")
        lead = _person("mc-lead@example.com", org)
        member = _person("mc-member@example.com", org)
        team = Team.objects.create(org=org, name="Eng")
        TeamMembership.objects.create(team=team, user=lead, team_role=TeamMembership.ROLE_LEAD)
        TeamMembership.objects.create(team=team, user=member, weekly_target_hours=10)
        task = Task.objects.create(
            org=org, team=team, title="Fix login", priority="urgent", due_on=date.today() + timedelta(days=1),
            is_blocked=True, blocked_reason="No device", blocked_since=timezone.now() - timedelta(hours=3),
        )
        TaskAssignment.objects.create(task=task, user=member)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(lead.id))}")
        data = client.get(f"/api/v2/orgs/{org.id}/mission-control?team={team.id}").json()
        row = next(r for r in data["workload"] if r["user_id"] == str(member.id))
        self.assertEqual((row["name"], row["tasks"][0]["title"], row["capacity_seconds"]), ("mc-member", "Fix login", 36000))
        self.assertEqual((data["blockers"][0]["reason"], data["blockers"][0]["people"][0]["name"]), ("No device", "mc-member"))
        self.assertEqual((data["deadlines"][0]["priority"], data["deadlines"][0]["urgency"]), ("urgent", "high"))
        self.assertEqual(client.get(f"/api/v2/orgs/{org.id}/mission-control?team=bad").status_code, 404)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(member.id))}")
        self.assertEqual(client.get(f"/api/v2/orgs/{org.id}/mission-control").status_code, 403)


class DemoTasksSeedTests(TestCase):
    """demo/extras/30_tasks.py: the tour stop and the reminders work on a fresh demo org."""

    def test_demo_board(self):
        from django.test import override_settings

        from demo import seed
        from timetracking.models import TimeEntry

        with override_settings(DEMO_MODE=True, DEMO_AI=True):
            seed.reset()
        org = Organization.objects.get(slug="demo")
        fix = Task.objects.get(org=org, title="Fix login timeout on Android")
        self.assertEqual((fix.is_blocked, fix.priority), (True, "urgent"))
        self.assertIn("Android test device", fix.blocked_reason)
        kinds = set(Notification.objects.filter(org=org).values_list("kind", flat=True))
        self.assertTrue({"task.due_soon", "task.overdue"} <= kinds)
        entries = TimeEntry.objects.filter(org=org)
        self.assertEqual(set(entries.values_list("category", flat=True)), {"projects", "onboarding", "masterclass"})
        self.assertEqual(entries.filter(approval_status="submitted").count(), 1)
        self.assertTrue(ProjectTemplate.objects.filter(org=org).exists())
        member = org.memberships.get(user__demo_account__role="member").user
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(member.id))}")
        board = client.get(f"/api/v2/orgs/{org.id}/tasks?page_size=100").json()["results"]
        card = next(t for t in board if t["title"] == fix.title)
        self.assertTrue(card["can_edit"])
        moved = client.post(f"/api/v2/orgs/{org.id}/tasks/{fix.id}/move", {"status": "to_do", "position": 0}, format="json")
        self.assertEqual(moved.status_code, 200, moved.content)
