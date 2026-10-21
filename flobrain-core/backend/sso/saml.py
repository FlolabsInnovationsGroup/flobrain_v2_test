"""SAML 2.0 Web SSO, SP-initiated only (HTTP-Redirect AuthnRequest, HTTP-POST response).

The response is trusted only through the signed element ``signxml`` hands back
(``verify(...).signed_xml``), verified with the IdP certificate the owner pasted, never
one inside the message. Before that, the document must hold exactly one Response and
one Assertion (no wrapping), no DTD or entities, no encrypted assertion. Then:
``InResponseTo`` is a stored, unexpired request ID used once; ``Destination`` and
``Recipient`` are our ACS; ``Audience`` is this org's SP entity ID; time windows with
90 s of skew; ``Issuer`` is the IdP entity ID; status Success. After that the same
rules as OIDC apply (``oidc.member_for``) and the same one-time browser-bound code.
IdP-initiated (unsolicited) responses are refused.
"""

import base64
import hashlib
import hmac
import secrets
import urllib.parse
import zlib
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.conf import settings
from django.utils import timezone
from lxml import etree
from signxml import SignatureConfiguration, XMLVerifier
from signxml.exceptions import SignXMLException

from sso import oidc
from sso.models import SAMLRequest

SAMLP = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML = "urn:oasis:names:tc:SAML:2.0:assertion"
MD = "urn:oasis:names:tc:SAML:2.0:metadata"
DS = "http://www.w3.org/2000/09/xmldsig#"
NS = {"samlp": SAMLP, "saml": SAML, "ds": DS}
EMAIL_FORMAT = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
REDIRECT_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
SKEW = timedelta(seconds=90)
REQUEST_TTL = timedelta(minutes=10)
MAX_RESPONSE_CHARS = 512 * 1024


class SAMLError(oidc.OIDCError):
    pass


def _q(ns, tag):
    return f"{{{ns}}}{tag}"


def _base():
    return (getattr(settings, "PUBLIC_API_BASE_URL", "") or "http://localhost:8000").rstrip("/")


def acs_url() -> str:
    return f"{_base()}/api/v2/sso/saml/acs"


def sp_entity_id(org_id) -> str:
    """Per org (also the metadata URL), so an assertion for one org is never good for another."""
    return f"{_base()}/api/v2/sso/saml/{org_id}/metadata"


def is_complete(connection) -> bool:
    return bool(connection.idp_entity_id and connection.idp_sso_url and connection.idp_cert_pem)


# --- certificate -------------------------------------------------------------------------


def parse_certificate(text):
    """Return (pem, sha256 fingerprint, not_valid_after) for one IdP signing certificate."""
    text = str(text or "").strip()
    if not text or len(text) > 20000 or text.count("-----BEGIN") > 1:
        raise SAMLError("bad_certificate")
    if "-----BEGIN CERTIFICATE-----" not in text:  # bare base64, as in IdP metadata
        text = "-----BEGIN CERTIFICATE-----\n" + "".join(text.split()) + "\n-----END CERTIFICATE-----\n"
    try:
        cert = x509.load_pem_x509_certificate(text.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise SAMLError("bad_certificate") from exc
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        if key.key_size < 2048:
            raise SAMLError("weak_certificate")
    elif not isinstance(key, ec.EllipticCurvePublicKey):
        raise SAMLError("bad_certificate")
    if cert.not_valid_after_utc <= timezone.now():
        raise SAMLError("certificate_expired")
    fingerprint = ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii"), fingerprint, cert.not_valid_after_utc


def certificate_expiry(pem):
    try:
        return x509.load_pem_x509_certificate(pem.encode("ascii")).not_valid_after_utc
    except (ValueError, UnicodeEncodeError, AttributeError):
        return None


# --- XML ---------------------------------------------------------------------------------


def _parser():
    """No DTDs, no entity expansion, no network: XXE and billion-laughs stay out."""
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False)


def _parse(data: bytes):
    try:
        root = etree.fromstring(data, parser=_parser())
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise SAMLError("bad_response") from exc
    info = root.getroottree().docinfo
    if info.doctype or info.internalDTD is not None or info.externalDTD is not None:
        raise SAMLError("bad_response")
    if next(root.iter(etree.Entity), None) is not None:
        raise SAMLError("bad_response")
    return root


def _text(node):
    return None if node is None else "".join(node.itertext()).strip()


def _time(value):
    try:
        moment = datetime.fromisoformat(value.strip())
    except (AttributeError, ValueError) as exc:
        raise SAMLError("bad_response") from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=dt_timezone.utc)


def _instant(moment) -> str:
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def metadata_xml(connection) -> bytes:
    root = etree.Element(_q(MD, "EntityDescriptor"), nsmap={"md": MD}, entityID=sp_entity_id(connection.org_id))
    sp = etree.SubElement(
        root,
        _q(MD, "SPSSODescriptor"),
        AuthnRequestsSigned="false",
        WantAssertionsSigned="true",
        protocolSupportEnumeration=SAMLP,
    )
    etree.SubElement(sp, _q(MD, "NameIDFormat")).text = EMAIL_FORMAT
    etree.SubElement(sp, _q(MD, "AssertionConsumerService"), Binding=POST_BINDING, Location=acs_url(), index="0", isDefault="true")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _authn_request(connection, request_id) -> bytes:
    root = etree.Element(
        _q(SAMLP, "AuthnRequest"),
        nsmap={"samlp": SAMLP, "saml": SAML},
        ID=request_id,
        Version="2.0",
        IssueInstant=_instant(timezone.now()),
        Destination=connection.idp_sso_url,
        AssertionConsumerServiceURL=acs_url(),
        ProtocolBinding=POST_BINDING,
    )
    etree.SubElement(root, _q(SAML, "Issuer")).text = sp_entity_id(connection.org_id)
    if not connection.email_attribute:
        etree.SubElement(root, _q(SAMLP, "NameIDPolicy"), Format=EMAIL_FORMAT, AllowCreate="true")
    return etree.tostring(root)


def _sha(value) -> str:
    return hashlib.sha256((value or "").encode()).hexdigest()


# --- flow --------------------------------------------------------------------------------


def start(connection, client_nonce) -> str:
    """The IdP URL with a deflated, base64 AuthnRequest (HTTP-Redirect binding)."""
    if not is_complete(connection):
        raise SAMLError("disabled")
    request_id = "_" + secrets.token_hex(20)
    relay_state = secrets.token_urlsafe(32)
    SAMLRequest.objects.create(
        connection=connection,
        request_id=request_id,
        relay_hash=_sha(relay_state),
        client_hash=oidc.client_hash(client_nonce),
        expires_at=timezone.now() + REQUEST_TTL,
    )
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)  # raw DEFLATE, as the binding requires
    deflated = packer.compress(_authn_request(connection, request_id)) + packer.flush()
    query = urllib.parse.urlencode({"SAMLRequest": base64.b64encode(deflated).decode("ascii"), "RelayState": relay_state})
    return f"{connection.idp_sso_url}{'&' if '?' in connection.idp_sso_url else '?'}{query}"


def _pending_request(request_id, relay_state):
    row = (
        SAMLRequest.objects.select_related("connection", "connection__org")
        .filter(request_id=request_id or "-", used_at__isnull=True)
        .first()
    )
    if row is None or row.expires_at <= timezone.now():
        raise SAMLError("invalid_state")
    if not hmac.compare_digest(row.relay_hash, _sha(relay_state)):
        raise SAMLError("invalid_state")
    return row


def _verified(xml, root, assertion, connection):
    """Check the signature and return (response or None, assertion), both from the signed bytes only."""
    cert = x509.load_pem_x509_certificate(connection.idp_cert_pem.encode("ascii"))
    if root.find("ds:Signature", NS) is not None:
        location, tag, element_id = "./", _q(SAMLP, "Response"), root.get("ID")
    elif assertion.find("ds:Signature", NS) is not None:
        location, tag, element_id = f"./{_q(SAML, 'Assertion')}/", _q(SAML, "Assertion"), assertion.get("ID")
    else:
        raise SAMLError("unsigned")
    if not element_id:
        raise SAMLError("bad_response")
    try:
        result = XMLVerifier().verify(
            xml,
            x509_cert=cert,
            parser=_parser(),
            expect_config=SignatureConfiguration(location=location, expect_references=1),
        )
    except (SignXMLException, etree.XMLSyntaxError, ValueError, TypeError) as exc:
        raise SAMLError("bad_signature") from exc
    signed = result.signed_xml
    if signed is None or signed.tag != tag or signed.get("ID") != element_id:
        raise SAMLError("bad_signature")  # the signature must cover the element that holds it
    if tag == _q(SAML, "Assertion"):
        return None, signed
    inner = signed.findall("saml:Assertion", NS)
    if len(inner) != 1:
        raise SAMLError("bad_response")
    return signed, inner[0]


def _check_confirmation(data, request_id, now):
    if data is None:
        return "bad_subject"
    if data.get("Recipient") != acs_url():
        return "bad_destination"
    if data.get("InResponseTo") != request_id:
        return "invalid_state"
    if not data.get("NotOnOrAfter") or _time(data.get("NotOnOrAfter")) <= now - SKEW:
        return "expired"
    if data.get("NotBefore") and _time(data.get("NotBefore")) > now + SKEW:
        return "not_yet_valid"
    return None


def _email(connection, assertion):
    name = connection.email_attribute
    values = []
    if not name:
        name_id = assertion.find("saml:Subject/saml:NameID", NS)
        if name_id is not None and name_id.get("Format") == EMAIL_FORMAT:
            values = [_text(name_id)]
        else:
            name = "email"
    if name:
        for attribute in assertion.iterfind("saml:AttributeStatement/saml:Attribute", NS):
            if attribute.get("Name") == name:
                values += [_text(v) for v in attribute.findall("saml:AttributeValue", NS)]
    values = {v.lower() for v in values if v}
    if len(values) != 1:
        raise SAMLError("no_email")
    email = values.pop()
    if len(email) > 254 or email.count("@") != 1 or any(ch.isspace() for ch in email) or email.startswith("@") or email.endswith("@"):
        raise SAMLError("no_email")
    return email


def finish(saml_response, relay_state):
    """Return (user, org, client_hash) for a valid HTTP-POST response, or raise SAMLError."""
    raw = "".join(str(saml_response or "").split())
    if not raw or len(raw) > MAX_RESPONSE_CHARS:
        raise SAMLError("bad_response")
    try:
        xml = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise SAMLError("bad_response") from exc
    root = _parse(xml)
    if root.tag != _q(SAMLP, "Response") or sum(1 for _ in root.iter(_q(SAMLP, "Response"))) != 1:
        raise SAMLError("bad_response")
    if next(root.iter(_q(SAML, "EncryptedAssertion")), None) is not None:
        raise SAMLError("encrypted_assertion")
    assertions = list(root.iter(_q(SAML, "Assertion")))
    if len(assertions) != 1 or assertions[0].getparent() is not root:
        raise SAMLError("bad_response")  # one assertion, directly in the response: nothing to wrap

    # Unverified lookup only to find which IdP certificate to check with.
    unverified = root.find("saml:Assertion/saml:Subject/saml:SubjectConfirmation/saml:SubjectConfirmationData", NS)
    request_id = root.get("InResponseTo") or (unverified.get("InResponseTo") if unverified is not None else None)
    row = _pending_request(request_id, relay_state)
    connection = row.connection
    if not connection.enabled or connection.protocol != connection.PROTOCOL_SAML or not is_complete(connection):
        raise SAMLError("disabled")

    response, assertion = _verified(xml, root, assertions[0], connection)
    if not SAMLRequest.objects.filter(pk=row.pk, used_at__isnull=True).update(used_at=timezone.now()):
        raise SAMLError("invalid_state")  # single use, even under a race

    now = timezone.now()
    idp = connection.idp_entity_id
    # The outer response is trusted only when signed; unsigned, it can still make us refuse.
    outer = response if response is not None else root
    status = outer.find("samlp:Status/samlp:StatusCode", NS)
    if status is None or status.get("Value") != SUCCESS:
        raise SAMLError("idp_error")
    destination = outer.get("Destination")
    if destination != acs_url() and (response is not None or destination is not None):
        raise SAMLError("bad_destination")
    if outer.get("InResponseTo") not in (None, row.request_id):
        raise SAMLError("invalid_state")
    outer_issuer = outer.find("saml:Issuer", NS)
    if outer_issuer is not None and _text(outer_issuer) != idp:
        raise SAMLError("bad_issuer")

    if assertion.get("Version") != "2.0":
        raise SAMLError("bad_response")
    if _text(assertion.find("saml:Issuer", NS)) != idp:
        raise SAMLError("bad_issuer")
    bearers = [c for c in assertion.findall("saml:Subject/saml:SubjectConfirmation", NS) if c.get("Method") == BEARER]
    problems = [_check_confirmation(c.find("saml:SubjectConfirmationData", NS), row.request_id, now) for c in bearers]
    if None not in problems:
        raise SAMLError(problems[0] if problems else "bad_subject")
    conditions = assertion.find("saml:Conditions", NS)
    if conditions is None or not conditions.get("NotOnOrAfter") or _time(conditions.get("NotOnOrAfter")) <= now - SKEW:
        raise SAMLError("expired")
    if conditions.get("NotBefore") and _time(conditions.get("NotBefore")) > now + SKEW:
        raise SAMLError("not_yet_valid")
    restrictions = conditions.findall("saml:AudienceRestriction", NS)
    audience = sp_entity_id(connection.org_id)
    if not restrictions or any(audience not in [_text(a) for a in r.findall("saml:Audience", NS)] for r in restrictions):
        raise SAMLError("bad_audience")
    if assertion.find("saml:AuthnStatement", NS) is None:
        raise SAMLError("bad_response")

    return oidc.member_for(connection, _email(connection, assertion)), connection.org, row.client_hash
