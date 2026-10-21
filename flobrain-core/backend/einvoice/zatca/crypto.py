"""EGS keys, the onboarding CSR, CSID certificates and the ECDSA signature (``cryptography``).

Key: ECDSA on secp256k1, as in ZATCA's SDK and the OpenSSL command in its onboarding guidance
(``openssl ecparam -name secp256k1 -genkey``). Note: the Security Features standard (2023) speaks
of a 256-bit ECDSA key without naming the curve; secp256k1 is what ZATCA's CA has accepted.

CSR (Security Features Implementation Standard, section on the CSR; field layout as in ZATCA's
SDK ``csr-config`` and the OpenSSL config ZATCA's developer community documents):
- subject: C (ISO 3166 alpha-2), OU (branch name, or the 10-digit TIN of a VAT group member),
  O (taxpayer name), CN (EGS unit name or asset tracking number);
- extension certificateTemplateName (OID 1.3.6.1.4.1.311.20.2), a PrintableString:
  ``TSTZATCA-Code-Signing`` for the developer portal, ``PREZATCA-Code-Signing`` for simulation,
  ``ZATCA-Code-Signing`` for production;
- subjectAltName dirName with SN = EGS serial ``1-<solution>|2-<model or version>|3-<serial>``,
  UID = the 15-digit VAT number (organization identifier), title = the 4-digit functionality map
  (T S X Y; 1100 = standard and simplified), registeredAddress = branch address,
  businessCategory = industry.
The CSR goes to the compliance API as Base64 of the PEM text (``csr_for_api``); that is what the
SDK's ``fatoora -csr`` writes. ``CSR_ENCODING = "der_base64"`` switches to the bare DER Base64 if
ZATCA's answer says the CSR is invalid.

Signature: ECDSA with SHA-256 over the 32 raw bytes of the invoice hash (the community-documented
ZATCA procedure; the SDK does the same). Verified in tests with the public key.
"""

import base64
import hashlib
import re
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier

TEMPLATE_OID = ObjectIdentifier("1.3.6.1.4.1.311.20.2")
TEMPLATES = {"sandbox": "TSTZATCA-Code-Signing", "simulation": "PREZATCA-Code-Signing", "production": "ZATCA-Code-Signing"}
OID_SN = NameOID.SURNAME  # 2.5.4.4, written "SN" in ZATCA's config
OID_UID = NameOID.USER_ID  # 0.9.2342.19200300.100.1.1
OID_TITLE = NameOID.TITLE  # 2.5.4.12
OID_REGISTERED_ADDRESS = ObjectIdentifier("2.5.4.26")
OID_BUSINESS_CATEGORY = NameOID.BUSINESS_CATEGORY  # 2.5.4.15
VAT_RE = re.compile(r"^3\d{13}3$")
SERIAL_RE = re.compile(r"^1-[^|]{1,60}\|2-[^|]{1,60}\|3-[^|]{1,80}$")
MAP_RE = re.compile(r"^[01]{4}$")


class CryptoError(ValueError):
    pass


def generate_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256K1())


def key_to_pem(key) -> str:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode("ascii")


def key_from_pem(pem: str):
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256K1):
        raise CryptoError("the EGS key must be an ECDSA secp256k1 key")
    return key


def public_key_der(key_or_cert) -> bytes:
    public = key_or_cert.public_key()
    return public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def _printable_string(value: str) -> bytes:
    data = value.encode("ascii")
    if len(data) > 127:
        raise CryptoError("template name too long")
    return bytes([0x13, len(data)]) + data  # DER PrintableString


def validate_csr_fields(*, common_name, egs_serial, vat_number, branch_name, org_name, functionality_map, location, industry, country="SA"):
    if not VAT_RE.match(vat_number or ""):
        raise CryptoError("The VAT number has 15 digits and starts and ends with 3")
    if not SERIAL_RE.match(egs_serial or ""):
        raise CryptoError("The EGS serial number looks like 1-Solution|2-Version|3-Serial")
    if not MAP_RE.match(functionality_map or ""):
        raise CryptoError("The invoice types are 4 digits of 0 or 1, for example 1100")
    for name, value in (("unit name", common_name), ("branch", branch_name), ("organization name", org_name), ("location", location), ("industry", industry)):
        if not (value or "").strip():
            raise CryptoError(f"The {name} is required")
    if len(country or "") != 2:
        raise CryptoError("The country is a 2-letter code")


def build_csr(key, *, environment, common_name, egs_serial, vat_number, branch_name, org_name, functionality_map, location, industry, country="SA") -> str:
    validate_csr_fields(
        common_name=common_name, egs_serial=egs_serial, vat_number=vat_number, branch_name=branch_name,
        org_name=org_name, functionality_map=functionality_map, location=location, industry=industry, country=country,
    )
    template = TEMPLATES.get(environment)
    if template is None:
        raise CryptoError("unknown environment")
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, country),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, branch_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, org_name),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )
    alt = x509.DirectoryName(
        x509.Name(
            [
                x509.NameAttribute(OID_SN, egs_serial),
                x509.NameAttribute(OID_UID, vat_number),
                x509.NameAttribute(OID_TITLE, functionality_map),
                x509.NameAttribute(OID_REGISTERED_ADDRESS, location),
                x509.NameAttribute(OID_BUSINESS_CATEGORY, industry),
            ]
        )
    )
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .add_extension(x509.UnrecognizedExtension(TEMPLATE_OID, _printable_string(template)), critical=False)
        .add_extension(x509.SubjectAlternativeName([alt]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode("ascii")


def csr_for_api(csr_pem: str, encoding: str = "pem_base64") -> str:
    if encoding == "der_base64":
        csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
        return base64.b64encode(csr.public_bytes(serialization.Encoding.DER)).decode("ascii")
    return base64.b64encode(csr_pem.encode("ascii")).decode("ascii")


# --- certificates ------------------------------------------------------------------------


def certificate_from_token(binary_security_token: str) -> str:
    """ZATCA's ``binarySecurityToken`` is Base64 of the certificate's Base64 DER text. Returns the
    certificate Base64 text (what goes in ds:X509Certificate)."""
    try:
        text = base64.b64decode(binary_security_token, validate=True).decode("ascii").strip()
        load_certificate(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise CryptoError("the CSID certificate could not be read") from exc
    return text


def load_certificate(cert_b64: str) -> x509.Certificate:
    try:
        return x509.load_der_x509_certificate(base64.b64decode(cert_b64, validate=True))
    except ValueError as exc:
        raise CryptoError("the certificate could not be read") from exc


def certificate_hash(cert_b64: str) -> str:
    """xades:CertDigest value as ZATCA computes it: SHA-256 over the certificate's Base64 text,
    hex-encoded, then Base64 (documented on ZATCA's developer community; not plain XAdES)."""
    return base64.b64encode(hashlib.sha256(cert_b64.encode("ascii")).hexdigest().encode("ascii")).decode("ascii")


def issuer_name(cert: x509.Certificate) -> str:
    """Issuer as in ZATCA's samples: ``CN=..., DC=extgazt, DC=gov, DC=local``."""
    return ", ".join(rdn.rfc4514_string() for rdn in reversed(cert.issuer.rdns))


def certificate_signature(cert: x509.Certificate) -> bytes:
    return cert.signature


def sign_hash(key, invoice_hash_b64: str) -> str:
    signature = key.sign(base64.b64decode(invoice_hash_b64), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode("ascii")


def verify_hash_signature(public_der: bytes, invoice_hash_b64: str, signature_b64: str) -> bool:
    public = serialization.load_der_public_key(public_der)
    try:
        public.verify(base64.b64decode(signature_b64), base64.b64decode(invoice_hash_b64), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    return True


def demo_certificate(key, vat_number: str, org_name: str) -> str:
    """A self-signed certificate for the demo workspace only. Clearly not issued by ZATCA."""
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "DEMO - not issued by ZATCA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, org_name[:64] or "Demo"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "SA"),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode("ascii")
