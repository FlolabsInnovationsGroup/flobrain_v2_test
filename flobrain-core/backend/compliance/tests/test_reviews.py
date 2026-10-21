"""Access reviews: items, reviewers, decisions that really remove access (with audit), reminders, completion."""

from datetime import timedelta

from django.utils import timezone

from compliance.models import AccessReview, AccessReviewItem
from compliance.tests.base import ComplianceBase
from notifications.models import Notification
from organizations.models import AuditEvent, OrgMembership, PermissionGrant
from organizations.permissions import can


class ReviewBase(ComplianceBase):
    def setUp(self):
        super().setUp()
        self.grant = PermissionGrant.objects.create(org=self.org, grantee=self.users["member"], perm_key="audit.view", granted_by=self.users["admin"])

    def start(self, key="admin", **body):
        self.auth(key)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"{self.base}/reviews", {"reviewer_mode": "team_leads", **body}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return AccessReview.objects.get(pk=response.json()["id"])

    def item(self, review, kind, key):
        return review.items.get(kind=kind, subject=self.users[key])

    def decide(self, key, review, item, decision, **extra):
        self.auth(key)
        return self.client.post(f"{self.base}/reviews/{review.id}/items/{item.id}/decision", {"decision": decision, **extra}, format="json")


class CreateTests(ReviewBase):
    def test_items_and_reviewers(self):
        review = self.start()
        kinds = sorted(review.items.values_list("kind", flat=True))
        self.assertEqual(kinds.count("membership"), 5)
        self.assertEqual(kinds.count("grant"), 1)
        # Team members are reviewed by their lead; admins, the owner and the lead herself by admins.
        self.assertEqual(self.item(review, "membership", "member").reviewer_id, self.users["lead"].id)
        self.assertEqual(self.item(review, "grant", "member").reviewer_id, self.users["lead"].id)
        self.assertIsNone(self.item(review, "membership", "lead").reviewer_id)
        self.assertIsNone(self.item(review, "membership", "admin").reviewer_id)
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="compliance.review.create").exists())
        self.assertTrue(Notification.objects.filter(user=self.users["lead"], kind="compliance.review_assigned").exists())

    def test_admin_mode_assigns_nobody(self):
        review = self.start(reviewer_mode="admins")
        self.assertFalse(review.items.exclude(reviewer__isnull=True).exists())

    def test_one_open_review_at_a_time(self):
        self.start()
        self.auth("admin")
        self.assertEqual(self.client.post(f"{self.base}/reviews", {}, format="json").status_code, 409)

    def test_includes_personal_connections_and_shared_buddies(self):
        from buddies.models import Buddy
        from integrations.write.models import WriteConnection

        WriteConnection.objects.create(org=self.org, owner=self.users["member"], provider="google", account_label="member@example.com")
        Buddy.objects.create(org=self.org, slug="helper", name="Helper", created_by=self.users["member"], visibility=Buddy.VIS_ORG)
        Buddy.objects.create(org=self.org, slug="mine", name="Mine", created_by=self.users["member"], visibility=Buddy.VIS_PRIVATE)
        review = self.start()
        self.assertEqual(review.items.filter(kind="integration").count(), 1)
        self.assertEqual(review.items.filter(kind="buddy").count(), 1)


class DecisionTests(ReviewBase):
    def test_admin_revokes_a_grant_and_it_is_gone(self):
        review = self.start()
        self.assertTrue(can(self.users["member"], "audit.view", self.org))
        response = self.decide("admin", review, self.item(review, "grant", "member"), "revoke", note="Not needed after the audit")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNotNone(response.json()["applied_at"])
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.revoked_at)
        self.assertEqual(self.grant.revoked_by, self.users["admin"])
        self.assertFalse(can(self.users["member"], "audit.view", self.org))
        event = AuditEvent.objects.get(org=self.org, action="perm.revoke")
        self.assertEqual(event.payload["via"], "access_review")
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="compliance.review.decide").exists())

    def test_admin_revokes_membership_and_the_person_loses_access(self):
        review = self.start()
        self.auth("member")
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.org.id}/compliance/me").status_code, 200)
        self.assertEqual(self.decide("admin", review, self.item(review, "membership", "member"), "revoke").status_code, 200)
        self.assertEqual(self.membership("member").employment_status, OrgMembership.STATUS_PAUSED)
        self.auth("member")
        self.assertEqual(self.client.get(f"/api/v2/orgs/{self.org.id}/compliance/me").status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="member.status", payload__status="paused").exists())

    def test_change_role(self):
        review = self.start()
        item = self.item(review, "membership", "admin")
        self.assertEqual(self.decide("owner", review, item, "change", change_to={"org_role": "member"}).status_code, 200)
        self.assertEqual(self.membership("admin").org_role, "member")
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="member.role").exists())
        self.assertEqual(self.decide("owner", review, item, "change", change_to={"org_role": "owner"}).status_code, 400)

    def test_change_grant_sets_an_end_date(self):
        review = self.start()
        item = self.item(review, "grant", "member")
        self.assertEqual(self.decide("admin", review, item, "change", change_to={"expires_in_days": 45}).status_code, 400)
        self.assertEqual(self.decide("admin", review, item, "change", change_to={"expires_in_days": 30}).status_code, 200)
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.expires_at)
        self.assertLess(self.grant.expires_at, timezone.now() + timedelta(days=31))

    def test_revoke_integration_disconnects(self):
        from integrations.write.models import WriteConnection

        conn = WriteConnection.objects.create(org=self.org, owner=self.users["member"], provider="google")
        review = self.start()
        self.assertEqual(self.decide("admin", review, self.item(review, "integration", "member"), "revoke").status_code, 200)
        self.assertFalse(WriteConnection.objects.filter(pk=conn.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="integration.write.disconnect").exists())

    def test_revoke_buddy_makes_it_private(self):
        from buddies.models import Buddy

        buddy = Buddy.objects.create(org=self.org, slug="helper", name="Helper", created_by=self.users["member"], visibility=Buddy.VIS_ORG)
        review = self.start()
        self.assertEqual(self.decide("admin", review, self.item(review, "buddy", "member"), "revoke").status_code, 200)
        buddy.refresh_from_db()
        self.assertEqual(buddy.visibility, Buddy.VIS_PRIVATE)

    def test_owner_access_is_never_revoked(self):
        review = self.start()
        response = self.decide("admin", review, self.item(review, "membership", "owner"), "revoke")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.membership("owner").employment_status, "active")

    def test_nobody_reviews_themselves(self):
        review = self.start()
        response = self.decide("admin", review, self.item(review, "membership", "admin"), "keep")
        self.assertEqual(response.status_code, 403)

    def test_lead_decides_only_her_items_and_revokes_wait_for_an_admin(self):
        review = self.start()
        self.assertEqual(self.decide("lead", review, self.item(review, "membership", "admin"), "keep").status_code, 403)
        self.assertEqual(self.decide("teammate", review, self.item(review, "grant", "member"), "keep").status_code, 403)
        response = self.decide("lead", review, self.item(review, "grant", "member"), "revoke")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["applied_at"])
        self.grant.refresh_from_db()
        self.assertIsNone(self.grant.revoked_at)  # not yet
        self.auth("admin")
        self.assertEqual(self.client.post(f"{self.base}/reviews/{review.id}/apply").json()["applied"], 1)
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.revoked_at)

    def test_lead_sees_her_items_without_compliance_view(self):
        review = self.start()
        self.auth("lead")
        self.assertEqual(self.client.get(f"{self.base}/overview").status_code, 403)
        mine = self.client.get(f"{self.base}/my-reviews").json()
        subjects = {i["subject"]["name"] for i in mine[0]["items"]}
        self.assertEqual(subjects, {"Member", "Teammate"})
        detail = self.client.get(f"{self.base}/reviews/{review.id}").json()
        self.assertEqual(len(detail["items"]), 3)  # member's membership and grant, teammate's membership
        self.auth("teammate")
        self.assertEqual(self.client.get(f"{self.base}/reviews/{review.id}").status_code, 403)


class CompletionTests(ReviewBase):
    def decide_all(self, review):
        for item in review.items.all():
            decider = "owner" if item.subject_id != self.users["owner"].id else "admin"
            self.assertEqual(self.decide(decider, review, item, "keep").status_code, 200)

    def test_complete_needs_every_decision(self):
        review = self.start()
        self.auth("admin")
        self.assertEqual(self.client.post(f"{self.base}/reviews/{review.id}/complete").status_code, 409)
        self.decide_all(review)
        self.auth("admin")
        response = self.client.post(f"{self.base}/reviews/{review.id}/complete")
        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        self.assertEqual(review.status, "completed")
        self.assertEqual(review.summary["progress"]["pending"], 0)
        report = self.client.get(f"{self.base}/reviews/{review.id}/report").json()
        self.assertEqual(report["by_kind"]["membership"]["keep"], 5)
        csv_response = self.client.get(f"{self.base}/reviews/{review.id}/report?export=csv")
        self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("c-member@example.com", csv_response.content.decode())

    def test_reminders_notify_reviewers_once_an_hour(self):
        review = self.start()
        Notification.objects.all().delete()
        self.auth("admin")
        response = self.client.post(f"{self.base}/reviews/{review.id}/remind")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Notification.objects.filter(user=self.users["lead"], kind="compliance.review_reminder").exists())
        self.assertTrue(Notification.objects.filter(user=self.users["owner"], kind="compliance.review_reminder").exists())
        self.assertEqual(self.client.post(f"{self.base}/reviews/{review.id}/remind").status_code, 429)

    def test_tick_reminds_due_reviews(self):
        from io import StringIO

        from django.core.management import call_command

        review = self.start()
        AccessReview.objects.filter(pk=review.pk).update(due_at=timezone.now() + timedelta(days=1), last_reminded_at=None)
        Notification.objects.all().delete()
        out = StringIO()
        call_command("compliance_tick", stdout=out)
        self.assertIn("reminded=1", out.getvalue())
        self.assertTrue(Notification.objects.filter(kind="compliance.review_reminder").exists())
        call_command("compliance_tick", stdout=out)
        self.assertIn("reminded=0", out.getvalue())

    def test_closed_review_takes_no_decisions(self):
        review = self.start()
        self.auth("admin")
        self.client.post(f"{self.base}/reviews/{review.id}/cancel")
        item = self.item(review, "grant", "member")
        self.assertEqual(self.decide("admin", review, item, "revoke").status_code, 400)
        self.assertEqual(AccessReviewItem.objects.get(pk=item.pk).decision, "pending")
