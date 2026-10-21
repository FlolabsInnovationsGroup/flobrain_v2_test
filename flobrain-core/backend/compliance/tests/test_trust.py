"""Trust center: off until published, only published sections, nothing internal, request form with rate limits."""

from django.core import mail
from django.core.cache import cache

from compliance import trust
from compliance.models import TrustCenter, TrustRequest
from compliance.tests.base import ComplianceBase
from notifications.models import Notification


class TrustBase(ComplianceBase):
    def save(self, key="admin", **body):
        self.auth(key)
        return self.client.put(f"{self.base}/trust", body, format="json")

    def public(self, slug="acme"):
        self.client.credentials()
        return self.client.get(f"/api/v2/public/trust/{slug}")

    def ask(self, slug="acme", ip="198.51.100.7", **body):
        self.client.credentials()
        data = {"name": "Dana Buyer", "email": "dana@buyer.example.com", "company": "Buyer Inc", "documents": ["soc2-readiness"], **body}
        return self.client.post(f"/api/v2/public/trust/{slug}/requests", data, format="json", REMOTE_ADDR=ip)

    def publish_full(self):
        example = trust.FLOBRAIN_EXAMPLE
        response = self.save(slug="acme", published=True, sections=["overview", "controls", "subprocessors", "documents"],
                             overview=example["overview"], subprocessors=example["subprocessors"], documents=example["documents"],
                             data_location="Secret internal note: eu-west-1 only", contact_email="security@acme.example.com")
        self.assertEqual(response.status_code, 200, response.content)
        return response


class PublishTests(TrustBase):
    def test_off_until_published(self):
        self.assertEqual(self.public().status_code, 404)
        self.save(slug="acme", sections=["overview"], overview="Hello")
        self.assertEqual(self.public().status_code, 404)
        self.save(published=True)
        self.assertEqual(self.public().status_code, 200)
        self.save(published=False)
        self.assertEqual(self.public().status_code, 404)

    def test_flag_off_hides_the_page(self):
        self.publish_full()
        self.org.settings = {"flags": {"compliance": False}}
        self.org.save()
        self.assertEqual(self.public().status_code, 404)

    def test_only_published_sections(self):
        self.publish_full()
        body = self.public().json()
        self.assertEqual(body["sections"], ["overview", "controls", "subprocessors", "documents"])
        self.assertNotIn("data_location", body)  # filled in but not chosen
        self.assertNotIn("eu-west-1", str(body))
        self.assertNotIn("contact_email", body)
        self.assertNotIn("security@acme.example.com", str(body))
        self.assertEqual(len(body["subprocessors"]), len(trust.FLOBRAIN_EXAMPLE["subprocessors"]))
        self.assertIn("not certification", body["disclaimer"])

    def test_controls_summary_has_no_internal_details(self):
        self.publish_full()
        controls = self.public().json()["controls"]
        self.assertEqual({c["framework"] for c in controls}, {"soc2", "iso27001"})
        text = str(controls)
        for internal in ("evidence", "check", "attestation", "summary", "c-admin@example.com", "Admin", "dormant"):
            self.assertNotIn(internal, text)
        self.assertEqual(set(controls[0]), {"framework", "name", "readiness", "passing", "applicable", "groups"})

    def test_validation(self):
        self.assertEqual(self.save(slug="Bad Slug!").status_code, 400)
        self.assertEqual(self.save(sections=["secrets"]).status_code, 400)
        self.assertEqual(self.save(contact_email="nope").status_code, 400)
        self.assertEqual(self.save(subprocessors="x").status_code, 400)
        # Links must be https; control characters are dropped.
        self.save(subprocessors=[{"name": "A\x07WS", "website": "javascript:alert(1)"}, {"name": ""}])
        row = TrustCenter.objects.get(org=self.org)
        self.assertEqual(row.subprocessors, [{"name": "AWS", "purpose": "", "location": "", "website": ""}])

    def test_slug_is_unique(self):
        from organizations.models import Organization

        other = Organization.objects.create(name="Other", slug="other", settings={"flags": {"compliance": True}})
        TrustCenter.objects.create(org=other, slug="taken")
        self.assertEqual(self.save(slug="taken").status_code, 409)

    def test_only_managers_edit(self):
        self.assertEqual(self.save(key="member", published=True).status_code, 403)
        self.auth("member")
        self.assertEqual(self.client.get(f"{self.base}/trust").status_code, 403)


class RequestTests(TrustBase):
    def setUp(self):
        super().setUp()
        self.publish_full()
        Notification.objects.all().delete()
        mail.outbox = []

    def test_request_notifies_admins_by_app_and_email(self):
        response = self.ask(documents=["soc2-readiness", "made-up"])
        self.assertEqual(response.status_code, 202)
        req = TrustRequest.objects.get(org=self.org)
        self.assertEqual(req.documents, ["soc2-readiness"])
        self.assertNotEqual(req.ip_hash, "198.51.100.7")
        self.assertTrue(Notification.objects.filter(user=self.users["admin"], kind="compliance.trust_request").exists())
        self.assertFalse(Notification.objects.filter(user=self.users["member"]).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("security@acme.example.com", mail.outbox[0].to)
        self.assertIn("c-admin@example.com", mail.outbox[0].to)

    def test_rate_limit_per_visitor(self):
        for _ in range(trust.IP_LIMIT_PER_HOUR):
            self.assertEqual(self.ask().status_code, 202)
        self.assertEqual(self.ask().status_code, 429)
        self.assertEqual(self.ask(ip="203.0.113.9").status_code, 202)  # someone else
        self.assertEqual(TrustRequest.objects.count(), trust.IP_LIMIT_PER_HOUR + 1)

    def test_rate_limit_per_org(self):
        cache.clear()
        for n in range(trust.ORG_LIMIT_PER_DAY):
            self.assertEqual(self.ask(ip=f"203.0.113.{n + 1}").status_code, 202)
        self.assertEqual(self.ask(ip="192.0.2.200").status_code, 429)

    def test_validation_and_honeypot(self):
        self.assertEqual(self.ask(email="bad").status_code, 400)
        self.assertEqual(self.ask(name="").status_code, 400)
        self.assertEqual(self.ask(documents="x").status_code, 400)
        self.assertEqual(self.ask(website="http://spam.example").status_code, 202)
        self.assertEqual(TrustRequest.objects.count(), 0)

    def test_no_form_when_documents_section_is_off(self):
        self.save(sections=["overview"])
        self.assertEqual(self.ask().status_code, 404)

    def test_admin_marks_requests(self):
        self.ask()
        req = TrustRequest.objects.get()
        self.auth("admin")
        rows = self.client.get(f"{self.base}/trust/requests").json()
        self.assertEqual(rows[0]["email"], "dana@buyer.example.com")
        response = self.client.patch(f"{self.base}/trust/requests/{req.id}", {"status": "sent"}, format="json")
        self.assertEqual(response.json()["status"], "sent")
        self.auth("member")
        self.assertEqual(self.client.patch(f"{self.base}/trust/requests/{req.id}", {"status": "declined"}, format="json").status_code, 403)
