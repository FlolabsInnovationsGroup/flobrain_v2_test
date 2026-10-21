"""ZATCA pieces without the database: UBL structure, invoice hash, signature block, QR TLV, keys and CSR."""

import base64
import hashlib
from decimal import Decimal as D

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from django.test import SimpleTestCase
from lxml import etree

from einvoice import money
from einvoice.zatca import crypto, qr, ubl

NS = ubl.XPATH_NS | {"ds": ubl.NS_DS, "xades": ubl.NS_XADES}
VAT = "300000000000003"


def sample(kind="invoice", invoice_type="simplified", icv=1, pih=ubl.INITIAL_PIH, number="INV-1"):
    lines_in = [money.LineIn("Widget", D("3"), D("33.33"), D("1"), "S", D("15")), money.LineIn("Book", D("1"), D("50"), D("0"), "Z", D("0"), "VATEX-SA-EDU", "Education")]
    t = money.sa_totals(lines_in)
    return {
        "uuid": "3cf5ee18-ee25-44ea-a444-2c37ba7f28be", "number": number, "issue_date": "2026-10-21", "issue_time": "10:15:00",
        "type": invoice_type, "kind": kind, "currency": "SAR", "icv": icv, "pih": pih, "note": "",
        "billing_reference": "INV-0" if kind != "invoice" else "", "adjustment_reason": "Returned goods" if kind != "invoice" else "",
        "payment_means": "10", "supply_date": "2026-10-21" if invoice_type == "standard" else None,
        "seller": {"name": "Demo Co", "vat": VAT, "reg_id": "1010010000", "street": "King Fahd", "building": "1234", "district": "Olaya", "city": "Riyadh", "postal": "12345", "country": "SA"},
        "buyer": {"name": "Buyer Co", "vat": "311111111100003", "street": "Tahlia", "building": "4321", "district": "Rawdah", "city": "Jeddah", "postal": "23435", "country": "SA"} if invoice_type == "standard" else {},
        "lines": [
            {"id": i, "description": l.description, "quantity": l.quantity, "unit_price": l.unit_price, "discount": l.discount, "gross": o.gross, "net": o.net, "vat": o.vat, "total": o.total, "category": l.vat_category, "rate": l.vat_rate}
            for i, (l, o) in enumerate(zip(lines_in, t.lines), start=1)
        ],
        "totals": {"line_extension": t.line_extension, "tax_exclusive": t.tax_exclusive, "tax_total": t.tax_total, "tax_inclusive": t.tax_inclusive, "payable": t.payable, "breakdown": t.breakdown},
    }


class KeyMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = crypto.generate_key()
        cls.cert = crypto.demo_certificate(cls.key, VAT, "Demo Co")


class UBLStructureTests(KeyMixin, SimpleTestCase):
    def test_structure_and_order(self):
        out = ubl.finalize(sample(invoice_type="standard"), self.key, self.cert, signing_time="2026-10-21T10:15:00")
        root = etree.fromstring(out["xml"].encode())
        self.assertEqual(root.tag, f"{{{ubl.NS_INV}}}Invoice")
        children = [etree.QName(c).localname for c in root]
        expected_order = [
            "UBLExtensions", "ProfileID", "ID", "UUID", "IssueDate", "IssueTime", "InvoiceTypeCode", "DocumentCurrencyCode", "TaxCurrencyCode",
            "AdditionalDocumentReference", "AdditionalDocumentReference", "AdditionalDocumentReference", "Signature",
            "AccountingSupplierParty", "AccountingCustomerParty", "Delivery", "PaymentMeans", "TaxTotal", "TaxTotal", "LegalMonetaryTotal", "InvoiceLine", "InvoiceLine",
        ]
        self.assertEqual(children, expected_order)
        x = lambda path: root.xpath(path, namespaces=NS)  # noqa: E731
        self.assertEqual(x("string(cbc:ProfileID)"), "reporting:1.0")
        self.assertEqual(x("string(cbc:InvoiceTypeCode)"), "388")
        self.assertEqual(x("string(cbc:InvoiceTypeCode/@name)"), "0100000")
        self.assertEqual(x("string(cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID)"), "1")
        self.assertEqual(x("string(cac:AdditionalDocumentReference[cbc:ID='PIH']//cbc:EmbeddedDocumentBinaryObject)"), ubl.INITIAL_PIH)
        self.assertEqual(x("string(cac:AdditionalDocumentReference[cbc:ID='QR']//cbc:EmbeddedDocumentBinaryObject)"), out["qr"])
        self.assertEqual(x("string(cac:AccountingSupplierParty//cac:PartyTaxScheme/cbc:CompanyID)"), VAT)
        self.assertEqual(x("string(cac:AccountingSupplierParty//cac:PartyIdentification/cbc:ID/@schemeID)"), "CRN")
        self.assertEqual(x("string(cac:Delivery/cbc:ActualDeliveryDate)"), "2026-10-21")
        # BT-110 twice: once in SAR without breakdown, once with the breakdown
        self.assertEqual(x("string(cac:TaxTotal[1]/cbc:TaxAmount)"), "14.85")
        self.assertEqual(len(x("cac:TaxTotal[1]/cac:TaxSubtotal")), 0)
        self.assertEqual(len(x("cac:TaxTotal[2]/cac:TaxSubtotal")), 2)
        self.assertEqual(x("string(cac:TaxTotal[2]/cac:TaxSubtotal[cac:TaxCategory/cbc:ID='Z']/cac:TaxCategory/cbc:TaxExemptionReasonCode)"), "VATEX-SA-EDU")
        self.assertEqual(x("string(cac:TaxTotal[2]/cac:TaxSubtotal/cac:TaxCategory/cbc:ID/@schemeID)"), "UN/ECE 5305")
        self.assertEqual(x("string(cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount)"), "163.84")
        self.assertEqual(x("string(cac:LegalMonetaryTotal/cbc:PayableAmount/@currencyID)"), "SAR")
        line = x("cac:InvoiceLine[1]")[0]
        self.assertEqual(line.xpath("string(cbc:InvoicedQuantity)", namespaces=NS), "3.000000")
        self.assertEqual(line.xpath("string(cbc:LineExtensionAmount)", namespaces=NS), "98.99")
        self.assertEqual(line.xpath("string(cac:AllowanceCharge/cbc:Amount)", namespaces=NS), "1.00")
        self.assertEqual(line.xpath("string(cac:TaxTotal/cbc:TaxAmount)", namespaces=NS), "14.85")  # KSA-11
        self.assertEqual(line.xpath("string(cac:TaxTotal/cbc:RoundingAmount)", namespaces=NS), "113.84")  # KSA-12
        self.assertEqual(line.xpath("string(cac:Price/cbc:PriceAmount)", namespaces=NS), "33.33")
        # children of an InvoiceLine follow the UBL order
        self.assertEqual([etree.QName(c).localname for c in line], ["ID", "InvoicedQuantity", "LineExtensionAmount", "AllowanceCharge", "TaxTotal", "Item", "Price"])

    def test_notes_and_simplified(self):
        out = ubl.finalize(sample(kind="credit"), self.key, self.cert, signing_time="2026-10-21T10:15:00")
        root = etree.fromstring(out["xml"].encode())
        self.assertEqual(root.xpath("string(cbc:InvoiceTypeCode)", namespaces=NS), "381")
        self.assertEqual(root.xpath("string(cbc:InvoiceTypeCode/@name)", namespaces=NS), "0200000")
        self.assertEqual(root.xpath("string(cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID)", namespaces=NS), "INV-0")
        self.assertEqual(root.xpath("string(cac:PaymentMeans/cbc:InstructionNote)", namespaces=NS), "Returned goods")
        with self.assertRaises(ubl.UBLError):
            data = sample(kind="debit")
            data["adjustment_reason"] = ""
            ubl.build_tree(data)
        with self.assertRaises(ubl.UBLError):
            data = sample()
            data["currency"] = "USD"
            ubl.build_tree(data)

    def test_initial_pih(self):
        self.assertEqual(ubl.INITIAL_PIH, "NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjNzljMmRiYzIzOWRkNGU5MWI0NjcyOWQ3M2EyN2ZiNTdlOQ==")


class HashTests(KeyMixin, SimpleTestCase):
    def test_hash_ignores_signature_qr_and_extensions(self):
        out = ubl.finalize(sample(), self.key, self.cert, signing_time="2026-10-21T10:15:00")
        unsigned = ubl.build_tree(sample())
        self.assertEqual(ubl.invoice_hash(unsigned), out["hash"])  # before signing, QR empty
        self.assertEqual(ubl.invoice_hash(out["xml"]), out["hash"])  # after signing and QR
        # the hash is SHA-256 over the canonical document without those three elements
        root = etree.fromstring(out["xml"].encode())
        c14n = ubl.hashable(root)
        self.assertNotIn(b"UBLExtensions", c14n)
        self.assertNotIn(b"cac:Signature", c14n)
        self.assertNotIn(b"<cbc:ID>QR</cbc:ID>", c14n)
        self.assertIn(b"<cbc:ID>PIH</cbc:ID>", c14n)
        self.assertEqual(base64.b64encode(hashlib.sha256(c14n).digest()).decode(), out["hash"])

    def test_any_content_change_changes_the_hash(self):
        a = ubl.invoice_hash(ubl.build_tree(sample()))
        self.assertNotEqual(a, ubl.invoice_hash(ubl.build_tree(sample(number="INV-2"))))
        self.assertNotEqual(a, ubl.invoice_hash(ubl.build_tree(sample(icv=2))))

    def test_removal_keeps_neighbouring_text(self):
        xml = (
            f'<Invoice xmlns="{ubl.NS_INV}" xmlns:cac="{ubl.NS_CAC}" xmlns:cbc="{ubl.NS_CBC}" xmlns:ext="{ubl.NS_EXT}">\n'
            "  <cbc:ID>1</cbc:ID>\n  <cac:Signature><cbc:ID>x</cbc:ID></cac:Signature>\n  <cbc:Note>n</cbc:Note>\n</Invoice>"
        )
        self.assertIn(b"<cbc:ID>1</cbc:ID>\n  \n  <cbc:Note>", ubl.hashable(etree.fromstring(xml.encode())))

    def test_chain(self):
        first = ubl.finalize(sample(icv=1, pih=ubl.INITIAL_PIH), self.key, self.cert, signing_time="t")
        second = ubl.finalize(sample(icv=2, pih=first["hash"], number="INV-2"), self.key, self.cert, signing_time="t")
        root = etree.fromstring(second["xml"].encode())
        self.assertEqual(root.xpath("string(cac:AdditionalDocumentReference[cbc:ID='PIH']//cbc:EmbeddedDocumentBinaryObject)", namespaces=NS), first["hash"])


class SignatureBlockTests(KeyMixin, SimpleTestCase):
    def test_signature_and_digests(self):
        out = ubl.finalize(sample(), self.key, self.cert, signing_time="2026-10-21T10:15:00")
        root = etree.fromstring(out["xml"].encode())
        sig = root.xpath("//ds:Signature", namespaces=NS)[0]
        self.assertEqual(sig.xpath("string(ds:SignedInfo/ds:Reference[@Id='invoiceSignedData']/ds:DigestValue)", namespaces=NS), out["hash"])
        value = sig.xpath("string(ds:SignatureValue)", namespaces=NS)
        self.assertTrue(crypto.verify_hash_signature(crypto.public_key_der(self.key), out["hash"], value))
        self.assertEqual(sig.xpath("string(ds:KeyInfo/ds:X509Data/ds:X509Certificate)", namespaces=NS), self.cert)
        # SignedProperties digest: Base64(hex(SHA-256(exclusive C14N of the element as embedded)))
        props = root.xpath("//xades:SignedProperties", namespaces=NS)[0]
        canonical = etree.tostring(props, method="c14n", exclusive=True).decode()
        self.assertEqual(sig.xpath("string(ds:SignedInfo/ds:Reference[@URI='#xadesSignedProperties']/ds:DigestValue)", namespaces=NS), ubl.hex_b64_sha256(canonical))
        self.assertIn(f"<ds:DigestValue xmlns:ds=\"{ubl.NS_DS}\">{crypto.certificate_hash(self.cert)}</ds:DigestValue>", canonical)
        # the certificate digest is Base64 of the hex SHA-256 of the certificate text
        self.assertEqual(base64.b64decode(crypto.certificate_hash(self.cert)).decode(), hashlib.sha256(self.cert.encode()).hexdigest())
        self.assertEqual(props.xpath("string(.//xades:SigningTime)", namespaces=NS), "2026-10-21T10:15:00")

    def test_tampering_breaks_verification(self):
        out = ubl.finalize(sample(), self.key, self.cert, signing_time="t")
        tampered = out["xml"].replace("<cbc:ID>INV-1</cbc:ID>", "<cbc:ID>INV-9</cbc:ID>")
        self.assertNotEqual(ubl.invoice_hash(tampered), out["hash"])


class QRTests(KeyMixin, SimpleTestCase):
    def test_phase1_roundtrip(self):
        text = qr.encode(qr.phase1("بوبا للتأمين", VAT, "2026-10-21T10:15:00", "1150.00", "150.00"))
        tags = qr.decode(text)
        self.assertEqual(tags[1].decode(), "بوبا للتأمين")
        self.assertEqual(tags[2], VAT.encode())
        self.assertEqual(tags[4], b"1150.00")
        self.assertEqual(base64.b64decode(text)[:2], bytes([1, len("بوبا للتأمين".encode())]))

    def test_phase2_tags(self):
        out = ubl.finalize(sample(), self.key, self.cert, signing_time="t")
        tags = qr.decode(out["qr"])
        self.assertEqual(sorted(tags), list(range(1, 10)))
        self.assertEqual(tags[3], b"2026-10-21T10:15:00")
        self.assertEqual(tags[4], b"163.84")
        self.assertEqual(tags[5], b"14.85")
        self.assertEqual(tags[6].decode(), out["hash"])
        self.assertEqual(tags[8], crypto.public_key_der(self.key))
        self.assertEqual(tags[9], crypto.load_certificate(self.cert).signature)
        self.assertTrue(crypto.verify_hash_signature(tags[8], out["hash"], tags[7].decode()))
        standard = qr.decode(ubl.finalize(sample(invoice_type="standard"), self.key, self.cert, signing_time="t")["qr"])
        self.assertNotIn(9, standard)  # tag 9 is for simplified invoices only

    def test_raw_hash_encoding(self):
        out = ubl.finalize(sample(), self.key, self.cert, signing_time="t", qr_hash_encoding=qr.HASH_RAW)
        tags = qr.decode(out["qr"])
        self.assertEqual(tags[6], base64.b64decode(out["hash"]))
        self.assertEqual(len(tags[6]), 32)

    def test_limits(self):
        with self.assertRaises(qr.QRError):
            qr.tlv(1, "x" * 256)
        with self.assertRaises(qr.QRError):
            qr.encode([(1, "x" * 250), (2, "y" * 250), (3, "z" * 100)])  # Base64 over 700 characters
        with self.assertRaises(qr.QRError):
            qr.decode(base64.b64encode(bytes([1, 5, 65])).decode())


class CsrTests(SimpleTestCase):
    FIELDS = dict(
        common_name="TST-886431145-300000000000003", egs_serial="1-FloBrain|2-2.0|3-ed22f1d8-e6a2-1118-9b58-d9a8f11e445f", vat_number=VAT,
        branch_name="Riyadh Branch", org_name="Demo Co", functionality_map="1100", location="RRRD2929", industry="Supply activities",
    )

    def test_key_and_csr_fields(self):
        key = crypto.generate_key()
        self.assertIsInstance(key.curve, ec.SECP256K1)
        pem = crypto.build_csr(key, environment="simulation", **self.FIELDS)
        csr = x509.load_pem_x509_csr(pem.encode())
        self.assertTrue(csr.is_signature_valid)
        subject = {a.oid: a.value for a in csr.subject}
        self.assertEqual(subject[x509.NameOID.COUNTRY_NAME], "SA")
        self.assertEqual(subject[x509.NameOID.ORGANIZATIONAL_UNIT_NAME], "Riyadh Branch")
        self.assertEqual(subject[x509.NameOID.ORGANIZATION_NAME], "Demo Co")
        self.assertEqual(subject[x509.NameOID.COMMON_NAME], self.FIELDS["common_name"])
        template = csr.extensions.get_extension_for_oid(crypto.TEMPLATE_OID).value.value
        self.assertEqual(template, b"\x13\x15PREZATCA-Code-Signing")
        san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dirname = san.get_values_for_type(x509.DirectoryName)[0]
        values = {a.oid.dotted_string: a.value for a in dirname}
        self.assertEqual(values["2.5.4.4"], self.FIELDS["egs_serial"])
        self.assertEqual(values["0.9.2342.19200300.100.1.1"], VAT)
        self.assertEqual(values["2.5.4.12"], "1100")
        self.assertEqual(values["2.5.4.26"], "RRRD2929")
        self.assertEqual(values["2.5.4.15"], "Supply activities")
        self.assertIsInstance(csr.public_key().curve, ec.SECP256K1)
        # the compliance API gets Base64 of the PEM text
        self.assertEqual(base64.b64decode(crypto.csr_for_api(pem)).decode(), pem)
        self.assertEqual(base64.b64decode(crypto.csr_for_api(pem, "der_base64"))[:1], b"\x30")

    def test_templates_per_environment(self):
        key = crypto.generate_key()
        for env, name in (("sandbox", b"TSTZATCA-Code-Signing"), ("production", b"ZATCA-Code-Signing")):
            csr = x509.load_pem_x509_csr(crypto.build_csr(key, environment=env, **self.FIELDS).encode())
            self.assertTrue(csr.extensions.get_extension_for_oid(crypto.TEMPLATE_OID).value.value.endswith(name))

    def test_validation(self):
        key = crypto.generate_key()
        for field, bad in (("vat_number", "123"), ("egs_serial", "FloBrain-1"), ("functionality_map", "2100"), ("industry", " ")):
            with self.assertRaises(crypto.CryptoError, msg=field):
                crypto.build_csr(key, environment="sandbox", **{**self.FIELDS, field: bad})

    def test_token_roundtrip_and_key_pem(self):
        key = crypto.generate_key()
        cert = crypto.demo_certificate(key, VAT, "Demo")
        token = base64.b64encode(cert.encode()).decode()
        self.assertEqual(crypto.certificate_from_token(token), cert)
        with self.assertRaises(crypto.CryptoError):
            crypto.certificate_from_token("bm90IGEgY2VydA==")
        again = crypto.key_from_pem(crypto.key_to_pem(key))
        self.assertEqual(crypto.public_key_der(again), crypto.public_key_der(key))
        other = ec.generate_private_key(ec.SECP256R1())
        from cryptography.hazmat.primitives import serialization

        with self.assertRaises(crypto.CryptoError):
            crypto.key_from_pem(other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
