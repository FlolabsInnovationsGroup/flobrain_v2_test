from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from brain.models import Chat
from notifications.models import Notification
from organizations.models import OrgMembership, Organization, Team, TeamMembership
from privacy.models import DeletionRequest, RetentionPolicy
from privacy.services import apply_retention, build_export
from rooms.models import Room, RoomMessage
from timetracking.models import TimeEntry
from users.jwt_utils import make_access_token
from users.models import User


class PrivacyTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="P", slug="p-org")
        self.users = {}
        for name, role in (("owner", "owner"), ("admin", "admin"), ("lead", "member"), ("ana", "member")):
            u = User.objects.create(email=f"{name}@p.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            self.users[name] = u
        self.team = Team.objects.create(org=self.org, name="Eng")
        TeamMembership.objects.create(team=self.team, user=self.users["lead"], team_role="lead")
        TeamMembership.objects.create(team=self.team, user=self.users["ana"])
        self.room = Room.objects.filter(org=self.org, kind="team", team=self.team).first() or Room.objects.create(org=self.org, name="eng", kind="team", team=self.team)
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _as(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return c

    def test_inventory_and_who_can_see(self):
        RoomMessage.objects.create(room=self.room, author=self.users["ana"], body="hello")
        data = self._as("ana").get(f"{self.base}/me/privacy").json()
        self.assertEqual(data["data"]["room_messages"], 1)
        self.assertEqual(data["who_can_see"]["team_leads"], ["lead (Eng)"])
        self.assertTrue(data["settings"]["share_time_details_with_org"])

    def test_time_descriptions_hidden_from_leads_when_not_shared(self):
        TimeEntry.objects.create(org=self.org, user=self.users["ana"], description="interview prep", ended_at=timezone.now())
        lead = self._as("lead")
        rows = lead.get(f"{self.base}/time-entries", {"team": self.team.id}).json()["results"]
        self.assertEqual(rows[0]["description"], "interview prep")
        ana = self._as("ana")
        self.assertEqual(ana.put(f"{self.base}/me/privacy", {"share_time_details_with_org": "no"}, format="json").status_code, 400)
        ana.put(f"{self.base}/me/privacy", {"share_time_details_with_org": False}, format="json")
        rows = lead.get(f"{self.base}/time-entries", {"team": self.team.id}).json()["results"]
        self.assertEqual((rows[0]["description"], rows[0]["description_hidden"]), ("", True))
        self.assertEqual(ana.get(f"{self.base}/time-entries").json()["results"][0]["description"], "interview prep", "still yours")

    def test_deletion_request_flow(self):
        msg = RoomMessage.objects.create(room=self.room, author=self.users["ana"], body="secret plan")
        Chat.objects.create(org=self.org, user=self.users["ana"], title="mine")
        TimeEntry.objects.create(org=self.org, user=self.users["ana"], description="x", ended_at=timezone.now())
        ana = self._as("ana")
        self.assertEqual(self._as("owner").post(f"{self.base}/privacy/deletion-requests", {}, format="json").status_code, 409, "owner hands over first")
        r = ana.post(f"{self.base}/privacy/deletion-requests", {"reason": "leaving"}, format="json").json()
        self.assertEqual(ana.post(f"{self.base}/privacy/deletion-requests", {}, format="json").status_code, 409)
        self.assertTrue(Notification.objects.filter(user=self.users["admin"], kind="deletion_request").exists())
        self.assertEqual(self._as("lead").post(f"{self.base}/privacy/deletion-requests/{r['id']}", {"decision": "approve"}, format="json").status_code, 403)
        self.assertEqual(len(self._as("lead").get(f"{self.base}/privacy/deletion-requests", {"scope": "all"}).json()["results"]), 0)
        self.assertEqual(len(self._as("admin").get(f"{self.base}/privacy/deletion-requests", {"scope": "all"}).json()["results"]), 1)
        done = self._as("admin").post(f"{self.base}/privacy/deletion-requests/{r['id']}", {"decision": "approve"}, format="json").json()
        self.assertEqual(done["status"], "done")
        msg.refresh_from_db()
        self.assertEqual(msg.body, "")
        self.assertIsNotNone(msg.deleted_at)
        self.assertFalse(Chat.objects.filter(user=self.users["ana"]).exists())
        self.assertEqual(TimeEntry.objects.get(user=self.users["ana"]).description, "")
        self.assertEqual(OrgMembership.objects.get(org=self.org, user=self.users["ana"]).employment_status, "offboarding")
        self.assertEqual(self._as("admin").post(f"{self.base}/privacy/deletion-requests/{r['id']}", {"decision": "reject"}, format="json").status_code, 409)

    def test_retention_owner_only_and_deletes_old_rows(self):
        self.assertEqual(self._as("ana").get(f"{self.base}/privacy/retention").status_code, 403)
        self.assertFalse(self._as("admin").get(f"{self.base}/privacy/retention").json()["can_edit"])
        self.assertEqual(self._as("admin").put(f"{self.base}/privacy/retention", {"messages_days": 30}, format="json").status_code, 403)
        owner = self._as("owner")
        for bad in (3, 99999, True, "30"):
            self.assertEqual(owner.put(f"{self.base}/privacy/retention", {"messages_days": bad}, format="json").status_code, 400, bad)
        self.assertEqual(owner.put(f"{self.base}/privacy/retention", {"messages_days": 30}, format="json").json()["messages_days"], 30)
        old = RoomMessage.objects.create(room=self.room, author=self.users["ana"], body="old")
        RoomMessage.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
        new = RoomMessage.objects.create(room=self.room, author=self.users["ana"], body="new")
        out = apply_retention(RetentionPolicy.objects.get(org=self.org))
        self.assertEqual(out["messages"], 1)
        self.assertFalse(RoomMessage.objects.filter(pk=old.pk).exists())
        self.assertTrue(RoomMessage.objects.filter(pk=new.pk).exists())

    def test_retention_removes_vectors(self):
        from knowledge.models import KnowledgeChunk

        old = RoomMessage.objects.create(room=self.room, author=self.users["ana"], body="old")
        RoomMessage.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
        KnowledgeChunk.objects.create(org=self.org, room=self.room, source_type="room_message", source_id=old.id, text="old", content_hash="h", model="m", dimension=3)
        apply_retention(RetentionPolicy.objects.create(org=self.org, messages_days=30))
        self.assertFalse(KnowledgeChunk.objects.filter(source_id=old.id).exists())

    @override_settings(CONTENT_STORAGE="local")
    def test_my_data_export(self):
        RoomMessage.objects.create(room=self.room, author=self.users["ana"], body="mine")
        RoomMessage.objects.create(room=self.room, author=self.users["lead"], body="not mine")
        data, counts = build_export(self.users["ana"])
        self.assertIn(b"PK", data[:2])
        self.assertEqual(counts["messages_i_wrote.json"], 1)
        ana = self._as("ana")
        first = ana.post("/api/v2/me/data-exports")
        self.assertEqual(first.status_code, 202, first.content)
        job = first.json()
        again = ana.post("/api/v2/me/data-exports")
        self.assertEqual(again.status_code, 429, again.content)
        detail = ana.get(f"/api/v2/me/data-exports/{job['id']}").json()
        self.assertEqual(detail["status"], "succeeded")
        self.assertIn("download_url", detail)
        self.assertEqual(self._as("lead").get(f"/api/v2/me/data-exports/{job['id']}").status_code, 404)


class SeatAndOnboardingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="S", slug="s-org")
        self.admin = User.objects.create(email="a@s.test", username="a", password_hash=make_password("x"), is_platform_admin=True)
        OrgMembership.objects.create(org=self.org, user=self.admin, org_role="owner", employment_status="active")
        self.c = APIClient()
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.admin.id))}")

    @override_settings(BILLING_ENFORCE_ENTITLEMENTS=True)
    def test_seat_limit(self):
        from billing_v2.models import Plan, Subscription

        plan = Plan.objects.create(code="team", name="Team", entitlements={"flags": [], "limits": {}})
        Subscription.objects.create(org=self.org, plan=plan, status="active", seats=2)
        url = f"/api/v2/orgs/{self.org.id}/members"
        self.assertEqual(self.c.post(url, {"email": "b@s.test"}, format="json").status_code, 201)
        r = self.c.post(url, {"email": "c@s.test"}, format="json")
        self.assertEqual((r.status_code, r.json()["error"]), (409, "seat_limit"))

    def test_platform_org_onboarding(self):
        url = "/api/v2/platform/orgs"
        self.assertEqual(self.c.post(url, {"name": "X", "slug": "demo", "owner_email": "o@x.test"}, format="json").status_code, 400)
        self.assertEqual(self.c.post(url, {"name": "Acme", "slug": "Bad Slug", "owner_email": "o@x.test"}, format="json").status_code, 400)
        r = self.c.post(url, {"name": "Acme", "slug": "acme", "owner_email": "o@x.test"}, format="json")
        self.assertEqual(r.status_code, 201)
        org = Organization.objects.get(slug="acme")
        self.assertEqual(OrgMembership.objects.get(org=org).org_role, "owner")
        self.assertEqual(self.c.post(url, {"name": "Acme", "slug": "acme", "owner_email": "o@x.test"}, format="json").status_code, 409)
        other = User.objects.create(email="n@s.test", username="n", password_hash=make_password("x"))
        c2 = APIClient()
        c2.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(other.id))}")
        self.assertEqual(c2.post(url, {"name": "Z", "slug": "zed", "owner_email": "o@z.test"}, format="json").status_code, 403)


class Review16Tests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="R", slug="r-org")
        self.users = {}
        for name, role in (("owner", "owner"), ("admin", "admin"), ("ana", "member")):
            u = User.objects.create(email=f"{name}@r.test", username=name, password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=u, org_role=role, employment_status="active")
            self.users[name] = u
        self.staff = User.objects.create(email="staff@r.test", username="staff", password_hash=make_password("x"), is_platform_admin=True)
        self.users["staff"] = self.staff
        self.base = f"/api/v2/orgs/{self.org.id}"

    def _as(self, name):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.users[name].id))}")
        return c

    def test_erasure_removes_translations_and_owner_is_safe(self):
        from rooms.models import MessageTranslation

        room = Room.objects.create(org=self.org, name="g", kind="group")
        msg = RoomMessage.objects.create(room=room, author=self.users["ana"], body="secret")
        MessageTranslation.objects.create(message=msg, language="fr", text="secret-fr")
        r = self._as("ana").post(f"{self.base}/privacy/deletion-requests", {}, format="json").json()
        self.assertEqual(self._as("staff").post(f"{self.base}/privacy/deletion-requests/{r['id']}", {"decision": "approve"}, format="json").status_code, 403)
        self.assertEqual(self._as("staff").post(f"{self.base}/privacy/deletion-requests", {}, format="json").status_code, 403)
        OrgMembership.objects.filter(org=self.org, user=self.users["ana"]).update(org_role="owner")
        self.assertEqual(self._as("admin").post(f"{self.base}/privacy/deletion-requests/{r['id']}", {"decision": "approve"}, format="json").status_code, 409)
        OrgMembership.objects.filter(org=self.org, user=self.users["ana"]).update(org_role="member")
        self.assertEqual(self._as("admin").post(f"{self.base}/privacy/deletion-requests/{r['id']}", {"decision": "approve"}, format="json").status_code, 200)
        self.assertFalse(MessageTranslation.objects.filter(message=msg).exists())

    def test_product_analytics_consent_is_honoured(self):
        from telemetry.models import ProductEvent
        from telemetry.views import ALLOWED_EVENT_NAMES

        name = sorted(ALLOWED_EVENT_NAMES)[0]
        ana = self._as("ana")
        ana.put(f"{self.base}/me/privacy", {"consents": {"product_analytics": False}}, format="json")
        res = ana.post(f"{self.base}/events", {"name": name}, format="json")
        self.assertEqual(res.status_code, 202)
        self.assertFalse(ProductEvent.objects.filter(user=self.users["ana"]).exists())

    def test_onboarded_owner_is_active_and_slugs_are_safe(self):
        url = "/api/v2/platform/orgs"
        staff = self._as("staff")
        for bad in ("signin", "sso", "first-login", "a", "ab-"):
            self.assertEqual(staff.post(url, {"name": "X Co", "slug": bad, "owner_email": "o@x.test"}, format="json").status_code, 400, bad)
        self.assertEqual(staff.post(url, {"name": "X Co", "slug": "xco", "owner_email": "ana@r.test"}, format="json").status_code, 201)
        m = OrgMembership.objects.get(org__slug="xco", user=self.users["ana"])
        self.assertEqual((m.org_role, m.employment_status), ("owner", "active"))

    @override_settings(BILLING_ENFORCE_ENTITLEMENTS=True)
    def test_seat_cap_holds_on_reactivation(self):
        from billing_v2.models import Plan, Subscription

        plan = Plan.objects.create(code="t", name="T", entitlements={"flags": [], "limits": {}})
        Subscription.objects.create(org=self.org, plan=plan, status="active", seats=3)
        admin = self._as("admin")
        admin.patch(f"{self.base}/members/{self.users['ana'].id}", {"employment_status": "terminated"}, format="json")
        self.assertEqual(admin.post(f"{self.base}/members", {"email": "new@r.test"}, format="json").status_code, 201)
        res = admin.patch(f"{self.base}/members/{self.users['ana'].id}", {"employment_status": "active"}, format="json")
        self.assertEqual((res.status_code, res.json()["error"]), (409, "seat_limit"))

    @override_settings(DEMO_MODE=True)
    def test_demo_seat_cannot_set_a_password(self):
        from django.core.cache import cache

        cache.clear()
        tokens = APIClient().post("/api/v2/demo/signin", {"role": "member"}, format="json").json()
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(c.post("/api/v2/auth/first-login", {"password": "Str0ng-pass-123!", "password_confirm": "Str0ng-pass-123!"}, format="json").status_code, 403)

    def test_onboarding_matches_existing_email_in_any_case(self):
        mixed = User.objects.create(email="Mixed@R.test", username="mixed", password_hash=make_password("x"))
        self.assertEqual(self._as("staff").post("/api/v2/platform/orgs", {"name": "M Co", "slug": "mco", "owner_email": "mixed@r.test"}, format="json").status_code, 201)
        self.assertEqual(OrgMembership.objects.get(org__slug="mco").user_id, mixed.id)
        self.assertEqual(User.objects.filter(email__iexact="mixed@r.test").count(), 1)
