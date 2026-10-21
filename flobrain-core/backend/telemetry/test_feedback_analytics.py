from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from organizations.models import AuditEvent, OrgMembership, Organization
from privacy.models import PrivacySettings
from telemetry.models import FeedbackItem, ProductEvent
from users.jwt_utils import make_access_token
from users.models import User


def _user(email):
    return User.objects.create(email=email, username=email.split("@")[0], password_hash=make_password("x"))


class FeedbackInboxTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Fb Org", slug="fb-org")
        self.other = Organization.objects.create(name="Fb Other", slug="fb-other")
        self.admin = _user("fb-admin@example.com")
        self.member = _user("fb-member@example.com")
        self.peer = _user("fb-peer@example.com")
        OrgMembership.objects.create(org=self.org, user=self.admin, org_role="admin", employment_status="active")
        OrgMembership.objects.create(org=self.org, user=self.member, employment_status="active")
        OrgMembership.objects.create(org=self.org, user=self.peer, employment_status="active")
        self.base = f"/api/v2/orgs/{self.org.id}"

    def as_(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return self.client

    def test_report_with_details_then_triage(self):
        c = self.as_(self.member)
        res = c.post(
            f"{self.base}/feedback",
            {"kind": "bug", "text": "Save does nothing", "page": "/w/fb-org/tasks?x=1#top", "browser": "Firefox 140", "screenshot_note": "The save button stays grey"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        item = FeedbackItem.objects.get(pk=res.json()["id"])
        self.assertEqual(item.page, "/w/fb-org/tasks")
        self.assertEqual(item.screenshot_note, "The save button stays grey")
        self.as_(self.peer).post(f"{self.base}/feedback", {"kind": "idea", "text": "Dark mode"}, format="json")
        mine = self.as_(self.member).get(f"{self.base}/feedback").json()
        self.assertEqual([r["text"] for r in mine["results"]], ["Save does nothing"])
        inbox = self.as_(self.admin).get(f"{self.base}/admin/feedback").json()
        self.assertEqual(inbox["count"], 2)
        self.assertEqual(self.as_(self.admin).get(f"{self.base}/admin/feedback?kind=bug").json()["results"][0]["user"]["username"], "fb-member")
        url = f"{self.base}/admin/feedback/{item.id}"
        self.assertEqual(self.as_(self.member).patch(url, {"status": "closed"}, format="json").status_code, 403)
        self.assertEqual(self.as_(self.admin).patch(url, {"status": "done"}, format="json").status_code, 400)
        ok = self.as_(self.admin).patch(url, {"status": "triaged"}, format="json")
        self.assertEqual(ok.json()["status"], "triaged")
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="feedback.status").exists())
        self.assertEqual(self.as_(self.admin).get(f"{self.base}/admin/feedback?status=triaged").json()["count"], 1)
        self.assertEqual(self.as_(self.admin).get(f"{self.base}/admin/feedback?status=nope").status_code, 400)

    def test_bad_feedback_is_400_and_other_org_is_404(self):
        c = self.as_(self.member)
        self.assertEqual(c.post(f"{self.base}/feedback", {"kind": "rant", "text": "x"}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/feedback", {"kind": "bug", "text": "x" * 4001}, format="json").status_code, 400)
        foreign = FeedbackItem.objects.create(org=self.other, page="/", kind="bug", text="theirs")
        self.assertEqual(self.as_(self.admin).patch(f"{self.base}/admin/feedback/{foreign.id}", {"status": "closed"}, format="json").status_code, 404)


class EventAndAnalyticsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="An Org", slug="an-org")
        self.owner = _user("an-owner@example.com")
        OrgMembership.objects.create(org=self.org, user=self.owner, org_role="owner", employment_status="active")
        self.people = []
        for i in range(6):
            u = _user(f"an-{i}@example.com")
            OrgMembership.objects.create(org=self.org, user=u, employment_status="active")
            self.people.append(u)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def as_(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return self.client

    def test_batch_and_consent(self):
        c = self.as_(self.people[0])
        res = c.post(
            f"{self.base}/events",
            {"events": [{"name": "page.viewed", "properties": {"page": "/tasks"}}, {"name": "feature.used", "properties": {"feature": "timer", "text": "x"}}]},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["recorded"], 2)
        self.assertNotIn("text", ProductEvent.objects.get(name="feature.used").properties)
        self.assertEqual(c.post(f"{self.base}/events", {"events": []}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/events", {"events": [{"name": "page.viewed"}] * 21}, format="json").status_code, 400)
        self.assertEqual(c.post(f"{self.base}/events", {"events": [{"name": "secret.read"}]}, format="json").status_code, 400)
        PrivacySettings.objects.create(org=self.org, user=self.people[0], consents={"product_analytics": False})
        off = c.post(f"{self.base}/events", {"events": [{"name": "page.viewed", "properties": {"page": "/home"}}]}, format="json")
        self.assertEqual(off.status_code, 202)
        self.assertEqual(ProductEvent.objects.count(), 2)

    def test_analytics_hides_small_cells_and_personal_only(self):
        for u in self.people[:5]:
            ProductEvent.objects.create(org=self.org, user=u, name="page.viewed", properties={"page": "/tasks"})
        for u in self.people[:2]:
            ProductEvent.objects.create(org=self.org, user=u, name="page.viewed", properties={"page": "/rare"})
        res = self.as_(self.owner).get(f"{self.base}/admin/analytics")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual([p["page"] for p in body["pages"]], ["/tasks"])
        self.assertEqual(body["hidden"]["pages"], 1)
        self.assertEqual(body["by_day"][0]["users"], 5)
        PrivacySettings.objects.create(org=self.org, user=self.people[0], analytics_personal_only=True)
        body = self.as_(self.owner).get(f"{self.base}/admin/analytics").json()
        self.assertEqual(body["pages"], [])
        self.assertIsNone(body["active_users"])
        self.assertEqual(self.as_(self.owner).get(f"{self.base}/admin/analytics?days=0").status_code, 400)
        self.assertEqual(self.as_(self.people[1]).get(f"{self.base}/admin/analytics").status_code, 403)
