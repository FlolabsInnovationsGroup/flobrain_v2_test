"""Connection secrets: one encrypted JSON blob per connection, masked hints for display."""

import json

from integrations import crypto

SECRET_FIELDS = {
    "whatsapp": ("access_token", "app_secret", "verify_token"),
    "telegram": ("bot_token", "secret_token"),
    "website": (),
}


def hint(value: str) -> str:
    value = value or ""
    return f"…{value[-4:]}" if len(value) >= 8 else "set"


def store(connection, secrets: dict) -> None:
    """Encrypt ``secrets`` (merged over what is stored) on the connection. Caller saves."""
    current = read(connection) if connection.secrets_ciphertext else {}
    merged = {**current, **{k: v for k, v in secrets.items() if v}}
    connection.secrets_ciphertext = crypto.encrypt(json.dumps(merged), connection.id, connection.org_id)
    connection.key_version = crypto.current_key_version()
    connection.secret_hints = {k: hint(v) for k, v in merged.items()}


def read(connection) -> dict:
    """The decrypted secrets, or {} (raises ``CredentialCryptoError`` on a bad blob)."""
    if not connection.secrets_ciphertext:
        return {}
    raw = crypto.decrypt(bytes(connection.secrets_ciphertext), connection.id, connection.org_id, connection.key_version)
    data = json.loads(raw or "{}")
    return data if isinstance(data, dict) else {}


def get(connection, key: str) -> str:
    try:
        return str(read(connection).get(key) or "")
    except (crypto.CredentialCryptoError, ValueError):
        return ""
