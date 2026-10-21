"""DiscoverRunner that cannot hang quietly or call the public internet."""

import faulthandler
import os
import socket
import sys

from django.test.runner import DiscoverRunner

_ALLOWED_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_WATCHDOG_ARMED = False


def arm_hang_watchdog():
    """Arm before DB setup so a stall during migrate still dumps stacks."""
    global _WATCHDOG_ARMED
    timeout = int(os.getenv("TEST_HANG_TIMEOUT", "1200"))
    faulthandler.enable(all_threads=True, file=sys.stderr)
    faulthandler.dump_traceback_later(timeout, exit=True, file=sys.stderr)
    _WATCHDOG_ARMED = True
    return timeout


# Import happens when Django reads TEST_RUNNER, before the suite starts.
arm_hang_watchdog()


class HangSafeDiscoverRunner(DiscoverRunner):
    def run_tests(self, test_labels, extra_tests=None, **kwargs):
        arm_hang_watchdog()
        sys.stderr.write(
            f"HangSafeDiscoverRunner: dump_traceback_later={os.getenv('TEST_HANG_TIMEOUT', '1200')}s armed={_WATCHDOG_ARMED}\n"
        )
        sys.stderr.flush()
        return super().run_tests(test_labels, extra_tests=extra_tests, **kwargs)

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        arm_hang_watchdog()
        self._orig_connect = socket.socket.connect
        self._orig_connect_ex = socket.socket.connect_ex

        def _host(address):
            if isinstance(address, tuple) and address:
                return address[0]
            if isinstance(address, str):
                return address
            return ""

        def connect(sock, address):
            host = _host(address)
            if isinstance(host, bytes):
                host = host.decode()
            if host not in _ALLOWED_HOSTS:
                raise OSError(f"Outbound network is blocked in tests: {host}")
            return self._orig_connect(sock, address)

        def connect_ex(sock, address):
            host = _host(address)
            if isinstance(host, bytes):
                host = host.decode()
            if host not in _ALLOWED_HOSTS:
                return 13
            return self._orig_connect_ex(sock, address)

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex

    def teardown_test_environment(self, **kwargs):
        faulthandler.cancel_dump_traceback_later()
        socket.socket.connect = self._orig_connect
        socket.socket.connect_ex = self._orig_connect_ex
        super().teardown_test_environment(**kwargs)
