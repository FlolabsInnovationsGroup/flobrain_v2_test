"""demo/extras/92_channels.py: the channels demo is there after a reset and works without a network."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.jwt_utils import make_access_token

KEY = "cd" * 32


@override_settings(DEMO_MODE=True, DEMO_AI=True, CREDENTIALS_ENCRYPTION_KEY=KEY)
@patch("platform_api.net.fetch", side_effect=AssertionError("no network in demo"))
class ChannelsDemoSeedTests(TestCase):
    def test_seeded_and_simulated(self, fetch):
        from channels.models import ChannelConnection, CustomerConversation
        from demo import seed
        from demo.models import DemoAccount

        cache.clear()
        org = seed.reset()
        conns = ChannelConnection.objects.filter(org=org)
        self.assertEqual(sorted(conns.values_list("kind", flat=True)), ["telegram", "website", "whatsapp"])
        self.assertTrue(all(c.demo and c.status == "active" for c in conns))
        convs = CustomerConversation.objects.filter(org=org)
        self.assertEqual(convs.count(), 6)
        self.assertEqual(set(convs.values_list("status", flat=True)), {"open", "waiting_human", "resolved"})

        admin = DemoAccount.objects.get(role="admin").user
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(admin.id))}")
        inbox = client.get(f"/api/v2/orgs/{org.id}/customers/conversations")
        self.assertEqual(len(inbox.json()), 6)
        self.assertEqual(sum(c["drafts"] for c in inbox.json()), 2)
        web = conns.get(kind="website")
        sim = client.post(f"/api/v2/orgs/{org.id}/channels/demo/simulate", {"connection": str(web.id), "text": "What are your support hours?"}, format="json")
        self.assertEqual(sim.status_code, 201, sim.content)
        self.assertIn("(Demo answer)", sim.json()["conversation"]["messages"][-1]["text"])
        tg = conns.get(kind="telegram")
        me = client.post(f"/api/v2/orgs/{org.id}/channels/demo/simulate", {"connection": str(tg.id), "text": "Hi buddy", "from": "me"}, format="json")
        self.assertEqual(me.status_code, 200, me.content)
        self.assertTrue(me.json()["reply"])
        public = self.client.get(f"/api/v2/public/chat/{web.site_key}")
        self.assertEqual(public.json()["name"], "Nile Labs helper")
