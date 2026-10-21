"""E-invoicing API: flag and permissions, drafts with server totals, ZATCA onboarding and
submission (HTTP mocked), ETA submission and polling, signers and allowlists, approvals, secrets,
imports, the buddy tools, the demo seed. Nothing reaches the network."""

import base64
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from lxml import etree
from rest_framework.test import APIClient

from actions.models import ActionProposal
from actions.service import ActionDenied
from einvoice import services
from einvoice.models import AuthorityEvent, Invoice, TaxProfile
from einvoice.test_eta import fake_cms
from einvoice.transport import TransportError
from einvoice.zatca import crypto, qr, ubl
from organizations.models import OrgMembership, Organization
from users.jwt_utils import make_access_token
from users.models import User

TEST_KEY = "ab" * 32  # test-only encryption key
SA_VAT = "300000000000003"
SECRET = "zatca-secret-NOT-REAL-9f8e"
ETA_SECRET = "eta-client-secret-NOT-REAL-7d6c"


class FakeNet:
    """Replaces ``einvoice.transport._send``: (method, url prefix) -> list of (status, dict)."""

    def __init__(self, routes=None):
        self.routes = {k: list(v) for k, v in (routes or {}).items()}
        self.calls = []

    def __call__(self, method, url, body, headers, target):
        self.calls.append({"method": method, "url": url, "body": body, "headers": dict(headers), "target": target})
        for (m, prefix), responses in self.routes.items():
            if m == method and url.startswith(prefix):
                status, payload = responses.pop(0) if len(responses) > 1 else responses[0]
                return status, json.dumps(payload).encode()
        raise AssertionError(f"unexpected call {method} {url}")

    def patch(self):
        return patch("einvoice.transport._send", self)


def no_network():
    return patch("einvoice.transport._send", side_effect=AssertionError("network used"))


def token_for(key=None):
    key = key or crypto.generate_key()
    cert = crypto.demo_certificate(key, SA_VAT, "Test Co")
    return base64.b64encode(cert.encode()).decode(), cert


@override_settings(CREDENTIALS_ENCRYPTION_KEY=TEST_KEY, DEMO_MODE=False)
class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(name="E Org", slug="e-org", settings={"flags": {"einvoice": True, "ai_actions": True}})
        self.users = {}
        for key, role in (("owner", "owner"), ("admin", "admin"), ("member", "member")):
            user = User.objects.create(email=f"e-{key}@example.com", username=f"e-{key}", password_hash=make_password("x"))
            OrgMembership.objects.create(org=self.org, user=user, org_role=role, employment_status="active")
            self.users[key] = user
        self.base = f"/api/v2/orgs/{self.org.id}"

    def auth(self, key="admin"):
        user = self.users[key] if isinstance(key, str) else key
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(user.id))}")

    def sa_profile(self, onboarded=True):
        self.auth("admin")
        r = self.client.put(
            f"{self.base}/einvoice/settings/SA",
            {
                "seller_name": "Test Co", "tax_number": SA_VAT, "registration_scheme": "CRN", "registration_id": "1010010000",
                "street": "King Fahd", "building_number": "1234", "district": "Olaya", "city": "Riyadh", "postal_code": "12345",
                "egs_serial": "1-FloBrain|2-2.0|3-abc", "egs_common_name": "EGS-1", "branch_name": "Riyadh Branch",
                "functionality_map": "1100", "egs_location": "RRRD1234", "industry": "Software", "environment": "sandbox",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        profile = TaxProfile.objects.get(org=self.org, country="SA")
        if onboarded:
            key = crypto.generate_key()
            token, cert = token_for(key)
            profile.set_secret("private_key", crypto.key_to_pem(key))
            profile.set_secret("production", json.dumps({"token": token, "secret": SECRET}))
            profile.certificate_b64 = cert
            profile.onboarding = TaxProfile.ONB_PRODUCTION
            profile.save()
        return profile

    def eg_profile(self, **extra):
        self.auth("admin")
        body = {
            "seller_name": "Nile Test", "tax_number": "100200300", "registration_id": "0", "street": "Tahrir", "building_number": "5",
            "city": "Dokki", "region": "Giza", "activity_code": "6201", "environment": "preprod", "client_id": "client-1234",
            "client_secret": ETA_SECRET, "signer_mode": "manual", **extra,
        }
        r = self.client.put(f"{self.base}/einvoice/settings/EG", body, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return TaxProfile.objects.get(org=self.org, country="EG")

    def sa_invoice(self, **extra):
        body = {
            "country": "SA", "invoice_type": "simplified",
            "lines": [{"description": "Widget", "quantity": "3", "unit_price": "33.33", "discount": "1", "vat_category": "S", "vat_rate": "15"}],
            **extra,
        }
        r = self.client.post(f"{self.base}/einvoices", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def eg_invoice(self, **extra):
        body = {
            "country": "EG", "invoice_type": "b2b", "buyer_name": "Delta", "buyer_tax_number": "200300400", "buyer_street": "Horreya",
            "buyer_building_number": "2", "buyer_city": "Alexandria", "buyer_region": "Alexandria", "buyer_country": "EG",
            "lines": [{"description": "Service", "quantity": "2", "unit_price": "1000", "vat_category": "V009", "vat_rate": "14", "item_type": "EGS", "item_code": "EG-100200300-1"}],
            **extra,
        }
        r = self.client.post(f"{self.base}/einvoices", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()


class GateTests(Base):
    def test_flag_off_is_501(self):
        self.org.settings = {"flags": {"einvoice": False}}
        self.org.save()
        self.auth("admin")
        for path in ("/einvoices", "/einvoice/meta", "/einvoice/residency"):
            self.assertEqual(self.client.get(self.base + path).status_code, 501, path)
        self.assertEqual(self.client.post(f"{self.base}/einvoices", {}, format="json").status_code, 501)

    def test_member_without_permission_is_403(self):
        self.auth("member")
        self.assertEqual(self.client.get(f"{self.base}/einvoices").status_code, 403)
        self.assertEqual(self.client.post(f"{self.base}/einvoices", {}, format="json").status_code, 403)
        self.assertEqual(self.client.put(f"{self.base}/einvoice/settings/SA", {}, format="json").status_code, 403)

    def test_outsider_is_403(self):
        outsider = User.objects.create(email="out@example.com", password_hash=make_password("x"))
        self.auth(outsider)
        self.assertEqual(self.client.get(f"{self.base}/einvoices").status_code, 403)

    def test_view_only_cannot_issue_or_manage(self):
        self.auth("member")
        with patch("einvoice.views.can", side_effect=lambda user, perm, obj=None: perm == "einvoice.view"):
            self.assertEqual(self.client.get(f"{self.base}/einvoices").status_code, 200)
            self.assertEqual(self.client.post(f"{self.base}/einvoices", {"country": "SA"}, format="json").status_code, 403)
            self.assertEqual(self.client.post(f"{self.base}/einvoice/zatca/key").status_code, 403)


class DraftTests(Base):
    def test_server_computes_totals_and_ignores_client_totals(self):
        self.auth("admin")
        data = self.sa_invoice(total="1.00", tax_total="0.00")
        self.assertEqual(data["totals"]["tax_inclusive"], "113.84")
        self.assertEqual(data["totals"]["tax_total"], "14.85")
        self.assertEqual(data["lines"][0]["net_amount"], "98.99")
        self.assertEqual(data["status"], "draft")
        self.assertTrue(data["number"].startswith("SA-"))

    def test_validation(self):
        self.auth("admin")
        bad = [
            {"country": "XX", "lines": []},
            {"country": "SA", "lines": []},
            {"country": "SA", "currency": "USD", "lines": [{"description": "a", "unit_price": "1"}]},
            {"country": "SA", "lines": [{"description": "a", "unit_price": "abc"}]},
            {"country": "SA", "lines": [{"description": "a", "unit_price": "1", "vat_category": "Z", "vat_rate": "0"}]},
            {"country": "SA", "invoice_type": "b2b", "lines": [{"description": "a", "unit_price": "1"}]},
            {"country": "SA", "number": "bad number!", "lines": [{"description": "a", "unit_price": "1"}]},
            {"country": "EG", "kind": "credit", "lines": [{"description": "a", "unit_price": "1"}]},
            {"country": "SA", "issue_datetime": (timezone.now() + timedelta(days=2)).isoformat(), "lines": [{"description": "a", "unit_price": "1"}]},
        ]
        for body in bad:
            self.assertEqual(self.client.post(f"{self.base}/einvoices", body, format="json").status_code, 400, body)

    def test_edit_and_delete_drafts_only(self):
        self.sa_profile()
        data = self.sa_invoice()
        url = f"{self.base}/einvoices/{data['id']}"
        r = self.client.patch(url, {"lines": [{"description": "Two", "quantity": "2", "unit_price": "10"}]}, format="json")
        self.assertEqual(r.json()["totals"]["tax_inclusive"], "23.00")
        self.assertEqual(self.client.post(f"{url}/prepare").status_code, 200)
        self.assertEqual(self.client.patch(url, {"note": "x"}, format="json").status_code, 409)
        self.assertEqual(self.client.delete(url).status_code, 409)
        other = self.sa_invoice()
        self.assertEqual(self.client.delete(f"{self.base}/einvoices/{other['id']}").status_code, 204)

    def test_duplicate_number(self):
        self.auth("admin")
        self.sa_invoice(number="INV-1")
        r = self.client.post(f"{self.base}/einvoices", {"country": "SA", "number": "INV-1", "lines": [{"description": "a", "unit_price": "1"}]}, format="json")
        self.assertEqual(r.status_code, 409)


class ZatcaPrepareTests(Base):
    def test_prepare_needs_onboarding(self):
        self.sa_profile(onboarded=False)
        data = self.sa_invoice()
        r = self.client.post(f"{self.base}/einvoices/{data['id']}/prepare")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"], "not_onboarded")

    def test_prepare_signs_and_chains(self):
        profile = self.sa_profile()
        ids = [self.sa_invoice()["id"] for _ in range(3)]
        with no_network():
            results = [self.client.post(f"{self.base}/einvoices/{i}/prepare").json() for i in ids]
        self.assertEqual([r["icv"] for r in results], [1, 2, 3])
        self.assertEqual(results[0]["pih"], ubl.INITIAL_PIH)
        self.assertEqual(results[1]["pih"], results[0]["invoice_hash"])
        self.assertEqual(results[2]["pih"], results[1]["invoice_hash"])
        self.assertEqual(services.chain_ok(self.org), {"ok": True, "count": 3})
        profile.refresh_from_db()
        self.assertEqual((profile.icv_counter, profile.last_hash), (3, results[2]["invoice_hash"]))
        invoice = Invoice.objects.get(pk=ids[0])
        self.assertEqual(ubl.invoice_hash(invoice.xml), invoice.invoice_hash)
        self.assertEqual(qr.decode(invoice.qr)[6].decode(), invoice.invoice_hash)
        self.assertEqual(results[0]["qr_fields"]["2"], SA_VAT)
        root = etree.fromstring(invoice.xml.encode())
        self.assertEqual(root.xpath("string(//cbc:UUID)", namespaces=ubl.XPATH_NS), str(invoice.id))
        # the XML download
        xml = self.client.get(f"{self.base}/einvoices/{ids[0]}/xml").json()
        self.assertEqual(xml["xml"], invoice.xml)
        # tampering with the chain is detected
        Invoice.objects.filter(pk=ids[1]).update(pih="AAAA")
        self.assertFalse(services.chain_ok(self.org)["ok"])

    def test_standard_invoice_needs_buyer(self):
        self.sa_profile()
        data = self.sa_invoice(invoice_type="standard")
        r = self.client.post(f"{self.base}/einvoices/{data['id']}/prepare")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Invoice.objects.get(pk=data["id"]).status, "draft")


class ZatcaSubmitTests(Base):
    def ready_invoice(self, **extra):
        self.sa_profile()
        data = self.sa_invoice(**extra)
        self.assertEqual(self.client.post(f"{self.base}/einvoices/{data['id']}/prepare").status_code, 200)
        return data["id"]

    def test_submit_waits_for_approval_then_reports(self):
        invoice_id = self.ready_invoice()
        with no_network():
            r = self.client.post(f"{self.base}/einvoices/{invoice_id}/submit")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()["invoice"]["waiting_approval"])
        self.assertIn("ZATCA for reporting", r.json()["approval"]["summary"])
        self.assertEqual(self.client.post(f"{self.base}/einvoices/{invoice_id}/submit").status_code, 409)  # already waiting
        net = FakeNet({("POST", "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal/invoices/reporting/single"): [(200, {"reportingStatus": "REPORTED", "validationResults": {"status": "PASS", "infoMessages": [], "warningMessages": [], "errorMessages": []}})]})
        with net.patch():
            r = self.client.post(f"{self.base}/einvoices/{invoice_id}/approval/approve")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["invoice"]["status"], "accepted")
        self.assertEqual(r.json()["approval"]["status"], "executed")
        call = net.calls[0]
        self.assertEqual(call["headers"]["Accept-Version"], "V2")
        invoice = Invoice.objects.get(pk=invoice_id)
        token = json.loads(TaxProfile.objects.get(org=self.org, country="SA").secret("production"))["token"]
        self.assertEqual(call["headers"]["Authorization"], "Basic " + base64.b64encode(f"{token}:{SECRET}".encode()).decode())
        body = json.loads(call["body"])
        self.assertEqual(body["invoiceHash"], invoice.invoice_hash)
        self.assertEqual(body["uuid"], str(invoice.id))
        self.assertEqual(base64.b64decode(body["invoice"]).decode(), invoice.xml)
        self.assertEqual(AuthorityEvent.objects.filter(invoice=invoice, action="reporting").count(), 1)

    def test_clearance_and_rejection_recorded(self):
        invoice_id = self.ready_invoice(
            invoice_type="standard", buyer_name="Buyer", buyer_tax_number="311111111100003", buyer_street="Tahlia", buyer_city="Jeddah", supply_date="2026-10-01",
        )
        self.client.post(f"{self.base}/einvoices/{invoice_id}/submit")
        answer = {"clearanceStatus": "NOT_CLEARED", "validationResults": {"status": "ERROR", "errorMessages": [{"type": "ERROR", "code": "BR-KSA-XX", "category": "KSA", "message": "Example error", "status": "ERROR"}]}}
        net = FakeNet({("POST", "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal/invoices/clearance/single"): [(400, answer)]})
        with net.patch():
            r = self.client.post(f"{self.base}/einvoices/{invoice_id}/approval/approve")
        self.assertEqual(net.calls[0]["headers"]["Clearance-Status"], "1")
        data = r.json()["invoice"]
        self.assertEqual(data["status"], "rejected")
        self.assertEqual(data["authority_status"], "NOT_CLEARED")
        self.assertEqual(data["authority_response"]["errorMessages"][0]["code"], "BR-KSA-XX")
        # a rejected invoice is copied to a new draft, never edited
        copy = self.client.post(f"{self.base}/einvoices/{invoice_id}/copy").json()
        self.assertEqual(copy["status"], "draft")
        self.assertNotEqual(copy["number"], data["number"])

    def test_network_error_marks_error_and_can_retry(self):
        invoice_id = self.ready_invoice()
        self.client.post(f"{self.base}/einvoices/{invoice_id}/submit")
        with patch("einvoice.transport._send", side_effect=OSError("down")):
            data = self.client.post(f"{self.base}/einvoices/{invoice_id}/approval/approve").json()["invoice"]
        self.assertEqual(data["status"], "error")
        self.assertEqual(self.client.post(f"{self.base}/einvoices/{invoice_id}/submit").status_code, 201)

    def test_reject_sends_nothing(self):
        invoice_id = self.ready_invoice()
        self.client.post(f"{self.base}/einvoices/{invoice_id}/submit")
        with no_network():
            r = self.client.post(f"{self.base}/einvoices/{invoice_id}/approval/reject")
        self.assertEqual(r.json()["approval"]["status"], "rejected")
        self.assertEqual(r.json()["invoice"]["status"], "ready")

    def test_only_the_proposer_decides(self):
        invoice_id = self.ready_invoice()
        self.client.post(f"{self.base}/einvoices/{invoice_id}/submit")
        self.auth("owner")
        with no_network():
            r = self.client.post(f"{self.base}/einvoices/{invoice_id}/approval/approve")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Invoice.objects.get(pk=invoice_id).status, "ready")

    def test_draft_cannot_be_submitted(self):
        self.sa_profile()
        data = self.sa_invoice()
        self.assertEqual(self.client.post(f"{self.base}/einvoices/{data['id']}/submit").status_code, 409)


class OnboardingTests(Base):
    def test_full_flow_with_mocked_zatca(self):
        self.sa_profile(onboarded=False)
        r = self.client.post(f"{self.base}/einvoice/zatca/key")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["onboarding"], "key_ready")
        profile = TaxProfile.objects.get(org=self.org, country="SA")
        self.assertNotIn(b"PRIVATE KEY", bytes(profile.private_key_ciphertext))  # encrypted at rest
        self.assertIn("BEGIN CERTIFICATE REQUEST", self.client.get(f"{self.base}/einvoice/zatca/csr").json()["csr"])
        self.assertEqual(self.client.post(f"{self.base}/einvoice/zatca/compliance", {"otp": "12"}, format="json").status_code, 400)
        token, _ = token_for()
        base = "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal"
        net = FakeNet(
            {
                ("POST", f"{base}/compliance/invoices"): [(200, {"reportingStatus": "REPORTED", "validationResults": {"status": "PASS"}})],
                ("POST", f"{base}/compliance"): [(200, {"requestID": 1234567890123, "dispositionMessage": "ISSUED", "binarySecurityToken": token, "secret": SECRET})],
                ("POST", f"{base}/production/csids"): [(200, {"requestID": 30368, "dispositionMessage": "ISSUED", "binarySecurityToken": token, "secret": SECRET})],
            }
        )
        with net.patch():
            r = self.client.post(f"{self.base}/einvoice/zatca/compliance", {"otp": "123456"}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(net.calls[0]["headers"]["OTP"], "123456")
            self.assertEqual(base64.b64decode(json.loads(net.calls[0]["body"])["csr"]).decode(), profile.csr_pem if profile.csr_pem else TaxProfile.objects.get(pk=profile.pk).csr_pem)
            r = self.client.post(f"{self.base}/einvoice/zatca/checks")
            self.assertEqual(r.json()["onboarding"], "checks_passed", r.content)
            self.assertEqual(len(r.json()["compliance_results"]), 6)  # 1100: standard and simplified x invoice, credit, debit
            r = self.client.post(f"{self.base}/einvoice/zatca/production")
            self.assertEqual(r.json()["onboarding"], "production")
        check_calls = [c for c in net.calls if c["url"].endswith("/compliance/invoices")]
        self.assertEqual(len(check_calls), 6)
        self.assertEqual(json.loads(net.calls[-1]["body"]), {"compliance_request_id": "1234567890123"})
        # the samples used their own chain: the production counter is untouched
        profile = TaxProfile.objects.get(pk=profile.pk)
        self.assertEqual(profile.icv_counter, 0)
        body = json.dumps(self.client.get(f"{self.base}/einvoice/meta").json())
        for secret in (SECRET, token, "PRIVATE KEY"):
            self.assertNotIn(secret, body)

    def test_rejected_otp(self):
        self.sa_profile(onboarded=False)
        self.client.post(f"{self.base}/einvoice/zatca/key")
        net = FakeNet({("POST", "https://gw-fatoora.zatca.gov.sa/"): [(400, {"errors": [{"code": "Invalid-OTP", "message": "Invalid OTP"}]})]})
        with net.patch():
            r = self.client.post(f"{self.base}/einvoice/zatca/compliance", {"otp": "000000"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(TaxProfile.objects.get(org=self.org, country="SA").onboarding, "key_ready")

    def test_environment_locked_after_onboarding_and_reset(self):
        self.sa_profile()
        r = self.client.put(f"{self.base}/einvoice/settings/SA", {"environment": "production"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.post(f"{self.base}/einvoice/zatca/reset").json()["onboarding"], "none")
        profile = TaxProfile.objects.get(org=self.org, country="SA")
        self.assertFalse(profile.has_secret("private_key") or profile.has_secret("production"))
        self.assertEqual(self.client.put(f"{self.base}/einvoice/settings/SA", {"environment": "production"}, format="json").status_code, 200)

    @override_settings(CREDENTIALS_ENCRYPTION_KEY="")
    def test_no_encryption_key_no_secrets(self):
        self.auth("admin")
        r = self.client.put(f"{self.base}/einvoice/settings/EG", {"client_secret": "x" * 20}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_validation_of_profile(self):
        self.auth("admin")
        self.assertEqual(self.client.put(f"{self.base}/einvoice/settings/SA", {"tax_number": "123456789012345"}, format="json").status_code, 400)
        self.assertEqual(self.client.put(f"{self.base}/einvoice/settings/EG", {"tax_number": "12"}, format="json").status_code, 400)
        self.assertEqual(self.client.put(f"{self.base}/einvoice/settings/XX", {}, format="json").status_code, 400)


class EtaTests(Base):
    def test_secrets_masked_and_encrypted(self):
        profile = self.eg_profile()
        self.assertNotIn(ETA_SECRET.encode(), bytes(profile.client_secret_ciphertext))
        self.assertEqual(profile.secret("client_secret"), ETA_SECRET)
        body = json.dumps(self.client.get(f"{self.base}/einvoice/meta").json(), ensure_ascii=False)
        self.assertNotIn(ETA_SECRET, body)
        self.assertIn("…7d6c", body)

    def test_manual_signing_submit_and_poll(self):
        self.eg_profile()
        data = self.eg_invoice()
        self.assertEqual(data["totals"]["tax_inclusive"], "2280.00000")
        r = self.client.post(f"{self.base}/einvoices/{data['id']}/prepare")
        self.assertEqual(r.status_code, 200, r.content)
        doc = self.client.get(f"{self.base}/einvoices/{data['id']}/eta-document").json()
        parsed = json.loads(doc["document"])
        self.assertEqual(parsed["documentType"], "I")
        self.assertEqual(parsed["documentTypeVersion"], "1.0")
        self.assertEqual(parsed["issuer"]["address"]["branchID"], "0")
        self.assertEqual(parsed["receiver"]["type"], "B")
        self.assertEqual(parsed["invoiceLines"][0]["taxableItems"][0], {"taxType": "T1", "amount": 280, "subType": "V009", "rate": 14})
        self.assertIn('"TAXABLEITEMS""TAXABLEITEMS""TAXTYPE""T1""AMOUNT""280.00""SUBTYPE""V009""RATE""14.00"', doc["canonical"])
        self.assertNotIn("SIGNATURES", doc["canonical"])
        # manual mode: no sending until the signature from the token is uploaded
        r = self.client.post(f"{self.base}/einvoices/{data['id']}/submit")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.post(f"{self.base}/einvoices/{data['id']}/signature", {"signature": "bm9wZQ=="}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{self.base}/einvoices/{data['id']}/signature", {"signature": fake_cms()}, format="json").status_code, 200)
        self.assertEqual(self.client.post(f"{self.base}/einvoices/{data['id']}/submit").status_code, 201)
        net = FakeNet(
            {
                ("POST", "https://id.preprod.eta.gov.eg/connect/token"): [(200, {"access_token": "eta-access-NOT-REAL", "expires_in": 3600})],
                ("POST", "https://api.preprod.invoicing.eta.gov.eg/api/v1.0/documentsubmissions/"): [
                    (202, {"submissionUUID": "S" * 26, "acceptedDocuments": [{"uuid": "U" * 26, "longId": "L" * 42, "internalId": data["number"]}], "rejectedDocuments": []})
                ],
                ("GET", "https://api.preprod.invoicing.eta.gov.eg/api/v1.0/documentsubmissions/"): [
                    (200, {"overallStatus": "valid", "documentSummary": [{"uuid": "U" * 26, "internalId": data["number"], "status": "Valid"}]})
                ],
            }
        )
        with net.patch():
            r = self.client.post(f"{self.base}/einvoices/{data['id']}/approval/approve")
            self.assertEqual(r.json()["invoice"]["status"], "submitted", r.content)
            r = self.client.post(f"{self.base}/einvoices/{data['id']}/poll")
        self.assertEqual(r.json()["status"], "accepted")
        token_body = net.calls[0]["body"].decode()
        self.assertIn("grant_type=client_credentials", token_body)
        self.assertIn("scope=InvoicingAPI", token_body)
        submitted = json.loads(net.calls[1]["body"])["documents"][0]
        self.assertEqual(submitted["signatures"], [{"signatureType": "I", "value": fake_cms()}])
        self.assertEqual(net.calls[1]["headers"]["Authorization"], "Bearer eta-access-NOT-REAL")
        self.assertIn("pageNo=1", net.calls[-1]["url"])

    def test_rejected_document(self):
        self.eg_profile()
        data = self.eg_invoice()
        self.client.post(f"{self.base}/einvoices/{data['id']}/prepare")
        self.client.post(f"{self.base}/einvoices/{data['id']}/signature", {"signature": fake_cms()}, format="json")
        self.client.post(f"{self.base}/einvoices/{data['id']}/submit")
        net = FakeNet({
            ("POST", "https://id.preprod.eta.gov.eg/"): [(200, {"access_token": "t"})],
            ("POST", "https://api.preprod.invoicing.eta.gov.eg/"): [(202, {"submissionUUID": "S" * 26, "acceptedDocuments": [], "rejectedDocuments": [{"internalId": data["number"], "error": {"code": "BadStructure", "message": "Invalid", "details": [{"code": "x", "message": "receiver.id"}]}}]})],
        })
        with net.patch():
            r = self.client.post(f"{self.base}/einvoices/{data['id']}/approval/approve")
        invoice = r.json()["invoice"]
        self.assertEqual(invoice["status"], "rejected")
        self.assertEqual(invoice["authority_response"]["rejected"][0]["error"]["code"], "BadStructure")

    @override_settings(EINVOICE_SIGNER_ALLOWED_HOSTS="signer.customer.example")
    def test_external_signer_allowlist_and_flow(self):
        self.auth("admin")
        self.assertEqual(self.client.put(f"{self.base}/einvoice/settings/EG", {"signer_url": "https://evil.example/sign"}, format="json").status_code, 400)
        self.assertEqual(self.client.put(f"{self.base}/einvoice/settings/EG", {"signer_url": "http://signer.customer.example/sign"}, format="json").status_code, 400)
        self.eg_profile(signer_mode="external", signer_url="https://signer.customer.example/sign", signer_token="signer-token-NOT-REAL-1234")
        data = self.eg_invoice()
        self.client.post(f"{self.base}/einvoices/{data['id']}/prepare")
        self.assertEqual(self.client.post(f"{self.base}/einvoices/{data['id']}/submit").status_code, 201)
        net = FakeNet({
            ("POST", "https://signer.customer.example/sign"): [(200, {"signature": fake_cms()})],
            ("POST", "https://id.preprod.eta.gov.eg/"): [(200, {"access_token": "t"})],
            ("POST", "https://api.preprod.invoicing.eta.gov.eg/"): [(202, {"submissionUUID": "S" * 26, "acceptedDocuments": [{"uuid": "U" * 26, "longId": "L", "internalId": data["number"]}]})],
        })
        with net.patch():
            r = self.client.post(f"{self.base}/einvoices/{data['id']}/approval/approve")
        self.assertEqual(r.json()["invoice"]["status"], "submitted")
        sign_call = net.calls[0]
        self.assertEqual(sign_call["target"], "signer")
        self.assertEqual(sign_call["headers"]["Authorization"], "Bearer signer-token-NOT-REAL-1234")
        sent = json.loads(sign_call["body"])
        invoice = Invoice.objects.get(pk=data["id"])
        self.assertEqual(base64.b64decode(sent["canonical_b64"]).decode(), services.eta_canonical(invoice))
        self.assertNotIn("signer-token-NOT-REAL", json.dumps(self.client.get(f"{self.base}/einvoice/meta").json()))

    @override_settings(EINVOICE_SIGNER_ALLOWED_HOSTS="signer.customer.example")
    def test_signer_failure_is_an_error_not_a_fake_signature(self):
        self.eg_profile(signer_mode="external", signer_url="https://signer.customer.example/sign")
        data = self.eg_invoice()
        self.client.post(f"{self.base}/einvoices/{data['id']}/prepare")
        self.client.post(f"{self.base}/einvoices/{data['id']}/submit")
        net = FakeNet({("POST", "https://signer.customer.example/sign"): [(200, {"signature": base64.b64encode(b"not cms").decode()})]})
        with net.patch():
            r = self.client.post(f"{self.base}/einvoices/{data['id']}/approval/approve")
        invoice = r.json()["invoice"]
        self.assertEqual(invoice["status"], "error")
        self.assertFalse(invoice["eta_signed"])
        self.assertEqual(len(net.calls), 1)  # nothing went to the ETA

    def test_eg_prepare_requirements(self):
        self.eg_profile()
        data = self.eg_invoice(lines=[{"description": "No code", "unit_price": "10"}])
        self.assertEqual(self.client.post(f"{self.base}/einvoices/{data['id']}/prepare").status_code, 409)
        quoted = self.eg_invoice(number="EG-Q", lines=[{"description": 'Say "hi"', "unit_price": "10", "item_type": "EGS", "item_code": "EG-1"}])
        self.assertEqual(self.client.post(f"{self.base}/einvoices/{quoted['id']}/prepare").status_code, 400)


class TransportTests(TestCase):
    def test_allowlist(self):
        from einvoice import transport

        for url in ("https://evil.example/x", "http://gw-fatoora.zatca.gov.sa/x", "https://gw-fatoora.zatca.gov.sa:8443/x", "https://user:pw@gw-fatoora.zatca.gov.sa/x"):
            with self.assertRaises(TransportError, msg=url):
                transport.request("zatca", "POST", url)
        with self.assertRaises(TransportError):
            transport.request("signer", "POST", "https://signer.customer.example/x")  # nothing allowlisted by default
        with self.assertRaises(TransportError):
            transport.request("eta", "POST", "https://gw-fatoora.zatca.gov.sa/x")  # ZATCA host is not an ETA host

    @override_settings(EINVOICE_ZATCA_BASE_SANDBOX="https://attacker.example/zatca")
    def test_overridden_base_url_still_allowlisted(self):
        from einvoice.zatca import api

        with self.assertRaises(TransportError):
            api.reporting("sandbox", "t", "s", "h", "u", "<x/>")

    def test_private_signer_address_refused(self):
        from einvoice import transport

        with override_settings(EINVOICE_SIGNER_ALLOWED_HOSTS="signer.local.example"), patch("platform_api.net.resolve", return_value=["10.0.0.5"]):
            with self.assertRaises(TransportError) as ctx:
                transport.request("signer", "POST", "https://signer.local.example/sign")
        self.assertEqual(ctx.exception.code, "blocked_host")


class ToolTests(Base):
    def test_prepare_tool_needs_approval_and_creates_a_draft(self):
        from actions import service

        self.auth("admin")
        args = {"country": "SA", "invoice_type": "simplified", "lines": [{"description": "Plan", "quantity": "2", "unit_price": "100"}]}
        summary = service.check("einvoice.prepare", self.users["admin"], self.org, args)
        self.assertIn("SAR 230.00", summary)
        self.assertEqual(Invoice.objects.count(), 0)  # checking creates nothing
        proposal = ActionProposal.objects.create(org=self.org, user=self.users["admin"], tool_key="einvoice.prepare", arguments=args, summary=summary)
        proposal = service.approve(proposal.id, self.users["admin"], self.org)
        self.assertEqual(proposal.status, "executed", proposal.error)
        invoice = Invoice.objects.get(pk=proposal.result["invoice"])
        self.assertEqual((invoice.status, invoice.source, str(invoice.tax_inclusive)), ("draft", "buddy", "230.00000"))

    def test_tools_refused_without_flag_or_permission(self):
        from actions import service

        args = {"country": "SA", "invoice_type": "simplified", "lines": [{"description": "Plan", "unit_price": "100"}]}
        with self.assertRaises(ActionDenied):
            service.check("einvoice.prepare", self.users["member"], self.org, args)
        self.org.settings = {"flags": {"einvoice": False}}
        self.org.save()
        with self.assertRaises(ActionDenied):
            service.check("einvoice.prepare", self.users["admin"], self.org, args)

    def test_submit_tool_refuses_unprepared(self):
        from actions import service

        self.sa_profile()
        data = self.sa_invoice()
        with self.assertRaises(ActionDenied) as ctx:
            service.check("einvoice.submit", self.users["admin"], self.org, {"invoice": data["id"]})
        self.assertEqual(ctx.exception.code, "not_available")

    @override_settings(DEMO_MODE=True, DEMO_AI=True)
    def test_demo_model_proposes_prepare(self):
        from brain.llm.demo_handlers import einvoice as handler

        tools = [{"function": {"name": "einvoice__prepare"}}]
        result = handler.handle("You are a FloBrain buddy.", "", [{"role": "user", "content": "Draft a ZATCA e-invoice for Gulf Retail for 4,500 SAR"}], tools)
        args = json.loads(result.tool_calls[0]["arguments"])
        self.assertEqual((args["country"], args["invoice_type"], args["buyer_name"], args["lines"][0]["unit_price"]), ("SA", "standard", "Gulf Retail", "4500.00"))
        self.assertIsNone(handler.handle("You are a FloBrain buddy.", "", [{"role": "user", "content": "hello"}], tools))
        self.assertIsNone(handler.handle("other", "", [{"role": "user", "content": "ZATCA invoice"}], tools))


class ImportTests(Base):
    def test_odoo_import_reads_through_the_write_connection(self):
        from integrations.write.models import WriteConnection
        from integrations.write.testing import FakeNet as WriteNet

        conn = WriteConnection(org=self.org, provider="odoo", account_label="odoo", scopes=[], config={"url": "https://acme.odoo.com", "database": "acme", "uid": 7}, connected_by=self.users["admin"])
        conn.set_secrets("odoo-api-key-NOT-REAL")
        conn.save()
        net = WriteNet({("POST", "https://acme.odoo.com/jsonrpc"): [
            (200, {"result": [{"name": "INV/2026/0007", "partner_id": [3, "Gulf Retail"], "invoice_line_ids": [11, 12], "move_type": "out_invoice", "currency_id": [1, "SAR"]}]}),
            (200, {"result": [{"vat": "311111111100003"}]}),
            (200, {"result": [{"name": "Setup", "quantity": 1, "price_unit": 1000.0, "discount": 10.0, "display_type": "product", "tax_ids": [1]}, {"name": "Section", "display_type": "line_section"}]}),
        ]})
        self.auth("admin")
        with net.patch():
            r = self.client.post(f"{self.base}/einvoices/import", {"provider": "odoo", "ref": "7", "country": "SA", "invoice_type": "standard"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()
        self.assertEqual((data["buyer_name"], data["buyer_tax_number"], data["source"]), ("Gulf Retail", "311111111100003", "odoo"))
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(data["totals"]["tax_inclusive"], "1035.00")  # 1000 - 10% = 900, + 15%
        self.assertEqual(json.loads(net.calls[0]["body"])["params"]["args"][3:5], ["account.move", "read"])

    def test_import_without_connection(self):
        self.auth("admin")
        r = self.client.post(f"{self.base}/einvoices/import", {"provider": "odoo", "ref": "7", "country": "SA"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.post(f"{self.base}/einvoices/import", {"provider": "sap", "ref": "7", "country": "SA"}, format="json").status_code, 400)


class ResidencyTests(Base):
    @override_settings(DATA_REGION_DEPLOYMENT="sa", AI_SELF_HOSTED_HOSTS="vllm.internal", AI_DIRECT_BASE_URL="https://api.openai.example/v1", ASR_BASE_URL="https://vllm.internal/asr", CONTENT_STORAGE="s3", CONTENT_S3_REGION="eu-central-1", DATA_REGION_HOSTS="api.openai.example=us")
    def test_report_and_pinning(self):
        self.auth("admin")
        r = self.client.patch(f"{self.base}/einvoice/residency", {"region": "sa", "pinned": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        rows = {row["class"]: row for row in r.json()["classes"]}
        self.assertEqual(rows["database"]["status"], "ok")
        self.assertEqual(rows["files"]["status"], "mismatch")  # eu-central-1
        self.assertEqual(rows["ai"]["status"], "blocked")  # api.openai.example is in the US
        self.assertEqual(rows["transcription"]["status"], "ok")  # self-hosted in the deployment region
        self.assertIn("ai", r.json()["mismatches"])
        self.org.refresh_from_db()
        from einvoice import residency

        self.assertFalse(residency.allowed_ai_host(self.org, "api.openai.example"))
        self.assertTrue(residency.allowed_ai_host(self.org, "vllm.internal"))
        self.assertTrue(residency.allowed_ai_host(self.org, ""))
        self.assertEqual(residency.check_ai_residency(self.org, "direct"), "data_region")
        self.assertEqual(residency.check_ai_residency(self.org, "legacy"), "data_region")
        with override_settings(DATA_REGION_AI_HOSTS_SA="api.openai.example"):
            self.assertTrue(residency.allowed_ai_host(self.org, "api.openai.example"))
        r = self.client.patch(f"{self.base}/einvoice/residency", {"pinned": False}, format="json")
        self.org.refresh_from_db()
        self.assertTrue(residency.allowed_ai_host(self.org, "api.openai.example"))

    def test_validation_and_permissions(self):
        self.auth("admin")
        self.assertEqual(self.client.patch(f"{self.base}/einvoice/residency", {"region": "mars"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(f"{self.base}/einvoice/residency", {"pinned": "yes"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(f"{self.base}/einvoice/residency", {"pinned": True}, format="json").json()["pinned"], False)  # no region yet
        self.auth("member")
        self.assertEqual(self.client.patch(f"{self.base}/einvoice/residency", {"region": "sa"}, format="json").status_code, 403)

    def test_unpinned_org_not_restricted(self):
        from einvoice import residency

        self.assertTrue(residency.allowed_ai_host(self.org, "anything.example"))
        self.assertEqual(residency.cloud_region("me-central-1"), "ae")
        self.assertEqual(residency.cloud_region("me-central2"), "sa")
        self.assertEqual(residency.cloud_region("eu-west-1"), "eu")
        self.assertEqual(residency.cloud_region("ap-south-1"), "unknown")


@override_settings(CREDENTIALS_ENCRYPTION_KEY=TEST_KEY, DEMO_MODE=True)
class DemoTests(TestCase):
    def test_seed_and_simulated_submission(self):
        import importlib

        org = Organization.objects.create(name="Demo", slug="demo-e", settings={"flags": {"einvoice": True}, "demo": True})
        users = {}
        for key, role in (("admin", "admin"), ("member", "member")):
            user = User.objects.create(email=f"d-{key}@example.com", username=f"d-{key}", password_hash=make_password("x"))
            OrgMembership.objects.create(org=org, user=user, org_role=role, employment_status="active")
            users[key] = user
        seed = importlib.import_module("demo.extras.a3_einvoice").seed
        with no_network():
            seed(org, users, timezone.now())
        statuses = sorted(Invoice.objects.filter(org=org).values_list("status", flat=True))
        self.assertEqual(len(statuses), 8)
        self.assertEqual(statuses, sorted(["accepted", "accepted", "rejected", "ready", "draft", "accepted", "submitted", "error"]))
        self.assertTrue(services.chain_ok(org)["ok"])
        waiting = Invoice.objects.get(org=org, status="ready")
        self.assertIsNotNone(services.pending_proposal(waiting))
        # approving in the demo simulates ZATCA: no network
        from actions import service

        with no_network():
            proposal = service.approve(waiting.proposal_id, users["admin"], org)
        self.assertEqual(proposal.status, "executed", proposal.error)
        waiting.refresh_from_db()
        self.assertEqual((waiting.status, waiting.simulated), ("accepted", True))
        # the submitted Egyptian invoice polls to accepted without the network
        submitted = Invoice.objects.get(org=org, status="submitted")
        with no_network():
            services.poll(users["admin"], org, submitted)
        self.assertEqual(submitted.status, "accepted")

    @override_settings(DEMO_MODE=False)
    def test_demo_profile_outside_demo_mode_is_refused(self):
        org = Organization.objects.create(name="Real", slug="real-e", settings={"flags": {"einvoice": True}})
        profile = TaxProfile.objects.create(org=org, country="SA", demo=True, onboarding=TaxProfile.ONB_PRODUCTION)
        invoice = Invoice.objects.create(org=org, country="SA", invoice_type="simplified", number="X-1", currency="SAR", status="ready")
        self.assertIn("demo workspace", services.submit_blocker(invoice, profile))
