"""ETA (Egyptian Tax Authority) e-invoicing API client.

Hosts (allowlisted in ``einvoice.transport``):
- identity: https://id.eta.gov.eg (production), https://id.preprod.eta.gov.eg (pre-production)
- API: https://api.invoicing.eta.gov.eg, https://api.preprod.invoicing.eta.gov.eg
Paths (ETA SDK, sdk.invoicing.eta.gov.eg):
- POST /connect/token  form grant_type=client_credentials, client_id, client_secret,
  scope=InvoicingAPI -> {"access_token", "expires_in"} (tokens last about an hour)
- POST /api/v1.0/documentsubmissions/  {"documents": [...]} -> 202 {submissionUUID|submissionId,
  acceptedDocuments [{uuid, longId, internalId}], rejectedDocuments [{internalId, error}]};
  422 DuplicateSubmission for an identical payload within 10 minutes (Retry-After header)
- GET  /api/v1.0/documentsubmissions/{uuid}?pageNo=1&pageSize=10 -> {overallStatus,
  documentSummary [{uuid, internalId, status: submitted|valid|invalid|rejected|cancelled}]}
Some ETA examples send the client id and secret as HTTP Basic instead of form fields;
``EINVOICE_ETA_TOKEN_AUTH=basic`` switches to that.
"""

import base64
import urllib.parse

from einvoice import transport

HOSTS = {
    "preprod": ("https://id.preprod.eta.gov.eg", "https://api.preprod.invoicing.eta.gov.eg"),
    "production": ("https://id.eta.gov.eg", "https://api.invoicing.eta.gov.eg"),
}


def bases(environment: str) -> tuple[str, str]:
    if environment not in HOSTS:
        raise transport.TransportError("invalid", "Pick the pre-production or production environment")
    idp, api = HOSTS[environment]
    return (
        (transport.env(f"EINVOICE_ETA_ID_{environment.upper()}") or idp).rstrip("/"),
        (transport.env(f"EINVOICE_ETA_API_{environment.upper()}") or api).rstrip("/"),
    )


def token(environment: str, client_id: str, client_secret: str) -> str:
    idp, _ = bases(environment)
    form = {"grant_type": "client_credentials", "scope": "InvoicingAPI"}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if transport.env("EINVOICE_ETA_TOKEN_AUTH").lower() == "basic":
        headers["Authorization"] = "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    else:
        form.update({"client_id": client_id, "client_secret": client_secret})
    status, parsed = transport.request("eta", "POST", f"{idp}/connect/token", body=urllib.parse.urlencode(form).encode(), headers=headers)
    access = parsed.get("access_token") if isinstance(parsed, dict) else None
    if status != 200 or not isinstance(access, str) or not access:
        raise transport.TransportError("auth_failed", f"The ETA did not accept the client id and secret ({status})")
    return access


def submit(environment: str, access_token: str, document_json: str) -> tuple[int, dict]:
    _, api = bases(environment)
    body = ('{"documents":[' + document_json + "]}").encode("utf-8")
    status, parsed = transport.request(
        "eta", "POST", f"{api}/api/v1.0/documentsubmissions/", body=body,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=utf-8"},
    )
    return status, parsed if isinstance(parsed, dict) else {}


def submission(environment: str, access_token: str, submission_uuid: str) -> tuple[int, dict]:
    _, api = bases(environment)
    safe = urllib.parse.quote(submission_uuid, safe="")
    status, parsed = transport.request(
        "eta", "GET", f"{api}/api/v1.0/documentsubmissions/{safe}?pageNo=1&pageSize=10",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    return status, parsed if isinstance(parsed, dict) else {}


def short_error(error) -> dict:
    if not isinstance(error, dict):
        return {"message": str(error)[:300]}
    out = {k: str(error.get(k) or "")[:300] for k in ("code", "message", "target") if error.get(k)}
    details = error.get("details")
    if isinstance(details, list):
        out["details"] = [short_error(d) for d in details[:10]]
    return out


def submission_outcome(parsed: dict) -> dict:
    accepted = parsed.get("acceptedDocuments") if isinstance(parsed.get("acceptedDocuments"), list) else []
    rejected = parsed.get("rejectedDocuments") if isinstance(parsed.get("rejectedDocuments"), list) else []
    first = accepted[0] if accepted and isinstance(accepted[0], dict) else {}
    return {
        "submission": str(parsed.get("submissionUUID") or parsed.get("submissionId") or "")[:80],
        "uuid": str(first.get("uuid") or "")[:80],
        "long_id": str(first.get("longId") or "")[:80],
        "rejected": [{"internalId": str(r.get("internalId") or "")[:60], "error": short_error(r.get("error"))} for r in rejected[:5] if isinstance(r, dict)],
    }


STATUS_MAP = {"valid": "accepted", "invalid": "rejected", "rejected": "rejected", "cancelled": "rejected", "submitted": "submitted"}


def document_status(parsed: dict, internal_id: str, uuid: str = "") -> str:
    rows = parsed.get("documentSummary") if isinstance(parsed.get("documentSummary"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if (uuid and row.get("uuid") == uuid) or row.get("internalId") == internal_id:
            return str(row.get("status") or "").lower()
    return ""

