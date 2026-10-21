from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import AuditEvent, OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


class CommissionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="C", slug="c-org", settings={"flags": {"commissions": True}})
        self.users = {}
        for name, role in (("admin", "admin"), ("ana", "member"), ("ben", "member")):
            u = User.objects.create(email=f"{name}@c.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            self.users[name] = u
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _as(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return c

    def test_pipeline_and_money_rules(self):
        ana = self._as("ana")
        self.assertEqual(ana.post(f"{self.base}/leads", {"project_or_product": "App", "contact_name": "X", "contact_email": "bad"}, format="json").status_code, 400)
        lead = ana.post(f"{self.base}/leads", {"project_or_product": "App", "contact_name": "Acme", "estimated_value": "5000"}, format="json").json()
        self.assertEqual(self._as("ben").get(f"{self.base}/leads").json(), [], "others' leads are hidden")
        self.assertEqual(self._as("ben").patch(f"{self.base}/leads/{lead['id']}", {"stage": "won"}, format="json").status_code, 404)
        self.assertEqual(ana.patch(f"{self.base}/leads/{lead['id']}", {"stage": "won"}, format="json").json()["stage"], "won")
        self.assertEqual(ana.post(f"{self.base}/commissions", {"lead": lead["id"], "amount": "500"}, format="json").status_code, 403)
        admin = self._as("admin")
        for bad in ("-5", "NaN", "Infinity", "1e99", "abc"):
            self.assertEqual(admin.post(f"{self.base}/commissions", {"lead": lead["id"], "amount": bad}, format="json").status_code, 400, bad)
        c = admin.post(f"{self.base}/commissions", {"lead": lead["id"], "amount": "500", "currency": "egp"}, format="json").json()
        self.assertEqual((c["user"]["name"], c["currency"]), ("ana", "EGP"))
        self.assertEqual(ana.patch(f"{self.base}/commissions/{c['id']}", {"status": "paid"}, format="json").status_code, 403)
        admin.patch(f"{self.base}/commissions/{c['id']}", {"status": "approved", "amount": "450"}, format="json")
        event = AuditEvent.objects.filter(org=self.org, action="commission.update").first()
        self.assertEqual(event.payload["before"], {"amount": "500.00", "status": "pending"})
        summary = ana.get(f"{self.base}/commissions/summary").json()
        self.assertEqual((summary["earned"], summary["referrals_sent"], summary["conversion_rate"]), ("450.00 EGP", 1, 1.0))
        self.assertEqual(self._as("ben").get(f"{self.base}/commissions").json(), [])

    def test_member_flag_switches_it_off_per_person(self):
        OrgMembership.objects.filter(org=self.org, user=self.users["ben"]).update(feature_flags={"commissions": False})
        self.assertEqual(self._as("ben").get(f"{self.base}/leads").status_code, 501)
        self.assertEqual(self._as("ana").get(f"{self.base}/leads").status_code, 200)

    def test_review_deleting_people_works_and_no_self_approval(self):
        from commissions.models import Commission, Lead

        admin = self._as("admin")
        own = Lead.objects.create(org=self.org, owner_user=self.users["admin"], project_or_product="X", contact_name="Y")
        self.assertEqual(admin.post(f"{self.base}/commissions", {"lead": str(own.id), "amount": "10"}, format="json").status_code, 403)
        lead = Lead.objects.create(org=self.org, owner_user=self.users["ana"], project_or_product="X", contact_name="Y")
        self.assertEqual(admin.post(f"{self.base}/commissions", {"lead": str(lead.id), "amount": "10", "currency": "USD\n"}, format="json").status_code, 400)
        Commission.objects.create(org=self.org, lead=lead, user=self.users["ana"], amount=10)
        self.users["ana"].delete()  # was a 500 (ProtectedError)
        self.org.delete()
