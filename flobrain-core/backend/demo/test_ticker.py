from unittest import mock

from django.test import SimpleTestCase, override_settings

from demo import ticker


class TickerTests(SimpleTestCase):
    def test_never_starts_under_tests_or_outside_the_demo(self):
        self.assertFalse(ticker.should_start())
        with override_settings(DEMO_MODE=False, TESTING=False):
            self.assertFalse(ticker.should_start())

    @override_settings(DEMO_MODE=True, TESTING=False)
    def test_starts_for_the_server_and_runs_every_tick(self):
        with mock.patch.object(ticker.sys, "argv", ["gunicorn"]), mock.patch.dict("os.environ", {"DEMO_TICKS": "1"}):
            self.assertTrue(ticker.should_start())
        with mock.patch.object(ticker.sys, "argv", ["manage.py", "migrate"]):
            self.assertFalse(ticker.should_start())
        with mock.patch.dict("os.environ", {"DEMO_TICKS": "off"}), mock.patch.object(ticker.sys, "argv", ["gunicorn"]):
            self.assertFalse(ticker.should_start())
        with mock.patch("django.core.management.call_command") as call, mock.patch("django.db.close_old_connections"), mock.patch("django.db.connection", mock.MagicMock(vendor="sqlite")):
            ticker._tick_once()
        self.assertEqual([c.args[0] for c in call.call_args_list], list(ticker.COMMANDS))
