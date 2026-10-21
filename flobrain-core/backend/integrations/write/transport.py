"""The only way write-back connectors reach the network.

- A URL must be https on port 443, without credentials, and its host must be on the provider's
  allowlist (``Provider.host_allowed``). Anything else raises ``WriteError("blocked_host")``
  before a socket is opened.
- The request then goes through ``platform_api.net.fetch_full``: the host must resolve to public
  addresses only, the connection is pinned to the checked address, and redirects are never followed.
- A 401 triggers one token refresh and one retry. A second 401, or a failed refresh, marks the
  connection expired.
- Error messages never include tokens or response bodies beyond a short provider message.
"""

import json
import logging
import urllib.parse
from datetime import timedelta

from django.utils import timezone

from platform_api import net

logger = logging.getLogger(__name__)

TIMEOUT = 15
MAX_BYTES = 1024 * 1024


class WriteError(Exception):
    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code
        self.details = details or code


def _send(method: str, url: str, body: bytes, headers: dict) -> tuple[int, bytes]:
    """The network boundary (mocked in tests)."""
    status, _headers, data = net.fetch_full(method, url, body, headers, timeout=TIMEOUT, max_bytes=MAX_BYTES)
    return status, data


def check_url(provider, url: str, connection=None) -> str:
    try:
        parsed = urllib.parse.urlparse(url or "")
        port = parsed.port
    except ValueError as exc:
        raise WriteError("blocked_host", "That address is not allowed") from exc
    if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443):
        raise WriteError("blocked_host", "That address is not allowed")
    host = (parsed.hostname or "").lower()
    if not host or not provider.host_allowed(host, connection):
        raise WriteError("blocked_host", f"{provider.name}: {host or 'that host'} is not on the allowed list")
    return host


def _decode(data: bytes):
    if not data:
        return {}
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _provider_message(parsed) -> str:
    """A short, human message from a provider error body (never a token, never the whole body)."""
    if not isinstance(parsed, dict):
        return ""
    for path in (("error", "message"), ("message",), ("error_description",), ("errorMessages",), ("error",)):
        value = parsed
        for part in path:
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, list) and value:
            value = value[0]
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:120]
    return ""


def raw_request(provider, method, url, *, body=b"", headers=None, connection=None):
    """Allowlisted request without auth handling. Returns (status, parsed JSON or {})."""
    check_url(provider, url, connection)
    all_headers = {"Accept": "application/json", "User-Agent": "FloBrain"}
    all_headers.update(headers or {})
    try:
        status, data = _send(method, url, body or b"", all_headers)
    except net.UnsafeURL as exc:
        raise WriteError("blocked_host", "That address resolves to a private network") from exc
    except OSError as exc:
        raise WriteError("unreachable", f"{provider.name} could not be reached") from exc
    return status, _decode(data)


def form(data: dict) -> tuple[bytes, dict]:
    return urllib.parse.urlencode(data).encode(), {"Content-Type": "application/x-www-form-urlencoded"}


def refresh(provider, connection) -> None:
    """Swap the refresh token for a new access token. Marks the connection expired on failure."""
    from integrations.crypto import CredentialCryptoError

    try:
        token = connection.refresh_token()
    except CredentialCryptoError:
        token = ""
    if not token or provider.auth != "oauth2" or not provider.configured():
        _expire(connection, "refresh_unavailable")
        raise WriteError("expired", f"{provider.name} needs to be connected again")
    body, headers = form(
        {
            "grant_type": "refresh_token",
            "refresh_token": token,
            "client_id": provider.client_id(),
            "client_secret": provider.client_secret(),
        }
    )
    status, parsed = raw_request(provider, "POST", provider.resolve(provider.token_url), body=body, headers=headers, connection=connection)
    access = parsed.get("access_token") if isinstance(parsed, dict) else None
    if status != 200 or not isinstance(access, str) or not access:
        _expire(connection, "refresh_failed")
        raise WriteError("expired", f"{provider.name} needs to be connected again")
    connection.set_secrets(access, parsed.get("refresh_token") or None, keep_refresh=True)
    connection.expires_at = _expiry(parsed.get("expires_in"))
    connection.status = connection.STATUS_CONNECTED
    connection.last_error = ""
    connection.save(update_fields=["access_ciphertext", "refresh_ciphertext", "key_version", "expires_at", "status", "last_error", "updated_at"])
    logger.info("write connection %s refreshed", connection.id)  # never the token


def _expiry(expires_in):
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return timezone.now() + timedelta(seconds=max(seconds, 0))


def _expire(connection, code):
    connection.status = connection.STATUS_EXPIRED
    connection.last_error = code
    connection.save(update_fields=["status", "last_error", "updated_at"])


class Client:
    """Calls one provider with one connection's token (or a fixed token while connecting)."""

    def __init__(self, provider, connection=None, token: str | None = None):
        self.provider = provider
        self.connection = connection
        self._token = token

    def token(self) -> str:
        if self._token is not None:
            return self._token
        from integrations.crypto import CredentialCryptoError

        conn = self.connection
        if (
            conn.expires_at
            and conn.expires_at <= timezone.now() + timedelta(seconds=60)
            and conn.refresh_ciphertext
            and self.provider.auth == "oauth2"
        ):
            refresh(self.provider, conn)
        try:
            return conn.access_token()
        except CredentialCryptoError as exc:
            _expire(conn, "decrypt_failed")
            raise WriteError("expired", f"{self.provider.name} needs to be connected again") from exc

    def call(self, method, url, *, json_body=None, body=None, content_type=None, headers=None, auth=True, ok=(200, 201, 202, 204)):
        payload = b""
        extra = dict(headers or {})
        if json_body is not None:
            payload = json.dumps(json_body).encode("utf-8")
            extra["Content-Type"] = "application/json"
        elif body is not None:
            payload = body if isinstance(body, bytes) else str(body).encode("utf-8")
            if content_type:
                extra["Content-Type"] = content_type
        status, parsed = 0, {}
        for attempt in (0, 1):
            send_headers = dict(extra)
            if auth:
                send_headers.update(self.provider.auth_header(self.token()))
            status, parsed = raw_request(self.provider, method, url, body=payload, headers=send_headers, connection=self.connection)
            can_refresh = auth and self._token is None and self.connection is not None and self.provider.auth == "oauth2"
            if status == 401 and attempt == 0 and can_refresh:
                refresh(self.provider, self.connection)
                continue
            break
        if status == 401:
            if self.connection is not None and self._token is None:
                _expire(self.connection, "token_rejected")
            raise WriteError("expired", f"{self.provider.name} refused the token. Connect it again.")
        if status not in ok:
            message = _provider_message(parsed)
            detail = f"{self.provider.name} answered {status}" + (f": {message}" if message else "")
            raise WriteError("provider_error", detail[:180])
        return parsed
