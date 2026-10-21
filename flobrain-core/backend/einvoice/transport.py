"""The only way the e-invoicing app reaches the network.

- https on port 443 only, no credentials in the URL, the host on the allowlist of the target
  (ZATCA, ETA identity, ETA API, or the customer's signer). Anything else raises
  ``TransportError("blocked_host")`` before a socket is opened.
- ZATCA and ETA hosts must resolve to public addresses and the connection is pinned to the
  checked address (``platform_api.net``); redirects are never followed.
- The customer's signer: its host must be listed by the operator in
  ``EINVOICE_SIGNER_ALLOWED_HOSTS``. On-premises signers in self-hosted installs may sit on a
  private network: ``EINVOICE_SIGNER_ALLOW_PRIVATE=True`` allows that, for signer hosts only.
  mTLS: ``EINVOICE_SIGNER_CLIENT_CERT`` and ``EINVOICE_SIGNER_CLIENT_KEY`` (file paths) give a
  client certificate; ``EINVOICE_SIGNER_CA_FILE`` pins the signer's CA.
- Error messages never include credentials or response bodies beyond a short message.
- ``_send`` is the network boundary; tests and the demo never reach it.
"""

import http.client
import json
import logging
import os
import socket
import ssl
import threading
import urllib.parse

from django.conf import settings

from platform_api import net

logger = logging.getLogger(__name__)

TIMEOUT = 30
MAX_BYTES = 4 * 1024 * 1024

ZATCA_HOSTS = frozenset({"gw-fatoora.zatca.gov.sa"})
ETA_ID_HOSTS = frozenset({"id.eta.gov.eg", "id.preprod.eta.gov.eg"})
ETA_API_HOSTS = frozenset({"api.invoicing.eta.gov.eg", "api.preprod.invoicing.eta.gov.eg"})


class TransportError(Exception):
    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code
        self.details = details or code


def env(name: str, default: str = "") -> str:
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = os.environ.get(name, default)
    return str(value or "").strip()


def _list(name: str) -> set[str]:
    return {h.strip().lower().rstrip(".") for h in env(name).split(",") if h.strip()}


def zatca_hosts() -> set[str]:
    return set(ZATCA_HOSTS) | _list("EINVOICE_ZATCA_EXTRA_HOSTS")


def eta_hosts() -> set[str]:
    return set(ETA_ID_HOSTS) | set(ETA_API_HOSTS) | _list("EINVOICE_ETA_EXTRA_HOSTS")


def signer_hosts() -> set[str]:
    return _list("EINVOICE_SIGNER_ALLOWED_HOSTS")


def check_url(url: str, allowed: set[str]) -> str:
    try:
        parsed = urllib.parse.urlparse(url or "")
        port = parsed.port
    except ValueError as exc:
        raise TransportError("blocked_host", "That address is not allowed") from exc
    if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443):
        raise TransportError("blocked_host", "Only https addresses on port 443 are allowed")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host not in allowed:
        raise TransportError("blocked_host", f"{host or 'That host'} is not on the allowed list")
    return host


def _signer_context():
    context = ssl.create_default_context(cafile=env("EINVOICE_SIGNER_CA_FILE") or None)
    cert, key = env("EINVOICE_SIGNER_CLIENT_CERT"), env("EINVOICE_SIGNER_CLIENT_KEY")
    if cert and key:
        context.load_cert_chain(cert, key)
    return context


class _Pinned(http.client.HTTPSConnection):
    def __init__(self, host, ip, port, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _signer_fetch(method, url, body, headers):
    parsed = urllib.parse.urlparse(url)
    host, port = parsed.hostname, parsed.port or 443
    addresses = net.resolve(host, port)
    if not addresses:
        raise TransportError("unreachable", "The signer host does not resolve")
    allow_private = env("EINVOICE_SIGNER_ALLOW_PRIVATE").lower() in ("1", "true", "yes")
    if not allow_private and not all(net._public(a) for a in addresses):
        raise TransportError("blocked_host", "The signer resolves to a private address")
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    conn = _Pinned(host, addresses[0], port, TIMEOUT, _signer_context())
    killer = threading.Timer(TIMEOUT, conn.close)
    killer.daemon = True
    killer.start()
    try:
        conn.request(method, path, body=body or None, headers={**headers, "Host": host})
        response = conn.getresponse()
        return response.status, response.read(MAX_BYTES)
    finally:
        killer.cancel()
        conn.close()


def _send(method: str, url: str, body: bytes, headers: dict, target: str) -> tuple[int, bytes]:
    """The network boundary (mocked in tests)."""
    if target == "signer":
        return _signer_fetch(method, url, body, headers)
    status, _headers, data = net.fetch_full(method, url, body, headers, timeout=TIMEOUT, max_bytes=MAX_BYTES)
    return status, data


def request(target: str, method: str, url: str, *, body: bytes = b"", headers: dict | None = None) -> tuple[int, object]:
    """Returns (status, parsed JSON or {}). ``target`` is zatca | eta | signer."""
    allowed = {"zatca": zatca_hosts, "eta": eta_hosts, "signer": signer_hosts}[target]()
    check_url(url, allowed)
    all_headers = {"Accept": "application/json", "User-Agent": "FloBrain-einvoice"}
    all_headers.update(headers or {})
    try:
        status, data = _send(method, url, body or b"", all_headers, target)
    except net.UnsafeURL as exc:
        raise TransportError("blocked_host", "That address resolves to a private network") from exc
    except TransportError:
        raise
    except (OSError, ssl.SSLError) as exc:
        logger.info("einvoice %s request failed: %s", target, type(exc).__name__)
        raise TransportError("unreachable", "The service could not be reached") from exc
    try:
        parsed = json.loads(data.decode("utf-8")) if data else {}
    except (ValueError, UnicodeDecodeError):
        parsed = {}
    return status, parsed
