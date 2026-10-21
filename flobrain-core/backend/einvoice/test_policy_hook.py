"""A pinned data region is enforced by brain.llm.policy.check_ai, which every AI call path uses."""

from django.test import TestCase, override_settings

from brain.llm.policy import check_ai
from organizations.models import Organization


@override_settings(AI_DIRECT_BASE_URL="https://api.openai.com", EMBEDDINGS_BACKEND="fake")
class ResidencyPolicyHookTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Riyadh Co", slug="riyadh-co", settings={})

    def test_unpinned_org_is_not_restricted(self):
        self.assertEqual(check_ai(self.org, "direct"), "")

    def test_pinned_org_refuses_ai_outside_its_region(self):
        self.org.settings = {"data_region": {"region": "sa", "pinned": True}}
        self.org.save()
        self.assertEqual(check_ai(self.org, "direct"), "data_region")

    @override_settings(DATA_REGION_AI_HOSTS_SA="api.openai.com")
    def test_pinned_org_allows_hosts_listed_for_its_region(self):
        self.org.settings = {"data_region": {"region": "sa", "pinned": True}}
        self.org.save()
        self.assertEqual(check_ai(self.org, "direct"), "")

    def test_fake_embeddings_never_leave(self):
        self.org.settings = {"data_region": {"region": "sa", "pinned": True}}
        self.org.save()
        self.assertEqual(check_ai(self.org, "embeddings"), "")
