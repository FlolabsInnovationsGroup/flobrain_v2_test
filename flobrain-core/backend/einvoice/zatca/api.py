"""ZATCA Fatoora API client (onboarding, compliance checks, clearance, reporting).

Base URLs (configurable; must stay on the allowlist in ``einvoice.transport``):
- developer portal (sandbox): https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal
- simulation: https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation
- production: https://gw-fatoora.zatca.gov.sa/e-invoicing/core
Override with ``EINVOICE_ZATCA_BASE_SANDBOX`` / ``_SIMULATION`` / ``_PRODUCTION`` if ZATCA moves
them (ZATCA's developer community notes URLs have changed before).

Endpoints (ZATCA developer community "E-Invoicing API endpoints"; Fatoora developer portal):
- POST /compliance                 OTP header, {"csr": Base64 CSR} -> compliance CSID
- POST /compliance/invoices        Basic auth (compliance CSID), {invoiceHash, uuid, invoice}
- POST /production/csids           Basic auth (compliance CSID), {"compliance_request_id"}
- POST /invoices/clearance/single  Basic auth (production CSID), header Clearance-Status: 1
- POST /invoices/reporting/single  Basic auth (production CSID)
Every call sends ``Accept-Version: V2`` and ``Accept-Language: en``. Basic auth is
``binarySecurityToken:secret``. The invoice is the Base64 of the signed XML.
HTTP 200 accepted, 202 accepted with warnings, 400 rejected, 401 bad credentials, others error.
"""

import base64
import json

from einvoice import transport

DEFAULT_BASES = {
    "sandbox": "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal",
    "simulation": "https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation",
    "production": "https://gw-fatoora.zatca.gov.sa/e-invoicing/core",
}


def base_url(environment: str) -> str:
    if environment not in DEFAULT_BASES:
        raise transport.TransportError("invalid", "Pick the sandbox, simulation or production environment")
    return (transport.env(f"EINVOICE_ZATCA_BASE_{environment.upper()}") or DEFAULT_BASES[environment]).rstrip("/")


def _headers(extra=None) -> dict:
    out = {"Accept-Version": "V2", "Accept-Language": "en", "Content-Type": "application/json"}
    out.update(extra or {})
    return out


def _basic(token: str, secret: str) -> dict:
    raw = f"{token}:{secret}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def _post(url: str, body: dict, headers: dict) -> tuple[int, dict]:
    status, parsed = transport.request("zatca", "POST", url, body=json.dumps(body).encode("utf-8"), headers=headers)
    return status, parsed if isinstance(parsed, dict) else {}


def compliance_csid(environment: str, otp: str, csr_b64: str) -> tuple[int, dict]:
    return _post(f"{base_url(environment)}/compliance", {"csr": csr_b64}, _headers({"OTP": otp}))


def compliance_check(environment: str, token: str, secret: str, invoice_hash: str, uuid: str, xml: str) -> tuple[int, dict]:
    body = {"invoiceHash": invoice_hash, "uuid": uuid, "invoice": base64.b64encode(xml.encode("utf-8")).decode("ascii")}
    return _post(f"{base_url(environment)}/compliance/invoices", body, _headers(_basic(token, secret)))


def production_csid(environment: str, token: str, secret: str, request_id: str) -> tuple[int, dict]:
    return _post(f"{base_url(environment)}/production/csids", {"compliance_request_id": request_id}, _headers(_basic(token, secret)))


def clearance(environment: str, token: str, secret: str, invoice_hash: str, uuid: str, xml: str) -> tuple[int, dict]:
    body = {"invoiceHash": invoice_hash, "uuid": uuid, "invoice": base64.b64encode(xml.encode("utf-8")).decode("ascii")}
    return _post(f"{base_url(environment)}/invoices/clearance/single", body, _headers({**_basic(token, secret), "Clearance-Status": "1"}))


def reporting(environment: str, token: str, secret: str, invoice_hash: str, uuid: str, xml: str) -> tuple[int, dict]:
    body = {"invoiceHash": invoice_hash, "uuid": uuid, "invoice": base64.b64encode(xml.encode("utf-8")).decode("ascii")}
    return _post(f"{base_url(environment)}/invoices/reporting/single", body, _headers(_basic(token, secret)))


def messages(parsed: dict) -> dict:
    """Validation messages only (code, category, message), at most 20 of each kind."""
    results = parsed.get("validationResults") if isinstance(parsed.get("validationResults"), dict) else {}
    out = {"status": str(results.get("status") or "")[:20]}
    for key in ("errorMessages", "warningMessages", "infoMessages"):
        rows = results.get(key) if isinstance(results.get(key), list) else []
        out[key] = [
            {k: str(row.get(k) or "")[:300] for k in ("type", "code", "category", "message", "status")}
            for row in rows[:20]
            if isinstance(row, dict)
        ]
    errors = parsed.get("errors")
    if isinstance(errors, list) and errors:
        out["errors"] = [str(e)[:300] if not isinstance(e, dict) else {k: str(v)[:300] for k, v in list(e.items())[:5]} for e in errors[:10]]
    return out


def outcome(status: int, parsed: dict, mode: str) -> str:
    """accepted | rejected | error for a clearance or reporting answer."""
    key = "clearanceStatus" if mode == "clearance" else "reportingStatus"
    value = str(parsed.get(key) or "").upper()
    if status in (200, 202) and value in ("CLEARED", "REPORTED"):
        return "accepted"
    if status in (400, 200, 202) and value.startswith("NOT_"):
        return "rejected"
    if status == 400:
        return "rejected"
    return "error"
