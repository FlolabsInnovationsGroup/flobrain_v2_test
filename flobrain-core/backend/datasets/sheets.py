"""Google Sheets through a "Publish to the web" CSV link (no Google sign-in, no tokens).

Only ``https://docs.google.com/spreadsheets/d/e/<id>/pub?output=csv`` links are accepted (optional
``gid`` and ``single``). The fetch goes through ``platform_api.net`` (public addresses only, pinned
connection, no automatic redirects, size cap). Google answers with one redirect to
``*.googleusercontent.com``; that one hop is followed only to that domain over https.
"""

import re
import urllib.parse

from datasets.ingest import IngestError, max_bytes

HOST = "docs.google.com"
PATH_RE = re.compile(r"^/spreadsheets/d/e/[A-Za-z0-9_-]{20,200}/pub$")
REDIRECT_SUFFIX = ".googleusercontent.com"
ALLOWED_QUERY = {"output", "gid", "single"}


class SheetError(ValueError):
    def __init__(self, code, details):
        super().__init__(details)
        self.code, self.details = code, details


def normalize_url(url: str) -> str:
    """Return the canonical CSV link or raise SheetError."""
    bad = SheetError(
        "invalid_url",
        "Use the link from File, Share, Publish to the web, with the CSV format selected",
    )
    if not isinstance(url, str) or len(url) > 500:
        raise bad
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        port = parsed.port
    except ValueError as exc:
        raise bad from exc
    if parsed.scheme != "https" or parsed.hostname != HOST or port not in (None, 443):
        raise bad
    if parsed.username or parsed.password or parsed.fragment:
        raise bad
    if not PATH_RE.match(parsed.path):
        raise bad
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if set(query) - ALLOWED_QUERY or query.get("output") != ["csv"]:
        raise bad
    if "gid" in query and not re.fullmatch(r"\d{1,12}", query["gid"][0]):
        raise bad
    if "single" in query and query["single"][0] not in ("true", "false"):
        raise bad
    clean = [("output", "csv")] + [(k, query[k][0]) for k in ("gid", "single") if k in query]
    return urllib.parse.urlunsplit(("https", HOST, parsed.path, urllib.parse.urlencode(clean), ""))


def _redirect_ok(location: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(location)
    except ValueError:
        return False
    host = parsed.hostname or ""
    return parsed.scheme == "https" and host.endswith(REDIRECT_SUFFIX) and not parsed.username and parsed.port in (None, 443)


def fetch_csv(url: str) -> bytes:
    """Download the published CSV. Raises SheetError."""
    from platform_api.net import UnsafeURL, fetch_full

    url = normalize_url(url)
    limit = max_bytes() + 1
    try:
        status, headers, body = fetch_full("GET", url, headers={"Accept": "text/csv"}, timeout=15, max_bytes=limit)
        if status in (301, 302, 303, 307, 308):
            location = headers.get("location", "")
            if not _redirect_ok(location):
                raise SheetError("fetch_failed", "The sheet link redirected somewhere unexpected")
            status, headers, body = fetch_full("GET", location, headers={"Accept": "text/csv"}, timeout=15, max_bytes=limit)
    except UnsafeURL as exc:
        raise SheetError("fetch_failed", "The sheet could not be reached safely") from exc
    except OSError as exc:
        raise SheetError("fetch_failed", "The sheet could not be downloaded. Try again later.") from exc
    if status != 200:
        raise SheetError("fetch_failed", f"Google answered {status}. Check that the sheet is still published.")
    if "text/html" in headers.get("content-type", ""):
        raise SheetError("not_published", "That link is not published as CSV. Publish the sheet to the web as CSV.")
    if len(body) >= limit:
        raise IngestError("too_large", f"The sheet is larger than {max_bytes() // (1024 * 1024)} MB")
    return body
