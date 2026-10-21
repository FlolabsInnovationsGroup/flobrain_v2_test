import hashlib
import hmac
import json

from django.contrib.auth.hashers import check_password, make_password
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from organizations.models import AuditEvent, OrgMembership, Organization, Team, TeamMembership
from users.jwt_utils import make_access_token
from users.models import User


def _user(email):
    return User.objects.create(email=email, username=email.split("@")[0], password_hash=make_password("x"))


@override_settings(HR_WEBHOOK_SECRET="hr-secret")
class PendingMemberTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="HR Org", slug="hr-org")
        self.other = Organization.objects.create(name="Other HR", slug="other-hr")
        self.admin = _user("hr-admin@example.com")
        self.lead = _user("hr-lead@example.com")
        self.member = _user("hr-member@example.com")
        OrgMembership.objects.create(org=self.org, user=self.admin, org_role="admin", employment_status="active")
        OrgMembership.objects.create(org=self.org, user=self.lead, employment_status="active")
        OrgMembership.objects.create(org=self.org, user=self.member, employment_status="active")
        self.team = Team.objects.create(org=self.org, name="Engineering")
        self.design = Team.objects.create(org=self.org, name="Design")
        self.foreign_team = Team.objects.create(org=self.other, name="Theirs")
        TeamMembership.objects.create(team=self.team, user=self.lead, team_role="lead")
        self.base = f"/api/v2/orgs/{self.org.id}/pending-members"
        body = json.dumps({"email": "applicant@example.com", "full_name": "Ada Applicant", "org_slug": "hr-org", "reference": "n8n-42"})
        sig = hmac.new(b"hr-secret", body.encode(), hashlib.sha256).hexdigest()
        res = self.client.post("/api/v2/integrations/hr/applicants", data=body, content_type="application/json", HTTP_X_FLOBRAIN_SIGNATURE=sig)
        self.assertEqual(res.status_code, 201, res.content)
        self.applicant = User.objects.get(email="applicant@example.com")
        mail.outbox.clear()

    def as_(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return self.client

    def test_list_shows_hr_source_to_admins_and_leads(self):
        rows = self.as_(self.admin).get(self.base).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["full_name"], "Ada Applicant")
        self.assertEqual(rows[0]["source"], "hr_webhook")
        self.assertEqual(rows[0]["email"], "applicant@example.com")
        lead_rows = self.as_(self.lead).get(self.base).json()
        self.assertNotIn("email", lead_rows[0])
        self.assertEqual(self.as_(self.member).get(self.base).status_code, 403)

    def test_lead_confirms_into_own_team_only(self):
        url = f"{self.base}/{self.applicant.id}/confirm"
        self.assertEqual(self.as_(self.lead).post(url, {"team_id": str(self.design.id)}, format="json").status_code, 403)
        self.assertEqual(self.as_(self.lead).post(url, {}, format="json").status_code, 400)
        self.assertEqual(self.as_(self.lead).post(url, {"team_id": str(self.foreign_team.id)}, format="json").status_code, 400)
        ok = self.as_(self.lead).post(url, {"team_id": str(self.team.id)}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        membership = OrgMembership.objects.get(org=self.org, user=self.applicant)
        self.assertEqual(membership.employment_status, "active")
        self.assertTrue(TeamMembership.objects.filter(team=self.team, user=self.applicant, team_role="member").exists())
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="member.confirm").exists())
        self.assertEqual(len(mail.outbox), 1)
        self.applicant.refresh_from_db()
        self.assertFalse(check_password("x", self.applicant.password_hash))
        # Not pending any more.
        self.assertEqual(self.as_(self.lead).post(url, {"team_id": str(self.team.id)}, format="json").status_code, 404)

    def test_decline_is_admin_only(self):
        url = f"{self.base}/{self.applicant.id}/decline"
        self.assertEqual(self.as_(self.lead).post(url, {}, format="json").status_code, 403)
        ok = self.as_(self.admin).post(url, {"reason": "Position filled"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(OrgMembership.objects.get(org=self.org, user=self.applicant).employment_status, "terminated")
        self.assertEqual(self.as_(self.admin).post(f"{self.base}/{self.applicant.id}/maybe", {}, format="json").status_code, 404)

    def test_other_org_cannot_see_or_confirm(self):
        outsider = _user("hr-out@example.com")
        OrgMembership.objects.create(org=self.other, user=outsider, org_role="admin", employment_status="active")
        self.assertEqual(self.as_(outsider).get(self.base).status_code, 403)
        self.assertEqual(
            self.as_(outsider).post(f"/api/v2/orgs/{self.other.id}/pending-members/{self.applicant.id}/confirm", {"team_id": str(self.foreign_team.id)}, format="json").status_code,
            404,
        )
