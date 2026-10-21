from unittest import mock

from django.test import TestCase, override_settings

from brain.llm.providers import DirectProvider, ProviderResult
from organizations.models import Organization
from pulse.models import RoutingPolicy


def _fake(outcomes):
    calls = []

    def chat_complete(messages, model=None, credential=None, tools=None):
        calls.append(model)
        code = outcomes.get(model, "")
        return ProviderResult(text=None if code else "ok", model=model or "default", error_code=code, provider="p")

    return chat_complete, calls


@override_settings(AI_DIRECT_MODEL_ALLOWLIST="m-a,m-b,m-c", AI_DIRECT_BASE_URL="https://example.invalid", AI_DIRECT_API_KEY="k")
class RoutingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="R", slug="route-org")
        RoutingPolicy.objects.create(org=self.org, primary_model="m-a", fallback_models=["not-allowed", "m-b", "m-c"])

    def test_fails_over_only_on_provider_failures(self):
        fake, calls = _fake({"m-a": "provider_unavailable"})
        with mock.patch("brain.llm.direct.chat_complete", fake):
            result = DirectProvider(self.org).complete([{"role": "user", "content": "hi"}])
        self.assertEqual((result.model, calls), ("m-b", ["m-a", "m-b"]), "the model not on the allowlist is skipped")
        self.assertEqual([f.model for f in result.failed_attempts], ["m-a"])

        fake, calls = _fake({"m-a": "invalid"})
        with mock.patch("brain.llm.direct.chat_complete", fake):
            result = DirectProvider(self.org).complete([{"role": "user", "content": "hi"}])
        self.assertEqual((result.error_code, calls), ("invalid", ["m-a"]), "a refusal is not hidden by a fallback")

    def test_explicit_models_customer_keys_and_no_org_are_not_routed(self):
        fake, calls = _fake({})
        with mock.patch("brain.llm.direct.chat_complete", fake):
            DirectProvider(self.org).complete([], model="m-c")
            DirectProvider(self.org).complete([], credential=object())
            DirectProvider().complete([])
        self.assertEqual(calls, ["m-c", None, None])

    def test_failed_attempts_are_recorded_as_errors(self):
        from telemetry.models import AITrace, UsageEvent
        from telemetry.writers import record_v2_provider_event

        fake, _ = _fake({"m-a": "provider_error"})
        with mock.patch("brain.llm.direct.chat_complete", fake):
            result = DirectProvider(self.org).complete([])
        record_v2_provider_event(None, result, org=self.org, surface="room_ai")
        self.assertEqual(sorted(UsageEvent.objects.filter(org=self.org).values_list("model", "status")), [("m-a", "error"), ("m-b", "ok")])
        self.assertEqual(AITrace.objects.get(org=self.org).outcome, "fallback")


@override_settings(AI_DIRECT_MODEL_ALLOWLIST="m-a,m-b,m-c", AI_DIRECT_BASE_URL="https://example.invalid", AI_DIRECT_API_KEY="k", AI_DIRECT_PROVIDER="p")
class RoutingScreenTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.org = Organization.objects.create(name="S", slug="screen-org")
        self.policy = RoutingPolicy.objects.create(org=self.org, primary_model="m-a", fallback_models=["m-b"])

    def test_unhealthy_primary_is_skipped_before_calling(self):
        from telemetry.models import UsageEvent

        for _ in range(6):
            UsageEvent.objects.create(org=self.org, provider="p", model="m-a", status="error", error_code="provider_error")
        fake, calls = _fake({})
        with mock.patch("brain.llm.direct.chat_complete", fake):
            DirectProvider(self.org).complete([{"role": "user", "content": "hi"}])
        self.assertEqual(calls, ["m-b"])

    def test_cost_cap_rules_out_expensive_models(self):
        from decimal import Decimal

        from telemetry.models import PriceTable

        PriceTable.objects.create(provider="p", model="m-a", input_price=Decimal("100000"), output_price=Decimal("100000"))
        PriceTable.objects.create(provider="p", model="m-b", input_price=Decimal("0.1"), output_price=Decimal("0.1"))
        self.policy.max_task_cost = Decimal("0.05")
        self.policy.save()
        fake, calls = _fake({})
        with mock.patch("brain.llm.direct.chat_complete", fake):
            DirectProvider(self.org).complete([{"role": "user", "content": "hi"}])
        self.assertEqual(calls, ["m-b"])
        PriceTable.objects.filter(model="m-b").update(input_price=Decimal("100000"))
        with mock.patch("brain.llm.direct.chat_complete", fake):
            result = DirectProvider(self.org).complete([{"role": "user", "content": "hi"}])
        self.assertEqual(result.error_code, "cost_limit")
