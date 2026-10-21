"""Flag, permissions and the main read endpoints."""

from compliance.models import ControlAttestation
from compliance.tests.base import ComplianceBase
from organizations.models import AuditEvent, PermissionGrant

READS = ("/overview", "/controls", "/settings", "/reviews", "/evidence", "/policies", "/policy-templates", "/trust", "/trust/requests")
MEMBER_READS = ("/me", "/my-reviews", "/my-policies")


class GateTests(ComplianceBase):
    def test_flag_off_is_501_everywhere(self):
        self.org.settings = {"flags": {"compliance": False}}
        self.org.save()
        self.auth("admin")
        for path in READS + MEMBER_READS:
            self.assertEqual(self.client.get(self.base + path).status_code, 501, path)
        self.assertEqual(self.client.post(f"{self.base}/reviews", {}, format="json").status_code, 501)

    def test_flag_off_for_one_member(self):
        m = self.membership("admin")
        m.feature_flags = {"compliance": False}
        m.save()
        self.auth("admin")
        self.assertEqual(self.client.get(f"{self.base}/overview").status_code, 501)

    def test_members_need_compliance_view(self):
        self.auth("member")
        for path in READS:
            self.assertEqual(self.client.get(self.base + path).status_code, 403, path)
        for path in MEMBER_READS:
            self.assertEqual(self.client.get(self.base + path).status_code, 200, path)
        me = self.client.get(f"{self.base}/me").json()
        self.assertEqual((me["can_view"], me["can_manage"]), (False, False))

    def test_view_grant_reads_but_does_not_manage(self):
        PermissionGrant.objects.create(org=self.org, grantee=self.users["member"], perm_key="compliance.view")
        self.auth("member")
        for path in READS:
            self.assertEqual(self.client.get(self.base + path).status_code, 200, path)
        self.assertEqual(self.client.post(f"{self.base}/reviews", {}, format="json").status_code, 403)
        self.assertEqual(self.client.put(f"{self.base}/controls/iso27001/7.1/attestation", {"status": "pass", "note": "x" * 20}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"{self.base}/settings", {"dormant_days": 60}, format="json").status_code, 403)

    def test_outsider_and_anonymous(self):
        self.auth(self.outsider)
        self.assertEqual(self.client.get(f"{self.base}/me").status_code, 403)
        self.client.credentials()
        self.assertIn(self.client.get(f"{self.base}/overview").status_code, (401, 403))


class ReadTests(ComplianceBase):
    def test_overview(self):
        self.auth("admin")
        body = self.client.get(f"{self.base}/overview").json()
        self.assertEqual({f["framework"] for f in body["frameworks"]}, {"soc2", "iso27001"})
        iso = next(f for f in body["frameworks"] if f["framework"] == "iso27001")
        self.assertEqual(iso["counts"]["total"], 93)
        self.assertEqual(len(iso["groups"]), 4)
        self.assertEqual(len(body["checks"]), 19)
        self.assertIn("not certification", body["disclaimer"])

    def test_controls_filters(self):
        self.auth("admin")
        rows = self.client.get(f"{self.base}/controls?framework=iso27001&group=7").json()["controls"]
        self.assertEqual(len(rows), 14)
        rows = self.client.get(f"{self.base}/controls?q=cryptography").json()["controls"]
        self.assertEqual([r["id"] for r in rows], ["8.24"])
        self.assertEqual(self.client.get(f"{self.base}/controls?framework=nist").status_code, 400)

    def test_settings_limit_frameworks(self):
        self.auth("admin")
        self.assertEqual(self.client.patch(f"{self.base}/settings", {"frameworks": ["iso27001"], "dormant_days": 60}, format="json").status_code, 200)
        body = self.client.get(f"{self.base}/overview").json()
        self.assertEqual([f["framework"] for f in body["frameworks"]], ["iso27001"])
        self.assertEqual(self.client.patch(f"{self.base}/settings", {"frameworks": ["nist"]}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(f"{self.base}/settings", {"dormant_days": 5}, format="json").status_code, 400)


class AttestationTests(ComplianceBase):
    def url(self, fw="iso27001", cid="7.1"):
        return f"{self.base}/controls/{fw}/{cid}/attestation"

    def test_attest_and_remove(self):
        self.auth("admin")
        self.assertEqual(self.client.put(self.url(), {"status": "pass", "note": "short"}, format="json").status_code, 400)
        self.assertEqual(self.client.put(self.url(), {"status": "maybe", "note": "x" * 20}, format="json").status_code, 400)
        self.assertEqual(self.client.put(self.url(cid="99.1"), {"status": "pass", "note": "x" * 20}, format="json").status_code, 404)
        self.assertEqual(self.client.put(self.url(), {"status": "pass", "note": "Badge access log reviewed", "evidence_url": "javascript:x"}, format="json").status_code, 400)
        response = self.client.put(self.url(), {"status": "pass", "note": "Badge access log reviewed monthly", "evidence_url": "https://drive.example.com/x", "owner": str(self.users["lead"].id)}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "pass")
        self.assertEqual(response.json()["attestation"]["owner"]["name"], "Lead")
        self.assertTrue(AuditEvent.objects.filter(org=self.org, action="compliance.attest").exists())
        self.assertEqual(self.client.delete(self.url()).status_code, 204)
        self.assertFalse(ControlAttestation.objects.exists())
