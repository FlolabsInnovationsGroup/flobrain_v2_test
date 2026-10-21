"""Who signs an Egyptian invoice. FloBrain never does: the ETA requires a CAdES-BES signature made
with the taxpayer's eSeal certificate on a USB token or HSM, issued to the taxpayer's
registration number. Two ways to get it:

- ``external``: the customer runs a small signer service next to the token (on their premises).
  FloBrain POSTs ``{"internal_id", "canonical_b64", "sha256"}`` to its https URL (the host must
  be allowlisted by the operator; mTLS supported, see ``einvoice.transport``) with the bearer
  token the admin saved, and expects ``{"signature": "<Base64 CAdES-BES>"}``.
- ``manual``: an admin downloads the canonical text, signs it with their own tool (for example
  the ETA signing utility) and uploads the Base64 signature.

We only check that what comes back looks like a CMS SignedData structure (DER SEQUENCE with the
signedData OID 1.2.840.113549.1.7.2); the ETA verifies the signature itself.
"""

import base64
import json

from einvoice import transport
from einvoice.eta.serialize import sha256_hex

SIGNED_DATA_OID = bytes.fromhex("06092a864886f70d010702")
MAX_SIGNATURE = 64 * 1024


class SignerError(Exception):
    def __init__(self, code: str, details: str):
        super().__init__(details)
        self.code = code
        self.details = details


def check_signature(value: str) -> str:
    text = "".join((value or "").split())
    if not text or len(text) > MAX_SIGNATURE:
        raise SignerError("invalid_signature", "Paste the Base64 CAdES-BES signature")
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as exc:
        raise SignerError("invalid_signature", "The signature is not Base64") from exc
    if not raw or raw[0] != 0x30 or SIGNED_DATA_OID not in raw[:64]:
        raise SignerError("invalid_signature", "That is not a CAdES-BES (CMS SignedData) signature")
    return text


def external_sign(url: str, bearer: str, internal_id: str, canonical: str) -> str:
    body = json.dumps(
        {
            "internal_id": internal_id,
            "canonical_b64": base64.b64encode(canonical.encode("utf-8")).decode("ascii"),
            "sha256": sha256_hex(canonical),
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        status, parsed = transport.request("signer", "POST", url, body=body, headers=headers)
    except transport.TransportError as exc:
        raise SignerError(exc.code, f"The signer service: {exc.details}") from exc
    if status != 200 or not isinstance(parsed, dict) or not isinstance(parsed.get("signature"), str):
        raise SignerError("signer_failed", f"The signer service did not sign ({status}). Check that the token is plugged in.")
    return check_signature(parsed["signature"])
