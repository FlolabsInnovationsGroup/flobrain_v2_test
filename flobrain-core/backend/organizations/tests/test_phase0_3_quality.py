import hashlib
import hmac
import json
from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from organizations.models import OrgMembership, Organization, PermissionRequest, Team, TeamMembership
from organizations.permissions.engine import can
from organizations.permissions.registry import PHASE_0_TO_3_API_KEYS, ROLE_DEFAULTS
from organizations.services.members import can_receive_dm
from tasks.models import Task
from timetracking.models import TimeEntry
from users.jwt_utils import make_access_token
from users.models import User


def _user(email: str, password="correct-horse") -> User:
    return User.objects.create(email=email, password_hash=make_password(password), username=email.split("@")[0])


def _member(org, user, role=OrgMembership.ORG_ROLE_MEMBER, status=OrgMembership.STATUS_ACTIVE):
    return OrgMembership.objects.create(org=org, user=user, org_role=role, employment_status=status)


class Phase03PermissionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Quality Org", slug="quality-org")
        self.owner = _user("q-owner@example.com")
        self.admin = _user("q-admin@example.com")
        self.member = _user("q-member@example.com")
        self.outsider = _user("q-out@example.com")
        _member(self.org, self.owner, OrgMembership.ORG_ROLE_OWNER)
        _member(self.org, self.admin, OrgMembership.ORG_ROLE_ADMIN)
        _member(self.org, self.member)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def _probe(self, key, as_user):
        self._auth(as_user)
        if key == "org.members.view":
            return self.client.get(f"{self.base}/members")
        if key == "org.members.manage":
            return self.client.post(f"{self.base}/members", {"email": f"{as_user.id}@invite.test"}, format="json")
        if key == "org.members.view_contact":
            return self.client.get(f"{self.base}/members")
        if key == "grants.create":
            return self.client.post(
                f"{self.base}/grants",
                {"grantee": str(self.member.id), "perm_key": "hr.view"},
                format="json",
            )
        if key == "grants.revoke":
            self._auth(self.owner)
            created = self.client.post(
                f"{self.base}/grants",
                {"grantee": str(self.member.id), "perm_key": "hr.view"},
                format="json",
            )
            grant_id = created.json()["id"]
            self._auth(as_user)
            return self.client.delete(f"{self.base}/grants/{grant_id}")
        if key == "permission_requests.create":
            return self.client.post(
                f"{self.base}/permission-requests",
                {"perm_key": "hr.view", "reason": "need"},
                format="json",
            )
        if key == "permission_requests.decide":
            req = PermissionRequest.objects.create(org=self.org, requester=self.member, perm_key="hr.view")
            return self.client.post(f"{self.base}/permission-requests/{req.id}/reject", {}, format="json")
        if key == "audit.view":
            return self.client.get(f"{self.base}/audit-events")
        if key == "org.view":
            return self.client.get(f"{self.base}/teams")
        if key == "team.view":
            return self.client.get(f"{self.base}/teams")
        if key == "team.manage":
            return self.client.post(f"{self.base}/teams", {"name": f"Team-{as_user.id}"}, format="json")
        if key == "project.view":
            return self.client.get(f"{self.base}/projects")
        if key == "project.manage":
            return self.client.post(f"{self.base}/projects", {"name": f"P-{as_user.id}"}, format="json")
        if key == "task.view":
            return self.client.get(f"{self.base}/tasks")
        if key == "task.write":
            return self.client.post(f"{self.base}/tasks", {"title": "Quality task"}, format="json")
        if key == "time.view":
            return self.client.get(f"{self.base}/timer")
        if key == "time.write":
            return self.client.post(f"{self.base}/timer/start", {"description": "probe"}, format="json")
        if key == "chat.use":
            return self.client.post(
                f"{self.base}/dms",
                {"user_id": str(self.member.id), "body": "hello"},
                format="json",
            )
        if key == "mission.view":
            return self.client.get(f"{self.base}/mission-control")
        raise AssertionError(f"no probe for {key}")

    def test_every_phase_0_to_3_key_allowed_and_denied(self):
        member_defaults = ROLE_DEFAULTS[OrgMembership.ORG_ROLE_MEMBER]
        owner_defaults = ROLE_DEFAULTS[OrgMembership.ORG_ROLE_OWNER]
        for key in PHASE_0_TO_3_API_KEYS:
            self.assertIn(key, owner_defaults)
            allowed_user = self.member if key in member_defaults else self.owner
            allowed = self._probe(key, allowed_user)
            self.assertIn(allowed.status_code, {200, 201, 204}, msg=f"{key} allowed {allowed.status_code} {allowed.content}")
            if key == "org.members.view_contact":
                row = next(r for r in allowed.json()["results"] if r["id"] == str(self.member.id))
                if allowed_user == self.owner:
                    self.assertIn("email", row)
                else:
                    self.assertNotIn("email", row)
                denied = self._probe(key, self.member)
                hidden = next(r for r in denied.json()["results"] if r["id"] == str(self.owner.id))
                self.assertNotIn("email", hidden)
                continue
            denied = self._probe(key, self.outsider)
            self.assertIn(denied.status_code, {401, 403}, msg=f"{key} outsider {denied.status_code}")
            if key not in member_defaults:
                member_denied = self._probe(key, self.member)
                self.assertEqual(member_denied.status_code, 403, msg=f"{key} member should be 403")

    def test_can_matches_role_defaults_for_every_key(self):
        for key in PHASE_0_TO_3_API_KEYS:
            self.assertTrue(can(self.owner, key, self.org))
            self.assertEqual(can(self.member, key, self.org), key in ROLE_DEFAULTS[OrgMembership.ORG_ROLE_MEMBER])
            self.assertFalse(can(self.outsider, key, self.org))


class TeamIsolationAndAssignTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Iso Org", slug="iso-org")
        self.owner = _user("iso-owner@example.com")
        self.lead = _user("iso-lead@example.com")
        self.member_a = _user("iso-a@example.com")
        self.member_b = _user("iso-b@example.com")
        self.inactive = _user("iso-inactive@example.com")
        for user, role in (
            (self.owner, OrgMembership.ORG_ROLE_OWNER),
            (self.lead, OrgMembership.ORG_ROLE_MEMBER),
            (self.member_a, OrgMembership.ORG_ROLE_MEMBER),
            (self.member_b, OrgMembership.ORG_ROLE_MEMBER),
        ):
            _member(self.org, user, role)
        _member(self.org, self.inactive, status=OrgMembership.STATUS_TERMINATED)
        self.team_a = Team.objects.create(org=self.org, name="Team A")
        self.team_b = Team.objects.create(org=self.org, name="Team B")
        TeamMembership.objects.create(team=self.team_a, user=self.lead, team_role=TeamMembership.ROLE_LEAD)
        TeamMembership.objects.create(team=self.team_a, user=self.member_a)
        TeamMembership.objects.create(team=self.team_b, user=self.member_b)
        self.task_a = Task.objects.create(org=self.org, team=self.team_a, title="A work", created_by=self.lead)
        self.task_b = Task.objects.create(org=self.org, team=self.team_b, title="B work", created_by=self.member_b)
        TimeEntry.objects.create(
            org=self.org,
            user=self.member_b,
            description="B time",
            started_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now() - timedelta(hours=1),
        )
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _auth(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def test_member_cannot_assign_others(self):
        self._auth(self.member_a)
        denied = self.client.post(
            f"{self.base}/tasks/{self.task_a.id}/assign",
            {"user_id": str(self.lead.id)},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

    def test_lead_assigns_own_team_only(self):
        self._auth(self.lead)
        ok = self.client.post(
            f"{self.base}/tasks/{self.task_a.id}/assign",
            {"user_id": str(self.member_a.id)},
            format="json",
        )
        self.assertEqual(ok.status_code, 200, ok.content)
        outside = self.client.post(
            f"{self.base}/tasks/{self.task_a.id}/assign",
            {"user_id": str(self.member_b.id)},
            format="json",
        )
        self.assertIn(outside.status_code, {403, 404})

    def test_team_a_cannot_read_team_b(self):
        self._auth(self.member_a)
        self.assertEqual(self.client.get(f"{self.base}/teams/{self.team_b.id}").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/teams/{self.team_b.id}/members").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/tasks/{self.task_b.id}").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/time-entries?team={self.team_b.id}").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/time-reports/team/{self.team_b.id}").status_code, 404)
        listed = self.client.get(f"{self.base}/tasks")
        self.assertEqual(listed.status_code, 200)
        ids = {row["id"] for row in listed.json()["results"]}
        self.assertIn(str(self.task_a.id), ids)
        self.assertNotIn(str(self.task_b.id), ids)

    def test_inactive_cannot_be_assigned_or_receive_dm(self):
        self._auth(self.owner)
        assigned = self.client.post(
            f"{self.base}/tasks/{self.task_a.id}/assign",
            {"user_id": str(self.inactive.id)},
            format="json",
        )
        self.assertEqual(assigned.status_code, 404)
        dm = self.client.post(
            f"{self.base}/dms",
            {"user_id": str(self.inactive.id), "body": "hi"},
            format="json",
        )
        self.assertEqual(dm.status_code, 404)
        self.assertFalse(can_receive_dm(self.inactive, self.org))
        self.assertTrue(can_receive_dm(self.member_a, self.org))


class SignInStatusTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Sign Org", slug="sign-org")

    def test_pending_and_inactive_cannot_sign_in(self):
        pending = _user("pending@example.com")
        inactive = _user("inactive@example.com")
        personal = _user("personal@example.com")
        _member(self.org, pending, status=OrgMembership.STATUS_PENDING)
        _member(self.org, inactive, status=OrgMembership.STATUS_TERMINATED)
        pending_res = self.client.post(
            "/api/v2/auth/signin",
            {"email": "pending@example.com", "password": "correct-horse"},
            format="json",
        )
        self.assertEqual(pending_res.status_code, 403)
        inactive_res = self.client.post(
            "/api/v2/auth/signin",
            {"email": "inactive@example.com", "password": "correct-horse"},
            format="json",
        )
        self.assertEqual(inactive_res.status_code, 403)
        personal_res = self.client.post(
            "/api/v2/auth/signin",
            {"email": "personal@example.com", "password": "correct-horse"},
            format="json",
        )
        self.assertEqual(personal_res.status_code, 200, personal_res.content)


class TimerAndReportQualityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Timer Org", slug="timer-quality")
        self.user = _user("timer-q@example.com")
        _member(self.org, self.user)
        self.token = make_access_token(str(self.user.id))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.base = f"/api/v2/orgs/{self.org.id}"

    def test_second_start_409_and_running_survives_new_client(self):
        start = self.client.post(f"{self.base}/timer/start", {"description": "deep work"}, format="json")
        self.assertEqual(start.status_code, 201, start.content)
        again = self.client.post(f"{self.base}/timer/start", {}, format="json")
        self.assertEqual(again.status_code, 409)
        other = APIClient()
        other.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        running = other.get(f"{self.base}/timer")
        self.assertEqual(running.status_code, 200)
        self.assertEqual(running.json()["running"]["id"], start.json()["id"])
        second_device = other.post(f"{self.base}/timer/start", {}, format="json")
        self.assertEqual(second_device.status_code, 409)

    def test_weekly_report_equals_sum_of_entries(self):
        now = timezone.now()
        this_week = TimeEntry.objects.create(
            org=self.org,
            user=self.user,
            description="week",
            started_at=now - timedelta(hours=3),
            ended_at=now - timedelta(hours=1),
        )
        extra = TimeEntry.objects.create(
            org=self.org,
            user=self.user,
            description="week-2",
            started_at=now - timedelta(hours=6),
            ended_at=now - timedelta(hours=5),
        )
        TimeEntry.objects.create(
            org=self.org,
            user=self.user,
            description="old",
            started_at=now - timedelta(days=20),
            ended_at=now - timedelta(days=20, hours=-2),
        )
        expected = this_week.seconds + extra.seconds
        report = self.client.get(f"{self.base}/time-reports/me?period=week")
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()["seconds"], expected)
        self.assertEqual(report.json()["entries"], 2)
        self.assertEqual(report.json()["period"], "week")


class HRWebhookHmacTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="FloLabs", slug="flolabs")
        self.client = APIClient()

    @override_settings(HR_WEBHOOK_SECRET="quality-hr-secret")
    def test_bad_hmac_rejected(self):
        body = json.dumps({"email": "hmac@example.com", "org_slug": "flolabs"})
        bad = self.client.post(
            "/api/v2/integrations/hr/applicants",
            data=body,
            content_type="application/json",
            HTTP_X_FLOBRAIN_SIGNATURE="deadbeef",
        )
        self.assertEqual(bad.status_code, 401)
        missing = self.client.post(
            "/api/v2/integrations/hr/applicants",
            data=body,
            content_type="application/json",
        )
        self.assertEqual(missing.status_code, 401)
        sig = hmac.new(b"quality-hr-secret", body.encode(), hashlib.sha256).hexdigest()
        ok = self.client.post(
            "/api/v2/integrations/hr/applicants",
            data=body,
            content_type="application/json",
            HTTP_X_FLOBRAIN_SIGNATURE=sig,
        )
        self.assertEqual(ok.status_code, 201, ok.content)
