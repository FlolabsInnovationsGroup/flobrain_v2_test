import faulthandler
import socket

from django.conf import settings
from django.test import SimpleTestCase

from flobrain.test_runner import _WATCHDOG_ARMED


class NetworkGuardTests(SimpleTestCase):
    def test_unmocked_external_call_fails_fast(self):
        with self.assertRaises(OSError) as ctx:
            socket.create_connection(("1.1.1.1", 443), timeout=2)
        self.assertIn("blocked", str(ctx.exception).lower())

    def test_hang_watchdog_is_armed(self):
        self.assertEqual(settings.TEST_RUNNER, "flobrain.test_runner.HangSafeDiscoverRunner")
        self.assertTrue(_WATCHDOG_ARMED)
        self.assertTrue(faulthandler.is_enabled())
