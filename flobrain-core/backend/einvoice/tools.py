"""Approval-gated tools (``actions.plugins.register_tool``).

- ``einvoice.prepare``: a buddy drafts an e-invoice (country, type, buyer, lines). After approval
  a *draft* is created; nothing is signed or sent. Totals are computed on the server.
- ``einvoice.submit``: send a prepared invoice to ZATCA (clearance for standard, reporting for
  simplified) or the ETA. The invoice page creates this proposal; a buddy may propose it too.
  It only runs from ``actions.service`` after a person approved it.

Both need the ``einvoice`` flag and ``einvoice.issue``; ``check`` runs at proposal and approval.
"""

from django.db import transaction

from actions.registry import EXTERNAL, WRITE

FLAG = "einvoice"
DEC = {"type": "string", "minLength": 1, "maxLength": 20}
LINE = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "minLength": 1, "maxLength": 300},
        "quantity": DEC,
        "unit_price": DEC,
        "discount": {"type": "string", "maxLength": 20},
        "vat_category": {"type": "string", "maxLength": 4},
        "vat_rate": {"type": "string", "maxLength": 6},
        "exemption_code": {"type": "string", "maxLength": 30},
        "exemption_reason": {"type": "string", "maxLength": 200},
        "item_code": {"type": "string", "maxLength": 100},
        "item_type": {"type": "string", "enum": ["GS1", "EGS"]},
    },
    "required": ["description", "unit_price"],
    "additionalProperties": False,
}
PREPARE = {
    "perm_key": "einvoice.issue",
    "flag": FLAG,
    "risk": WRITE,
    "label": "Draft an e-invoice",
    "description": (
        "Draft a Saudi (ZATCA) or Egyptian (ETA) e-invoice in FloBrain. country is SA or EG; "
        "invoice_type is standard or simplified for SA, b2b or b2c for EG. Amounts are plain numbers "
        "as strings. VAT category: S, Z, E or O for SA (Z, E and O need an exemption code); "
        "V001 to V010 for EG (V009 is general sales at 14%). Creates a draft only: nothing is sent "
        "to the tax authority. Needs approval."
    ),
    "schema": {
        "type": "object",
        "properties": {
            "country": {"type": "string", "enum": ["SA", "EG"]},
            "invoice_type": {"type": "string", "enum": ["standard", "simplified", "b2b", "b2c"]},
            "buyer_name": {"type": "string", "maxLength": 200},
            "buyer_tax_number": {"type": "string", "maxLength": 20},
            "buyer_city": {"type": "string", "maxLength": 120},
            "buyer_street": {"type": "string", "maxLength": 200},
            "currency": {"type": "string", "maxLength": 3},
            "note": {"type": "string", "maxLength": 500},
            "lines": {"type": "array", "items": LINE, "maxItems": 50},
        },
        "required": ["country", "invoice_type", "lines"],
        "additionalProperties": False,
    },
}
SUBMIT = {
    "perm_key": "einvoice.issue",
    "flag": FLAG,
    "risk": EXTERNAL,
    "label": "Send an e-invoice to the tax authority",
    "description": "Send a prepared e-invoice to ZATCA or the ETA. Needs approval; the authority's answer is recorded on the invoice.",
    "schema": {"type": "object", "properties": {"invoice": {"type": "string", "format": "uuid"}}, "required": ["invoice"], "additionalProperties": False},
}


def _denied(code, details):
    from actions.service import ActionDenied

    return ActionDenied(code, details)


def _gate(user, org):
    from einvoice import services
    from organizations.permissions import can

    if not services.flag_on(user, org):
        raise _denied("not_available", "E-invoicing is switched off")
    if not can(user, "einvoice.issue", org):
        raise _denied("permission", "Missing permission: einvoice.issue")


def _amount(value) -> str:
    from einvoice.money import fmt2

    return fmt2(value)


def check_prepare(user, org, args) -> str:
    from einvoice import services

    _gate(user, org)
    try:
        lines = services._lines_in(args["country"], args["lines"])
        totals = services.compute(args["country"], lines)
    except services.EInvoiceError as exc:
        raise _denied("invalid", exc.details) from exc
    if args["invoice_type"] not in (("standard", "simplified") if args["country"] == "SA" else ("b2b", "b2c")):
        raise _denied("invalid", "That invoice type does not exist for this country")
    who = args.get("buyer_name") or "a consumer"
    currency = args.get("currency") or ("SAR" if args["country"] == "SA" else "EGP")
    n = len(lines)
    return f"Draft a {args['country']} e-invoice for {who[:60]}: {n} line{'s' if n != 1 else ''}, total {currency} {_amount(totals.tax_inclusive)} (draft only, not sent)"


def execute_prepare(user, org, args) -> dict:
    from einvoice import services

    check_prepare(user, org, args)
    try:
        invoice = services.save_invoice(user, org, dict(args), source="buddy")
    except services.EInvoiceError as exc:
        raise _denied("invalid", exc.details) from exc
    return {"invoice": str(invoice.id), "number": invoice.number, "status": invoice.status, "total": str(invoice.tax_inclusive), "url": ""}


def _invoice(org, args):
    from einvoice.models import Invoice

    invoice = Invoice.objects.filter(org=org, pk=args["invoice"]).first()
    if invoice is None:
        raise _denied("not_found", "invoice not found")
    return invoice


def check_submit(user, org, args) -> str:
    from einvoice import services

    _gate(user, org)
    invoice = _invoice(org, args)
    blocker = services.submit_blocker(invoice, services.profile_for(org, invoice.country))
    if blocker:
        raise _denied("not_available", blocker)
    profile = services.profile_for(org, invoice.country)
    if invoice.country == "SA":
        what = "clearance" if invoice.invoice_type == "standard" else "reporting"
        line = f"Send {invoice.number} ({invoice.currency} {_amount(invoice.tax_inclusive)}) to ZATCA for {what}"
    else:
        line = f"Send {invoice.number} ({invoice.currency} {_amount(invoice.tax_inclusive)}) to the ETA"
    if services.simulated(profile):
        line += " [demo, simulated]"
    return line[:300]


def execute_submit(user, org, args) -> dict:
    from einvoice import services

    check_submit(user, org, args)
    with transaction.atomic():
        try:
            return services.submit(user, org, args["invoice"])
        except services.EInvoiceError as exc:
            raise _denied("not_available" if exc.status == 409 else "invalid", exc.details) from exc


def register():
    from actions.plugins import handler, register_tool

    if handler("einvoice.prepare") is None:
        register_tool("einvoice.prepare", PREPARE, check=check_prepare, execute=execute_prepare)
    if handler("einvoice.submit") is None:
        register_tool("einvoice.submit", SUBMIT, check=check_submit, execute=execute_submit)
