"""Notion pages and databases as FloBrain Documents.

Two ways in:

- **API**: an existing Notion connection (``connectors``, internal integration token, stored
  encrypted). We list what the integration can see (``POST /v1/search``), and for each picked page
  read its blocks; a database becomes one document with its rows as a simple table. Calls go
  through ``platform_api.net.fetch`` (https, public IPs only, no redirects) to api.notion.com only.
- **Export ZIP** ("Markdown & CSV"): pages are ``Title <32 hex id>.md``, databases
  ``Title <id>.csv`` (``_all.csv`` preferred). One level of nested ZIP (newer exports wrap the
  pages in an inner archive) is read with the same safety rules.

Both keep a link back to Notion (``https://www.notion.so/<id>``) and use the same idempotency key
(``notion:<id>``), so importing a page twice, by either route, never makes two documents.
"""

import io
import json
import re

from imports import textract
from imports.safezip import Limits, SafeZip, ZipSafetyError

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
HEX32 = re.compile(r"([0-9a-f]{32})", re.I)
NAME_ID = re.compile(r"\s+([0-9a-f]{32})(?=(_all)?\.(md|csv)$)", re.I)
MAX_BLOCK_PAGES = 20  # x 100 blocks per level
MAX_DEPTH = 3
MAX_ROWS = 500
MAX_SEARCH_PAGES = 3


class NotionError(Exception):
    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code
        self.details = details or code


def dashed(raw: str) -> str:
    h = (raw or "").replace("-", "").lower()
    if not re.fullmatch(r"[0-9a-f]{32}", h):
        raise NotionError("invalid", "Not a Notion id")
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def source_key(raw_id: str) -> str:
    return "notion:" + (raw_id or "").replace("-", "").lower()


def page_url(raw_id: str) -> str:
    return "https://www.notion.so/" + (raw_id or "").replace("-", "").lower()


# --- rich text and blocks -------------------------------------------------------------------


def rich(parts) -> str:
    out = []
    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict):
            continue
        text = str(part.get("plain_text") or "")
        href = part.get("href")
        if isinstance(href, str) and href.startswith("https://") and href not in text:
            text = f"{text} ({href})"
        out.append(text)
    return "".join(out)


def _link(block_type, value) -> str:
    if not isinstance(value, dict):
        return ""
    url = value.get("url") or ((value.get("external") or {}).get("url") if isinstance(value.get("external"), dict) else "")
    caption = rich(value.get("caption"))
    label = {"image": "Image", "video": "Video", "file": "File", "pdf": "PDF", "bookmark": "Link", "embed": "Embed", "link_preview": "Link", "audio": "Audio"}.get(block_type, "Link")
    if isinstance(url, str) and url.startswith("https://") and "secure.notion-static.com" not in url and "amazonaws.com" not in url:
        return f"[{label}: {caption or url}] ({url})"
    return f"[{label}{': ' + caption if caption else ''}]"


def block_lines(block: dict, children: list | None = None, depth: int = 0) -> list[str]:
    """One Notion block (and its already fetched children) as Markdown lines."""
    kind = block.get("type") or ""
    value = block.get(kind) if isinstance(block.get(kind), dict) else {}
    text = rich(value.get("rich_text"))
    pad = "  " * depth
    lines: list[str] = []
    if kind == "paragraph":
        lines.append(pad + text if text else "")
    elif kind in ("heading_1", "heading_2", "heading_3"):
        lines += ["", "#" * int(kind[-1]) + " " + text]
    elif kind == "bulleted_list_item":
        lines.append(f"{pad}- {text}")
    elif kind == "numbered_list_item":
        lines.append(f"{pad}1. {text}")
    elif kind == "to_do":
        lines.append(f"{pad}- [{'x' if value.get('checked') else ' '}] {text}")
    elif kind == "toggle":
        lines.append(f"{pad}- {text}")
    elif kind == "quote":
        lines.append(f"{pad}> {text}")
    elif kind == "callout":
        lines.append(f"{pad}> {text}")
    elif kind == "code":
        lines += ["```", text, "```"]
    elif kind == "divider":
        lines.append("---")
    elif kind == "equation":
        lines.append(pad + str(value.get("expression") or ""))
    elif kind == "child_page":
        lines.append(f"{pad}Subpage: {value.get('title') or 'Untitled'}")
    elif kind == "child_database":
        lines.append(f"{pad}Database: {value.get('title') or 'Untitled'}")
    elif kind in ("image", "video", "file", "pdf", "bookmark", "embed", "link_preview", "audio"):
        lines.append(pad + _link(kind, value))
    elif kind == "table_row":
        cells = value.get("cells") if isinstance(value.get("cells"), list) else []
        lines.append(pad + " | ".join(rich(c).replace("\n", " ") for c in cells))
    elif kind in ("table", "column_list", "column", "synced_block"):
        pass  # their children carry the content
    elif text:
        lines.append(pad + text)
    child_depth = depth + 1 if kind in ("bulleted_list_item", "numbered_list_item", "to_do", "toggle") else depth
    for child in children or []:
        lines += block_lines(child.get("block", child), child.get("children"), child_depth)
    if kind == "table":
        lines.append("")
    return lines


def blocks_to_markdown(tree: list) -> str:
    """``tree``: [{"block": {...}, "children": [...]}] or plain blocks. Returns tidy Markdown."""
    lines = []
    for node in tree:
        block = node.get("block", node) if isinstance(node, dict) else {}
        lines += block_lines(block, node.get("children") if isinstance(node, dict) else None)
    out, blank = [], True
    for line in lines:
        if not line.strip():
            if not blank:
                out.append("")
            blank = True
            continue
        out.append(line.rstrip())
        blank = False
    return "\n".join(out).strip()


def prop_text(prop) -> str:
    if not isinstance(prop, dict):
        return ""
    kind = prop.get("type")
    value = prop.get(kind)
    if kind in ("title", "rich_text"):
        return rich(value)
    if kind in ("select", "status"):
        return str((value or {}).get("name") or "") if isinstance(value, dict) else ""
    if kind == "multi_select":
        return ", ".join(str(o.get("name")) for o in value or [] if isinstance(o, dict) and o.get("name"))
    if kind == "people":
        return ", ".join(str(p.get("name") or "") for p in value or [] if isinstance(p, dict))
    if kind == "date":
        if not isinstance(value, dict):
            return ""
        return str(value.get("start") or "") + (f" to {value['end']}" if value.get("end") else "")
    if kind == "checkbox":
        return "Yes" if value else "No"
    if kind in ("number", "url", "email", "phone_number", "created_time", "last_edited_time"):
        return "" if value is None else str(value)
    if kind == "formula" and isinstance(value, dict):
        inner = value.get(value.get("type") or "")
        return "" if inner is None else str(inner)
    if kind == "relation":
        return f"{len(value or [])} linked"
    return ""


def title_of(obj: dict) -> str:
    if not isinstance(obj, dict):
        return "Untitled"
    if obj.get("object") == "database":
        return rich(obj.get("title")).strip() or "Untitled"
    props = obj.get("properties") if isinstance(obj.get("properties"), dict) else {}
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return rich(prop.get("title")).strip() or "Untitled"
    return "Untitled"


def rows_table(columns: list[str], rows: list[dict]) -> str:
    lines = [" | ".join(columns)]
    for row in rows[:MAX_ROWS]:
        lines.append(" | ".join(prop_text(row.get(c)).replace("\n", " ") for c in columns))
    if len(rows) > MAX_ROWS:
        lines.append(f"[{MAX_ROWS} rows shown]")
    return "\n".join(lines)


# --- API client -----------------------------------------------------------------------------


class Client:
    """A Notion API client for one token. The network boundary is ``platform_api.net.fetch``."""

    def __init__(self, token: str):
        self.token = token

    def call(self, method: str, path: str, body=None):
        from platform_api import net

        try:
            status, data = net.fetch(
                method,
                API + path,
                body=json.dumps(body).encode() if body is not None else b"",
                headers={"Authorization": f"Bearer {self.token}", "Notion-Version": VERSION, "Content-Type": "application/json", "User-Agent": "FloBrain"},
                timeout=15,
                max_bytes=8 * 1024 * 1024,
            )
        except (net.UnsafeURL, OSError) as exc:
            raise NotionError("unreachable", "Notion could not be reached") from exc
        if status == 401:
            raise NotionError("invalid_credential", "Notion refused the token. Reconnect Notion in Integrations")
        if status in (403, 404):
            raise NotionError("not_found", "Notion did not find it. Share the page with the integration (••• > Connections)")
        if status == 429:
            raise NotionError("rate_limited", "Notion is rate limiting. Try again in a minute")
        if status != 200:
            raise NotionError("provider_error", f"Notion answered {status}")
        try:
            return json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise NotionError("provider_error", "Notion sent something unexpected") from exc

    def search(self, query: str = "") -> list[dict]:
        out, cursor = [], None
        for _ in range(MAX_SEARCH_PAGES):
            body = {"page_size": 100, "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
            if query:
                body["query"] = query[:100]
            if cursor:
                body["start_cursor"] = cursor
            data = self.call("POST", "/search", body)
            for obj in data.get("results") or [] if isinstance(data, dict) else []:
                if not isinstance(obj, dict) or obj.get("object") not in ("page", "database") or obj.get("archived") or obj.get("in_trash"):
                    continue
                if not HEX32.fullmatch(str(obj.get("id") or "").replace("-", "")):
                    continue
                out.append({
                    "id": str(obj["id"]).replace("-", "").lower(),
                    "type": obj["object"],
                    "title": title_of(obj)[:200],
                    "url": page_url(obj["id"]),
                    "last_edited": str(obj.get("last_edited_time") or "")[:40],
                })
            cursor = data.get("next_cursor") if isinstance(data, dict) and data.get("has_more") else None
            if not cursor:
                break
        return out

    def children(self, block_id: str, depth: int = 0) -> list:
        tree, cursor = [], None
        for _ in range(MAX_BLOCK_PAGES):
            path = f"/blocks/{dashed(block_id)}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
            data = self.call("GET", path)
            for block in data.get("results") or [] if isinstance(data, dict) else []:
                if not isinstance(block, dict):
                    continue
                kids = None
                if block.get("has_children") and depth < MAX_DEPTH and block.get("type") not in ("child_page", "child_database"):
                    kids = self.children(str(block.get("id") or ""), depth + 1)
                tree.append({"block": block, "children": kids})
            cursor = data.get("next_cursor") if isinstance(data, dict) and data.get("has_more") else None
            if not cursor or not re.fullmatch(r"[0-9a-fA-F-]{32,36}", str(cursor)):
                break
        return tree

    def page_document(self, page_id: str) -> tuple[str, str]:
        page = self.call("GET", f"/pages/{dashed(page_id)}")
        title = title_of(page)
        props = page.get("properties") if isinstance(page.get("properties"), dict) else {}
        facts = [f"{name}: {prop_text(p)}" for name, p in props.items() if isinstance(p, dict) and p.get("type") != "title" and prop_text(p)]
        body = blocks_to_markdown(self.children(page_id))
        return title, "\n".join(facts[:30]) + ("\n\n" if facts else "") + body

    def database_document(self, database_id: str) -> tuple[str, str]:
        db = self.call("GET", f"/databases/{dashed(database_id)}")
        title = title_of(db)
        props = db.get("properties") if isinstance(db.get("properties"), dict) else {}
        columns = sorted(props, key=lambda n: (props[n].get("type") != "title", n))[:20] if props else []
        rows, cursor = [], None
        for _ in range(MAX_ROWS // 100):
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            data = self.call("POST", f"/databases/{dashed(database_id)}/query", body)
            for row in data.get("results") or [] if isinstance(data, dict) else []:
                if isinstance(row, dict) and isinstance(row.get("properties"), dict):
                    rows.append(row["properties"])
            cursor = data.get("next_cursor") if isinstance(data, dict) and data.get("has_more") else None
            if not cursor:
                break
        return title, rows_table(columns, rows)


# --- export ZIP -----------------------------------------------------------------------------

MAX_INNER = 10
INNER_LIMITS = Limits(max_files=20000, max_total=2 * 1024**3, max_member=200 * 1024**2, max_ratio=100)
MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\((?!https?://)[^)]*\)")
MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
TAG = re.compile(r"</?(aside|details|summary|span|div|br|figure|figcaption|mark|u|sub|sup)\b[^>]*>", re.I)
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def simplify_markdown(text: str) -> str:
    """Notion's Markdown, simplified: no HTML, links to other export files become their label,
    images become ``[Image: alt]``, table rules are dropped and table rows become ``a | b``."""
    text = TAG.sub("", text or "")

    def image(match):
        alt, target = match.group(1), match.group(2)
        return f"[Image: {alt or 'image'}] ({target})" if target.startswith("https://") else f"[Image: {alt or 'image'}]"

    text = MD_IMAGE.sub(image, text)
    text = MD_LINK.sub(lambda m: m.group(1), text)
    out = []
    for line in text.splitlines():
        if TABLE_RULE.match(line) and "|" in line:
            continue
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
            line = " | ".join(cell.strip() for cell in stripped[1:-1].split("|"))
        out.append(line.rstrip())
    return "\n".join(out).strip()


def clean_title(filename: str) -> tuple[str, str]:
    """(title, 32-hex id or '') from ``Some page 0123….md``."""
    base = filename.rsplit("/", 1)[-1]
    found = NAME_ID.search(base)
    raw_id = found.group(1).lower() if found else ""
    title = NAME_ID.sub("", base)
    title = re.sub(r"(_all)?\.(md|csv)$", "", title, flags=re.I).strip()
    return (title or "Untitled")[:200], raw_id


class NotionExport:
    """The archive itself plus any inner ZIPs (one level deep, same limits; deeper ones are ignored)."""

    def __init__(self, zf: SafeZip):
        self.archives = [zf]
        inner = [name for name in zf.names() if name.lower().endswith(".zip")]
        if len(inner) > MAX_INNER:
            raise ZipSafetyError("too_many_files", "The export has too many inner archives")
        for name in inner:
            self.archives.append(SafeZip(io.BytesIO(zf.read(name)), INNER_LIMITS))
        self.items = export_items(self.archives)
        if not self.items:
            raise NotionError("not_notion", "No Notion pages found. Export with the Markdown & CSV format")

    def document(self, item: dict) -> tuple[str, str]:
        return export_document(self.archives[item["archive"]], item)


def export_items(archives: list) -> list[dict]:
    """What a Notion export holds: [{name, title, notion_id, kind (page|database), size, archive}]."""
    items = []
    for n, archive in enumerate(archives):
        names = archive.names()
        with_all = {name[: -len("_all.csv")] for name in names if name.lower().endswith("_all.csv")}
        for name in names:
            low = name.lower()
            base = name.rsplit("/", 1)[-1]
            if base.startswith(".") or "__macosx" in low:
                continue
            if low.endswith(".md"):
                kind = "page"
            elif low.endswith(".csv"):
                if not low.endswith("_all.csv") and name[: -len(".csv")] in with_all:
                    continue
                kind = "database"
            else:
                continue
            title, raw_id = clean_title(name)
            items.append({"name": name, "title": title, "notion_id": raw_id, "kind": kind, "size": archive.size(name), "archive": n})
    return items


def export_document(archive: SafeZip, item: dict) -> tuple[str, str]:
    """(title, text) for one item from ``export_items``."""
    data = archive.read(item["name"], max_bytes=20 * 1024 * 1024)
    if item["kind"] == "database":
        return item["title"], textract.csv_text(data.decode("utf-8-sig", errors="replace"), max_rows=MAX_ROWS)
    text = data.decode("utf-8-sig", errors="replace")
    title = item["title"]
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()[:200] or title
        text = "\n".join(lines[1:])
    return title, simplify_markdown(text)
