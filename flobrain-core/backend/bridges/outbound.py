"""Outbound HTTPS for the bridges: allowlisted hosts only, simulated in demo and tests.

Every call goes through ``platform_api.net.fetch`` (https, public addresses only, pinned, no
redirects) after the host is checked against an allowlist. When the workspace is a demo row or the
server runs in demo mode nothing leaves FloBrain: the call is recorded in the current ``capture()``
block (the demo simulator shows it) and a canned success is returned. Tokens never reach logs.
"""

import contextlib
import contextvars
import json
import logging
import urllib.parse

from django.conf import settings

logger = logging.getLogger(__name__)

SLACK_HOSTS = frozenset({"slack.com"})
MICROSOFT_LOGIN_HOSTS = frozenset({"login.microsoftonline.com", "login.botframework.com"})
MAX_RESPONSE = 256 * 1024

_captured: contextvars.ContextVar = contextvars.ContextVar("bridges_captured", default=None)


class BridgeHTTPError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def teams_service_host_ok(host: str) -> bool:
    """Bot Framework service URLs: ``*.botframework.com`` and ``smba.trafficmanager.net`` only."""
    host = (host or "").lower().rstrip(".")
    return host == "smba.trafficmanager.net" or (host.endswith(".botframework.com") and host != ".botframework.com")


def host_allowed(url: str, extra=frozenset()) -> bool:
    try:
        parsed = urllib.parse.urlparse(url or "")
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    return host in SLACK_HOSTS or host in MICROSOFT_LOGIN_HOSTS or host in extra or teams_service_host_ok(host)


def simulated(workspace=None) -> bool:
    return bool((workspace is not None and workspace.demo) or getattr(settings, "DEMO_MODE", False))


@contextlib.contextmanager
def capture():
    """Collect the simulated calls made inside the block: ``with capture() as calls: ...``."""
    calls: list = []
    token = _captured.set(calls)
    try:
        yield calls
    finally:
        _captured.reset(token)


def record_simulated(kind: str, payload: dict) -> None:
    calls = _captured.get()
    if calls is not None:
        calls.append({"call": kind, "payload": payload})


def request(method: str, url: str, *, body: bytes = b"", headers: dict | None = None, timeout: int = 10):
    """(status, decoded JSON or {}) for an allowlisted https URL. Raises ``BridgeHTTPError``."""
    if not host_allowed(url):
        raise BridgeHTTPError("host_not_allowed")
    from platform_api import net

    try:
        status, data = net.fetch(method, url, body, dict(headers or {}), timeout=timeout, max_bytes=MAX_RESPONSE)
    except (net.UnsafeURL, OSError) as exc:
        logger.info("bridges: %s %s failed: %s", method, urllib.parse.urlparse(url).hostname, type(exc).__name__)
        raise BridgeHTTPError("provider_unavailable") from exc
    try:
        decoded = json.loads(data.decode("utf-8") or "{}") if data else {}
    except (UnicodeDecodeError, ValueError):
        decoded = {}
    return status, decoded if isinstance(decoded, dict) else {"value": decoded}


def status_error(status: int) -> str:
    if status in (401, 403):
        return "invalid_credentials"
    if status == 429:
        return "rate_limited"
    if 400 <= status < 500:
        return "provider_rejected"
    return "provider_unavailable"
