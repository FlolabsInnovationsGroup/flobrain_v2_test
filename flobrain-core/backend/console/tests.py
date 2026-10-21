from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from console.models import ImpersonationSession
from notifications.models import Notification
from organizations.models import AuditEvent, OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User


def _user(email, **extra):
    return User.objects.create(email=email, password_hash=make_password("x"), **extra)


class ConsoleTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme-console", settings={"flags": {"buddies": True}})
        self.other = Organization.objects.create(name="Other", slug="other-console")
        self.staff = _user("staff@flobrain.test", is_platform_admin=True)
        self.owner = _user("owner@acme.test")
        self.ana = _user("ana@acme.test")
        OrgMembership.objects.create(org=self.org, user=self.owner, org_role=OrgMembership.ORG_ROLE_OWNER, employment_status="active")
        OrgMembership.objects.create(org=self.org, user=self.ana, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status="active")
        OrgMembership.objects.create(org=self.other, user=self.ana, org_role=OrgMembership.ORG_ROLE_MEMBER, employment_status="active")

    def _as(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")
        return client

    def _start(self, **overrides):
        body = {"org": str(self.org.id), "user": str(self.ana.id), "reason": "Ticket 4411: tasks page empty", "minutes": 15}
        body.update(overrides)
        return self._as(self.staff).post("/api/v2/platform/impersonations", body, format="json")

    def test_platform_only(self):
        self.assertEqual(self._as(self.owner).get("/api/v2/platform/orgs").status_code, 403)
        self.assertEqual(self._as(self.owner).put(f"/api/v2/platform/orgs/{self.org.id}/flags", {"flags": {"x": True}}, format="json").status_code, 403)
        self.assertEqual(self._as(self.owner).post("/api/v2/platform/impersonations", {}, format="json").status_code, 403)
        listed = self._as(self.staff).get("/api/v2/platform/orgs?q=acme").json()
        self.assertEqual([o["slug"] for o in listed], ["acme-console"])
        self.assertEqual(listed[0]["active_members"], 2)

    def test_flags_are_audited_and_validated(self):
        staff = self._as(self.staff)
        self.assertEqual(staff.put(f"/api/v2/platform/orgs/{self.org.id}/flags", {"flags": {"buddies": "yes"}}, format="json").status_code, 400)
        self.assertEqual(staff.put(f"/api/v2/platform/orgs/{self.org.id}/flags", {"flags": {"Bad Key": True}}, format="json").status_code, 400)
        done = staff.put(f"/api/v2/platform/orgs/{self.org.id}/flags", {"flags": {"content_studio": True}}, format="json")
        self.assertEqual(done.json()["flags"], {"buddies": True, "content_studio": True})
        event = AuditEvent.objects.get(org=self.org, action="platform.flags.update")
        self.assertEqual(event.actor, self.staff)

    def test_start_needs_reason_and_bounds(self):
        self.assertEqual(self._start(reason="short").status_code, 400)
        self.assertEqual(self._start(minutes=500).status_code, 400)
        self.assertEqual(self._start(user=str(self.staff.id)).status_code, 404, "not a member")
        stranger = _user("x@else.test")
        self.assertEqual(self._start(user=str(stranger.id)).status_code, 404)

    def test_read_only_org_bound_audited_and_visible(self):
        started = self._start()
        self.assertEqual(started.status_code, 201, started.content)
        token, session_id = started.json()["token"], started.json()["id"]
        # The customer sees it: notifications to the person viewed and to the owner.
        notified = set(Notification.objects.filter(kind="impersonation.started").values_list("user_id", flat=True))
        self.assertEqual(notified, {self.ana.id, self.owner.id})
        imp = APIClient()
        imp.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(imp.get(f"/api/v2/orgs/{self.org.id}/notifications").status_code, 200)
        self.assertEqual(imp.get(f"/api/v2/orgs/{self.other.id}/notifications").status_code, 403, "other org of the same user")
        self.assertEqual(imp.post(f"/api/v2/orgs/{self.org.id}/marketplace", {}, format="json").status_code, 403, "read-only")
        self.assertEqual(imp.get("/api/v2/platform/orgs").status_code, 403)
        self.assertEqual(imp.get("/api/profile/").status_code, 401, "V1 ignores the token")
        self.assertEqual(imp.post("/api/profile/delete/", {}, format="json").status_code, 401)
        event = AuditEvent.objects.filter(org=self.org, action="impersonation.request").first()
        self.assertEqual((event.actor, event.impersonator), (self.ana, self.staff))
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="impersonation.start", impersonator=self.staff).exists())
        # The org can list it (with the reason) and stop it.
        owner = self._as(self.owner)
        listed = owner.get(f"/api/v2/orgs/{self.org.id}/impersonations").json()
        self.assertEqual(listed[0]["reason"], "Ticket 4411: tasks page empty")
        self.assertEqual(self._as(self.ana).get(f"/api/v2/orgs/{self.org.id}/impersonations").status_code, 403)
        self.assertEqual(owner.post(f"/api/v2/orgs/{self.org.id}/impersonations/{session_id}/end").status_code, 204)
        self.assertEqual(imp.get(f"/api/v2/orgs/{self.org.id}/notifications").status_code, 401)

    def test_expiry_and_revoked_admin(self):
        token = self._start().json()["token"]
        imp = APIClient()
        imp.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        User.objects.filter(pk=self.staff.pk).update(is_platform_admin=False)
        self.assertEqual(imp.get(f"/api/v2/orgs/{self.org.id}/notifications").status_code, 401)
        User.objects.filter(pk=self.staff.pk).update(is_platform_admin=True)
        ImpersonationSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(imp.get(f"/api/v2/orgs/{self.org.id}/notifications").status_code, 401)

    def test_paused_target_ends_access(self):
        token = self._start().json()["token"]
        imp = APIClient()
        imp.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        OrgMembership.objects.filter(org=self.org, user=self.ana).update(employment_status="paused")
        self.assertEqual(imp.get(f"/api/v2/orgs/{self.org.id}/notifications").status_code, 401)

    def test_support_session_has_no_side_effects(self):
        from rooms.models import Room, RoomMember

        room = Room.objects.create(org=self.org, name="g", kind=Room.KIND_GROUP)
        RoomMember.objects.create(room=room, user=self.ana)
        imp = APIClient()
        imp.credentials(HTTP_AUTHORIZATION=f"Bearer {self._start().json()['token']}")
        self.assertEqual(imp.get(f"/api/v2/orgs/{self.org.id}/rooms/{room.id}/messages").status_code, 200)
        self.assertIsNone(RoomMember.objects.get(room=room, user=self.ana).last_read_at)
        self.assertEqual(imp.get(f"/api/v2/orgs/{self.org.id}/rooms/{room.id}/messages?translate_to=ar").status_code, 403)

    def test_bad_bodies_are_400(self):
        staff = self._as(self.staff)
        self.assertEqual(staff.put(f"/api/v2/platform/orgs/{self.org.id}/flags", [1, 2], format="json").status_code, 400)
        self.assertEqual(staff.post("/api/v2/platform/impersonations", [1], format="json").status_code, 400)
