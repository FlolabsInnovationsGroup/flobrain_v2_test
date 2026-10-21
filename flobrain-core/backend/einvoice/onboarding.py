"""ZATCA onboarding of an EGS unit, and the ETA credentials check. Admins with
``einvoice.manage`` run each step themselves (the OTP they type is the human step ZATCA requires).

1. ``generate_key``: secp256k1 key (stored encrypted) and the CSR from the profile's EGS fields.
2. ``compliance_csid``: the 6-digit OTP from the Fatoora portal (valid one hour, never stored)
   and the CSR -> compliance CSID (certificate + secret, stored encrypted).
3. ``compliance_checks``: signs and sends sample documents with the compliance CSID, as the
   Detailed Technical Guidelines ask: for each invoice type the EGS is set up for (functionality
   map: standard, simplified) an invoice, a credit note and a debit note. The samples use their
   own counter and hash chain and never touch the production chain.
4. ``production_csid``: the compliance request id -> production CSID used for clearance and
   reporting. Its certificate replaces the compliance one on the profile.
In the demo workspace every step is simulated with a self-signed certificate labelled as demo.
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from einvoice import money
from einvoice.eta import api as eta_api
from einvoice.models import SA, AuthorityEvent, TaxProfile
from einvoice.services import EInvoiceError, OTP_RE, RIYADH, profile_for, qr_options, simulated
from einvoice.transport import TransportError, env
from einvoice.zatca import api as zatca_api
from einvoice.zatca import crypto, ubl


def _audit(user, org, action, profile, payload=None):
    from organizations.services.core import audit

    audit(user, action, target=profile, payload={"country": profile.country, **(payload or {})}, org=org)


def _event(org, action, status, outcome, response, sim, user, country=SA):
    AuthorityEvent.objects.create(org=org, country=country, action=action, http_status=status, outcome=outcome[:40], response=response, simulated=sim, actor=user)


def _locked(org):
    profile = profile_for(org, SA)
    if profile is None:
        raise EInvoiceError("incomplete", "Save the seller details first", 409)
    return TaxProfile.objects.select_for_update().get(pk=profile.pk)


def _require_crypto():
    from integrations import crypto as cred_crypto

    if not cred_crypto.is_configured():
        raise EInvoiceError("not_configured", "Keys can't be stored: the server has no encryption key (CREDENTIALS_ENCRYPTION_KEY)", 409)


def generate_key(user, org) -> TaxProfile:
    _require_crypto()
    with transaction.atomic():
        profile = _locked(org)
        if profile.onboarding not in (TaxProfile.ONB_NONE, TaxProfile.ONB_KEY):
            raise EInvoiceError("conflict", "This unit is already onboarded. Reset onboarding to start again.", 409)
        key = crypto.generate_key()
        try:
            csr = crypto.build_csr(
                key, environment=profile.environment, common_name=profile.egs_common_name, egs_serial=profile.egs_serial,
                vat_number=profile.tax_number, branch_name=profile.branch_name, org_name=profile.seller_name,
                functionality_map=profile.functionality_map, location=profile.egs_location, industry=profile.industry,
            )
        except crypto.CryptoError as exc:
            raise EInvoiceError("invalid", str(exc), 400) from exc
        profile.set_secret("private_key", crypto.key_to_pem(key))
        profile.csr_pem = csr
        profile.onboarding = TaxProfile.ONB_KEY
        profile.onboarding_error = ""
        profile.updated_by = user
        profile.save()
    _audit(user, org, "einvoice.key_generated", profile)
    return profile


def _store_csid(profile, field, token, secret_value):
    cert_b64 = crypto.certificate_from_token(token)
    profile.set_secret(field, json.dumps({"token": token, "secret": secret_value}))
    profile.certificate_b64 = cert_b64
    cert = crypto.load_certificate(cert_b64)
    profile.certificate_expires_at = cert.not_valid_after_utc


def _demo_token(profile) -> str:
    import base64

    key = crypto.key_from_pem(profile.secret("private_key"))
    cert_b64 = crypto.demo_certificate(key, profile.tax_number, profile.seller_name)
    return base64.b64encode(cert_b64.encode("ascii")).decode("ascii")


def compliance_csid(user, org, otp: str) -> TaxProfile:
    otp = (otp or "").strip()
    if not OTP_RE.match(otp):
        raise EInvoiceError("invalid", "The OTP has 6 digits (from the Fatoora portal, valid for one hour)", 400)
    _require_crypto()
    with transaction.atomic():
        profile = _locked(org)
        if profile.onboarding != TaxProfile.ONB_KEY or not profile.csr_pem:
            raise EInvoiceError("conflict", "Generate the key and CSR first", 409)
        sim = simulated(profile)
        try:
            if sim:
                status, parsed = 200, {"requestID": 1234567890123, "dispositionMessage": "ISSUED", "binarySecurityToken": _demo_token(profile), "secret": "demo-secret-not-real"}
            else:
                csr_b64 = crypto.csr_for_api(profile.csr_pem, env("EINVOICE_ZATCA_CSR_ENCODING") or "pem_base64")
                status, parsed = zatca_api.compliance_csid(profile.environment, otp, csr_b64)
        except TransportError as exc:
            raise EInvoiceError(exc.code, exc.details, 502) from exc
        token, secret_value = parsed.get("binarySecurityToken"), parsed.get("secret")
        if status != 200 or not isinstance(token, str) or not isinstance(secret_value, str):
            message = zatca_api.messages(parsed)
            profile.onboarding_error = f"ZATCA answered {status}"[:300]
            profile.save(update_fields=["onboarding_error", "updated_at"])
            _event(org, "compliance_csid", status, "rejected", message, sim, user)
            raise EInvoiceError("rejected", f"ZATCA did not issue a compliance CSID ({status}). Check the OTP and the CSR fields.", 409, response=message)
        try:
            _store_csid(profile, "compliance", token, secret_value)
        except crypto.CryptoError as exc:
            raise EInvoiceError("invalid", str(exc), 502) from exc
        profile.compliance_request_id = str(parsed.get("requestID") or "")[:40]
        profile.onboarding = TaxProfile.ONB_COMPLIANCE
        profile.onboarding_error = ""
        profile.updated_by = user
        profile.save()
        _event(org, "compliance_csid", status, "issued", {"disposition": str(parsed.get("dispositionMessage") or "")[:40]}, sim, user)
    _audit(user, org, "einvoice.compliance_csid", profile, {"simulated": sim})
    return profile


def _sample(profile, kind, invoice_type, icv, pih):
    """A small sample document for the compliance checks."""
    now = timezone.now().astimezone(RIYADH)
    totals = money.sa_totals([money.LineIn("Compliance check item", Decimal("1"), Decimal("100.00"), Decimal("0"), "S", Decimal("15"))])
    line = totals.lines[0]
    import uuid

    data = {
        "uuid": str(uuid.uuid4()),
        "number": f"CMP-{icv:04d}",
        "issue_date": now.strftime("%Y-%m-%d"),
        "issue_time": now.strftime("%H:%M:%S"),
        "type": invoice_type,
        "kind": kind,
        "currency": "SAR",
        "icv": icv,
        "pih": pih,
        "note": "",
        "billing_reference": "CMP-0001" if kind != "invoice" else "",
        "adjustment_reason": "Compliance check adjustment" if kind != "invoice" else "",
        "payment_means": "10",
        "supply_date": now.strftime("%Y-%m-%d") if invoice_type == "standard" else None,
        "seller": {
            "name": profile.seller_name, "vat": profile.tax_number, "scheme": profile.registration_scheme or "CRN", "reg_id": profile.registration_id,
            "street": profile.street, "building": profile.building_number, "district": profile.district, "city": profile.city, "postal": profile.postal_code, "country": "SA",
        },
        "buyer": (
            {"name": "Compliance Buyer", "vat": "399999999800003", "street": "Prince Sultan", "building": "2322", "district": "Al-Murabba", "city": "Riyadh", "postal": "23333", "country": "SA"}
            if invoice_type == "standard" else {}
        ),
        "lines": [{"id": 1, "description": "Compliance check item", "quantity": Decimal("1"), "unit_price": Decimal("100.00"), "discount": Decimal("0"), "gross": line.gross, "net": line.net, "vat": line.vat, "total": line.total, "category": "S", "rate": Decimal("15"), "unit_code": "PCE"}],
        "totals": {"line_extension": totals.line_extension, "tax_exclusive": totals.tax_exclusive, "tax_total": totals.tax_total, "tax_inclusive": totals.tax_inclusive, "payable": totals.payable, "breakdown": totals.breakdown},
    }
    return data


def compliance_checks(user, org) -> TaxProfile:
    with transaction.atomic():
        profile = _locked(org)
        if profile.onboarding != TaxProfile.ONB_COMPLIANCE:
            raise EInvoiceError("conflict", "Get the compliance CSID first", 409)
        sim = simulated(profile)
        key = crypto.key_from_pem(profile.secret("private_key"))
        creds = json.loads(profile.secret("compliance"))
        types = [t for t, flag in (("standard", profile.functionality_map[:1]), ("simplified", profile.functionality_map[1:2])) if flag == "1"]
        if not types:
            raise EInvoiceError("invalid", "The invoice types must include standard or simplified (1100, 1000 or 0100)", 400)
        results, icv, pih, passed = [], 0, ubl.INITIAL_PIH, True
        for invoice_type in types:
            for kind in ("invoice", "credit", "debit"):
                icv += 1
                data = _sample(profile, kind, invoice_type, icv, pih)
                out = ubl.finalize(data, key, profile.certificate_b64, signing_time=timezone.now().astimezone(RIYADH).strftime("%Y-%m-%dT%H:%M:%S"), **qr_options())
                pih = out["hash"]
                try:
                    if sim:
                        key_name = "clearanceStatus" if invoice_type == "standard" else "reportingStatus"
                        status, parsed = 200, {key_name: "CLEARED" if invoice_type == "standard" else "REPORTED", "validationResults": {"status": "PASS"}}
                    else:
                        status, parsed = zatca_api.compliance_check(profile.environment, creds["token"], creds["secret"], out["hash"], data["uuid"], out["xml"])
                except TransportError as exc:
                    raise EInvoiceError(exc.code, exc.details, 502) from exc
                messages = zatca_api.messages(parsed)
                ok = status in (200, 202) and messages.get("status") in ("PASS", "WARNING")
                passed = passed and ok
                results.append({"type": invoice_type, "kind": kind, "http_status": status, "ok": ok, **messages})
        profile.compliance_results = results
        profile.onboarding = TaxProfile.ONB_CHECKED if passed else TaxProfile.ONB_COMPLIANCE
        profile.onboarding_error = "" if passed else "Some compliance checks failed. Fix the details and run them again."
        profile.updated_by = user
        profile.save()
        _event(org, "compliance_checks", None, "passed" if passed else "failed", {"results": [{k: r[k] for k in ("type", "kind", "http_status", "ok", "status")} for r in results]}, sim, user)
    _audit(user, org, "einvoice.compliance_checks", profile, {"passed": passed, "simulated": sim})
    return profile


def production_csid(user, org) -> TaxProfile:
    with transaction.atomic():
        profile = _locked(org)
        if profile.onboarding != TaxProfile.ONB_CHECKED:
            raise EInvoiceError("conflict", "Pass the compliance checks first", 409)
        sim = simulated(profile)
        creds = json.loads(profile.secret("compliance"))
        try:
            if sim:
                status, parsed = 200, {"requestID": 30368, "dispositionMessage": "ISSUED", "binarySecurityToken": _demo_token(profile), "secret": "demo-secret-not-real"}
            else:
                status, parsed = zatca_api.production_csid(profile.environment, creds["token"], creds["secret"], profile.compliance_request_id)
        except TransportError as exc:
            raise EInvoiceError(exc.code, exc.details, 502) from exc
        token, secret_value = parsed.get("binarySecurityToken"), parsed.get("secret")
        if status != 200 or not isinstance(token, str) or not isinstance(secret_value, str):
            _event(org, "production_csid", status, "rejected", zatca_api.messages(parsed), sim, user)
            raise EInvoiceError("rejected", f"ZATCA did not issue the production CSID ({status})", 409)
        try:
            _store_csid(profile, "production", token, secret_value)
        except crypto.CryptoError as exc:
            raise EInvoiceError("invalid", str(exc), 502) from exc
        profile.onboarding = TaxProfile.ONB_PRODUCTION
        profile.onboarding_error = ""
        profile.updated_by = user
        profile.save()
        _event(org, "production_csid", status, "issued", {"disposition": str(parsed.get("dispositionMessage") or "")[:40]}, sim, user)
    _audit(user, org, "einvoice.production_csid", profile, {"simulated": sim})
    return profile


def reset(user, org) -> TaxProfile:
    """Wipe the key and CSIDs (the counter and hash chain stay: they belong to the EGS unit)."""
    with transaction.atomic():
        profile = _locked(org)
        for field in ("private_key", "compliance", "production"):
            profile.set_secret(field, None)
        profile.csr_pem = ""
        profile.certificate_b64 = ""
        profile.certificate_expires_at = None
        profile.compliance_request_id = ""
        profile.compliance_results = []
        profile.onboarding = TaxProfile.ONB_NONE
        profile.onboarding_error = ""
        profile.updated_by = user
        profile.save()
    _audit(user, org, "einvoice.onboarding_reset", profile)
    return profile


def eta_check(user, org) -> dict:
    """Ask the ETA for a token with the saved credentials. Writes nothing outside FloBrain."""
    profile = profile_for(org, "EG")
    if profile is None or not (profile.client_id and profile.has_secret("client_secret")):
        raise EInvoiceError("incomplete", "Add the ETA client id and secret first", 409)
    if simulated(profile):
        return {"ok": True, "simulated": True}
    try:
        eta_api.token(profile.environment, profile.client_id, profile.secret("client_secret"))
    except TransportError as exc:
        _event(org, "token_check", None, "failed", {"error": exc.details}, False, user, country="EG")
        return {"ok": False, "error": exc.details}
    _event(org, "token_check", 200, "ok", {}, False, user, country="EG")
    return {"ok": True, "simulated": False}


def expires_soon(profile) -> bool:
    return bool(profile.certificate_expires_at and profile.certificate_expires_at <= timezone.now() + timedelta(days=30))
