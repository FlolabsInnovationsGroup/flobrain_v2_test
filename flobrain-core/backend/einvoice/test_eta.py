"""ETA pieces without the database: canonical serialization (known answers), JSON text, signature checks."""

import base64
import json
from decimal import Decimal as D

from django.test import SimpleTestCase

from einvoice.eta import document, serialize, signer

# Fragments quoted from the ETA SDK sample (sdk.invoicing.eta.gov.eg/files/one-doc-serialized.json.txt,
# the serialization of one-doc.json). We rebuild the matching parts of the sample document and
# check that our serializer produces exactly these characters.
SDK_PREFIX = '"ISSUER""ADDRESS""BRANCHID""1""COUNTRY""EG""GOVERNATE""Cairo""REGIONCITY""Nasr City""STREET""580 Clementina Ke'
SDK_LINES = 'INVOICELINES""INVOICELINES""DESCRIPTION""Computer1""ITEMTYPE""GPC""ITEMCODE""10001774""UNITTYPE""EA""QUANTITY"'
SDK_TAXABLE = 'TAXABLEITEMS""TAXABLEITEMS""TAXTYPE""T1""AMOUNT""272.07""SUBTYPE""T1""RATE""14.00""TAXABLEITEMS""TAXTYPE""T2'


class CanonicalTests(SimpleTestCase):
    def test_sdk_fragments(self):
        # Rebuilt from the SDK sample: the first issuer address fields and the start of line 1.
        # The sample is document version 0.9 (itemType GPC); the serialization rules are the same.
        text = (
            '{"issuer":{"address":{"branchID":"1","country":"EG","governate":"Cairo","regionCity":"Nasr City",'
            '"street":"580 Clementina Key","buildingNumber":"Bldg. 0"}},'
            '"invoiceLines":[{"description":"Computer1","itemType":"GPC","itemCode":"10001774","unitType":"EA","quantity":5,'
            '"taxableItems":[{"taxType":"T1","amount":272.07,"subType":"T1","rate":14.00},{"taxType":"T2","amount":208.22,"subType":"T2","rate":12}]}]}'
        )
        out = serialize.canonical_from_json(text)
        self.assertTrue(out.startswith(SDK_PREFIX))
        self.assertIn(SDK_LINES, out)
        self.assertIn(SDK_TAXABLE, out)

    def test_constructed_known_answer(self):
        doc = {
            "issuer": {"type": "B", "id": "100200300", "name": "Nile Labs"},
            "receiver": {"type": "P"},
            "documentType": "I",
            "documentTypeVersion": "1.0",
            "invoiceLines": [
                {"description": "Item A", "quantity": D("2"), "taxableItems": [{"taxType": "T1", "amount": D("28"), "subType": "V009", "rate": D("14")}]},
                {"description": "صنف ب", "quantity": D("1.5"), "taxableItems": []},
            ],
            "taxTotals": [{"taxType": "T1", "amount": D("28.000")}],
            "totalAmount": D("228"),
            "signatures": [{"signatureType": "I", "value": "ignored"}],
        }
        expected = (
            '"ISSUER""TYPE""B""ID""100200300""NAME""Nile Labs"'
            '"RECEIVER""TYPE""P"'
            '"DOCUMENTTYPE""I""DOCUMENTTYPEVERSION""1.0"'
            '"INVOICELINES"'
            '"INVOICELINES""DESCRIPTION""Item A""QUANTITY""2.00""TAXABLEITEMS""TAXABLEITEMS""TAXTYPE""T1""AMOUNT""28.00""SUBTYPE""V009""RATE""14.00"'
            '"INVOICELINES""DESCRIPTION""صنف ب""QUANTITY""1.50""TAXABLEITEMS"'
            '"TAXTOTALS""TAXTOTALS""TAXTYPE""T1""AMOUNT""28.00"'
            '"TOTALAMOUNT""228.00"'
        )
        self.assertEqual(serialize.canonical(doc), expected)
        # the stored JSON text gives the same canonical string (numbers as written)
        text = serialize.to_json(doc)
        self.assertIn('"quantity":2.00', text)
        self.assertIn('"description":"صنف ب"', text)  # UTF-8, not \\u escapes
        self.assertEqual(serialize.canonical_from_json(text), expected)
        self.assertEqual(serialize.sha256_hex(expected), __import__("hashlib").sha256(expected.encode("utf-8")).hexdigest())

    def test_values_kept_as_written(self):
        self.assertEqual(serialize.canonical_from_json('{"a":0.0,"b":1.50000,"c":"x"}'), '"A""0.0""B""1.50000""C""x"')

    def test_signatures_skipped_only_at_the_root(self):
        self.assertEqual(serialize.canonical({"x": {"signatures": "kept"}, "signatures": []}), '"X""SIGNATURES""kept"')

    def test_unsafe_strings_refused(self):
        for bad in ('He said "hi"', "back\\slash", "line\nbreak"):
            with self.assertRaises(serialize.SerializeError):
                serialize.to_json({"description": bad})


class DocumentTests(SimpleTestCase):
    def test_with_signature_keeps_text(self):
        text = '{"a":1.50}'
        signed = document.with_signature(text, "MIIB")
        self.assertEqual(signed, '{"a":1.50,"signatures":[{"signatureType": "I", "value": "MIIB"}]}')
        self.assertEqual(json.loads(signed)["signatures"][0]["signatureType"], "I")
        # the signature is outside what was signed
        self.assertEqual(serialize.canonical_from_json(signed), serialize.canonical_from_json(text))


def fake_cms() -> str:
    # SEQUENCE { OID signedData, ... }: enough for the shape check (the ETA verifies the real thing)
    body = bytes.fromhex("06092a864886f70d010702") + bytes.fromhex("a003020101")
    return base64.b64encode(bytes([0x30, len(body)]) + body).decode()


class SignerTests(SimpleTestCase):
    def test_check_signature(self):
        self.assertEqual(signer.check_signature(fake_cms()), fake_cms())
        self.assertEqual(signer.check_signature(" " + fake_cms()[:10] + "\n" + fake_cms()[10:]), fake_cms())
        for bad in ("", "not base64!", base64.b64encode(b"hello").decode(), base64.b64encode(b"\x30\x03\x02\x01\x01").decode()):
            with self.assertRaises(signer.SignerError, msg=bad):
                signer.check_signature(bad)
