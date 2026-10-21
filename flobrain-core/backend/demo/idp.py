"""A demo SAML identity provider (``DEMO_MODE`` only), so single sign-on can be tried end to end.

The demo org's SSO connection points at ``/api/v2/demo/idp/sso``. That page reads the
AuthnRequest, lists the demo people of the org, and posts a signed SAML response to FloBrain's
real ACS, which checks it exactly as it checks any IdP. The signing key is a throwaway made
when the demo is seeded and kept with the demo connection; it is never used outside the demo.
"""

import base64
import html
import secrets
import zlib
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.http import HttpResponse
from lxml import etree
from signxml import XMLSigner, methods

from sso import saml

IDP_ENTITY = "https://idp.demo.flobrain.example/saml"
SAML_NS, SAMLP = saml.SAML, saml.SAMLP


def sso_url() -> str:
    return f"{saml._base()}/api/v2/demo/idp/sso"


def make_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Demo IdP (FloBrain demo only)")])
    now = datetime.now(dt_timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=730))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return key_pem, cert.public_bytes(serialization.Encoding.PEM).decode()


def configure(org):
    """Point the demo org's SSO at the demo IdP (called from the demo seed)."""
    from demo.seed import DEMO_DOMAIN
    from sso.models import SSOConnection

    key_pem, cert_pem = make_keypair()
    _, fingerprint, _ = saml.parse_certificate(cert_pem)
    return SSOConnection.objects.update_or_create(
        org=org,
        defaults=dict(
            protocol=SSOConnection.PROTOCOL_SAML, issuer=IDP_ENTITY, client_id="", secret_ciphertext=b"",
            idp_entity_id=IDP_ENTITY, idp_sso_url=sso_url(), idp_cert_pem=cert_pem, idp_cert_fingerprint=fingerprint,
            verified_domains=[DEMO_DOMAIN], enabled=True, enforced=False, metadata={"demo_idp_key": key_pem},
        ),
    )[0]


def _iso(delta=0):
    return (datetime.now(dt_timezone.utc) + timedelta(seconds=delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _el(parent, ns, tag, text=None, **attrs):
    node = etree.SubElement(parent, f"{{{ns}}}{tag}", **attrs)
    if text is not None:
        node.text = text
    return node


def read_request(encoded):
    """(request id, SP entity id) from a deflated, base64 AuthnRequest, or None."""
    try:
        xml = zlib.decompress(base64.b64decode(encoded or "", validate=True), -15)
        root = saml._parse(xml)
    except (ValueError, zlib.error, saml.SAMLError):
        return None
    if root.tag != f"{{{SAMLP}}}AuthnRequest" or root.get("AssertionConsumerServiceURL") != saml.acs_url():
        return None
    issuer = root.find("saml:Issuer", saml.NS)
    return (root.get("ID"), saml._text(issuer)) if root.get("ID") and issuer is not None else None


def signed_response(connection, request_id, email) -> str:
    key = serialization.load_pem_private_key(connection.metadata["demo_idp_key"].encode(), password=None)
    cert = x509.load_pem_x509_certificate(connection.idp_cert_pem.encode())
    a = etree.Element(f"{{{SAML_NS}}}Assertion", nsmap={"saml": SAML_NS}, ID=f"_a{secrets.token_hex(10)}", Version="2.0", IssueInstant=_iso())
    _el(a, SAML_NS, "Issuer", IDP_ENTITY)
    subject = _el(a, SAML_NS, "Subject")
    _el(subject, SAML_NS, "NameID", email, Format=saml.EMAIL_FORMAT)
    conf = _el(subject, SAML_NS, "SubjectConfirmation", Method=saml.BEARER)
    _el(conf, SAML_NS, "SubjectConfirmationData", InResponseTo=request_id, Recipient=saml.acs_url(), NotOnOrAfter=_iso(300))
    cond = _el(a, SAML_NS, "Conditions", NotBefore=_iso(-30), NotOnOrAfter=_iso(300))
    _el(_el(cond, SAML_NS, "AudienceRestriction"), SAML_NS, "Audience", saml.sp_entity_id(connection.org_id))
    _el(a, SAML_NS, "AuthnStatement", AuthnInstant=_iso())
    a = XMLSigner(method=methods.enveloped, c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#").sign(a, key=key, cert=[cert])
    r = etree.Element(f"{{{SAMLP}}}Response", nsmap={"samlp": SAMLP, "saml": SAML_NS}, ID=f"_r{secrets.token_hex(10)}", Version="2.0",
                      IssueInstant=_iso(), Destination=saml.acs_url(), InResponseTo=request_id)
    _el(r, SAML_NS, "Issuer", IDP_ENTITY)
    _el(_el(r, SAMLP, "Status"), SAMLP, "StatusCode", Value=saml.SUCCESS)
    r.append(a)
    return base64.b64encode(etree.tostring(r)).decode("ascii")


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Demo sign-in</title><style>
body{{font:16px/1.5 system-ui,sans-serif;background:#14101f;color:#f3f0fa;margin:0;display:grid;place-items:center;min-height:100vh}}
main{{max-width:28rem;padding:2rem 1rem}}h1{{font-size:1.4rem;margin:0 0 .25rem}}p{{color:#b9b1cc;margin:0 0 1.5rem}}
button{{display:block;width:100%;text-align:start;margin:.5rem 0;padding:.8rem 1rem;border-radius:.75rem;border:1px solid #3a3150;background:#211a31;color:inherit;font:inherit;cursor:pointer}}
button:hover,button:focus-visible{{border-color:#a855f7;outline:none}}small{{display:block;color:#b9b1cc}}
</style></head><body><main><h1>Demo identity provider</h1>
<p>This stands in for your company's Okta, Entra ID or Google Workspace. Pick who signs in; FloBrain checks the signed answer like any real IdP's.</p>
{forms}</main></body></html>"""


def page(connection, request_id, relay_state):
    from organizations.models import OrgMembership

    people = OrgMembership.objects.filter(org=connection.org, employment_status="active", user__is_platform_admin=False).select_related("user").order_by("user__username")
    forms = []
    for m in people[:12]:
        email = m.user.email
        if email.rsplit("@", 1)[-1] not in connection.verified_domains:
            continue
        forms.append(
            f'<form method="post" action="{html.escape(saml.acs_url())}">'
            f'<input type="hidden" name="SAMLResponse" value="{signed_response(connection, request_id, email)}">'
            f'<input type="hidden" name="RelayState" value="{html.escape(relay_state)}">'
            f'<button type="submit">{html.escape(m.user.username or email)}<small>{html.escape(email)}</small></button></form>'
        )
    body = PAGE.format(forms="".join(forms) or "<p>No demo people to sign in.</p>")
    response = HttpResponse(body, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = f"default-src 'none'; style-src 'unsafe-inline'; form-action {saml._base()}"
    response["Cache-Control"] = "no-store"
    return response
