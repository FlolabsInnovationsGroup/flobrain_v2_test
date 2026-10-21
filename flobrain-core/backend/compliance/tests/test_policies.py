"""Policies: templates match the docs, install as Documents, publish versions, acknowledgements per version."""

import os

from compliance import policies
from compliance.models import Policy, PolicyAck
from compliance.tests.base import ComplianceBase
from docs_app.models import Document
from notifications.models import Notification
from organizations.models import AuditEvent
from rooms.services import user_can_access_room

DOCS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "docs", "v2", "compliance", "templates"))


class TemplateTests(ComplianceBase):
    def test_every_template_exists_and_matches_the_docs_copy(self):
        for meta in policies.TEMPLATES:
            text = policies.template_text(meta["key"])
            self.assertIn("{{ORG_NAME}}", text)
            docs_path = os.path.join(DOCS, f"{meta['key']}.md")
            if os.path.isdir(DOCS):
                with open(docs_path, encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), text, meta["key"])
        self.assertIn("AI", policies.template_text("acceptable-use"))

    def test_fill_replaces_placeholders(self):
        text = policies.fill(policies.template_text("data-retention"), self.org, "Owner")
        self.assertNotIn("{{", text)
        self.assertIn("Acme Org", text)


class InstallTests(ComplianceBase):
    def install(self, keys, publish=False, key="admin"):
        self.auth(key)
        return self.client.post(f"{self.base}/policies", {"templates": keys, "publish": publish}, format="json")

    def test_install_creates_documents_members_can_read(self):
        response = self.install(["access-control", "acceptable-use"])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Policy.objects.filter(org=self.org).count(), 2)
        doc = Document.objects.get(title="Access control policy")
        self.assertIn("Acme Org", doc.content_text)
        self.assertTrue(user_can_access_room(self.users["member"], doc.room))
        self.assertFalse(user_can_access_room(self.outsider, doc.room))
        self.assertIsNone(response.json()[0]["version"])  # installed, not published yet
        # Installing again keeps the existing one.
        self.assertEqual(self.install(["access-control"]).json(), [])
        self.assertEqual(self.install(["nope"]).status_code, 400)
        self.assertEqual(self.install(["access-control"], key="member").status_code, 403)

    def test_publish_versions_and_acknowledge(self):
        self.install(["acceptable-use"])
        policy = Policy.objects.get(org=self.org)
        self.auth("admin")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"{self.base}/policies/{policy.id}/publish")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["version"], 1)
        self.assertTrue(Notification.objects.filter(user=self.users["member"], kind="compliance.policy_published").exists())
        # Publishing the same text again changes nothing.
        self.assertEqual(self.client.post(f"{self.base}/policies/{policy.id}/publish").json()["changed"], False)

        self.auth("member")
        mine = self.client.get(f"{self.base}/my-policies").json()
        self.assertEqual(mine[0]["version"], 1)
        self.assertIsNone(mine[0]["acknowledged_at"])
        self.assertIn("Acme Org", mine[0]["body"])
        self.assertEqual(self.client.post(f"{self.base}/policies/{policy.id}/acknowledge", {"version": 1}, format="json").status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="compliance.policy.ack", actor=self.users["member"]).exists())

        # The admin edits the document and publishes version 2: the old acknowledgement does not count.
        Document.objects.filter(pk=policy.document_id).update(content_text=policy.document.content_text + "\nNew rule.")
        self.auth("admin")
        self.assertEqual(self.client.post(f"{self.base}/policies/{policy.id}/publish").json()["version"], 2)
        self.auth("member")
        self.assertEqual(self.client.post(f"{self.base}/policies/{policy.id}/acknowledge", {"version": 1}, format="json").status_code, 409)
        self.assertIsNone(self.client.get(f"{self.base}/my-policies").json()[0]["acknowledged_at"])
        self.assertEqual(self.client.post(f"{self.base}/policies/{policy.id}/acknowledge", {"version": 2}, format="json").status_code, 200)
        self.assertEqual(PolicyAck.objects.filter(user=self.users["member"]).count(), 2)

        self.auth("admin")
        detail = self.client.get(f"{self.base}/policies/{policy.id}").json()
        self.assertEqual(detail["stats"]["acknowledged"], 1)
        self.assertEqual(len(detail["missing"]), 4)
        self.assertEqual([v["version"] for v in detail["versions"]], [2, 1])

    def test_install_and_publish_at_once(self):
        self.install([t["key"] for t in policies.TEMPLATES], publish=True)
        self.assertEqual(Policy.objects.filter(org=self.org).count(), 7)
        self.assertTrue(all(p.versions.exists() for p in Policy.objects.filter(org=self.org)))
        self.assertEqual(Notification.objects.filter(user=self.users["member"], kind="compliance.policy_published").count(), 1)
