"""Start an e-invoice from an Odoo or Zoho Books invoice, read through the org's write-back
connection (``integrations.write``). Reading writes nothing outside FloBrain, so it needs no
approval; the result is a *draft* for a person to review (VAT categories are a first guess:
a positive tax rate becomes standard rated, 0% becomes "out of scope" with a review note).

- Odoo: JSON-RPC ``account.move`` read (``move_type`` out_invoice), lines from
  ``account.move.line`` (sections and notes skipped; Odoo's discount is a percentage), the
  partner's name and VAT. Uses the connection's API key; nothing is posted.
- Zoho Books: ``GET /books/v3/invoices/{id}?organization_id=...``. Zoho needs the
  ``ZohoBooks.invoices.READ`` scope, which the write-back Zoho connection does not request today
  (it asks for ``ZohoBooks.invoices.CREATE``); until it does, Zoho answers 401/403 and we say so.
In the demo workspace the connection is simulated and a sample invoice is returned.
"""

import re
from decimal import Decimal

from einvoice.money import q2
from einvoice.services import EInvoiceError

ODOO_ID_RE = re.compile(r"^\d{1,12}$")
ZOHO_ID_RE = re.compile(r"^\d{1,25}$")


def _rate_category(country, rate: Decimal) -> dict:
    if country == "SA":
        if rate > 0:
            return {"vat_category": "S", "vat_rate": str(rate)}
        return {"vat_category": "O", "vat_rate": "0", "exemption_code": "VATEX-SA-OOS", "exemption_reason": "Imported at 0%: check the VAT category"}
    return {"vat_category": "V009" if rate > 0 else "V003", "vat_rate": str(rate)}


def _demo(provider, ref, country):
    rate = Decimal("15") if country == "SA" else Decimal("14")
    lines = [
        {"description": "Consulting days (imported, demo)", "quantity": "4", "unit_price": "1500.00", "discount": "0", **_rate_category(country, rate)},
        {"description": "Travel expenses (imported, demo)", "quantity": "1", "unit_price": "820.50", "discount": "20.50", **_rate_category(country, rate)},
    ]
    if country == "EG":
        for i, line in enumerate(lines):
            line.update({"item_type": "EGS", "item_code": f"EG-100000001-{1001 + i}"})
    return {
        "buyer_name": "Delta Trading (demo import)",
        "note": f"Imported from {provider.title()} invoice {ref} (demo, simulated)",
        "lines": lines,
    }


def _odoo(conn, ref, country):
    from integrations.write.catalog.odoo import _execute

    if not ODOO_ID_RE.match(ref):
        raise EInvoiceError("invalid", "Use the Odoo invoice number (the id in its address, digits only)")
    rows = _execute(conn, "account.move", "read", [[int(ref)], ["name", "partner_id", "invoice_line_ids", "move_type", "currency_id"]])
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise EInvoiceError("not_found", "Odoo has no invoice with that number", 404)
    move = rows[0]
    if move.get("move_type") not in ("out_invoice", "out_refund"):
        raise EInvoiceError("invalid", "That Odoo record is not a customer invoice")
    partner = move.get("partner_id") if isinstance(move.get("partner_id"), list) else [None, ""]
    vat = ""
    if isinstance(partner[0], int):
        found = _execute(conn, "res.partner", "read", [[partner[0]], ["vat", "street", "city", "zip"]])
        if isinstance(found, list) and found and isinstance(found[0], dict):
            vat = str(found[0].get("vat") or "")
    line_ids = [i for i in (move.get("invoice_line_ids") or []) if isinstance(i, int)][:200]
    raw_lines = _execute(conn, "account.move.line", "read", [line_ids, ["name", "quantity", "price_unit", "discount", "display_type", "tax_ids"]]) if line_ids else []
    lines = []
    for row in raw_lines if isinstance(raw_lines, list) else []:
        if not isinstance(row, dict) or row.get("display_type") in ("line_section", "line_note"):
            continue
        qty = Decimal(str(row.get("quantity") or 1))
        price = Decimal(str(row.get("price_unit") or 0))
        pct = Decimal(str(row.get("discount") or 0))
        rate = Decimal("15") if country == "SA" else Decimal("14")
        lines.append({"description": str(row.get("name") or "Item")[:300], "quantity": str(qty), "unit_price": str(price), "discount": str(q2(qty * price * pct / 100)), **_rate_category(country, rate if row.get("tax_ids") else Decimal("0"))})
    currency = move.get("currency_id")[1] if isinstance(move.get("currency_id"), list) and len(move["currency_id"]) > 1 else ""
    return {"buyer_name": str(partner[1] or "")[:200], "buyer_tax_number": re.sub(r"\s", "", vat)[:20], "currency": currency if len(str(currency)) == 3 else "", "note": f"Imported from Odoo {move.get('name') or ref}", "lines": lines}


def _zoho(provider, conn, ref, country):
    from integrations.write.catalog.zoho import _api
    from integrations.write.transport import Client

    if not ZOHO_ID_RE.match(ref):
        raise EInvoiceError("invalid", "Use the Zoho Books invoice id (digits only)")
    org_id = str((conn.config or {}).get("books_org_id") or "")
    if not ZOHO_ID_RE.match(org_id):
        raise EInvoiceError("not_available", "No Zoho Books organization is linked. Connect Zoho again.", 409)
    data = Client(provider, conn).call("GET", f"{_api(conn)}/books/v3/invoices/{ref}?organization_id={org_id}")
    invoice = data.get("invoice") if isinstance(data, dict) and isinstance(data.get("invoice"), dict) else None
    if invoice is None:
        raise EInvoiceError("not_found", "Zoho Books has no invoice with that id", 404)
    lines = []
    for row in invoice.get("line_items") or []:
        if not isinstance(row, dict):
            continue
        qty = Decimal(str(row.get("quantity") or 1))
        price = Decimal(str(row.get("rate") or 0))
        discount = row.get("discount")
        if isinstance(discount, str) and discount.endswith("%"):
            amount = q2(qty * price * Decimal(discount[:-1] or 0) / 100)
        else:
            amount = Decimal(str(row.get("discount_amount") or discount or 0))
        rate = Decimal(str(row.get("tax_percentage") or 0))
        lines.append({"description": str(row.get("name") or row.get("description") or "Item")[:300], "quantity": str(qty), "unit_price": str(price), "discount": str(amount), **_rate_category(country, rate)})
    return {"buyer_name": str(invoice.get("customer_name") or "")[:200], "currency": str(invoice.get("currency_code") or "")[:3], "note": f"Imported from Zoho Books {invoice.get('invoice_number') or ref}", "lines": lines}


def fetch(user, org, provider_key: str, ref: str, country: str) -> dict:
    """Invoice fields for ``services.save_invoice`` (country and type are added by the caller)."""
    from integrations.write import registry
    from integrations.write.connections import connection_for
    from integrations.write.transport import WriteError

    if provider_key not in ("odoo", "zoho"):
        raise EInvoiceError("invalid", "Import from Odoo or Zoho Books")
    provider = registry.get(provider_key)
    conn, reason = connection_for(user, org, provider)
    if conn is None:
        raise EInvoiceError("not_available", reason, 409)
    ref = (ref or "").strip()
    if not ref:
        raise EInvoiceError("invalid", "Give the invoice number in the other system")
    if conn.demo:
        return _demo(provider_key, ref, country)
    try:
        data = _odoo(conn, ref, country) if provider_key == "odoo" else _zoho(provider, conn, ref, country)
    except WriteError as exc:
        hint = " Zoho needs read access to Books invoices (ZohoBooks.invoices.READ)." if provider_key == "zoho" and exc.code == "expired" else ""
        raise EInvoiceError("provider_error", f"{exc.details}{hint}", 502) from exc
    if not data["lines"]:
        raise EInvoiceError("invalid", "That invoice has no lines to import")
    if country == "SA" and data.get("currency") and data["currency"] != "SAR":
        raise EInvoiceError("invalid", "That invoice is not in SAR")
    return data
