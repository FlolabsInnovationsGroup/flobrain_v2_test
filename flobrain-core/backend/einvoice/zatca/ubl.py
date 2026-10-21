"""UBL 2.1 invoice XML for ZATCA, the invoice hash, the XAdES block in UBLExtensions and the QR.

Sources (cited in docs/v2/features/EINVOICE.md): ZATCA E-invoicing XML Implementation Standard
(2023-05-19), Security Features Implementation Standard (2023-05-19), E-invoicing Detailed
Technical Guidelines, and the signing procedure published on ZATCA's developer community.

Layout (element order follows the UBL 2.1 Invoice schema):
ext:UBLExtensions (the signature), cbc:ProfileID ``reporting:1.0``, cbc:ID, cbc:UUID, IssueDate,
IssueTime, InvoiceTypeCode (388 invoice, 381 credit note, 383 debit note; ``@name`` is the
transaction code: "01" standard or "02" simplified, then five flags for third party, nominal,
export, summary and self-billed, all 0 here), Note, DocumentCurrencyCode, TaxCurrencyCode (SAR),
BillingReference (notes), AdditionalDocumentReference ICV (counter, KSA-16), PIH (previous invoice
hash, KSA-13) and QR (KSA-14), cac:Signature, seller, buyer, Delivery (supply date, KSA-5),
PaymentMeans (and the note reason, KSA-10), two TaxTotal blocks (BT-110 in SAR; then the VAT
breakdown), LegalMonetaryTotal, InvoiceLine (with line VAT KSA-11 and amount with VAT KSA-12).

The XML is written without indentation, so removing the signature, ``cac:Signature`` and the QR
reference for hashing leaves no stray whitespace and the hash is the same whoever removes them.

Hash (Security Features standard): remove ``ext:UBLExtensions``, ``cac:Signature`` and
``cac:AdditionalDocumentReference[cbc:ID='QR']``, canonicalize (C14N 1.1; for this document,
which has no xml:id or xml:base attributes, lxml's C14N 1.0 output is byte-identical), SHA-256,
Base64 of the 32 raw bytes. The first document of an EGS uses the PIH ``INITIAL_PIH``
(Base64 of the hex SHA-256 of "0", as in ZATCA's SDK samples).

Signature block: the procedure documented by ZATCA (``Signing Process`` on the developer
community): the SignatureValue is the ECDSA signature of the invoice hash; the certificate digest
and the SignedProperties digest are Base64 of the *hex* SHA-256 (a ZATCA specific, not plain
XAdES). SignedProperties is written exactly as its exclusive canonical form, so its digest is the
same whether a validator hashes the text or canonicalizes the element. This must be checked with
the official SDK (``fatoora -validate``) and the compliance API before going live.
"""

import base64
import hashlib
from decimal import Decimal

from lxml import etree

from einvoice.money import fmt2
from einvoice.zatca import crypto, qr

NS_INV = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
NS_EXT = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"
NSMAP = {None: NS_INV, "cac": NS_CAC, "cbc": NS_CBC, "ext": NS_EXT}
XPATH_NS = {"inv": NS_INV, "cac": NS_CAC, "cbc": NS_CBC, "ext": NS_EXT}

INITIAL_PIH = base64.b64encode(hashlib.sha256(b"0").hexdigest().encode("ascii")).decode("ascii")
TYPE_CODES = {"invoice": "388", "credit": "381", "debit": "383"}
TRANSACTION = {"standard": "0100000", "simplified": "0200000"}
# ZATCA's SDK samples use the xmldsig SignatureProperties type for the second reference; the
# Security Features standard names the ETSI type. Kept as a constant to switch if ZATCA says so.
SIGNED_PROPERTIES_TYPE = "http://www.w3.org/2000/09/xmldsig#SignatureProperties"


class UBLError(ValueError):
    pass


def _el(parent, tag, text=None, **attrs):
    prefix, _, local = tag.partition(":")
    ns = {"cac": NS_CAC, "cbc": NS_CBC, "ext": NS_EXT}[prefix]
    node = etree.SubElement(parent, f"{{{ns}}}{local}")
    for key, value in attrs.items():
        node.set(key, value)
    if text is not None:
        node.text = str(text)
    return node


def _amount(parent, tag, value, currency):
    return _el(parent, tag, fmt2(value), currencyID=currency)


def _qty(value: Decimal) -> str:
    return f"{Decimal(value):.6f}"


def _price(value) -> str:
    """Unit price: 2 decimals, or more when the price has them (BT-146 has no 2-decimal rule)."""
    value = Decimal(value)
    if value == value.quantize(Decimal("0.01")):
        return f"{value:.2f}"
    return f"{value.normalize():f}"


def _address(parent, party: dict):
    address = _el(parent, "cac:PostalAddress")
    for key, tag in (("street", "cbc:StreetName"), ("building", "cbc:BuildingNumber"), ("district", "cbc:CitySubdivisionName"), ("city", "cbc:CityName"), ("postal", "cbc:PostalZone")):
        if party.get(key):
            _el(address, tag, party[key])
    country = _el(address, "cac:Country")
    _el(country, "cbc:IdentificationCode", party.get("country") or "SA")


def _party(root, tag, party: dict, *, seller: bool):
    wrapper = _el(root, tag)
    node = _el(wrapper, "cac:Party")
    if party.get("reg_id"):
        ident = _el(node, "cac:PartyIdentification")
        _el(ident, "cbc:ID", party["reg_id"], schemeID=party.get("scheme") or "CRN")
    if seller or any(party.get(k) for k in ("street", "city", "postal")):
        _address(node, party)
    if seller or party.get("vat"):
        scheme = _el(node, "cac:PartyTaxScheme")
        if party.get("vat"):
            _el(scheme, "cbc:CompanyID", party["vat"])
        tax = _el(scheme, "cac:TaxScheme")
        _el(tax, "cbc:ID", "VAT")
    if party.get("name"):
        legal = _el(node, "cac:PartyLegalEntity")
        _el(legal, "cbc:RegistrationName", party["name"])


def _tax_category(parent, tag, category, rate, code="", reason="", scheme_ids=True):
    node = _el(parent, tag)
    if scheme_ids:
        _el(node, "cbc:ID", category, schemeID="UN/ECE 5305", schemeAgencyID="6")
    else:
        _el(node, "cbc:ID", category)
    _el(node, "cbc:Percent", f"{Decimal(rate):.2f}")
    if code:
        _el(node, "cbc:TaxExemptionReasonCode", code)
    if reason:
        _el(node, "cbc:TaxExemptionReason", reason)
    scheme = _el(node, "cac:TaxScheme")
    if scheme_ids:
        _el(scheme, "cbc:ID", "VAT", schemeID="UN/ECE 5153", schemeAgencyID="6")
    else:
        _el(scheme, "cbc:ID", "VAT")
    return node


def _doc_reference(root, ident, *, uuid=None, binary=None):
    ref = _el(root, "cac:AdditionalDocumentReference")
    _el(ref, "cbc:ID", ident)
    if uuid is not None:
        _el(ref, "cbc:UUID", uuid)
    if binary is not None:
        attachment = _el(ref, "cac:Attachment")
        _el(attachment, "cbc:EmbeddedDocumentBinaryObject", binary, mimeCode="text/plain")
    return ref


def build_tree(data: dict) -> etree._Element:
    """The invoice without UBLExtensions, with an empty QR reference to fill after hashing."""
    currency = data["currency"]
    if currency != "SAR":
        raise UBLError("Saudi invoices are issued in SAR here (BT-111 needs the VAT in SAR)")
    root = etree.Element(f"{{{NS_INV}}}Invoice", nsmap=NSMAP)
    _el(root, "cbc:ProfileID", "reporting:1.0")
    _el(root, "cbc:ID", data["number"])
    _el(root, "cbc:UUID", data["uuid"])
    _el(root, "cbc:IssueDate", data["issue_date"])
    _el(root, "cbc:IssueTime", data["issue_time"])
    _el(root, "cbc:InvoiceTypeCode", TYPE_CODES[data["kind"]], name=TRANSACTION[data["type"]])
    if data.get("note"):
        _el(root, "cbc:Note", data["note"], languageID=data.get("note_language") or "ar")
    _el(root, "cbc:DocumentCurrencyCode", currency)
    _el(root, "cbc:TaxCurrencyCode", "SAR")
    if data["kind"] != "invoice":
        if not data.get("billing_reference"):
            raise UBLError("A credit or debit note needs the number of the original invoice")
        billing = _el(root, "cac:BillingReference")
        ref = _el(billing, "cac:InvoiceDocumentReference")
        _el(ref, "cbc:ID", data["billing_reference"])
    _doc_reference(root, "ICV", uuid=str(data["icv"]))
    _doc_reference(root, "PIH", binary=data["pih"])
    _doc_reference(root, "QR", binary="")
    signature = _el(root, "cac:Signature")
    _el(signature, "cbc:ID", "urn:oasis:names:specification:ubl:signature:Invoice")
    _el(signature, "cbc:SignatureMethod", "urn:oasis:names:specification:ubl:dsig:enveloped:xades")
    _party(root, "cac:AccountingSupplierParty", data["seller"], seller=True)
    _party(root, "cac:AccountingCustomerParty", data.get("buyer") or {}, seller=False)
    if data.get("supply_date"):
        delivery = _el(root, "cac:Delivery")
        _el(delivery, "cbc:ActualDeliveryDate", data["supply_date"])
    means = _el(root, "cac:PaymentMeans")
    _el(means, "cbc:PaymentMeansCode", data.get("payment_means") or "10")
    if data["kind"] != "invoice":
        if not data.get("adjustment_reason"):
            raise UBLError("A credit or debit note needs the reason for the change")
        _el(means, "cbc:InstructionNote", data["adjustment_reason"])
    totals = data["totals"]
    first = _el(root, "cac:TaxTotal")
    _amount(first, "cbc:TaxAmount", totals["tax_total"], "SAR")
    second = _el(root, "cac:TaxTotal")
    _amount(second, "cbc:TaxAmount", totals["tax_total"], currency)
    for group in totals["breakdown"]:
        sub = _el(second, "cac:TaxSubtotal")
        _amount(sub, "cbc:TaxableAmount", group["taxable"], currency)
        _amount(sub, "cbc:TaxAmount", group["tax"], currency)
        _tax_category(sub, "cac:TaxCategory", group["category"], group["rate"], group.get("exemption_code", ""), group.get("exemption_reason", ""))
    legal = _el(root, "cac:LegalMonetaryTotal")
    _amount(legal, "cbc:LineExtensionAmount", totals["line_extension"], currency)
    _amount(legal, "cbc:TaxExclusiveAmount", totals["tax_exclusive"], currency)
    _amount(legal, "cbc:TaxInclusiveAmount", totals["tax_inclusive"], currency)
    _amount(legal, "cbc:AllowanceTotalAmount", 0, currency)
    _amount(legal, "cbc:PrepaidAmount", 0, currency)
    _amount(legal, "cbc:PayableAmount", totals["payable"], currency)
    for line in data["lines"]:
        node = _el(root, "cac:InvoiceLine")
        _el(node, "cbc:ID", str(line["id"]))
        _el(node, "cbc:InvoicedQuantity", _qty(line["quantity"]), unitCode=line.get("unit_code") or "PCE")
        _amount(node, "cbc:LineExtensionAmount", line["net"], currency)
        if Decimal(line.get("discount") or 0) > 0:
            # Line allowance (BG-27): reason, amount and the base it applies to.
            allowance = _el(node, "cac:AllowanceCharge")
            _el(allowance, "cbc:ChargeIndicator", "false")
            _el(allowance, "cbc:AllowanceChargeReason", "discount")
            _amount(allowance, "cbc:Amount", line["discount"], currency)
            _amount(allowance, "cbc:BaseAmount", line["gross"], currency)
        tax = _el(node, "cac:TaxTotal")
        _amount(tax, "cbc:TaxAmount", line["vat"], currency)
        _amount(tax, "cbc:RoundingAmount", line["total"], currency)
        item = _el(node, "cac:Item")
        _el(item, "cbc:Name", line["description"])
        _tax_category(item, "cac:ClassifiedTaxCategory", line["category"], line["rate"], scheme_ids=False)
        price = _el(node, "cac:Price")
        _el(price, "cbc:PriceAmount", _price(line["unit_price"]), currencyID=currency)
    return root


# --- hashing -----------------------------------------------------------------------------


def _remove(node):
    """Remove an element but keep the text after it (XPath filtering keeps sibling text nodes)."""
    parent = node.getparent()
    if node.tail:
        previous = node.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + node.tail
        else:
            parent.text = (parent.text or "") + node.tail
    parent.remove(node)


def hashable(root) -> bytes:
    copy = etree.fromstring(etree.tostring(root))
    for node in copy.xpath("//ext:UBLExtensions | //cac:Signature | //cac:AdditionalDocumentReference[normalize-space(cbc:ID)='QR']", namespaces=XPATH_NS):
        _remove(node)
    return etree.tostring(copy, method="c14n", exclusive=False, with_comments=False)


def invoice_hash(root_or_xml) -> str:
    root = etree.fromstring(root_or_xml.encode("utf-8") if isinstance(root_or_xml, str) else root_or_xml) if isinstance(root_or_xml, (str, bytes)) else root_or_xml
    return base64.b64encode(hashlib.sha256(hashable(root)).digest()).decode("ascii")


# --- signature block ---------------------------------------------------------------------


def signed_properties(signing_time: str, cert_digest: str, issuer: str, serial: int) -> str:
    sp = etree.Element(f"{{{NS_XADES}}}SignedProperties", nsmap={"xades": NS_XADES})
    sp.set("Id", "xadesSignedProperties")
    ssp = etree.SubElement(sp, f"{{{NS_XADES}}}SignedSignatureProperties")
    etree.SubElement(ssp, f"{{{NS_XADES}}}SigningTime").text = signing_time
    cert = etree.SubElement(etree.SubElement(ssp, f"{{{NS_XADES}}}SigningCertificate"), f"{{{NS_XADES}}}Cert")
    digest = etree.SubElement(cert, f"{{{NS_XADES}}}CertDigest")
    etree.SubElement(digest, f"{{{NS_DS}}}DigestMethod", nsmap={"ds": NS_DS}).set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
    etree.SubElement(digest, f"{{{NS_DS}}}DigestValue", nsmap={"ds": NS_DS}).text = cert_digest
    serial_node = etree.SubElement(cert, f"{{{NS_XADES}}}IssuerSerial")
    etree.SubElement(serial_node, f"{{{NS_DS}}}X509IssuerName", nsmap={"ds": NS_DS}).text = issuer
    etree.SubElement(serial_node, f"{{{NS_DS}}}X509SerialNumber", nsmap={"ds": NS_DS}).text = str(serial)
    return etree.tostring(sp, method="c14n", exclusive=True).decode("utf-8")


def hex_b64_sha256(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).hexdigest().encode("ascii")).decode("ascii")


def ubl_extensions(*, invoice_hash_b64: str, signature_b64: str, cert_b64: str, signed_props: str) -> str:
    props_digest = hex_b64_sha256(signed_props)
    return (
        "<ext:UBLExtensions><ext:UBLExtension>"
        "<ext:ExtensionURI>urn:oasis:names:specification:ubl:dsig:enveloped:xades</ext:ExtensionURI>"
        "<ext:ExtensionContent>"
        '<sig:UBLDocumentSignatures xmlns:sig="urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2" '
        'xmlns:sac="urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2" '
        'xmlns:sbc="urn:oasis:names:specification:ubl:schema:xsd:SignatureBasicComponents-2">'
        "<sac:SignatureInformation>"
        "<cbc:ID>urn:oasis:names:specification:ubl:signature:1</cbc:ID>"
        "<sbc:ReferencedSignatureID>urn:oasis:names:specification:ubl:signature:Invoice</sbc:ReferencedSignatureID>"
        f'<ds:Signature xmlns:ds="{NS_DS}" Id="signature">'
        "<ds:SignedInfo>"
        '<ds:CanonicalizationMethod Algorithm="http://www.w3.org/2006/12/xml-c14n11"/>'
        '<ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"/>'
        '<ds:Reference Id="invoiceSignedData" URI="">'
        "<ds:Transforms>"
        '<ds:Transform Algorithm="http://www.w3.org/TR/1999/REC-xpath-19991116"><ds:XPath>not(//ancestor-or-self::ext:UBLExtensions)</ds:XPath></ds:Transform>'
        '<ds:Transform Algorithm="http://www.w3.org/TR/1999/REC-xpath-19991116"><ds:XPath>not(//ancestor-or-self::cac:Signature)</ds:XPath></ds:Transform>'
        "<ds:Transform Algorithm=\"http://www.w3.org/TR/1999/REC-xpath-19991116\"><ds:XPath>not(//ancestor-or-self::cac:AdditionalDocumentReference[cbc:ID='QR'])</ds:XPath></ds:Transform>"
        '<ds:Transform Algorithm="http://www.w3.org/2006/12/xml-c14n11"/>'
        "</ds:Transforms>"
        '<ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>'
        f"<ds:DigestValue>{invoice_hash_b64}</ds:DigestValue>"
        "</ds:Reference>"
        f'<ds:Reference Type="{SIGNED_PROPERTIES_TYPE}" URI="#xadesSignedProperties">'
        '<ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>'
        f"<ds:DigestValue>{props_digest}</ds:DigestValue>"
        "</ds:Reference>"
        "</ds:SignedInfo>"
        f"<ds:SignatureValue>{signature_b64}</ds:SignatureValue>"
        f"<ds:KeyInfo><ds:X509Data><ds:X509Certificate>{cert_b64}</ds:X509Certificate></ds:X509Data></ds:KeyInfo>"
        "<ds:Object>"
        f'<xades:QualifyingProperties xmlns:xades="{NS_XADES}" Target="signature">'
        f"{signed_props}"
        "</xades:QualifyingProperties>"
        "</ds:Object>"
        "</ds:Signature>"
        "</sac:SignatureInformation>"
        "</sig:UBLDocumentSignatures>"
        "</ext:ExtensionContent>"
        "</ext:UBLExtension></ext:UBLExtensions>"
    )


def qr_timestamp(data: dict, suffix: str = "") -> str:
    return f"{data['issue_date']}T{data['issue_time']}{suffix}"


def finalize(data: dict, key, cert_b64: str, *, signing_time: str, qr_hash_encoding: str = qr.HASH_TEXT, qr_time_suffix: str = "") -> dict:
    """Build, hash, sign and stamp. Returns {xml, hash, qr, signature}."""
    root = build_tree(data)
    hash_b64 = invoice_hash(root)
    signature_b64 = crypto.sign_hash(key, hash_b64)
    cert = crypto.load_certificate(cert_b64)
    props = signed_properties(signing_time, crypto.certificate_hash(cert_b64), crypto.issuer_name(cert), cert.serial_number)
    totals = data["totals"]
    seller = data["seller"]
    qr_value = qr.phase2(
        seller["name"],
        seller["vat"],
        qr_timestamp(data, qr_time_suffix),
        fmt2(totals["tax_inclusive"]),
        fmt2(totals["tax_total"]),
        invoice_hash_b64=hash_b64,
        signature_b64=signature_b64,
        public_key_der=crypto.public_key_der(key),
        certificate_signature=crypto.certificate_signature(cert) if data["type"] == "simplified" else None,
        hash_encoding=qr_hash_encoding,
    )
    qr_node = root.xpath("cac:AdditionalDocumentReference[cbc:ID='QR']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject", namespaces=XPATH_NS)[0]
    qr_node.text = qr_value
    body = etree.tostring(root, encoding="unicode")
    end = body.index(">") + 1
    extensions = ubl_extensions(invoice_hash_b64=hash_b64, signature_b64=signature_b64, cert_b64=cert_b64, signed_props=props)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + body[:end] + extensions + body[end:]
    if invoice_hash(xml) != hash_b64:  # the stamp and QR must not change the hash
        raise UBLError("the invoice hash changed after signing")
    return {"xml": xml, "hash": hash_b64, "qr": qr_value, "signature": signature_b64}
