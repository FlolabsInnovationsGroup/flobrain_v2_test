"""E-invoicing services: validation, totals, prepare (ZATCA XML / ETA document), submission,
status polling, onboarding and payloads. Views and the buddy tools call these.

Rules that hold everywhere:
- totals are computed here from the lines (``einvoice.money``); client totals are ignored;
- an invoice is editable only as a draft; ``prepare`` freezes it (SA: counter, previous hash,
  signed XML and QR; EG: the document JSON);
- sending to ZATCA or the ETA only happens in ``submit`` (the ``einvoice.submit`` tool), which
  runs after a person approved it in ``actions``; nothing here calls the authority otherwise,
  except onboarding steps an admin starts with ``einvoice.manage`` and read-only status polls;
- the demo workspace never reaches the network: onboarding and answers are simulated and labelled.
"""

import base64
import json
import logging
import re
import secrets
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from einvoice import money
from einvoice.eta import api as eta_api
from einvoice.eta import document as eta_document
from einvoice.eta import serialize as eta_serialize
from einvoice.eta import signer as eta_signer
from einvoice.models import EG, SA, AuthorityEvent, Invoice, InvoiceLine, TaxProfile
from einvoice.transport import TransportError, env
from einvoice.zatca import api as zatca_api
from einvoice.zatca import crypto, qr, ubl

logger = logging.getLogger(__name__)

FLAG = "einvoice"
VIEW, ISSUE, MANAGE = "einvoice.view", "einvoice.issue", "einvoice.manage"
RIYADH = ZoneInfo("Asia/Riyadh")
MAX_LINES = 200
SA_VAT_RE = re.compile(r"^3\d{13}3$")
EG_TAX_RE = re.compile(r"^\d{9}$")
SA_SCHEMES = {"CRN", "MOM", "MLS", "700", "SAG", "OTH", "TIN", "NAT", "GCC", "IQA", "PAS"}
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.-]{0,49}$")
OTP_RE = re.compile(r"^\d{6}$")
ACTIVITY_RE = re.compile(r"^\d{4}$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class EInvoiceError(Exception):
    def __init__(self, code: str, details: str, status: int = 400, **extra):
        super().__init__(details)
        self.code, self.details, self.status, self.extra = code, details, status, extra


def invalid(details: str) -> EInvoiceError:
    return EInvoiceError("invalid", details, 400)


# --- access ------------------------------------------------------------------------------


def membership(user, org):
    from organizations.models import OrgMembership

    return OrgMembership.objects.filter(org=org, user=user).first()


def flag_on(user, org) -> bool:
    from organizations.flags import effective_flag

    return effective_flag(org, membership(user, org), FLAG, default=False)


def demo_allowed(org) -> bool:
    return bool(getattr(settings, "DEMO_MODE", False)) and (org.settings or {}).get("demo") is True


def simulated(profile) -> bool:
    return bool(profile and profile.demo and demo_allowed(profile.org))


# --- text helpers ------------------------------------------------------------------------


def text(data, key, limit, *, required=False, name=None, one_line=True) -> str:
    value = data.get(key)
    value = "" if value is None else str(value)
    value = value.strip() if one_line else value
    if one_line:
        value = " ".join(value.split())
    if CONTROL_RE.search(value):
        raise invalid(f"{name or key} has characters that are not allowed")
    if len(value) > limit:
        raise invalid(f"{name or key} is longer than {limit} characters")
    if required and not value:
        raise invalid(f"{name or key} is required")
    return value


# --- profiles ----------------------------------------------------------------------------


def profile_for(org, country, create=False):
    profile = TaxProfile.objects.filter(org=org, country=country).first()
    if profile is None and create:
        env_default = TaxProfile.ENV_SANDBOX if country == SA else TaxProfile.ENV_PREPROD
        profile = TaxProfile.objects.create(org=org, country=country, environment=env_default, demo=demo_allowed(org))
    return profile


def _hint(value: str) -> str:
    return value[-4:] if len(value) >= 8 else ""


def profile_payload(profile, manager: bool) -> dict:
    if profile is None:
        return None
    out = {
        "country": profile.country,
        "environment": profile.environment,
        "seller_name": profile.seller_name,
        "seller_name_ar": profile.seller_name_ar,
        "tax_number": profile.tax_number,
        "registration_scheme": profile.registration_scheme,
        "registration_id": profile.registration_id,
        "street": profile.street,
        "building_number": profile.building_number,
        "district": profile.district,
        "city": profile.city,
        "region": profile.region,
        "postal_code": profile.postal_code,
        "activity_code": profile.activity_code,
        "simulated": simulated(profile),
        "updated_at": profile.updated_at.isoformat(),
    }
    if profile.country == SA:
        out.update(
            {
                "egs_serial": profile.egs_serial,
                "egs_common_name": profile.egs_common_name,
                "branch_name": profile.branch_name,
                "functionality_map": profile.functionality_map,
                "egs_location": profile.egs_location,
                "industry": profile.industry,
                "onboarding": profile.onboarding,
                "onboarding_error": profile.onboarding_error,
                "has_key": profile.has_secret("private_key"),
                "csr_ready": bool(profile.csr_pem),
                "compliance_results": profile.compliance_results if manager else [],
                "certificate_expires_at": profile.certificate_expires_at.isoformat() if profile.certificate_expires_at else None,
                "invoice_counter": profile.icv_counter,
            }
        )
    else:
        out.update(
            {
                "client_id_hint": _hint(profile.client_id) if profile.client_id else "",
                "client_id_set": bool(profile.client_id),
                "client_secret_set": profile.has_secret("client_secret"),
                "client_secret_hint": f"…{profile.client_secret_hint}" if profile.client_secret_hint else "",
                "signer_mode": profile.signer_mode,
                "signer_url": profile.signer_url if manager else ("set" if profile.signer_url else ""),
                "signer_token_set": profile.has_secret("signer_token"),
                "signer_token_hint": f"…{profile.signer_token_hint}" if profile.signer_token_hint else "",
            }
        )
    return out


SELLER_FIELDS = (
    ("seller_name", 200), ("seller_name_ar", 200), ("tax_number", 20), ("registration_scheme", 8), ("registration_id", 40),
    ("street", 200), ("building_number", 20), ("district", 120), ("city", 120), ("region", 120), ("postal_code", 10), ("activity_code", 8),
)
SA_EGS_FIELDS = (("egs_serial", 200), ("egs_common_name", 64), ("branch_name", 120), ("functionality_map", 4), ("egs_location", 120), ("industry", 120))


def update_profile(user, org, country, data) -> TaxProfile:
    from integrations import crypto as cred_crypto

    with transaction.atomic():
        profile = profile_for(org, country, create=True)
        profile = TaxProfile.objects.select_for_update().get(pk=profile.pk)
        for key, limit in SELLER_FIELDS + (SA_EGS_FIELDS if country == SA else ()):
            if key in data:
                setattr(profile, key, text(data, key, limit))
        if "environment" in data:
            allowed = (TaxProfile.ENV_SANDBOX, TaxProfile.ENV_SIMULATION, TaxProfile.ENV_PRODUCTION) if country == SA else (TaxProfile.ENV_PREPROD, TaxProfile.ENV_PRODUCTION)
            env_value = str(data.get("environment") or "")
            if env_value not in allowed:
                raise invalid("Pick one of the listed environments")
            if country == SA and env_value != profile.environment and profile.onboarding != TaxProfile.ONB_NONE and not simulated(profile):
                raise EInvoiceError("conflict", "Reset the ZATCA onboarding before you change the environment", 409)
            profile.environment = env_value
        if profile.tax_number:
            if country == SA and not SA_VAT_RE.match(profile.tax_number):
                raise invalid("The VAT number has 15 digits and starts and ends with 3")
            if country == EG and not EG_TAX_RE.match(profile.tax_number):
                raise invalid("The tax registration number has 9 digits")
        if country == SA and profile.registration_scheme and profile.registration_scheme not in SA_SCHEMES:
            raise invalid("The registration type is not one ZATCA lists (CRN, MOM, MLS, 700, SAG, OTH)")
        if country == SA and profile.functionality_map and not re.match(r"^[01]{4}$", profile.functionality_map):
            raise invalid("The invoice types are 4 digits of 0 or 1, for example 1100")
        if country == EG and profile.activity_code and not ACTIVITY_RE.match(profile.activity_code):
            raise invalid("The activity code has 4 digits")
        if country == EG:
            if "client_id" in data:
                profile.client_id = text(data, "client_id", 100)
            secrets_needed = [k for k in ("client_secret", "signer_token") if data.get(k)]
            if secrets_needed and not cred_crypto.is_configured():
                raise EInvoiceError("not_configured", "Secrets can't be stored: the server has no encryption key", 409)
            if data.get("client_secret"):
                value = text(data, "client_secret", 200)
                profile.set_secret("client_secret", value)
                profile.client_secret_hint = _hint(value)
            if data.get("clear_client_secret") is True:
                profile.set_secret("client_secret", None)
                profile.client_secret_hint = ""
            if "signer_mode" in data:
                mode = str(data.get("signer_mode") or "")
                if mode not in (TaxProfile.SIGNER_EXTERNAL, TaxProfile.SIGNER_MANUAL):
                    raise invalid("The signer is external or manual")
                profile.signer_mode = mode
            if "signer_url" in data:
                url = text(data, "signer_url", 300)
                if url:
                    from einvoice.transport import check_url, signer_hosts

                    try:
                        check_url(url, signer_hosts())
                    except TransportError as exc:
                        raise invalid(f"Signer address: {exc.details}. The server operator lists allowed signer hosts in EINVOICE_SIGNER_ALLOWED_HOSTS.") from exc
                profile.signer_url = url
            if data.get("signer_token"):
                value = text(data, "signer_token", 400)
                profile.set_secret("signer_token", value)
                profile.signer_token_hint = _hint(value)
            if data.get("clear_signer_token") is True:
                profile.set_secret("signer_token", None)
                profile.signer_token_hint = ""
        profile.updated_by = user
        profile.save()
    from organizations.services.core import audit

    audit(user, "einvoice.profile_updated", target=profile, payload={"country": country, "fields": sorted(k for k in data if "secret" not in k and "token" not in k)}, org=org)
    return profile


# --- invoices: input -----------------------------------------------------------------------


def _lines_in(country, rows) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise invalid("Add at least one line")
    if len(rows) > MAX_LINES:
        raise invalid(f"An invoice has at most {MAX_LINES} lines")
    out = []
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise invalid(f"line {i} is not valid")
        try:
            quantity = money.dec(row.get("quantity", "1"), f"line {i} quantity", places=6)
            price = money.dec(row.get("unit_price"), f"line {i} unit price", places=5)
            discount = money.dec(row.get("discount") or "0", f"line {i} discount", places=5)
            default_rate = "15" if country == SA else "14"
            rate = money.dec(row.get("vat_rate", default_rate), f"line {i} VAT rate", places=2)
        except money.MoneyError as exc:
            raise invalid(str(exc)) from exc
        category = str(row.get("vat_category") or ("S" if country == SA else "V009")).strip().upper()
        line = {
            "description": text(row, "description", 300, required=True, name=f"line {i} description"),
            "quantity": quantity,
            "unit_price": price,
            "discount": discount,
            "vat_category": category,
            "vat_rate": rate,
            "exemption_code": text(row, "exemption_code", 30).upper(),
            "exemption_reason": text(row, "exemption_reason", 200),
            "item_code": text(row, "item_code", 100),
            "item_type": text(row, "item_type", 3).upper(),
            "unit_code": text(row, "unit_code", 10).upper(),
        }
        if country == EG:
            if line["item_type"] and line["item_type"] not in ("GS1", "EGS"):
                raise invalid(f"line {i}: the item code type is GS1 or EGS")
        out.append(line)
    return out


def compute(country, lines: list[dict], exchange_rate=None) -> money.Totals:
    items = [
        money.LineIn(l["description"], l["quantity"], l["unit_price"], l["discount"], l["vat_category"], l["vat_rate"], l["exemption_code"], l["exemption_reason"])
        for l in lines
    ]
    try:
        return money.sa_totals(items) if country == SA else money.eg_totals(items, exchange_rate)
    except money.MoneyError as exc:
        raise invalid(str(exc)) from exc


INVOICE_TEXT = (
    ("buyer_name", 200), ("buyer_tax_number", 20), ("buyer_registration_scheme", 8), ("buyer_registration_id", 40), ("buyer_street", 200),
    ("buyer_building_number", 20), ("buyer_district", 120), ("buyer_city", 120), ("buyer_region", 120), ("buyer_postal_code", 10),
    ("note", 500), ("billing_reference", 50), ("adjustment_reason", 300),
)


def next_number(org, country) -> str:
    prefix = "SA" if country == SA else "EG"
    year = timezone.now().year
    n = Invoice.objects.filter(org=org, country=country).count() + 1
    while True:
        candidate = f"{prefix}-{year}-{n:05d}"
        if not Invoice.objects.filter(org=org, country=country, number=candidate).exists():
            return candidate
        n += 1


def save_invoice(user, org, data: dict, invoice: Invoice | None = None, *, source="manual", source_ref="") -> Invoice:
    if invoice is not None and invoice.status != Invoice.DRAFT:
        raise EInvoiceError("conflict", "Only drafts can be changed. Copy it to a new draft instead.", 409)
    country = invoice.country if invoice else str(data.get("country") or "").upper()
    if country not in (SA, EG):
        raise invalid("Pick Saudi Arabia (SA) or Egypt (EG)")
    current = invoice or Invoice(org=org, country=country, created_by=user, source=source, source_ref=source_ref[:80])
    types = (Invoice.STANDARD, Invoice.SIMPLIFIED) if country == SA else (Invoice.B2B, Invoice.B2C)
    invoice_type = str(data.get("invoice_type") or current.invoice_type or types[0])
    if invoice_type not in types:
        raise invalid(f"The invoice type is {' or '.join(types)}")
    current.invoice_type = invoice_type
    kind = str(data.get("kind") or current.kind or Invoice.INVOICE)
    if kind not in (Invoice.INVOICE, Invoice.CREDIT, Invoice.DEBIT) or (country == EG and kind != Invoice.INVOICE):
        raise invalid("Egyptian credit and debit notes are not supported yet" if country == EG else "The kind is invoice, credit or debit")
    current.kind = kind
    if "number" in data or not current.number:
        number = text(data, "number", 50) or (current.number or next_number(org, country))
        if not NUMBER_RE.match(number):
            raise invalid("The invoice number uses letters, digits, / _ . and - only")
        current.number = number
    currency = str(data.get("currency") or current.currency or ("SAR" if country == SA else "EGP")).upper()
    if not CURRENCY_RE.match(currency):
        raise invalid("The currency is a 3-letter code")
    if country == SA and currency != "SAR":
        raise invalid("Saudi invoices are issued in SAR here")
    current.currency = currency
    if country == EG and currency != "EGP":
        try:
            current.exchange_rate = money.dec(data.get("exchange_rate", current.exchange_rate), "exchange rate", places=5)
        except money.MoneyError as exc:
            raise invalid(str(exc)) from exc
        if current.exchange_rate <= 0:
            raise invalid("The exchange rate must be above 0")
    else:
        current.exchange_rate = None
    for key, limit in INVOICE_TEXT:
        if key in data:
            setattr(current, key, text(data, key, limit))
    if "buyer_country" in data:
        value = text(data, "buyer_country", 2).upper()
        if value and not re.match(r"^[A-Z]{2}$", value):
            raise invalid("The buyer country is a 2-letter code")
        current.buyer_country = value
    if "payment_means" in data:
        value = text(data, "payment_means", 4)
        if value and not re.match(r"^\d{1,3}$|^ZZZ$", value):
            raise invalid("The payment means is a UN/ECE 4461 code, for example 10 (cash) or 30 (credit transfer)")
        current.payment_means = value or "10"
    if "issue_datetime" in data and data.get("issue_datetime"):
        issued = parse_datetime(str(data["issue_datetime"]))
        if issued is None:
            raise invalid("The issue date and time is not valid")
        if timezone.is_naive(issued):
            issued = timezone.make_aware(issued, RIYADH if country == SA else ZoneInfo("Africa/Cairo"))
        if issued > timezone.now() + timedelta(minutes=5):
            raise invalid("The issue date can't be in the future")
        current.issue_datetime = issued
    if "supply_date" in data:
        current.supply_date = parse_date(str(data["supply_date"])) if data.get("supply_date") else None
    lines = _lines_in(country, data["lines"]) if "lines" in data else [
        {k: getattr(l, k) for k in ("description", "quantity", "unit_price", "discount", "vat_category", "vat_rate", "exemption_code", "exemption_reason", "item_code", "item_type", "unit_code")}
        for l in (current.lines.all() if current.pk and invoice else [])
    ]
    if not lines:
        raise invalid("Add at least one line")
    totals = compute(country, lines, current.exchange_rate)
    _apply_totals(current, totals)
    try:
        with transaction.atomic():
            current.save()
            if "lines" in data or invoice is None:
                current.lines.all().delete()
                InvoiceLine.objects.bulk_create(
                    [InvoiceLine(invoice=current, position=i, **line, gross_amount=out.gross, net_amount=out.net, vat_amount=out.vat, total_amount=out.total) for i, (line, out) in enumerate(zip(lines, totals.lines), start=1)]
                )
    except IntegrityError as exc:
        raise EInvoiceError("conflict", "An invoice with this number already exists", 409) from exc
    return current


def _apply_totals(invoice, totals: money.Totals):
    invoice.line_extension = totals.line_extension
    invoice.discount_total = totals.discount_total
    invoice.tax_exclusive = totals.tax_exclusive
    invoice.tax_total = totals.tax_total
    invoice.tax_inclusive = totals.tax_inclusive
    invoice.payable = totals.payable
    invoice.tax_breakdown = [
        {k: (str(v) if isinstance(v, Decimal) else v) for k, v in group.items()} for group in totals.breakdown
    ]


def line_rows(invoice) -> list[dict]:
    return [
        {k: getattr(l, k) for k in ("description", "quantity", "unit_price", "discount", "vat_category", "vat_rate", "exemption_code", "exemption_reason", "item_code", "item_type", "unit_code")}
        for l in invoice.lines.all()
    ]


def copy_as_draft(user, org, invoice) -> Invoice:
    data = {k: getattr(invoice, k) for k, _ in INVOICE_TEXT}
    data.update({"country": invoice.country, "invoice_type": invoice.invoice_type, "kind": invoice.kind, "currency": invoice.currency, "buyer_country": invoice.buyer_country, "payment_means": invoice.payment_means})
    if invoice.exchange_rate:
        data["exchange_rate"] = str(invoice.exchange_rate)
    data["lines"] = [{k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()} for row in line_rows(invoice)]
    return save_invoice(user, org, data, source=invoice.source, source_ref=invoice.source_ref)


# --- prepare -----------------------------------------------------------------------------


def _require(value, message):
    if not value:
        raise EInvoiceError("incomplete", message, 409)


def _check_sa_ready(invoice, profile):
    _require(profile and profile.seller_name and SA_VAT_RE.match(profile.tax_number or ""), "Add the seller name and VAT number in E-invoice settings")
    _require(profile.street and profile.city and profile.district and profile.building_number and profile.postal_code, "Add the seller's full national address in E-invoice settings")
    if not (re.match(r"^\d{4}$", profile.building_number) and re.match(r"^\d{5}$", profile.postal_code)):
        raise EInvoiceError("incomplete", "The seller's building number has 4 digits and the postal code 5 digits", 409)
    _require(profile.registration_id, "Add the seller's commercial registration (or other ID) in E-invoice settings")
    if invoice.invoice_type == Invoice.STANDARD:
        _require(invoice.buyer_name, "A standard invoice needs the buyer's name")
        _require(invoice.buyer_street and invoice.buyer_city, "A standard invoice needs the buyer's address")
        if invoice.buyer_tax_number:
            if not SA_VAT_RE.match(invoice.buyer_tax_number) and (invoice.buyer_country or "SA") == "SA":
                raise EInvoiceError("incomplete", "The buyer's VAT number has 15 digits and starts and ends with 3", 409)
        elif not (invoice.buyer_registration_id and invoice.buyer_registration_scheme in SA_SCHEMES):
            raise EInvoiceError("incomplete", "A standard invoice needs the buyer's VAT number or another ID (CRN, national ID…)", 409)
    if invoice.kind != Invoice.INVOICE:
        _require(invoice.billing_reference and invoice.adjustment_reason, "A note needs the original invoice number and the reason")
    ready = profile.onboarding == TaxProfile.ONB_PRODUCTION and profile.has_secret("private_key") and profile.certificate_b64
    if not ready:
        raise EInvoiceError("not_onboarded", "Finish ZATCA onboarding first (Settings tab)", 409)


def sa_data(invoice, profile, icv: int, pih: str, totals=None) -> dict:
    local = invoice.issue_datetime.astimezone(RIYADH)
    lines = list(invoice.lines.all())
    breakdown = totals.breakdown if totals is not None else [
        {"category": g["category"], "rate": Decimal(str(g["rate"])), "taxable": Decimal(str(g["taxable"])), "tax": Decimal(str(g["tax"])), "exemption_code": g.get("exemption_code", ""), "exemption_reason": g.get("exemption_reason", "")}
        for g in invoice.tax_breakdown
    ]
    supply = invoice.supply_date or (local.date() if invoice.invoice_type == Invoice.STANDARD else None)
    return {
        "uuid": str(invoice.id),
        "number": invoice.number,
        "issue_date": local.strftime("%Y-%m-%d"),
        "issue_time": local.strftime("%H:%M:%S"),
        "type": invoice.invoice_type,
        "kind": invoice.kind,
        "currency": invoice.currency,
        "icv": icv,
        "pih": pih,
        "note": invoice.note,
        "billing_reference": invoice.billing_reference,
        "adjustment_reason": invoice.adjustment_reason,
        "payment_means": invoice.payment_means or "10",
        "supply_date": supply.isoformat() if isinstance(supply, date) else None,
        "seller": {
            "name": profile.seller_name, "vat": profile.tax_number, "scheme": profile.registration_scheme or "CRN", "reg_id": profile.registration_id,
            "street": profile.street, "building": profile.building_number, "district": profile.district, "city": profile.city,
            "postal": profile.postal_code, "country": "SA",
        },
        "buyer": {
            "name": invoice.buyer_name, "vat": invoice.buyer_tax_number, "scheme": invoice.buyer_registration_scheme, "reg_id": "" if invoice.buyer_tax_number else invoice.buyer_registration_id,
            "street": invoice.buyer_street, "building": invoice.buyer_building_number, "district": invoice.buyer_district, "city": invoice.buyer_city,
            "postal": invoice.buyer_postal_code, "country": invoice.buyer_country or "SA",
        },
        "lines": [
            {
                "id": l.position, "description": l.description, "quantity": l.quantity, "unit_price": l.unit_price, "discount": l.discount,
                "gross": money.q2(l.quantity * l.unit_price), "net": l.net_amount, "vat": l.vat_amount, "total": l.total_amount,
                "category": l.vat_category, "rate": l.vat_rate, "unit_code": l.unit_code or "PCE",
            }
            for l in lines
        ],
        "totals": {
            "line_extension": invoice.line_extension, "tax_exclusive": invoice.tax_exclusive, "tax_total": invoice.tax_total,
            "tax_inclusive": invoice.tax_inclusive, "payable": invoice.payable, "breakdown": breakdown,
        },
    }


def _signing_time() -> str:
    return timezone.now().astimezone(RIYADH).strftime("%Y-%m-%dT%H:%M:%S")


def qr_options() -> dict:
    encoding = env("EINVOICE_ZATCA_QR_HASH_ENCODING") or qr.HASH_TEXT
    return {"qr_hash_encoding": encoding if encoding in (qr.HASH_TEXT, qr.HASH_RAW) else qr.HASH_TEXT, "qr_time_suffix": "Z" if env("EINVOICE_ZATCA_QR_TIME_SUFFIX") == "Z" else ""}


def prepare(user, org, invoice_id) -> Invoice:
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().filter(org=org, pk=invoice_id).first()
        if invoice is None:
            raise EInvoiceError("not_found", "Invoice not found", 404)
        if invoice.status != Invoice.DRAFT:
            raise EInvoiceError("conflict", "This invoice is already prepared", 409)
        # Recompute from the lines once more: what is frozen is what the server computed.
        totals = compute(invoice.country, line_rows(invoice), invoice.exchange_rate)
        _apply_totals(invoice, totals)
        if invoice.country == SA:
            _prepare_sa(invoice, org, totals)
        else:
            _prepare_eg(invoice, org, totals)
        invoice.status = Invoice.READY
        invoice.prepared_at = timezone.now()
        invoice.save()
    from organizations.services.core import audit

    audit(user, "einvoice.prepared", target=invoice, payload={"country": invoice.country, "number": invoice.number, "icv": invoice.icv}, org=org)
    return invoice


def _prepare_sa(invoice, org, totals):
    profile = TaxProfile.objects.select_for_update().filter(org=org, country=SA).first()
    _check_sa_ready(invoice, profile)
    key = crypto.key_from_pem(profile.secret("private_key"))
    icv = profile.icv_counter + 1
    pih = profile.last_hash or ubl.INITIAL_PIH
    data = sa_data(invoice, profile, icv, pih, totals)
    try:
        out = ubl.finalize(data, key, profile.certificate_b64, signing_time=_signing_time(), **qr_options())
    except (ubl.UBLError, qr.QRError, crypto.CryptoError) as exc:
        raise invalid(str(exc)) from exc
    profile.icv_counter = icv
    profile.last_hash = out["hash"]
    profile.save(update_fields=["icv_counter", "last_hash", "updated_at"])
    invoice.icv, invoice.pih, invoice.invoice_hash, invoice.qr, invoice.xml = icv, pih, out["hash"], out["qr"], out["xml"]


def _check_eg_ready(invoice, profile):
    _require(profile and profile.seller_name and EG_TAX_RE.match(profile.tax_number or ""), "Add the issuer name and 9-digit tax registration number in E-invoice settings")
    _require(profile.region and profile.city and profile.street and profile.building_number, "Add the issuer's address (governorate, city, street, building)")
    _require(ACTIVITY_RE.match(profile.activity_code or ""), "Add the 4-digit taxpayer activity code in E-invoice settings")
    rtype = eta_document.receiver_type(invoice)
    if rtype in ("B", "F"):
        _require(invoice.buyer_name and invoice.buyer_tax_number, "A business receiver needs a name and a tax registration number")
        _require(invoice.buyer_region and invoice.buyer_city and invoice.buyer_street and invoice.buyer_building_number, "A business receiver needs an address (governorate, city, street, building)")
        if rtype == "B" and not EG_TAX_RE.match(invoice.buyer_tax_number):
            raise EInvoiceError("incomplete", "An Egyptian business receiver has a 9-digit tax registration number", 409)
        if invoice.buyer_tax_number == profile.tax_number:
            raise EInvoiceError("incomplete", "The receiver can't be the issuer", 409)
    else:
        threshold = Decimal(env("EINVOICE_ETA_B2C_ID_THRESHOLD") or "50000")
        if invoice.tax_inclusive >= threshold:
            _require(invoice.buyer_name and invoice.buyer_tax_number, f"For a person, invoices of EGP {threshold:,.0f} or more need the buyer's name and national ID")
    for line in invoice.lines.all():
        _require(line.item_type in ("GS1", "EGS") and line.item_code, f"Line {line.position} needs a GS1 or EGS item code")


def _prepare_eg(invoice, org, totals):
    profile = profile_for(org, EG)
    _check_eg_ready(invoice, profile)
    doc = eta_document.build(invoice, profile, list(invoice.lines.all()), totals)
    try:
        invoice.eta_document = eta_serialize.to_json(doc)
    except eta_serialize.SerializeError as exc:
        raise invalid(str(exc)) from exc


def eta_canonical(invoice) -> str:
    return eta_serialize.canonical_from_json(invoice.eta_document)


def upload_signature(user, org, invoice, value: str) -> Invoice:
    if invoice.country != EG or invoice.status not in (Invoice.READY, Invoice.ERROR):
        raise EInvoiceError("conflict", "Signatures are uploaded for prepared Egyptian invoices", 409)
    try:
        invoice.eta_signature = eta_signer.check_signature(value)
    except eta_signer.SignerError as exc:
        raise invalid(exc.details) from exc
    invoice.eta_signature_simulated = False
    invoice.save(update_fields=["eta_signature", "eta_signature_simulated", "updated_at"])
    from organizations.services.core import audit

    audit(user, "einvoice.signature_uploaded", target=invoice, payload={"number": invoice.number}, org=org)
    return invoice


# --- submission (only from the approved einvoice.submit tool) ----------------------------


def submit_blocker(invoice, profile) -> str:
    """Why this invoice can't be sent now, or ""."""
    if invoice.status not in (Invoice.READY, Invoice.ERROR):
        return "Only prepared invoices can be sent"
    if profile is None:
        return "Set up e-invoicing for this country first"
    if simulated(profile):
        return ""
    if profile.demo:
        return "Demo settings only work in the demo workspace"
    if invoice.country == SA:
        if profile.onboarding != TaxProfile.ONB_PRODUCTION or not profile.has_secret("production"):
            return "Finish ZATCA onboarding first"
        return ""
    if not (profile.client_id and profile.has_secret("client_secret")):
        return "Add the ETA client id and secret first"
    if not invoice.eta_signature:
        if profile.signer_mode == TaxProfile.SIGNER_MANUAL:
            return "Upload the signature from your token first"
        if not profile.signer_url:
            return "Add the signer service address first"
    return ""


def authority_name(country) -> str:
    return "ZATCA" if country == SA else "the ETA"


def _event(org, invoice, action, status, outcome, response, sim, actor):
    AuthorityEvent.objects.create(org=org, invoice=invoice, country=invoice.country if invoice else SA, action=action, http_status=status, outcome=outcome[:40], response=response, simulated=sim, actor=actor)


def submit(user, org, invoice_id) -> dict:
    """Runs only from the approved ``einvoice.submit`` action. Never raises for an authority's
    answer: the invoice records accepted, rejected or error, and the result says which."""
    invoice = Invoice.objects.select_for_update().filter(org=org, pk=invoice_id).first()
    if invoice is None:
        raise EInvoiceError("not_found", "Invoice not found", 404)
    profile = profile_for(org, invoice.country)
    blocker = submit_blocker(invoice, profile)
    if blocker:
        raise EInvoiceError("not_available", blocker, 409)
    invoice.submitted_at = timezone.now()
    if invoice.country == SA:
        _submit_sa(user, org, invoice, profile)
    else:
        _submit_eg(user, org, invoice, profile)
    invoice.save()
    from organizations.services.core import audit

    audit(user, "einvoice.submitted", target=invoice, payload={"country": invoice.country, "number": invoice.number, "status": invoice.status, "simulated": invoice.simulated}, org=org)
    _notify(invoice)
    return {"invoice": str(invoice.id), "number": invoice.number, "status": invoice.status, "authority_status": invoice.authority_status, "simulated": invoice.simulated}


def _notify(invoice):
    if invoice.status not in (Invoice.REJECTED, Invoice.ERROR) or invoice.created_by is None:
        return
    try:
        from notifications.services import notify

        notify(
            invoice.org, [invoice.created_by], "einvoice.rejected",
            {
                "number": invoice.number, "status": invoice.status, "authority": authority_name(invoice.country),
                "text": f"E-invoice {invoice.number}: {'rejected by' if invoice.status == Invoice.REJECTED else 'could not be sent to'} {authority_name(invoice.country)}",
            },
            link=f"einvoices/{invoice.id}",
        )
    except Exception:  # noqa: BLE001 - a notification must never undo a submission record
        logger.exception("einvoice notification failed")


def _demo_sa_answer(invoice, mode):
    key = "clearanceStatus" if mode == "clearance" else "reportingStatus"
    answer = {
        key: "CLEARED" if mode == "clearance" else "REPORTED",
        "validationResults": {"status": "PASS", "infoMessages": [{"type": "INFO", "code": "XSD_ZATCA_VALID", "category": "XSD validation", "message": "Complied with UBL 2.1 standards (simulated in the demo)", "status": "PASS"}], "warningMessages": [], "errorMessages": []},
    }
    if mode == "clearance":
        answer["clearedInvoice"] = base64.b64encode(invoice.xml.encode("utf-8")).decode("ascii")
    return 200, answer


def _submit_sa(user, org, invoice, profile):
    mode = "clearance" if invoice.invoice_type == Invoice.STANDARD else "reporting"
    sim = simulated(profile)
    try:
        if sim:
            status, parsed = _demo_sa_answer(invoice, mode)
        else:
            creds = json.loads(profile.secret("production"))
            call = zatca_api.clearance if mode == "clearance" else zatca_api.reporting
            status, parsed = call(profile.environment, creds["token"], creds["secret"], invoice.invoice_hash, str(invoice.id), invoice.xml)
    except TransportError as exc:
        invoice.status, invoice.authority_status = Invoice.ERROR, exc.code
        invoice.authority_response = {"mode": mode, "error": exc.details}
        _event(org, invoice, mode, None, "error", invoice.authority_response, sim, user)
        return
    result = zatca_api.outcome(status, parsed, mode)
    invoice.status = {"accepted": Invoice.ACCEPTED, "rejected": Invoice.REJECTED}.get(result, Invoice.ERROR)
    invoice.authority_status = str(parsed.get("clearanceStatus" if mode == "clearance" else "reportingStatus") or f"HTTP {status}")[:40]
    invoice.authority_response = {"mode": mode, "http_status": status, "warnings": status == 202, **zatca_api.messages(parsed)}
    if mode == "clearance" and result == "accepted" and isinstance(parsed.get("clearedInvoice"), str):
        try:
            cleared = base64.b64decode(parsed["clearedInvoice"], validate=True)
            if len(cleared) <= 2 * 1024 * 1024:
                invoice.cleared_xml = cleared.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            pass
    invoice.simulated = sim
    invoice.decided_at = timezone.now() if invoice.status in (Invoice.ACCEPTED, Invoice.REJECTED) else None
    _event(org, invoice, mode, status, result, invoice.authority_response, sim, user)


def _eg_signature(invoice, profile, sim) -> str:
    if invoice.eta_signature:
        return invoice.eta_signature
    if sim:
        # Demo only: a stand-in, labelled as such. Real invoices are signed by the customer's token.
        invoice.eta_signature = "DEMO-SIMULATED-SIGNATURE"
        invoice.eta_signature_simulated = True
        return invoice.eta_signature
    signature = eta_signer.external_sign(profile.signer_url, profile.secret("signer_token"), invoice.number, eta_canonical(invoice))
    invoice.eta_signature = signature
    invoice.eta_signature_simulated = False
    return signature


def _submit_eg(user, org, invoice, profile):
    sim = simulated(profile)
    try:
        signature = _eg_signature(invoice, profile, sim)
        signed = eta_document.with_signature(invoice.eta_document, signature)
        if sim:
            n = secrets.token_hex(13).upper()[:26]
            status, parsed = 202, {"submissionUUID": f"DEMO{n[:22]}", "acceptedDocuments": [{"uuid": n, "longId": f"DEMO{secrets.token_hex(19).upper()}"[:42], "internalId": invoice.number}], "rejectedDocuments": []}
        else:
            access = eta_api.token(profile.environment, profile.client_id, profile.secret("client_secret"))
            status, parsed = eta_api.submit(profile.environment, access, signed)
    except eta_signer.SignerError as exc:
        invoice.status, invoice.authority_status = Invoice.ERROR, exc.code
        invoice.authority_response = {"error": exc.details}
        _event(org, invoice, "sign", None, "error", invoice.authority_response, sim, user)
        return
    except TransportError as exc:
        invoice.status, invoice.authority_status = Invoice.ERROR, exc.code
        invoice.authority_response = {"error": exc.details}
        _event(org, invoice, "submit", None, "error", invoice.authority_response, sim, user)
        return
    outcome = eta_api.submission_outcome(parsed)
    invoice.simulated = sim
    if status == 202 and outcome["uuid"]:
        invoice.status, invoice.authority_status = Invoice.SUBMITTED, "submitted"
        invoice.authority_uuid, invoice.authority_submission, invoice.authority_long_id = outcome["uuid"], outcome["submission"], outcome["long_id"]
        result = "submitted"
    elif status == 202 and outcome["rejected"]:
        invoice.status, invoice.authority_status = Invoice.REJECTED, "rejected"
        invoice.decided_at = timezone.now()
        result = "rejected"
    elif status == 422:
        invoice.status, invoice.authority_status = Invoice.ERROR, "duplicate"
        result = "error"
    else:
        invoice.status, invoice.authority_status = Invoice.ERROR, f"HTTP {status}"
        result = "error"
    invoice.authority_response = {"http_status": status, **outcome, "error": eta_api.short_error(parsed.get("error")) if parsed.get("error") else None}
    _event(org, invoice, "submit", status, result, invoice.authority_response, sim, user)


def poll(user, org, invoice) -> Invoice:
    """Read-only status check of a submitted Egyptian invoice."""
    if invoice.country != EG or invoice.status != Invoice.SUBMITTED or not invoice.authority_submission:
        raise EInvoiceError("conflict", "Only submitted Egyptian invoices have a status to check", 409)
    profile = profile_for(org, EG)
    sim = simulated(profile)
    try:
        if sim:
            status, parsed = 200, {"overallStatus": "valid", "documentSummary": [{"uuid": invoice.authority_uuid, "internalId": invoice.number, "status": "valid"}]}
        else:
            if not (profile and profile.client_id and profile.has_secret("client_secret")):
                raise EInvoiceError("not_available", "Add the ETA client id and secret first", 409)
            access = eta_api.token(profile.environment, profile.client_id, profile.secret("client_secret"))
            status, parsed = eta_api.submission(profile.environment, access, invoice.authority_submission)
    except TransportError as exc:
        raise EInvoiceError("unreachable", exc.details, 502) from exc
    state = eta_api.document_status(parsed, invoice.number, invoice.authority_uuid) if status == 200 else ""
    mapped = eta_api.STATUS_MAP.get(state)
    if mapped and mapped != Invoice.SUBMITTED:
        invoice.status = mapped
        invoice.decided_at = timezone.now()
    if state:
        invoice.authority_status = state
    invoice.authority_response = {**(invoice.authority_response or {}), "overall_status": str(parsed.get("overallStatus") or "")[:30], "checked_at": timezone.now().isoformat()}
    invoice.save()
    _event(org, invoice, "poll", status, state or f"HTTP {status}", {"status": state, "overall": str(parsed.get("overallStatus") or "")[:30]}, sim, user)
    _notify(invoice)
    return invoice


# --- approvals ---------------------------------------------------------------------------


def pending_proposal(invoice):
    from actions.models import ActionProposal

    proposal = invoice.proposal
    if proposal is None or proposal.status != ActionProposal.STATUS_PROPOSED or proposal.is_expired:
        return None
    return proposal


def request_submission(user, org, invoice) -> object:
    """Create the approval for sending. Nothing is sent until it is approved."""
    from actions.models import ActionProposal
    from actions.registry import TOOLS
    from actions.schema import validate
    from actions.service import ActionDenied, check

    from organizations.services.core import audit

    if pending_proposal(invoice) is not None:
        raise EInvoiceError("conflict", "This invoice is already waiting for approval", 409)
    args = validate(TOOLS["einvoice.submit"]["schema"], {"invoice": str(invoice.id)})
    try:
        summary = check("einvoice.submit", user, org, args)
    except ActionDenied as exc:
        status = {"not_available": 409, "invalid": 400, "not_found": 404}.get(exc.code, 403)
        raise EInvoiceError(exc.code, str(exc), status) from exc
    proposal = ActionProposal.objects.create(org=org, user=user, tool_key="einvoice.submit", arguments=args, summary=summary[:300])
    invoice.proposal = proposal
    invoice.save(update_fields=["proposal", "updated_at"])
    audit(user, "action.proposed", target=proposal, payload={"tool": "einvoice.submit", "status": proposal.status}, org=org)
    return proposal


# --- payloads ----------------------------------------------------------------------------


def _s(value):
    return str(value) if isinstance(value, Decimal) else value


def invoice_payload(invoice, detail=False) -> dict:
    proposal = pending_proposal(invoice)
    out = {
        "id": str(invoice.id),
        "country": invoice.country,
        "invoice_type": invoice.invoice_type,
        "kind": invoice.kind,
        "number": invoice.number,
        "currency": invoice.currency,
        "issue_datetime": invoice.issue_datetime.isoformat(),
        "buyer_name": invoice.buyer_name,
        "tax_total": _s(money.q2(invoice.tax_total) if invoice.country == SA else invoice.tax_total),
        "total": _s(money.q2(invoice.tax_inclusive) if invoice.country == SA else invoice.tax_inclusive),
        "status": invoice.status,
        "authority_status": invoice.authority_status,
        "simulated": invoice.simulated,
        "source": invoice.source,
        "waiting_approval": proposal is not None,
        "approval": {"id": str(proposal.id), "summary": proposal.summary, "expires_at": proposal.expires_at.isoformat(), "user": str(proposal.user_id)} if proposal else None,
        "created_at": invoice.created_at.isoformat(),
        "submitted_at": invoice.submitted_at.isoformat() if invoice.submitted_at else None,
    }
    if not detail:
        return out
    q = money.q2 if invoice.country == SA else (lambda v: v)
    out.update(
        {
            "exchange_rate": _s(invoice.exchange_rate),
            "supply_date": invoice.supply_date.isoformat() if invoice.supply_date else None,
            "payment_means": invoice.payment_means,
            "billing_reference": invoice.billing_reference,
            "adjustment_reason": invoice.adjustment_reason,
            "note": invoice.note,
            **{k: getattr(invoice, k) for k, _ in INVOICE_TEXT if k.startswith("buyer_")},
            "buyer_country": invoice.buyer_country,
            "lines": [
                {
                    "position": l.position, "description": l.description, "item_code": l.item_code, "item_type": l.item_type, "unit_code": l.unit_code,
                    "quantity": _s(l.quantity.normalize()), "unit_price": _s(l.unit_price.normalize()), "discount": _s(l.discount.normalize()),
                    "vat_category": l.vat_category, "vat_rate": _s(l.vat_rate), "exemption_code": l.exemption_code, "exemption_reason": l.exemption_reason,
                    "net_amount": _s(q(l.net_amount)), "vat_amount": _s(q(l.vat_amount)), "total_amount": _s(q(l.total_amount)),
                }
                for l in invoice.lines.all()
            ],
            "totals": {
                "line_extension": _s(q(invoice.line_extension)), "discount_total": _s(q(invoice.discount_total)), "tax_exclusive": _s(q(invoice.tax_exclusive)),
                "tax_total": _s(q(invoice.tax_total)), "tax_inclusive": _s(q(invoice.tax_inclusive)), "payable": _s(q(invoice.payable)),
                "breakdown": invoice.tax_breakdown,
            },
            "icv": invoice.icv,
            "pih": invoice.pih,
            "invoice_hash": invoice.invoice_hash,
            "qr": invoice.qr,
            "qr_fields": qr.readable(invoice.qr) if invoice.qr else {},
            "has_xml": bool(invoice.xml),
            "has_cleared_xml": bool(invoice.cleared_xml),
            "eta_ready": bool(invoice.eta_document),
            "eta_signed": bool(invoice.eta_signature),
            "eta_signature_simulated": invoice.eta_signature_simulated,
            "authority_uuid": invoice.authority_uuid,
            "authority_submission": invoice.authority_submission,
            "authority_long_id": invoice.authority_long_id,
            "authority_response": invoice.authority_response,
            "prepared_at": invoice.prepared_at.isoformat() if invoice.prepared_at else None,
            "decided_at": invoice.decided_at.isoformat() if invoice.decided_at else None,
            "events": [
                {"action": e.action, "http_status": e.http_status, "outcome": e.outcome, "simulated": e.simulated, "at": e.created_at.isoformat()}
                for e in invoice.events.all()[:20]
            ],
        }
    )
    profile = profile_for(invoice.org, invoice.country)
    out["seller"] = {
        "name": profile.seller_name if profile else "", "name_ar": profile.seller_name_ar if profile else "",
        "tax_number": profile.tax_number if profile else "", "registration_id": profile.registration_id if profile else "",
        "address": ", ".join(p for p in ((profile.building_number, profile.street, profile.district, profile.city, profile.region, profile.postal_code) if profile else ()) if p),
    }
    out["blocker"] = submit_blocker(invoice, profile) if invoice.status in (Invoice.READY, Invoice.ERROR) else ""
    out["signer_mode"] = profile.signer_mode if profile and invoice.country == EG else ""
    return out


def chain_ok(org) -> dict:
    """The Saudi hash chain: each prepared invoice's PIH is the previous one's hash."""
    rows = list(Invoice.objects.filter(org=org, country=SA, icv__isnull=False).order_by("icv").values("icv", "pih", "invoice_hash", "number"))
    expected = ubl.INITIAL_PIH
    for row in rows:
        if row["pih"] != expected:
            return {"ok": False, "broken_at": row["number"], "count": len(rows)}
        expected = row["invoice_hash"]
    return {"ok": True, "count": len(rows)}
