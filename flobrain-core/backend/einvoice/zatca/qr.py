"""ZATCA QR code: TLV (tag, one-byte length, value) then Base64.

Tags (E-invoicing Detailed Technical Guidelines; Security Features Implementation Standard):
1 seller name, 2 seller VAT number, 3 timestamp (IssueDate + "T" + IssueTime), 4 invoice total
with VAT (BT-112), 5 VAT total (BT-110) -- the Phase 1 tags, UTF-8 text;
6 invoice hash, 7 ECDSA signature, 8 ECDSA public key, 9 the ZATCA technical CA's signature over
the cryptographic stamp (simplified invoices and their notes only).

Encoding of tags 6 and 7 is not consistent across ZATCA's own material: the Security Features
standard describes tag 6 as the raw hash bytes, while the ZATCA SDK and the community-documented
procedure put the Base64 text of the hash and of the signature. ``HASH_ENCODING`` keeps it
configurable (default: Base64 text, as the SDK emits); validate one QR with the SDK
(``fatoora -validate``) in the developer portal before production. Tags 8 and 9 are raw bytes
(DER public key, certificate signature). The Base64 result is limited to 700 characters.
"""

import base64

MAX_BASE64 = 700
HASH_TEXT, HASH_RAW = "base64_text", "raw"


class QRError(ValueError):
    pass


def _bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def tlv(tag: int, value) -> bytes:
    data = _bytes(value)
    if not 1 <= tag <= 255:
        raise QRError("tag out of range")
    if len(data) > 255:
        raise QRError(f"tag {tag} is longer than 255 bytes")
    return bytes([tag, len(data)]) + data


def encode(fields: list[tuple[int, object]]) -> str:
    out = base64.b64encode(b"".join(tlv(tag, value) for tag, value in fields)).decode("ascii")
    if len(out) > MAX_BASE64:
        raise QRError("the QR code is longer than 700 characters")
    return out


def decode(text: str) -> dict[int, bytes]:
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as exc:
        raise QRError("not Base64") from exc
    out, i = {}, 0
    while i < len(raw):
        if i + 2 > len(raw):
            raise QRError("truncated TLV")
        tag, length = raw[i], raw[i + 1]
        value = raw[i + 2 : i + 2 + length]
        if len(value) != length:
            raise QRError("truncated TLV")
        out[tag] = value
        i += 2 + length
    return out


def phase1(seller_name: str, vat_number: str, timestamp: str, total: str, vat_total: str) -> list[tuple[int, object]]:
    return [(1, seller_name), (2, vat_number), (3, timestamp), (4, total), (5, vat_total)]


def phase2(
    seller_name: str,
    vat_number: str,
    timestamp: str,
    total: str,
    vat_total: str,
    *,
    invoice_hash_b64: str,
    signature_b64: str,
    public_key_der: bytes,
    certificate_signature: bytes | None = None,
    hash_encoding: str = HASH_TEXT,
) -> str:
    fields = phase1(seller_name, vat_number, timestamp, total, vat_total)
    if hash_encoding == HASH_RAW:
        fields += [(6, base64.b64decode(invoice_hash_b64)), (7, base64.b64decode(signature_b64))]
    else:
        fields += [(6, invoice_hash_b64), (7, signature_b64)]
    fields.append((8, public_key_der))
    if certificate_signature is not None:
        fields.append((9, certificate_signature))
    return encode(fields)


def readable(text: str) -> dict:
    """Decoded tags for the invoice view: text tags as text, binary tags as Base64."""
    tags = decode(text)
    out = {}
    for tag, value in tags.items():
        if tag in (1, 2, 3, 4, 5, 6, 7):
            try:
                out[str(tag)] = value.decode("utf-8")
                continue
            except UnicodeDecodeError:
                pass
        out[str(tag)] = base64.b64encode(value).decode("ascii")
    return out
