"""The ETA invoice document (document type ``I``, version ``1.0``) from an invoice and profile.

Field names and rules from the ETA SDK "Invoice v1.0" page (sdk.invoicing.eta.gov.eg/documents/
invoice-v1-0/); the casing of ``branchID`` and ``internalID`` follows the SDK sample documents
(the canonical form upper-cases names, so casing does not change the signature).
- issuer: type ``B``, id = tax registration number, name, address with branchID, country EG,
  governate, regionCity, street, buildingNumber;
- receiver: ``B`` business in Egypt, ``P`` person, ``F`` foreigner. A person below the ETA
  threshold may be sent without id, name and address (the threshold is set by the ETA and is not
  checked here);
- dateTimeIssued in UTC (``YYYY-MM-DDTHH:MM:SSZ``), not in the future;
- each line: description, itemType GS1|EGS, itemCode, unitType, quantity, unitValue
  {currencySold, amountEGP, amountSold and currencyExchangeRate when not EGP}, salesTotal,
  discount {rate, amount}, netTotal, taxableItems [{taxType T1, amount, subType, rate}], total,
  valueDifference, totalTaxableFees, itemsDiscount (0 here), internalCode;
- totals: totalSalesAmount, totalDiscountAmount, netAmount, taxTotals [{taxType, amount}],
  extraDiscountAmount, totalItemsDiscountAmount, totalAmount;
- signatures: [{signatureType "I", value: Base64 CAdES-BES}] added after signing.
Only invoices (``I``) are built here; credit and debit notes (``C``, ``D``) need references to
the original document's ETA uuid and are not supported yet.
"""

from datetime import timezone as dt_timezone
from decimal import Decimal

from einvoice.money import q5

ZERO = Decimal("0")


def _address(profile_or_invoice, prefix="", branch=None):
    get = lambda name: getattr(profile_or_invoice, f"{prefix}{name}")  # noqa: E731
    address = {}
    if branch is not None:
        address["branchID"] = branch
    address.update(
        {
            "country": (get("country") if prefix else "EG") or "EG",
            "governate": get("region"),
            "regionCity": get("city"),
            "street": get("street"),
            "buildingNumber": get("building_number"),
        }
    )
    if get("postal_code"):
        address["postalCode"] = get("postal_code")
    return address


def receiver_type(invoice) -> str:
    if invoice.buyer_country and invoice.buyer_country != "EG":
        return "F"
    return "B" if invoice.invoice_type == "b2b" else "P"


def build(invoice, profile, lines, totals) -> dict:
    """``lines`` are InvoiceLine rows; ``totals`` is einvoice.money.Totals for the same lines."""
    foreign = invoice.currency != "EGP"
    rtype = receiver_type(invoice)
    receiver = {"type": rtype}
    if invoice.buyer_tax_number:
        receiver["id"] = invoice.buyer_tax_number
    if invoice.buyer_name:
        receiver["name"] = invoice.buyer_name
    if invoice.buyer_street or invoice.buyer_city:
        receiver = {"address": _address(invoice, "buyer_"), **receiver}
    issued = invoice.issue_datetime.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document_lines = []
    for line, out in zip(lines, totals.lines):
        unit_value = {"currencySold": invoice.currency}
        if foreign:
            unit_value["amountEGP"] = q5(line.unit_price * invoice.exchange_rate)
            unit_value["amountSold"] = q5(line.unit_price)
            unit_value["currencyExchangeRate"] = q5(invoice.exchange_rate)
        else:
            unit_value["amountEGP"] = q5(line.unit_price)
        discount_amount = out.gross - out.net
        row = {
            "description": line.description,
            "itemType": line.item_type,
            "itemCode": line.item_code,
            "unitType": line.unit_code or "EA",
            "quantity": q5(line.quantity),
            "internalCode": f"L{line.position}",
            "salesTotal": out.gross,
            "total": out.total,
            "valueDifference": ZERO,
            "totalTaxableFees": ZERO,
            "netTotal": out.net,
            "itemsDiscount": ZERO,
            "unitValue": unit_value,
            # With a discount only the amount is sent: if both are given the ETA checks that the
            # amount equals the rate applied, and a rate rounded to 5 decimals may miss by 0.00001.
            "discount": {"amount": discount_amount} if discount_amount else {"rate": ZERO, "amount": ZERO},
            "taxableItems": [{"taxType": "T1", "amount": out.vat, "subType": line.vat_category, "rate": Decimal(line.vat_rate).quantize(Decimal("0.01"))}],
        }
        document_lines.append(row)
    return {
        "issuer": {
            "address": _address(profile, branch=profile.registration_id or "0"),
            "type": "B",
            "id": profile.tax_number,
            "name": profile.seller_name,
        },
        "receiver": receiver,
        "documentType": "I",
        "documentTypeVersion": "1.0",
        "dateTimeIssued": issued,
        "taxpayerActivityCode": profile.activity_code,
        "internalID": invoice.number,
        "invoiceLines": document_lines,
        "totalDiscountAmount": totals.discount_total,
        "totalSalesAmount": totals.line_extension,
        "netAmount": totals.tax_exclusive,
        "taxTotals": [{"taxType": "T1", "amount": totals.tax_total}],
        "totalAmount": totals.tax_inclusive,
        "extraDiscountAmount": ZERO,
        "totalItemsDiscountAmount": ZERO,
    }


def with_signature(document_json: str, signature_b64: str) -> str:
    """The stored JSON text plus ``signatures`` (the issuer's), without re-serializing numbers."""
    import json

    if not document_json.rstrip().endswith("}"):
        raise ValueError("not a document")
    sig = json.dumps([{"signatureType": "I", "value": signature_b64}])
    return document_json.rstrip()[:-1] + f',"signatures":{sig}' + "}"
