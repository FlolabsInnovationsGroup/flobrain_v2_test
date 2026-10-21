"""demo/extras/80_platform.py: the platform demo data is there after a demo reset."""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.jwt_utils import make_access_token

KEY = "cd" * 32


@override_settings(DEMO_MODE=True, DEMO_AI=True, CREDENTIALS_ENCRYPTION_KEY=KEY)
class PlatformDemoSeedTests(TestCase):
    def test_seeded_platform_data(self):
        from billing_v2.models import Subscription, UsageInvoiceLine
        from demo import seed
        from demo.models import DemoAccount
        from platform_api.models import DemoInboxDelivery, ExternalAgentCall, ExternalAgentServer, Incident

        org = seed.reset()
        self.assertTrue(Incident.objects.filter(org=org, status="resolved").exists())
        self.assertTrue(Incident.objects.filter(org__isnull=True, is_public=True, title__startswith="Demo: ").exists())
        self.assertEqual(Subscription.objects.get(org=org).plan.code, "studio")  # a8_pricing puts the demo on the workspace plan
        self.assertTrue(UsageInvoiceLine.objects.filter(org=org).exists())
        inbox = DemoInboxDelivery.objects.filter(org=org)
        self.assertTrue(inbox.filter(signature_valid=True).exists() and inbox.filter(signature_valid=False).exists())
        server = ExternalAgentServer.objects.get(org=org)
        self.assertTrue(server.tools_approved)
        member = DemoAccount.objects.get(role="member").user
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(member.id))}")
        calls = client.get(f"/api/v2/orgs/{org.id}/external-agents/calls").json()
        self.assertEqual({c["status"] for c in calls}, {"executed", "proposed"})
        executed = [c for c in calls if c["status"] == "executed"][0]
        self.assertTrue(executed["external"]["instructions_ignored"])
        self.assertEqual(ExternalAgentCall.objects.filter(org=org).count(), 2)
        seed.reset()
        self.assertEqual(Incident.objects.filter(org__isnull=True, title__startswith="Demo: ").count(), 1, "replaced, not duplicated")
