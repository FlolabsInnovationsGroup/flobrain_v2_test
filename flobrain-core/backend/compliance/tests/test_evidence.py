"""Evidence packages: manifest hashes, contents, no key material, storage, expiry, download permissions."""

import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from compliance import evidence
from compliance.models import EvidencePackage
from compliance.tests.base import MASTER_KEY, TEST_KEY, ComplianceBase
from integrations import crypto
from organizations.services.core import audit

SSO_SECRET = "sso-client-secret-Zq81mXv0PplR"
SCIM_TOKEN = "scim-raw-token-77Hh2kQ9wErT0"
OAUTH_ACCESS = "ya29.oauth-access-token-AbC123XyZ"


class EvidenceBase(ComplianceBase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="compliance-evidence-")
        self.storage = override_settings(CONTENT_STORAGE="local", CONTENT_LOCAL_DIR=self.tmp)
        self.storage.enable()
        self.env = patch.dict(os.environ, {"AES_MASTER_KEY": MASTER_KEY})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.storage.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def seed_secrets(self):
        """Put real-looking secrets where FloBrain keeps them, and in an audit payload."""
        from integrations.write.models import WriteConnection
        from sso.models import SCIMToken, SSOConnection

        conn = SSOConnection.objects.create(org=self.org, issuer="https://idp.example.com", client_id="client-1", secret_ciphertext=b"", enabled=True, enforced=True, verified_domains=["example.com"])
        conn.secret_ciphertext = crypto.encrypt(SSO_SECRET, conn.id, self.org.id)
        conn.save()
        SCIMToken.objects.create(org=self.org, token_hash=hashlib.sha256(SCIM_TOKEN.encode()).hexdigest(), last4=SCIM_TOKEN[-4:])
        wc = WriteConnection.objects.create(org=self.org, owner=self.users["member"], provider="google")
        wc.set_secrets(OAUTH_ACCESS, "refresh-" + OAUTH_ACCESS)
        wc.save()
        audit(self.users["admin"], "integration.connect", org=self.org, payload={"provider": "x", "client_secret": SSO_SECRET, "nested": {"api_key": "sk-abcdefghijklmnopqrstuv"}, "note": "-----BEGIN RSA PRIVATE KEY----- abc"})

    def generate(self):
        self.auth("admin")
        response = self.client.post(f"{self.base}/evidence", {}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return EvidencePackage.objects.get(pk=response.json()["id"])

    def download(self, package, key="admin"):
        self.auth(key)
        return self.client.get(f"{self.base}/evidence/{package.id}/download")


class PackageTests(EvidenceBase):
    def test_manifest_hashes_match_every_file(self):
        audit(self.users["admin"], "member.role", org=self.org, payload={"to": "admin"})
        package = self.generate()
        response = self.download(package)
        self.assertEqual(response.status_code, 200)
        data = response.content
        self.assertEqual(hashlib.sha256(data).hexdigest(), package.sha256)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))
            listed = {f["path"] for f in manifest["files"]}
            self.assertEqual(listed | {"manifest.json"}, names)
            for entry in manifest["files"]:
                body = zf.read(entry["path"])
                self.assertEqual(hashlib.sha256(body).hexdigest(), entry["sha256"], entry["path"])
                self.assertEqual(len(body), entry["bytes"])
            for wanted in ("controls.json", "controls.csv", "checks.json", "audit_log.csv", "access_reviews.json",
                           "access_review_items.csv", "policies.json", "policy_acknowledgements.csv", "config_snapshot.json", "README.txt"):
                self.assertIn(wanted, names)
            self.assertIn("member.role", zf.read("audit_log.csv").decode())
            self.assertIn("not a certification", zf.read("README.txt").decode())
        self.assertEqual(package.manifest["files"], manifest["files"])

    def test_no_key_material_in_the_zip(self):
        self.seed_secrets()
        package = self.generate()
        data = self.download(package).content
        blobs = [data]
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            blobs += [zf.read(n) for n in zf.namelist()]
            snapshot = json.loads(zf.read("config_snapshot.json"))
        text = b"\n".join(blobs).decode("utf-8", errors="ignore")
        for secret in (TEST_KEY, MASTER_KEY, SSO_SECRET, SCIM_TOKEN, OAUTH_ACCESS, "sk-abcdefghijklmnopqrstuv", "BEGIN RSA PRIVATE KEY",
                       hashlib.sha256(SCIM_TOKEN.encode()).hexdigest()):
            self.assertNotIn(secret, text, secret)
        self.assertEqual(snapshot["encryption"]["stored_data_encryption"], "set")
        self.assertEqual(snapshot["encryption"]["memory_archive_encryption"], "set")
        self.assertTrue(snapshot["sso"]["enforced"])
        self.assertNotIn("client_id", snapshot["sso"])

    def test_csv_cells_cannot_run_formulas(self):
        audit(self.users["admin"], "=HYPERLINK(\"http://evil\")", org=self.org)
        package = self.generate()
        with zipfile.ZipFile(io.BytesIO(self.download(package).content)) as zf:
            body = zf.read("audit_log.csv").decode()
        self.assertIn("'=HYPERLINK", body)

    def test_audit_extract_respects_the_period(self):
        old = audit(self.users["admin"], "old.action", org=self.org)
        type(old).objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=200))
        audit(self.users["admin"], "new.action", org=self.org)
        package = self.generate()  # default: the last 90 days
        with zipfile.ZipFile(io.BytesIO(self.download(package).content)) as zf:
            body = zf.read("audit_log.csv").decode()
        self.assertIn("new.action", body)
        self.assertNotIn("old.action", body)

    def test_expired_packages_are_deleted(self):
        package = self.generate()
        path = os.path.join(self.tmp, *package.storage_key.split("/"))
        self.assertTrue(os.path.isfile(path))
        EvidencePackage.objects.filter(pk=package.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.download(package).status_code, 410)
        self.assertEqual(evidence.expire(), 1)
        self.assertFalse(os.path.isfile(path))
        package.refresh_from_db()
        self.assertEqual(package.status, "expired")

    def test_valid_for_seven_days(self):
        package = self.generate()
        self.assertAlmostEqual((package.expires_at - package.created_at).total_seconds(), 7 * 86400, delta=60)

    def test_only_compliance_manage_downloads(self):
        package = self.generate()
        self.assertEqual(self.download(package, "member").status_code, 403)
        from organizations.models import PermissionGrant

        PermissionGrant.objects.create(org=self.org, grantee=self.users["member"], perm_key="compliance.view")
        self.assertEqual(self.download(package, "member").status_code, 403)
        self.auth("member")
        self.assertEqual(self.client.get(f"{self.base}/evidence").status_code, 200)
        self.assertEqual(self.client.post(f"{self.base}/evidence", {}, format="json").status_code, 403)

    def test_bad_period(self):
        self.auth("admin")
        for body in ({"start": "2026-10-10", "end": "2026-10-01"}, {"start": "nope"}, {"start": "2020-01-01", "end": "2026-01-01"}):
            self.assertEqual(self.client.post(f"{self.base}/evidence", body, format="json").status_code, 400, body)


class NoStorageTests(ComplianceBase):
    @override_settings(CONTENT_STORAGE="", DEMO_MODE=False)
    def test_without_storage_it_says_so(self):
        self.auth("admin")
        self.assertEqual(self.client.post(f"{self.base}/evidence", {}, format="json").status_code, 501)
