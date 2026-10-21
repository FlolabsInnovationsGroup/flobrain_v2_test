import time
from unittest.mock import patch

from django.test import TestCase
from pymongo import MongoClient
from rest_framework.test import APIClient

from users.jwt_utils import make_access_token
from users.models import User


class DashboardErrorLogsAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            username="Dash User",
            email="dash@example.com",
            password_hash="unused",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {make_access_token(str(self.user.id))}"
        )

    @patch(
        "dashboard.views.get_error_logs",
        return_value=[{"level": "error", "message": "x", "timestamp": "01/01/26"}],
    )
    def test_error_logs_returns_both_keys(self, _mock_logs):
        response = self.client.get("/api/dashboard/error-logs/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("error_logs", data)
        self.assertIn("error-logs", data)
        self.assertEqual(data["error_logs"], data["error-logs"])


class DashboardHealthMongoTests(TestCase):
    def test_missing_mongo_is_degraded_quickly(self):
        from memory.mongo_client import mongo_timeout_ms

        timeout = mongo_timeout_ms()
        self.assertEqual(timeout, 2000)
        dead = MongoClient(
            "mongodb://127.0.0.1:1/",
            serverSelectionTimeoutMS=timeout,
            connectTimeoutMS=timeout,
        )
        self.addCleanup(dead.close)
        started = time.monotonic()
        with patch("memory.mongo_client.client", dead):
            response = APIClient().get("/api/dashboard/health/")
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 10)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["system_status"], "degraded")
        self.assertEqual(body["mongodb"], "disconnected")
        self.assertEqual(body["database"], "connected")
        self.assertIn("connected_devices", body)


class HealthzTestCase(TestCase):
    def test_healthz_returns_ok_without_auth(self):
        client = APIClient()
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
