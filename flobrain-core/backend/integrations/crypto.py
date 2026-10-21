"""Credential encryption (Decision E20).

AES-256-GCM with a 96-bit random nonce. The associated data binds the
ciphertext to its credential id and org id, so a row copied to another
credential or org does not decrypt. ``key_version`` lets a later change add
rotation. Separate from ``memory/tier_3.SecureCipher`` on purpose: this module
never falls back to a default key.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

NONCE_BYTES = 12


class CredentialCryptoError(Exception):
    pass


def current_key_version() -> int:
    return int(getattr(settings, "CREDENTIALS_KEY_VERSION", 1) or 1)


def _key() -> bytes | None:
    raw = (getattr(settings, "CREDENTIALS_ENCRYPTION_KEY", "") or "").strip()
    if len(raw) != 64:
        return None
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        return None
    if key == b"\x00" * 32:
        return None
    return key


def is_configured() -> bool:
    return _key() is not None


def _aad(credential_id, org_id) -> bytes:
    return f"flobrain-credential:{credential_id}:{org_id}".encode()


def encrypt(secret: str, credential_id, org_id) -> bytes:
    key = _key()
    if key is None:
        raise CredentialCryptoError("CREDENTIALS_ENCRYPTION_KEY is not configured")
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, secret.encode("utf-8"), _aad(credential_id, org_id))


def decrypt(blob: bytes, credential_id, org_id, key_version: int) -> str:
    key = _key()
    if key is None:
        raise CredentialCryptoError("CREDENTIALS_ENCRYPTION_KEY is not configured")
    if int(key_version) != current_key_version():
        raise CredentialCryptoError("credential was encrypted with another key version")
    blob = bytes(blob)
    try:
        plain = AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], _aad(credential_id, org_id))
    except InvalidTag as exc:
        raise CredentialCryptoError("credential does not decrypt") from exc
    return plain.decode("utf-8")
