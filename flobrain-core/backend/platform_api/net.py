"""Outbound HTTPS to customer URLs (webhooks) without SSRF.

The host is resolved, every address must be public (no private, loopback,
link-local, multicast, reserved or unspecified), and the connection is made to
the checked address with the original host name for SNI and certificate
checks, so a DNS change between check and connect cannot redirect it.
Redirects are never followed.
"""

import http.client
import ipaddress
import socket
import ssl
import threading
import urllib.parse

DNS_TIMEOUT = 5
DEADLINE_SECONDS = 15  # whole request, not per socket operation


class UnsafeURL(ValueError):
    pass


def resolve(host, port):
    """getaddrinfo with a hard timeout (it has none of its own)."""
    out, err = [], []

    def run():
        try:
            out.extend(info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except OSError as exc:
            err.append(exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(DNS_TIMEOUT)
    if t.is_alive():
        raise OSError("dns timeout")
    if err:
        raise err[0]
    return out


def _public(addr) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip.is_site_local:  # deprecated fec0::/10
            return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def check_url(url):
    """Return (host, port, path, ip) for a safe https URL, or raise UnsafeURL."""
    try:
        parsed = urllib.parse.urlparse(url or "")
        hostname, port = parsed.hostname, parsed.port or 443
    except ValueError as exc:  # bad port and similar
        raise UnsafeURL("the URL is not valid") from exc
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise UnsafeURL("the URL must be https without credentials")
    if port not in (443, 8443):
        raise UnsafeURL("port must be 443 or 8443")
    is_literal = True
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        is_literal = False
    if is_literal:
        raise UnsafeURL("use a host name, not an IP address")
    try:
        hostname.encode("idna")
        addresses = resolve(hostname, port)
    except (OSError, UnicodeError, ValueError) as exc:
        raise UnsafeURL("the host does not resolve") from exc
    if not addresses or not all(_public(a) for a in addresses):
        raise UnsafeURL("the host resolves to a private or reserved address")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return hostname, port, path, addresses[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch(method, url, body: bytes = b"", headers: dict | None = None, timeout=10, max_bytes=4096):
    """Pinned request to a checked https URL. Returns (status, body bytes up to ``max_bytes``)."""
    status, _, data = fetch_full(method, url, body, headers, timeout, max_bytes)
    return status, data


def fetch_full(method, url, body: bytes = b"", headers: dict | None = None, timeout=10, max_bytes=4096):
    """Like ``fetch`` but also returns the response headers as a lower-cased dict."""
    host, port, path, ip = check_url(url)
    conn = _PinnedHTTPS(host, ip, port, timeout)
    # A receiver that trickles bytes would defeat per-operation timeouts; this closes it at the deadline.
    killer = threading.Timer(DEADLINE_SECONDS, conn.close)
    killer.daemon = True
    killer.start()
    try:
        conn.request(method, path, body=body or None, headers={**(headers or {}), "Host": host})
        response = conn.getresponse()
        data = response.read(max_bytes)
        response_headers = {str(k).lower(): str(v) for k, v in (response.getheaders() or [])} if hasattr(response, "getheaders") else {}
        return response.status, response_headers, data  # 3xx is returned as-is: never followed
    except AttributeError as exc:  # the socket was closed under us by the deadline
        raise OSError("deadline exceeded") from exc
    finally:
        killer.cancel()
        conn.close()


def post(url, body: bytes, headers: dict, timeout=10) -> int:
    """POST and return the status code. Raises UnsafeURL or OSError."""
    status, _ = fetch("POST", url, body, headers, timeout)
    return status
