"""Directory filters, member status/role rules, teams and projects admin, grants and requests, audit filters."""

from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import Notification
from organizations.models import (
    AuditEvent,
    MemberSkill,
    OrgMembership,
    Organization,
    PermissionGrant,
    PermissionRequest,
    Project,
    ProjectMembership,
    SkillTag,
    Team,
    TeamMembership,
)
from organizations.permissions.engine import can
from users.jwt_utils import make_access_token
from users.models import User


def _user(email, name=None):
    return User.objects.create(email=email, username=name or email.split("@")[0], password_hash=make_password("x"))


def _member(org, user, role=OrgMembership.ORG_ROLE_MEMBER, status=OrgMembership.STATUS_ACTIVE):
    return OrgMembership.objects.create(org=org, user=user, org_role=role, employment_status=status)


class Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="People Org", slug="people-org")
        self.other = Organization.objects.create(name="Other Org", slug="other-people-org")
        self.owner = _user("pa-owner@example.com", "Zed Owner")
        self.admin = _user("pa-admin@example.com", "Amal Admin")
        self.lead = _user("pa-lead@example.com", "Layla Lead")
        self.member = _user("pa-member@example.com", "Mona Member")
        self.peer = _user("pa-peer@example.com", "Badr Peer")
        self.outsider = _user("pa-out@example.com", "Omar Outsider")
        _member(self.org, self.owner, OrgMembership.ORG_ROLE_OWNER)
        _member(self.org, self.admin, OrgMembership.ORG_ROLE_ADMIN)
        _member(self.org, self.lead)
        _member(self.org, self.member)
        _member(self.org, self.peer, status=OrgMembership.STATUS_PAUSED)
        _member(self.other, self.outsider)
        self.team = Team.objects.create(org=self.org, name="Engineering")
        self.design = Team.objects.create(org=self.org, name="Design")
        self.other_team = Team.objects.create(org=self.other, name="Elsewhere")
        TeamMembership.objects.create(team=self.team, user=self.lead, team_role=TeamMembership.ROLE_LEAD)
        TeamMembership.objects.create(team=self.team, user=self.member)
        TeamMembership.objects.create(team=self.design, user=self.peer)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def as_(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return self.client


class DirectoryFilterTests(Base):
    def ids(self, res):
        self.assertEqual(res.status_code, 200, res.content)
        return {row["id"] for row in res.json()["results"]}

    def test_filters_and_ordering(self):
        c = self.as_(self.member)
        everyone = c.get(f"{self.base}/members")
        names = [r["username"] for r in everyone.json()["results"]]
        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertEqual(self.ids(c.get(f"{self.base}/members?team={self.team.id}")), {str(self.lead.id), str(self.member.id)})
        self.assertEqual(self.ids(c.get(f"{self.base}/members?role=lead")), {str(self.lead.id)})
        self.assertEqual(self.ids(c.get(f"{self.base}/members?role=admin")), {str(self.admin.id)})
        self.assertEqual(self.ids(c.get(f"{self.base}/members?status=inactive")), {str(self.peer.id)})
        self.assertNotIn(str(self.peer.id), self.ids(c.get(f"{self.base}/members?status=active")))
        skill = SkillTag.objects.create(org=self.org, name="Python")
        MemberSkill.objects.create(org=self.org, user=self.member, skill=skill)
        self.assertEqual(self.ids(c.get(f"{self.base}/members?skill=python")), {str(self.member.id)})
        self.assertEqual(self.ids(c.get(f"{self.base}/members?q=mona")), {str(self.member.id)})

    def test_members_cannot_search_by_email(self):
        self.assertEqual(self.ids(self.as_(self.member).get(f"{self.base}/members?q=pa-admin@")), set())
        self.assertEqual(self.ids(self.as_(self.admin).get(f"{self.base}/members?q=pa-admin@")), {str(self.admin.id)})

    def test_bad_filters_are_400(self):
        c = self.as_(self.member)
        for query in ("status=sleeping", "team=not-a-uuid", "role=boss", "ordering=email"):
            self.assertEqual(c.get(f"{self.base}/members?{query}").status_code, 400, query)

    def test_pending_only_for_managers(self):
        pending = _user("pa-pending@example.com")
        _member(self.org, pending, status=OrgMembership.STATUS_PENDING)
        self.assertEqual(self.as_(self.member).get(f"{self.base}/members?status=pending").status_code, 403)
        self.assertEqual(self.ids(self.as_(self.admin).get(f"{self.base}/members?status=pending")), {str(pending.id)})
        self.assertNotIn(str(pending.id), self.ids(self.as_(self.admin).get(f"{self.base}/members")))

    def test_profile_has_teams_projects_and_rights(self):
        project = Project.objects.create(org=self.org, name="Launch")
        ProjectMembership.objects.create(project=project, user=self.member)
        res = self.as_(self.lead).get(f"{self.base}/members/{self.member.id}")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual([t["name"] for t in body["team_roles"]], ["Engineering"])
        self.assertTrue(body["can"]["change_status"])
        self.assertFalse(body["can"]["change_role"])
        self.assertTrue(body["can"]["confirm_skills"])
        # The lead is not on the project, so it is not shown to them.
        self.assertEqual(body["projects"], [])
        self.assertEqual([p["name"] for p in self.as_(self.admin).get(f"{self.base}/members/{self.member.id}").json()["projects"]], ["Launch"])

    def test_other_org_member_is_404(self):
        self.assertEqual(self.as_(self.admin).get(f"{self.base}/members/{self.outsider.id}").status_code, 404)
        self.assertEqual(self.as_(self.outsider).get(f"{self.base}/members").status_code, 403)


class RegisterAndStatusTests(Base):
    def test_admin_registers_into_team_and_activates(self):
        res = self.as_(self.admin).post(
            f"{self.base}/members",
            {"email": "New.Person@Example.com", "username": "New Person", "team_id": str(self.team.id), "activate": True},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["employment_status"], "active")
        user = User.objects.get(email="new.person@example.com")
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=user).exists())
        again = self.as_(self.admin).post(f"{self.base}/members", {"email": "new.person@example.com"}, format="json")
        self.assertEqual(again.status_code, 409)

    def test_lead_registers_only_into_own_team_as_member(self):
        c = self.as_(self.lead)
        ok = c.post(f"{self.base}/members", {"email": "intern@example.com", "team_id": str(self.team.id)}, format="json")
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(c.post(f"{self.base}/members", {"email": "x1@example.com", "team_id": str(self.design.id)}, format="json").status_code, 403)
        self.assertEqual(c.post(f"{self.base}/members", {"email": "x2@example.com"}, format="json").status_code, 403)
        self.assertEqual(
            c.post(f"{self.base}/members", {"email": "x3@example.com", "team_id": str(self.team.id), "org_role": "admin"}, format="json").status_code,
            403,
        )
        self.assertEqual(
            c.post(f"{self.base}/members", {"email": "x4@example.com", "team_id": str(self.team.id), "team_role": "lead"}, format="json").status_code,
            403,
        )

    def test_register_bad_input(self):
        c = self.as_(self.admin)
        self.assertEqual(c.post(f"{self.base}/members", {"email": "not-an-email"}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/members", {"email": "a@example.com", "org_role": "owner"}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/members", {"email": "b@example.com", "team_id": str(self.other_team.id)}, format="json").status_code, 400)
        self.assertEqual(self.as_(self.member).post(f"{self.base}/members", {"email": "c@example.com"}, format="json").status_code, 403)

    def test_lead_changes_status_of_own_team_member_only(self):
        c = self.as_(self.lead)
        ok = c.patch(f"{self.base}/members/{self.member.id}", {"employment_status": "paused", "reason": "Exams"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="member.status", actor=self.lead).exists())
        self.assertEqual(c.patch(f"{self.base}/members/{self.peer.id}", {"employment_status": "active"}, format="json").status_code, 403)
        self.assertEqual(c.patch(f"{self.base}/members/{self.member.id}", {"org_role": "admin"}, format="json").status_code, 403)
        self.assertEqual(self.as_(self.member).patch(f"{self.base}/members/{self.lead.id}", {"employment_status": "paused"}, format="json").status_code, 403)

    def test_lead_cannot_pull_someone_from_another_team_to_gain_power_over_them(self):
        """Review finding 1: adding Badr (Design) to Layla's team would let her terminate him."""
        OrgMembership.objects.filter(org=self.org, user=self.peer).update(employment_status=OrgMembership.STATUS_ACTIVE)
        c = self.as_(self.lead)
        moved = c.post(f"{self.base}/teams/{self.team.id}/members", {"user_id": str(self.peer.id)}, format="json")
        self.assertEqual(moved.status_code, 403, moved.content)
        self.assertEqual(c.patch(f"{self.base}/members/{self.peer.id}", {"employment_status": "terminated"}, format="json").status_code, 403)
        newcomer = _user("pa-new@example.com", "Nour New")
        OrgMembership.objects.create(org=self.org, user=newcomer, org_role="member", employment_status="active")
        self.assertEqual(c.post(f"{self.base}/teams/{self.team.id}/members", {"user_id": str(newcomer.id)}, format="json").status_code, 201)
        self.assertEqual(self.as_(self.admin).post(f"{self.base}/teams/{self.team.id}/members", {"user_id": str(self.peer.id)}, format="json").status_code, 201)

    def test_role_rules(self):
        c = self.as_(self.admin)
        res = c.patch(f"{self.base}/members/{self.member.id}", {"org_role": "admin"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="member.role").exists())
        self.assertEqual(c.patch(f"{self.base}/members/{self.owner.id}", {"org_role": "member"}, format="json").status_code, 403)
        self.assertEqual(c.patch(f"{self.base}/members/{self.owner.id}", {"employment_status": "paused"}, format="json").status_code, 403)
        self.assertEqual(c.patch(f"{self.base}/members/{self.lead.id}", {"org_role": "owner"}, format="json").status_code, 400)
        self.assertEqual(c.patch(f"{self.base}/members/{self.admin.id}", {"employment_status": "paused"}, format="json").status_code, 403)
        self.assertEqual(c.patch(f"{self.base}/members/{self.lead.id}", {"employment_status": "sleeping"}, format="json").status_code, 400)
        self.assertEqual(c.patch(f"{self.base}/members/{self.lead.id}", {"employment_status": "pending"}, format="json").status_code, 400)
        self.assertEqual(c.patch(f"{self.base}/members/{self.outsider.id}", {"employment_status": "paused"}, format="json").status_code, 404)


class TeamProjectAdminTests(Base):
    def test_admin_creates_edits_archives_team(self):
        c = self.as_(self.admin)
        res = c.post(f"{self.base}/teams", {"name": "  Data  ", "description": "Numbers", "lead_id": str(self.member.id)}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        team_id = res.json()["id"]
        self.assertEqual(res.json()["leads"][0]["id"], str(self.member.id))
        self.assertEqual(c.post(f"{self.base}/teams", {"name": "data"}, format="json").status_code, 409)
        self.assertEqual(c.post(f"{self.base}/teams", {"name": ""}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/teams", {"name": "X", "lead_id": str(self.outsider.id)}, format="json").status_code, 400)
        archived = c.patch(f"{self.base}/teams/{team_id}", {"is_active": False}, format="json")
        self.assertEqual(archived.status_code, 200)
        self.assertFalse(archived.json()["is_active"])
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="team.archive").exists())

    def test_lead_edits_details_but_not_archive_or_other_team(self):
        c = self.as_(self.lead)
        self.assertEqual(c.patch(f"{self.base}/teams/{self.team.id}", {"description": "We build"}, format="json").status_code, 200)
        self.assertEqual(c.patch(f"{self.base}/teams/{self.team.id}", {"is_active": False}, format="json").status_code, 403)
        self.assertEqual(c.patch(f"{self.base}/teams/{self.design.id}", {"name": "Mine"}, format="json").status_code, 403)
        self.assertEqual(c.post(f"{self.base}/teams", {"name": "New"}, format="json").status_code, 403)
        self.assertEqual(self.as_(self.admin).patch(f"{self.base}/teams/{self.other_team.id}", {"name": "x"}, format="json").status_code, 404)

    def test_team_members_and_targets(self):
        c = self.as_(self.lead)
        added = c.post(f"{self.base}/teams/{self.team.id}/members", {"user_id": str(self.admin.id), "weekly_target_hours": "20"}, format="json")
        self.assertEqual(added.status_code, 201, added.content)
        self.assertEqual(c.post(f"{self.base}/teams/{self.team.id}/members", {"user_id": str(self.admin.id)}, format="json").status_code, 409)
        self.assertEqual(c.post(f"{self.base}/teams/{self.team.id}/members", {"user_id": str(self.outsider.id)}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/teams/{self.team.id}/members", {"user_id": str(self.peer.id)}, format="json").status_code, 400)
        url = f"{self.base}/teams/{self.team.id}/members/{self.member.id}"
        self.assertEqual(c.patch(url, {"weekly_target_hours": 25, "weekly_task_target": 4}, format="json").status_code, 200)
        self.assertEqual(c.patch(url, {"weekly_target_hours": 500}, format="json").status_code, 400)
        self.assertEqual(c.patch(url, {"weekly_task_target": "four"}, format="json").status_code, 400)
        self.assertEqual(c.patch(url, {"team_role": "lead"}, format="json").status_code, 403)
        promoted = self.as_(self.admin).patch(url, {"team_role": "lead"}, format="json")
        self.assertEqual(promoted.status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.user_type, "company_lead")
        self.assertEqual(self.as_(self.lead).delete(url).status_code, 403)  # now a lead
        self.assertEqual(self.as_(self.admin).delete(url).status_code, 204)
        self.assertFalse(TeamMembership.objects.filter(team=self.team, user=self.member).exists())
        self.assertEqual(self.as_(self.member).post(f"{self.base}/teams/{self.design.id}/members", {"user_id": str(self.member.id)}, format="json").status_code, 403)

    def test_projects_admin(self):
        c = self.as_(self.admin)
        res = c.post(
            f"{self.base}/projects",
            {"name": "Launch", "lead_id": str(self.lead.id), "team_ids": [str(self.team.id)], "starts_on": "2026-10-01", "due_on": "2026-12-01"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        pid = res.json()["id"]
        self.assertEqual(res.json()["teams"][0]["name"], "Engineering")
        self.assertEqual(c.post(f"{self.base}/projects", {"name": "Bad", "lead_id": str(self.outsider.id)}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/projects", {"name": "Bad", "team_ids": [str(self.other_team.id)]}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/projects", {"name": "Bad", "starts_on": "2026-10-10", "due_on": "2026-10-01"}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/projects", {"name": "Bad", "due_on": "soon"}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/projects", {}, format="json").status_code, 400)
        lead = self.as_(self.lead)
        self.assertEqual(lead.patch(f"{self.base}/projects/{pid}", {"description": "Ship it"}, format="json").status_code, 200)
        self.assertEqual(lead.patch(f"{self.base}/projects/{pid}", {"status": "archived"}, format="json").status_code, 403)
        self.assertEqual(lead.post(f"{self.base}/projects/{pid}/members", {"user_id": str(self.admin.id)}, format="json").status_code, 201)
        self.assertEqual(lead.post(f"{self.base}/projects/{pid}/members", {"user_id": str(self.admin.id)}, format="json").status_code, 409)
        self.assertEqual(lead.delete(f"{self.base}/projects/{pid}/members/{self.admin.id}").status_code, 204)
        self.assertEqual(self.as_(self.member).patch(f"{self.base}/projects/{pid}", {"name": "Mine"}, format="json").status_code, 403)
        c = self.as_(self.admin)
        archived = c.patch(f"{self.base}/projects/{pid}", {"status": "archived"}, format="json")
        self.assertEqual(archived.json()["status"], "archived")
        self.assertEqual(c.patch(f"{self.base}/projects/{pid}", {"status": "gone"}, format="json").status_code, 400)
        other_project = Project.objects.create(org=self.other, name="Theirs")
        self.assertEqual(c.patch(f"{self.base}/projects/{other_project.id}", {"name": "x"}, format="json").status_code, 404)


class GrantAndRequestTests(Base):
    def test_grant_with_expiry_and_scope(self):
        c = self.as_(self.admin)
        res = c.post(
            f"{self.base}/grants",
            {"grantee": str(self.member.id), "perm_key": "team.manage", "scope_type": "team", "scope_id": str(self.team.id), "expires_in_days": 7},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertTrue(body["active"])
        self.assertEqual(body["scope_name"], "Engineering")
        grant = PermissionGrant.objects.get(pk=body["id"])
        self.assertAlmostEqual((grant.expires_at - timezone.now()).total_seconds(), 7 * 86400, delta=60)
        self.assertTrue(can(self.member, "team.manage", self.team))
        self.assertFalse(can(self.member, "team.manage", self.design))
        self.assertTrue(Notification.objects.filter(user=self.member, kind="access.granted").exists())
        self.assertEqual(c.post(f"{self.base}/grants", {"grantee": str(self.member.id), "perm_key": "task.view"}, format="json").status_code, 409)

    def test_grant_bad_input_and_rules(self):
        c = self.as_(self.admin)
        post = lambda **kw: c.post(f"{self.base}/grants", {"grantee": str(self.member.id), "perm_key": "hr.view", **kw}, format="json")
        self.assertEqual(post(expires_in_days=0).status_code, 400)
        self.assertEqual(post(expires_in_days=400).status_code, 400)
        self.assertEqual(post(expires_at="2001-01-01T00:00:00Z").status_code, 400)
        self.assertEqual(post(scope_type="team").status_code, 400)
        self.assertEqual(post(scope_type="team", scope_id=str(self.other_team.id)).status_code, 400)
        self.assertEqual(post(scope_type="room").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/grants", {"grantee": str(self.outsider.id), "perm_key": "hr.view"}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/grants", {"grantee": str(self.admin.id), "perm_key": "hr.view"}, format="json").status_code, 400)
        # An admin does not hold payroll keys, so cannot hand them out.
        self.assertEqual(c.post(f"{self.base}/grants", {"grantee": str(self.member.id), "perm_key": "payroll.view"}, format="json").status_code, 403)
        expires = (timezone.now() + timedelta(days=3)).isoformat()
        self.assertEqual(post(expires_at=expires).status_code, 201)

    def test_members_see_only_their_own_grants_and_requests(self):
        PermissionGrant.objects.create(org=self.org, grantee=self.lead, perm_key="hr.view", granted_by=self.admin)
        mine = PermissionGrant.objects.create(org=self.org, grantee=self.member, perm_key="hr.view", granted_by=self.admin)
        PermissionRequest.objects.create(org=self.org, requester=self.lead, perm_key="audit.view")
        res = self.as_(self.member).get(f"{self.base}/grants")
        self.assertEqual([r["id"] for r in res.json()["results"]], [str(mine.id)])
        self.assertEqual(self.as_(self.member).get(f"{self.base}/permission-requests").json()["count"], 0)
        self.assertEqual(self.as_(self.admin).get(f"{self.base}/grants").json()["count"], 2)
        self.assertEqual(self.as_(self.admin).get(f"{self.base}/permission-requests").json()["count"], 1)

    def test_request_flow(self):
        c = self.as_(self.member)
        made = c.post(f"{self.base}/permission-requests", {"perm_key": "audit.view", "reason": "Checking a change"}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        self.assertEqual(made.json()["label"], "View audit events")
        self.assertTrue(Notification.objects.filter(user=self.admin, kind="access.requested").exists())
        self.assertEqual(c.post(f"{self.base}/permission-requests", {"perm_key": "audit.view"}, format="json").status_code, 409)
        self.assertEqual(c.post(f"{self.base}/permission-requests", {"perm_key": "task.view"}, format="json").status_code, 409)
        self.assertEqual(c.post(f"{self.base}/permission-requests", {"perm_key": "nope"}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/permission-requests", {"perm_key": "hr.view", "scope_type": "project"}, format="json").status_code, 400)
        rid = made.json()["id"]
        self.assertEqual(c.post(f"{self.base}/permission-requests/{rid}/approve", {}, format="json").status_code, 403)
        self.assertEqual(self.as_(self.admin).post(f"{self.base}/permission-requests/{rid}/maybe", {}, format="json").status_code, 404)
        approved = self.as_(self.admin).post(f"{self.base}/permission-requests/{rid}/approve", {"expires_in_days": 7}, format="json")
        self.assertEqual(approved.status_code, 200, approved.content)
        self.assertEqual(approved.json()["status"], "approved")
        grant = PermissionGrant.objects.get(grantee=self.member, perm_key="audit.view")
        self.assertIsNotNone(grant.expires_at)
        self.assertTrue(Notification.objects.filter(user=self.member, kind="access.decided").exists())
        self.assertEqual(self.as_(self.admin).post(f"{self.base}/permission-requests/{rid}/reject", {}, format="json").status_code, 409)

    def test_decider_must_hold_the_permission_and_not_be_requester(self):
        req = PermissionRequest.objects.create(org=self.org, requester=self.member, perm_key="payroll.view")
        self.assertEqual(self.as_(self.admin).post(f"{self.base}/permission-requests/{req.id}/approve", {}, format="json").status_code, 403)
        self.assertEqual(self.as_(self.owner).post(f"{self.base}/permission-requests/{req.id}/approve", {}, format="json").status_code, 200)
        own = PermissionRequest.objects.create(org=self.org, requester=self.admin, perm_key="payroll.view")
        self.assertEqual(self.as_(self.admin).post(f"{self.base}/permission-requests/{own.id}/approve", {}, format="json").status_code, 403)

    def test_other_org_request_is_404(self):
        foreign = PermissionRequest.objects.create(org=self.other, requester=self.outsider, perm_key="hr.view")
        self.assertEqual(self.as_(self.admin).post(f"{self.base}/permission-requests/{foreign.id}/approve", {}, format="json").status_code, 404)


class AuditFilterTests(Base):
    def setUp(self):
        super().setUp()
        AuditEvent.objects.create(org=self.org, actor=self.admin, action="perm.grant")
        AuditEvent.objects.create(org=self.org, actor=self.lead, action="member.status")
        old = AuditEvent.objects.create(org=self.org, actor=self.admin, action="team.create")
        AuditEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=10))
        AuditEvent.objects.create(org=self.other, actor=self.outsider, action="perm.grant")

    def test_filters(self):
        c = self.as_(self.owner)
        url = f"{self.base}/audit-events"
        self.assertEqual(c.get(url).json()["count"], 3)
        self.assertEqual(c.get(f"{url}?actor={self.admin.id}").json()["count"], 2)
        rows = c.get(f"{url}?action=perm").json()["results"]
        self.assertEqual([r["action"] for r in rows], ["perm.grant"])
        self.assertEqual(rows[0]["actor_user"]["username"], "Amal Admin")
        since = (timezone.now() - timedelta(days=2)).date().isoformat()
        self.assertEqual(c.get(f"{url}?since={since}").json()["count"], 2)
        self.assertEqual(c.get(f"{url}?until={since}").json()["count"], 1)
        self.assertEqual(c.get(f"{url}?since=yesterday").status_code, 400)
        self.assertEqual(c.get(f"{url}?actor=bob").status_code, 400)
        self.assertEqual(set(c.get(f"{url}/actions").json()), {"perm.grant", "member.status", "team.create"})

    def test_needs_audit_view(self):
        self.assertEqual(self.as_(self.member).get(f"{self.base}/audit-events").status_code, 403)
        self.assertEqual(self.as_(self.member).get(f"{self.base}/audit-events/actions").status_code, 403)
        PermissionGrant.objects.create(org=self.org, grantee=self.member, perm_key="audit.view", granted_by=self.owner)
        self.assertEqual(self.as_(self.member).get(f"{self.base}/audit-events").status_code, 200)


class DemoPeopleSeedTests(TestCase):
    def test_seed_twice_is_clean(self):
        from django.test import override_settings

        from demo.seed import reset
        from organizations.models import HRApplicant
        from telemetry.models import FeedbackItem

        with override_settings(DEMO_MODE=True):
            reset()
            reset()
        org = Organization.objects.get(slug="demo")
        self.assertEqual(OrgMembership.objects.filter(org=org, employment_status="pending").count(), 2)
        self.assertEqual(HRApplicant.objects.filter(org=org).count(), 2)
        self.assertTrue(PermissionGrant.objects.filter(org=org, expires_at__lte=timezone.now() + timedelta(days=2)).exists())
        self.assertEqual(PermissionRequest.objects.filter(org=org, status="pending").count(), 2)
        self.assertEqual(FeedbackItem.objects.filter(org=org).count(), 3)
        self.assertTrue(User.objects.filter(email="member@demo.flobrain.example", phone__startswith="+20").exists())
