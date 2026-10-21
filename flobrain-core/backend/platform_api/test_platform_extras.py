"""Webhook delivery log, retry, ping and the demo inbox; the public status page, subscriptions and
platform incidents; the PII detector."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import override_settings
from django.utils import timezone

from organizations.models import OrgPolicy
from platform_api import demo_hosts, pii, webhooks
from platform_api.models import DemoInboxDelivery, Incident, StatusSubscription, WebhookDelivery
from platform_api.tests import PlatformBase, _user
from tasks.models import Task


class WebhookLogTests(PlatformBase):
    def _hook(self, url="https://hooks.example.com/in"):
        self._session(self.owner)
        with patch("platform_api.net.resolve", return_value=["93.184.216.34"]):
            made = self.web.post(f"/api/v2/orgs/{self.org.id}/webhooks", {"url": url, "events": ["task.created"]}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        return made.json()

    def test_log_retry_and_ping(self):
        hook = self._hook()
        base = f"/api/v2/orgs/{self.org.id}/webhooks/{hook['id']}"
        with patch("platform_api.net.post", return_value=500), self.captureOnCommitCallbacks(execute=True):
            Task.objects.create(org=self.org, team=self.team, title="Fails")
        WebhookDelivery.objects.update(status="failed", attempts=webhooks.MAX_ATTEMPTS)
        log = self.web.get(base).json()
        row = log["deliveries"][0]
        self.assertEqual((row["status"], row["response_code"], row["attempts"]), ("failed", 500, webhooks.MAX_ATTEMPTS))
        self.assertEqual(row["payload"]["event"], "task.created")
        with patch("platform_api.net.post", return_value=204) as posted, self.captureOnCommitCallbacks(execute=True):
            retried = self.web.post(f"{base}/deliveries/{row['id']}/retry")
        self.assertEqual(retried.status_code, 202)
        self.assertEqual(posted.call_count, 1)
        self.assertEqual(WebhookDelivery.objects.get().status, "delivered")
        self.assertEqual(self.web.post(f"{base}/deliveries/{row['id']}/retry").status_code, 409, "delivered rows are final")
        with patch("platform_api.net.post", return_value=200) as posted, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.web.post(f"{base}/test").status_code, 202)
        self.assertEqual(posted.call_args[0][2]["FloBrain-Event"], "ping")
        self.assertEqual(self.web.patch(base, {"is_active": "no"}, format="json").status_code, 400)
        self.assertEqual(self.web.patch(base, {"is_active": False}, format="json").json()["is_active"], False)
        self.assertEqual(self.web.post(f"{base}/test").status_code, 409)
        self._session(self.member)
        self.assertEqual(self.web.get(base).status_code, 403)

    def test_demo_inbox_404_and_unreachable_outside_demo(self):
        self._session(self.owner)
        self.assertEqual(self.web.get(f"/api/v2/orgs/{self.org.id}/webhooks/demo-inbox").status_code, 404)
        with patch("platform_api.net.resolve", side_effect=OSError("nx")):
            response = self.web.post(f"/api/v2/orgs/{self.org.id}/webhooks", {"url": demo_hosts.inbox_url(self.org), "events": ["task.created"]}, format="json")
        self.assertEqual(response.status_code, 400)

    @override_settings(DEMO_MODE=True)
    def test_demo_inbox_receives_and_verifies_in_process(self):
        hook = self._hook(demo_hosts.inbox_url(self.org))
        self.assertTrue(hook["demo_inbox"])
        with patch("platform_api.net.post", side_effect=AssertionError("no network")), patch(
            "platform_api.net.resolve", side_effect=AssertionError("no dns")
        ), self.captureOnCommitCallbacks(execute=True):
            Task.objects.create(org=self.org, team=self.team, title="Demo")
            self.web.post(f"/api/v2/orgs/{self.org.id}/webhooks/{hook['id']}/test")
        inbox = self.web.get(f"/api/v2/orgs/{self.org.id}/webhooks/demo-inbox").json()
        self.assertEqual({r["event"] for r in inbox["received"]}, {"task.created", "ping"})
        self.assertTrue(all(r["signature_valid"] for r in inbox["received"]))
        self.assertEqual(set(WebhookDelivery.objects.values_list("status", flat=True)), {"delivered"})
        endpoint = WebhookDelivery.objects.first().endpoint
        from platform_api import demo_inbox

        self.assertEqual(demo_inbox.receive(endpoint, b"{}", {"FloBrain-Signature": webhooks.sign("wrong", int(timezone.now().timestamp()), b"{}")}), 401)
        self.assertFalse(DemoInboxDelivery.objects.order_by("-received_at").first().signature_valid)
        self._session(self.member)
        self.assertEqual(self.web.get(f"/api/v2/orgs/{self.org.id}/webhooks/demo-inbox").status_code, 403)


class StatusPageTests(PlatformBase):
    def test_public_status_is_sanitized(self):
        Incident.objects.create(org=self.org, title="Org private", components=["API"])
        Incident.objects.create(title="Platform hidden", components=["API"])
        Incident.objects.create(title="AI slow", severity="major", components=["AI"], is_public=True)
        Incident.objects.create(title="Old", severity="critical", components=["API"], is_public=True, status="resolved")
        data = self.client.get("/api/public/status").json()
        self.assertEqual([i["title"] for i in data["incidents"]], ["Old", "AI slow"])
        self.assertEqual({c["name"]: c["status"] for c in data["components"]}["AI"], "partial_outage")
        self.assertEqual({c["name"]: c["status"] for c in data["components"]}["API"], "operational")
        self.assertEqual(data["overall"], "partial_outage")
        text = json.dumps(data)
        self.assertNotIn("Org private", text)
        self.assertNotIn(str(self.org.id), text)

    def test_subscribe_confirm_unsubscribe(self):
        self.assertEqual(self.client.post("/api/public/status/subscribe", {"email": "nope"}, content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/api/public/status/subscribe", {"email": ["x"]}, content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/api/public/status/subscribe", {"email": "Fan@Example.com"}, content_type="application/json").status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        token = mail.outbox[0].body.split("confirm=")[1].split()[0]
        self.assertNotIn(token, json.dumps(list(StatusSubscription.objects.values()), default=str), "only the hash is stored")
        confirmed = self.client.post("/api/public/status/confirm", {"token": token}, content_type="application/json")
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(self.client.post("/api/public/status/confirm", {"token": token}, content_type="application/json").status_code, 404)
        self.client.post("/api/public/status/subscribe", {"email": "fan@example.com"}, content_type="application/json")
        self.assertEqual(len(mail.outbox), 1, "confirmed addresses get no new email; the answer is the same")
        self.client.post("/api/public/status/unsubscribe", {"token": "forged:abc"}, content_type="application/json")
        self.assertTrue(StatusSubscription.objects.exists())
        self.client.post("/api/public/status/unsubscribe", {"token": confirmed.json()["unsubscribe"]}, content_type="application/json")
        self.assertFalse(StatusSubscription.objects.exists())

    def test_platform_incidents_admins_only_and_subscribers_emailed(self):
        self._session(self.owner)
        self.assertEqual(self.web.post("/api/v2/platform/incidents", {"title": "x"}, format="json").status_code, 403)
        staff = _user("pa-staff@example.com")
        staff.is_platform_admin = True
        staff.save()
        StatusSubscription.objects.create(email="fan@example.com", confirmed_at=timezone.now())
        StatusSubscription.objects.create(email="pending@example.com")
        self._session(staff)
        with self.captureOnCommitCallbacks(execute=True):
            made = self.web.post("/api/v2/platform/incidents", {"title": "API errors", "severity": "critical", "components": ["API"], "is_public": True, "message": "Looking into it."}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        self.assertEqual([m.to for m in mail.outbox], [["fan@example.com"]])
        self.assertIn("unsubscribe=", mail.outbox[0].body)
        self.assertEqual(self.client.get("/api/public/status").json()["overall"], "major_outage")
        with self.captureOnCommitCallbacks(execute=True):
            resolved = self.web.patch(f"/api/v2/platform/incidents/{made.json()['id']}", {"status": "resolved"}, format="json").json()
        self.assertIsNotNone(resolved["resolved_at"])
        self.assertEqual(resolved["updates"][-1]["message"], "Resolved.")

    def test_org_incident_lifecycle_and_bad_input(self):
        self._session(self.owner)
        base = f"/api/v2/orgs/{self.org.id}/incidents"
        made = self.web.post(base, {"title": "Slow", "components": ["API"], "impact": "Slow pages", "next_update_at": (timezone.now() + timedelta(hours=1)).isoformat()}, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        self.assertEqual(len(made.json()["updates"]), 1)
        url = f"{base}/{made.json()['id']}"
        self.assertEqual(self.web.patch(url, {"next_update_at": "soon"}, format="json").status_code, 400)
        self.assertEqual(self.web.patch(url, {"title": 5}, format="json").status_code, 400)
        self.assertEqual(self.web.patch(url, {"message": ["x"]}, format="json").status_code, 400)
        done = self.web.patch(url, {"status": "resolved", "message": "Fixed the cache."}, format="json").json()
        self.assertEqual((done["status"], done["updates"][-1]["message"], done["next_update_at"]), ("resolved", "Fixed the cache.", None))
        self._session(self.member)
        self.assertEqual(self.web.get(base).status_code, 403)


class PIITests(PlatformBase):
    def test_regex_detector_basics(self):
        d = pii.RegexDetector()
        text, n = pii.redact("Mail nadia@example.com, call +20 100 123 4567, card 4242 4242 4242 4242, SSN 123-45-6789 on 2026-10-18.", d)
        self.assertEqual(n, 4)
        for raw in ("nadia@example.com", "4242", "123-45-6789", "+20 100"):
            self.assertNotIn(raw, text)
        self.assertIn("2026-10-18", text, "dates are not phone numbers")
        self.assertEqual(pii.redact("Card 4242 4242 4242 4241", d)[1], 0, "fails the Luhn check")

    def test_policy_toggle_needs_a_detector(self):
        self._session(self.owner)
        url = f"/api/v2/orgs/{self.org.id}/policy"
        with override_settings(PII_DETECTOR="", DEMO_MODE=False):
            self.assertEqual(self.web.put(url, {"pii_redaction": "always"}, format="json").status_code, 501)
            self.assertFalse(self.web.get(url).json()["pii_redaction_available"])
        with override_settings(PII_DETECTOR="", DEMO_MODE=True):
            got = self.web.get(url).json()
            self.assertEqual(got["pii_detector"], {"name": "regex", "basic": True})
        with override_settings(PII_DETECTOR="regex"):
            self.assertEqual(self.web.put(url, {"pii_redaction": "external_only"}, format="json").status_code, 200)
            self.assertEqual(OrgPolicy.objects.get(org=self.org).pii_redaction, "external_only")
            self._session(self.member)
            self.assertEqual(self.web.put(url, {"pii_redaction": "off"}, format="json").status_code, 403)
