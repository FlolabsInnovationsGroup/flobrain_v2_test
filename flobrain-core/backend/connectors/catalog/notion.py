"""Notion read connector (spec 8.4): masterclasses from one Notion database.

Auth is a Notion *internal integration* token (Settings > Connections > Develop or manage
integrations > New integration > Internal), shared with the masterclass database. No OAuth app.
FloBrain makes every call itself through ``platform_api.net.fetch`` (pinned, https, no redirects);
the model never talks to Notion.

Config:
- ``database_id``: the database id, or its Notion link.
- ``audience_property`` (optional, Q6): a people, select or multi-select property that names who a
  masterclass is for. People match by email, select values match team names. Empty: everyone.

Each page becomes an ``ExternalItem`` (kind ``masterclass``) with its title, link, status and last
edit time. Only the audience values are kept in ``meta`` (no page content, Q6).
"""

import json
import re
from datetime import datetime

from connectors.sdk import Connector, ConnectorError, register
from platform_api import net

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
TOKEN = re.compile(r"^(secret_|ntn_)[A-Za-z0-9_-]{20,200}$")
HEX32 = re.compile(r"[0-9a-fA-F]{32}")
AUDIENCE_TYPES = ("people", "select", "multi_select")
PAGE_URL = re.compile(r"^https://(www\.)?notion\.so/|^https://[a-z0-9-]+\.notion\.site/")
MAX_PAGES = 10  # 10 x 100 rows per sync (the sync job keeps at most 1000 items)


def database_id(raw) -> str:
    """A dashed uuid from a raw id, a dashed id or a Notion link (the path, never the ?v= view id)."""
    text = str(raw or "").strip()
    if text.startswith("https://"):
        text = text.split("?", 1)[0].split("#", 1)[0]
    found = HEX32.findall(text.replace("-", ""))
    if not found or len(text) > 300:
        raise ConnectorError("invalid", "database_id must be a Notion database id or link")
    h = found[-1].lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _call(method, path, token, body=None):
    try:
        status, data = net.fetch(
            method,
            API + path,
            body=json.dumps(body).encode() if body is not None else b"",
            headers={"Authorization": f"Bearer {token}", "Notion-Version": VERSION, "Content-Type": "application/json", "User-Agent": "FloBrain"},
            max_bytes=4 * 1024 * 1024,
        )
    except (net.UnsafeURL, OSError) as exc:
        raise ConnectorError("unreachable", "Notion could not be reached") from exc
    if status == 401:
        raise ConnectorError("invalid_credential", "Notion refused the token")
    if status in (403, 404):
        raise ConnectorError("not_found", "Database not found. Share it with the integration (••• > Connections)")
    if status == 429:
        raise ConnectorError("rate_limited", "Notion is rate limiting. Try again in a minute")
    if status != 200:
        raise ConnectorError("provider_error", f"Notion answered {status}")
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConnectorError("provider_error", "Notion sent something unexpected") from exc


def _plain(rich) -> str:
    if not isinstance(rich, list):
        return ""
    return "".join(str(part.get("plain_text") or "") for part in rich if isinstance(part, dict)).strip()


def _audience(prop) -> list:
    if not isinstance(prop, dict):
        return []
    kind = prop.get("type")
    if kind == "people":
        out = []
        for person in prop.get("people") or []:
            email = ((person or {}).get("person") or {}).get("email") if isinstance(person, dict) else None
            if isinstance(email, str) and "@" in email:
                out.append(email.strip().lower()[:200])
        return out
    if kind == "select":
        name = (prop.get("select") or {}).get("name") if isinstance(prop.get("select"), dict) else None
        return [str(name).strip().lower()[:100]] if name else []
    if kind == "multi_select":
        return [str(o.get("name")).strip().lower()[:100] for o in prop.get("multi_select") or [] if isinstance(o, dict) and o.get("name")]
    return []


def _status(prop) -> str:
    if not isinstance(prop, dict):
        return ""
    value = prop.get(prop.get("type") or "")
    if isinstance(value, dict) and value.get("name"):
        return str(value["name"])[:24]
    return ""


def _when(text):
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def page_item(page, config) -> dict | None:
    if not isinstance(page, dict) or page.get("object") != "page" or page.get("archived") or page.get("in_trash"):
        return None
    props = page.get("properties") if isinstance(page.get("properties"), dict) else {}
    title = next((_plain(p.get("title")) for p in props.values() if isinstance(p, dict) and p.get("type") == "title"), "")
    url = str(page.get("url") or "")
    audience_prop = config.get("audience_property") or ""
    status_prop = config.get("status_property") or ""
    return {
        "kind": "masterclass",
        "external_id": str(page.get("id") or "")[:128],
        "title": (title or "Untitled")[:300],
        "url": url if PAGE_URL.match(url) else "",
        "state": _status(props.get(status_prop)) if status_prop else "",
        "meta": {"audience": _audience(props.get(audience_prop))} if audience_prop else {},
        "external_updated_at": _when(page.get("last_edited_time")),
    }


class Notion(Connector):
    def _clean(self, config):
        config = config or {}
        audience = str(config.get("audience_property") or "").strip()[:100]
        return {"database_id": database_id(config.get("database_id")), "audience_property": audience}

    def validate(self, secret, config):
        clean = self._clean(config)
        if not secret or not TOKEN.match(secret.strip()):
            raise ConnectorError("invalid", "Paste the internal integration token (it starts with ntn_ or secret_)")
        db = _call("GET", f"/databases/{clean['database_id']}", secret.strip())
        if not isinstance(db, dict) or db.get("object") != "database":
            raise ConnectorError("not_found", "That id is not a database")
        props = db.get("properties") if isinstance(db.get("properties"), dict) else {}
        if clean["audience_property"]:
            prop = props.get(clean["audience_property"])
            if not isinstance(prop, dict):
                raise ConnectorError("invalid", f"The database has no property called {clean['audience_property']}")
            if prop.get("type") not in AUDIENCE_TYPES:
                raise ConnectorError("invalid", "The audience property must be a person, select or multi-select property")
            clean["audience_type"] = prop["type"]
        status = next((name for name, p in props.items() if isinstance(p, dict) and p.get("type") == "status"), "")
        status = status or ("Status" if isinstance(props.get("Status"), dict) and props["Status"].get("type") == "select" else "")
        clean["status_property"] = status[:100]
        clean["database_title"] = _plain(db.get("title"))[:200]
        return clean

    def sync(self, connection, secret):
        config = connection.config or {}
        db = database_id(config.get("database_id"))
        items, cursor = [], None
        for _ in range(MAX_PAGES):
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            data = _call("POST", f"/databases/{db}/query", secret.strip(), body)
            data = data if isinstance(data, dict) else {}
            for page in data.get("results") if isinstance(data.get("results"), list) else []:
                item = page_item(page, config)
                if item and item["external_id"]:
                    items.append(item)
            cursor = data.get("next_cursor") if data.get("has_more") else None
            if not cursor:
                break
        else:
            # More than MAX_PAGES pages: the list is partial, so nothing may be pruned.
            raise ConnectorError("too_many", f"The database has more than {MAX_PAGES * 100} pages")
        return items

    def validate_offline(self, config):
        return self._clean(config)

    def demo_items(self, connection):
        """Demo mode only: canned masterclasses, no network call. The audience is the Team property."""
        rows = (
            ("Git workflow at Nile Labs", "Published", ["engineering"]),
            ("Mobile release checklist", "Published", ["engineering"]),
            ("Design critique basics", "Published", ["design"]),
            ("Figma handoff for developers", "Published", ["design", "engineering"]),
            ("Writing good tickets", "Published", []),
            ("Giving feedback in 1:1s", "Draft", []),
        )
        audience = bool(connection.config.get("audience_property"))
        return [
            {
                "kind": "masterclass",
                "external_id": f"demo-masterclass-{i}",
                "title": title,
                "url": f"https://example.com/demo-notion/masterclass-{i}",
                "state": state,
                "meta": {"audience": teams} if audience else {},
                "external_updated_at": None,
            }
            for i, (title, state, teams) in enumerate(rows, start=1)
        ]


register(
    Notion(
        key="notion",
        name="Notion",
        description="Masterclasses from a Notion database, shown in Learning.",
        prunes=True,
        config_fields=[
            {"name": "database_id", "label": "Masterclass database", "hint": "The database id or its Notion link"},
            {
                "name": "audience_property",
                "label": "Audience property (optional)",
                "hint": "A person, select or multi-select property such as Team. Leave empty to show every masterclass to everyone.",
                "optional": True,
            },
        ],
        token_hint="A Notion internal integration token (starts with ntn_). Share the database with that integration first. It is stored encrypted and never shown again.",
    )
)
