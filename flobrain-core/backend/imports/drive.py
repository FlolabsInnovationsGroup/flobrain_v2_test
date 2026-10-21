"""Google Drive files as FloBrain Documents, through the Google Workspace write connection (W4).

The connection must have a Drive read scope (``drive.readonly`` or ``drive``). The Google
provider asks only for ``drive.file`` today, which cannot list other files, so until the read
scope is added (see docs/v2/features/IMPORTS.md) a real connection shows "needs Drive read
access" and people use a Google Takeout ZIP or file uploads instead.

- Google Docs are exported as Markdown (plain text when Markdown export is refused).
- DOCX is read by ``imports.textract``; PDF needs ``pypdf`` (reported when missing).
- Only ``www.googleapis.com`` is called (the provider's allowlist), through
  ``platform_api.net.fetch_full`` (public IPs only, pinned, no redirects). A 401 refreshes the
  token once. File size is capped by ``IMPORTS_DRIVE_MAX_FILE_MB`` (default 20).
- Demo connections never reach the network: they list and return canned files.
"""

import json
import re
import urllib.parse

from django.conf import settings

from imports import textract

DRIVE = "https://www.googleapis.com/drive/v3/files"
READ_SCOPES = {"drive.readonly", "drive"}
GDOC = "application/vnd.google-apps.document"
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_TYPES = {"text/plain": "txt", "text/markdown": "md", "text/csv": "csv", "text/html": "html"}
IMPORTABLE = (GDOC, PDF, DOCX, *TEXT_TYPES)
FILE_ID = re.compile(r"^[A-Za-z0-9_-]{10,100}$")
PAGE_TOKEN = re.compile(r"^[A-Za-z0-9_\-.~=+/]{1,500}$")
TIMEOUT = 30


class DriveError(Exception):
    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code
        self.details = details or code


def max_file_bytes() -> int:
    return int(getattr(settings, "IMPORTS_DRIVE_MAX_FILE_MB", 20)) * 1024 * 1024


def provider():
    from integrations.write import registry

    return registry.get("google_workspace")


def has_read_scope(conn) -> bool:
    from integrations.write.registry import normalize_scope

    return bool({normalize_scope(s) for s in conn.scopes or []} & READ_SCOPES)


def connection(user, org):
    """(connection or None, status, message). status: ready | needs_scope | not_connected."""
    prov = provider()
    if prov is None:
        return None, "not_connected", "Google Workspace is not available on this server"
    from integrations.write.connections import connection_for

    conn, reason = connection_for(user, org, prov)
    if conn is None:
        return None, "not_connected", reason
    if not conn.demo and not has_read_scope(conn):
        return None, "needs_scope", "Your Google connection can't read Drive yet. Reconnect it with Drive read access, or upload files instead"
    return conn, "ready", ""


def _fetch(method: str, url: str, headers: dict, max_bytes: int):
    """The network boundary (mocked in tests)."""
    from platform_api import net

    status, _headers, data = net.fetch_full(method, url, b"", headers, timeout=TIMEOUT, max_bytes=max_bytes)
    return status, data


def _get(conn, url: str, max_bytes: int) -> tuple[int, bytes]:
    from integrations.write import transport
    from platform_api import net

    prov = provider()
    transport.check_url(prov, url, conn)
    client = transport.Client(prov, conn)
    status, data = 0, b""
    for attempt in (0, 1):
        try:
            token = client.token()
        except transport.WriteError as exc:
            raise DriveError("expired", exc.details) from exc
        try:
            status, data = _fetch("GET", url, {**prov.auth_header(token), "User-Agent": "FloBrain"}, max_bytes + 1)
        except net.UnsafeURL as exc:
            raise DriveError("blocked_host", "That address is not allowed") from exc
        except OSError as exc:
            raise DriveError("unreachable", "Google Drive could not be reached") from exc
        if status == 401 and attempt == 0 and conn.refresh_ciphertext:
            try:
                transport.refresh(prov, conn)
            except transport.WriteError as exc:
                raise DriveError("expired", exc.details) from exc
            continue
        break
    if status == 401:
        raise DriveError("expired", "Google refused the token. Connect Google Workspace again")
    if status == 403:
        raise DriveError("forbidden", "Google Drive refused access to this file")
    if status == 404:
        raise DriveError("not_found", "File not found in Google Drive")
    if status == 429:
        raise DriveError("rate_limited", "Google Drive is rate limiting. Try again in a minute")
    if len(data) > max_bytes:
        raise DriveError("too_big", f"The file is bigger than {max_bytes // (1024 * 1024)} MB")
    return status, data


def _json(conn, url: str) -> dict:
    status, data = _get(conn, url, 2 * 1024 * 1024)
    if status != 200:
        raise DriveError("provider_error", f"Google Drive answered {status}")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise DriveError("provider_error", "Google Drive sent something unexpected") from exc
    return parsed if isinstance(parsed, dict) else {}


def _file_row(f: dict) -> dict | None:
    if not isinstance(f, dict) or not FILE_ID.match(str(f.get("id") or "")):
        return None
    mime = str(f.get("mimeType") or "")
    if mime not in IMPORTABLE:
        return None
    try:
        size = int(f.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    link = str(f.get("webViewLink") or "")
    return {
        "id": f["id"],
        "name": str(f.get("name") or "Untitled")[:200],
        "mime_type": mime,
        "kind": {GDOC: "google_doc", PDF: "pdf", DOCX: "docx"}.get(mime, TEXT_TYPES.get(mime, "file")),
        "size": size,
        "modified": str(f.get("modifiedTime") or "")[:40],
        "url": link if link.startswith("https://") else f"https://drive.google.com/file/d/{f['id']}/view",
        "too_big": size > max_file_bytes(),
        "supported": mime != PDF or textract.pdf_supported(),
    }


def list_files(conn, query: str = "", page_token: str = "") -> dict:
    if conn.demo:
        return {"files": [_file_row(f) for f in DEMO_FILES if not query or query.lower() in f["name"].lower()], "next_page_token": ""}
    clauses = ["trashed = false", "(" + " or ".join(f"mimeType = '{m}'" for m in IMPORTABLE) + ")"]
    if query:
        safe = query[:100].replace("\\", "\\\\").replace("'", "\\'")
        clauses.append(f"name contains '{safe}'")
    params = {
        "q": " and ".join(clauses),
        "pageSize": "100",
        "orderBy": "modifiedTime desc",
        "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,webViewLink)",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    if page_token:
        if not PAGE_TOKEN.match(page_token):
            raise DriveError("invalid", "Bad page token")
        params["pageToken"] = page_token
    data = _json(conn, f"{DRIVE}?{urllib.parse.urlencode(params)}")
    rows = [_file_row(f) for f in data.get("files") or [] if isinstance(data.get("files"), list)]
    token = str(data.get("nextPageToken") or "")
    return {"files": [r for r in rows if r], "next_page_token": token if PAGE_TOKEN.match(token or "-") and token else ""}


def file_meta(conn, file_id: str) -> dict:
    if not FILE_ID.match(file_id or ""):
        raise DriveError("invalid", "Not a Google Drive file id")
    if conn.demo:
        row = next((f for f in DEMO_FILES if f["id"] == file_id), None)
        if row is None:
            raise DriveError("not_found", "File not found in Google Drive")
        return _file_row(row)
    data = _json(conn, f"{DRIVE}/{file_id}?{urllib.parse.urlencode({'fields': 'id,name,mimeType,size,modifiedTime,webViewLink', 'supportsAllDrives': 'true'})}")
    row = _file_row(data)
    if row is None:
        raise DriveError("unsupported", "This file type can't be imported")
    return row


def file_text(conn, meta: dict) -> str:
    """The text of one file (``meta`` from ``file_meta``). Raises DriveError or textract.ExtractError."""
    if meta["too_big"]:
        raise DriveError("too_big", f"The file is bigger than {max_file_bytes() // (1024 * 1024)} MB")
    if conn.demo:
        return textract.cap(DEMO_TEXT.get(meta["id"], ""))
    fid = meta["id"]
    if meta["mime_type"] == GDOC:
        for export in ("text/markdown", "text/plain"):
            status, data = _get(conn, f"{DRIVE}/{fid}/export?{urllib.parse.urlencode({'mimeType': export})}", max_file_bytes())
            if status == 200:
                return textract.cap(data.decode("utf-8-sig", errors="replace"))
        raise DriveError("provider_error", "Google Drive could not export this document")
    status, data = _get(conn, f"{DRIVE}/{fid}?{urllib.parse.urlencode({'alt': 'media', 'supportsAllDrives': 'true'})}", max_file_bytes())
    if status != 200:
        raise DriveError("provider_error", f"Google Drive answered {status}")
    ext = {PDF: "pdf", DOCX: "docx"}.get(meta["mime_type"]) or TEXT_TYPES.get(meta["mime_type"], "txt")
    return textract.extract(f"file.{ext}", data)


# --- demo -----------------------------------------------------------------------------------

DEMO_FILES = [
    {"id": "demo-drive-doc-0001", "name": "Q4 plan (demo)", "mimeType": GDOC, "modifiedTime": "2026-10-01T09:00:00Z", "webViewLink": "https://docs.google.com/document/d/demo-drive-doc-0001/edit"},
    {"id": "demo-drive-doc-0002", "name": "Support playbook (demo)", "mimeType": GDOC, "modifiedTime": "2026-09-20T09:00:00Z", "webViewLink": "https://docs.google.com/document/d/demo-drive-doc-0002/edit"},
    {"id": "demo-drive-docx-0003", "name": "Office handbook (demo).docx", "mimeType": DOCX, "size": "48213", "modifiedTime": "2026-08-12T09:00:00Z"},
    {"id": "demo-drive-pdf-00004", "name": "Supplier contract (demo).pdf", "mimeType": PDF, "size": "220431", "modifiedTime": "2026-07-03T09:00:00Z"},
]
DEMO_TEXT = {
    "demo-drive-doc-0001": "# Q4 plan\n\nDemo data.\n\n## Goals\n- Ship the mobile app to the stores\n- Two new customers in Cairo\n- Cut support first response to 4 hours\n\n## Owners\nLayla: mobile. Omar: sales. Nadia: support.",
    "demo-drive-doc-0002": "# Support playbook\n\nDemo data.\n\n## First reply\nAnswer within 4 hours on working days. Say who you are and what happens next.\n\n## Escalation\nBilling problems go to Omar. Outages go to Layla.",
    "demo-drive-docx-0003": "# Office handbook\n\nDemo data.\n\n- Office hours: Sunday to Thursday, 9:00 to 17:00\n- Guests sign in at reception\n- Book meeting rooms in the shared calendar",
    "demo-drive-pdf-00004": "Supplier contract (demo). Term: 12 months. Notice period: 60 days. Payment: 30 days after invoice.",
}
