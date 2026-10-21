"""demo/extras/a7_compliance.py: the demo shows a realistic mix after a reset."""

import shutil
import tempfile

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.jwt_utils import make_access_token

KEY = "cd" * 32  # test-only


class ComplianceDemoSeedTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="compliance-demo-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_seeded_compliance_data(self):
        from compliance.models import AccessReview, EvidencePackage, Policy, PolicyAck, TrustCenter
        from demo import seed
        from demo.models import DemoAccount

        with override_settings(DEMO_MODE=True, DEMO_AI=True, CREDENTIALS_ENCRYPTION_KEY=KEY, CONTENT_STORAGE="local", CONTENT_LOCAL_DIR=self.tmp):
            org = seed.reset()
            admin = DemoAccount.objects.get(role="admin").user
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(admin.id))}")
            overview = client.get(f"/api/v2/orgs/{org.id}/compliance/overview").json()
            public = APIClient().get("/api/v2/public/trust/demo")

        for fw in overview["frameworks"]:
            self.assertGreaterEqual(fw["readiness"], 65, (fw["framework"], fw["counts"], [(c["key"], c["status"]) for c in overview["checks"]]))
            self.assertLessEqual(fw["readiness"], 80, fw["framework"])
            self.assertGreater(fw["counts"]["fail"] + fw["counts"]["manual"], 0)
        self.assertEqual(AccessReview.objects.filter(org=org, status="open").count(), 1)
        review = AccessReview.objects.get(org=org, status="open")
        self.assertTrue(review.items.exclude(decision="pending").exists())
        self.assertTrue(review.items.filter(decision="pending").exists())
        published = [p for p in Policy.objects.filter(org=org) if p.versions.exists()]
        self.assertEqual(len(published), 2)
        for policy in published:
            self.assertTrue(PolicyAck.objects.filter(version__policy=policy).exists())
        self.assertTrue(TrustCenter.objects.get(org=org).published)
        self.assertEqual(public.status_code, 200)
        self.assertIn("Amazon Web Services", str(public.json()["subprocessors"]))
        self.assertTrue(EvidencePackage.objects.filter(org=org, status="ready").exists())
