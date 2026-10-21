"""Text from files that become Documents: plain text, Markdown, CSV, HTML, DOCX and PDF.

- DOCX is read here (it is a ZIP of XML): the archive goes through ``SafeZip`` and the XML through
  ``defusedxml``. Headings, list items and tables are kept in a simple Markdown shape.
- PDF uses ``pypdf`` (in requirements.txt), at most 500 pages and ``MAX_CHARS`` of text. Where it
  is missing, PDFs are reported as ``pdf_unavailable`` and skipped (``pdf_supported()`` tells the UI).
- HTML is reduced to its text. Nothing is ever executed or fetched.
"""

import csv
import io
from html.parser import HTMLParser

from imports.safezip import Limits, SafeZip, ZipSafetyError

MAX_CHARS = 400_000
DOCX_LIMITS = Limits(max_files=2000, max_total=100 * 1024**2, max_member=50 * 1024**2, max_ratio=100)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

TEXT_EXT = (".txt", ".md", ".markdown")
SUPPORTED_EXT = TEXT_EXT + (".csv", ".html", ".htm", ".docx", ".pdf")


class ExtractError(Exception):
    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code
        self.details = details or code


def pdf_supported() -> bool:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


def docx_supported() -> bool:
    return True


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def cap(text: str) -> str:
    text = (text or "").replace("\x00", "").strip()
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS].rstrip() + "\n\n[Cut here: the original is longer.]"
    return text


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table", "ul", "ol"}
    SKIP = {"script", "style", "head", "title", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")
            elif tag in ("h1", "h2", "h3"):
                self.parts.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_text(source: str) -> str:
    parser = _Text()
    parser.feed(source)
    parser.close()
    lines = [" ".join(line.split()).rstrip(" |") for line in "".join(parser.parts).splitlines()]
    out, blank = [], False
    for line in lines:
        if not line:
            if not blank and out:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    return "\n".join(out).strip()


def csv_text(data: str, max_rows: int = 500) -> str:
    """A CSV as simple rows: ``a | b | c``."""
    rows = []
    try:
        for i, row in enumerate(csv.reader(io.StringIO(data))):
            if i > max_rows:
                rows.append(f"[{max_rows} rows shown]")
                break
            rows.append(" | ".join(cell.strip() for cell in row))
    except csv.Error:
        return data
    return "\n".join(rows)


def _docx_text(data: bytes) -> str:
    from defusedxml import ElementTree

    try:
        with SafeZip(io.BytesIO(data), DOCX_LIMITS) as zf:
            if "word/document.xml" not in zf.names():
                raise ExtractError("unreadable", "This Word file could not be read")
            xml = zf.read("word/document.xml")
    except ZipSafetyError as exc:
        raise ExtractError("unreadable", "This Word file could not be read") from exc
    try:
        root = ElementTree.fromstring(xml)
    except Exception as exc:  # noqa: BLE001 - defusedxml raises several types for hostile XML
        raise ExtractError("unreadable", "This Word file could not be read") from exc
    body = root.find(f"{W}body")
    if body is None:
        return ""

    def run_text(node) -> str:
        parts = []
        for el in node.iter():
            if el.tag == f"{W}t" and el.text:
                parts.append(el.text)
            elif el.tag == f"{W}tab":
                parts.append(" ")
            elif el.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
        return "".join(parts).strip()

    def paragraph(p) -> str:
        text = run_text(p)
        if not text:
            return ""
        ppr = p.find(f"{W}pPr")
        style = ""
        if ppr is not None:
            ps = ppr.find(f"{W}pStyle")
            style = (ps.get(f"{W}val") or "") if ps is not None else ""
            if ppr.find(f"{W}numPr") is not None:
                return f"- {text}"
        low = style.lower()
        if low == "title":
            return f"# {text}"
        if low.startswith("heading") and low[7:].isdigit():
            return "#" * min(int(low[7:]), 6) + " " + text
        if low.startswith("list"):
            return f"- {text}"
        return text

    lines = []
    for child in body:
        if child.tag == f"{W}p":
            line = paragraph(child)
            if line:
                lines.append(line)
        elif child.tag == f"{W}tbl":
            for tr in child.iter(f"{W}tr"):
                cells = [run_text(tc).replace("\n", " ") for tc in tr.iter(f"{W}tc")]
                if any(cells):
                    lines.append(" | ".join(cells))
            lines.append("")
    return "\n".join(lines)


def _pdf_text(data: bytes) -> str:
    try:
        import pypdf
    except ImportError as exc:
        raise ExtractError("pdf_unavailable", "PDF text needs the pypdf library, which is not installed on this server") from exc
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractError("unreadable", "Password-protected PDFs are not supported")
        parts = []
        for page in reader.pages[:500]:
            parts.append(page.extract_text() or "")
            if sum(len(p) for p in parts) > MAX_CHARS:
                break
        return "\n\n".join(p.strip() for p in parts if p.strip())
    except ExtractError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types for broken files
        raise ExtractError("unreadable", "This PDF could not be read") from exc


KINDS = {".txt": "txt", ".md": "md", ".markdown": "md", ".csv": "csv", ".html": "html", ".htm": "html", ".docx": "docx", ".pdf": "pdf"}


def kind_of(name: str) -> str:
    low = (name or "").lower()
    return next((kind for ext, kind in KINDS.items() if low.endswith(ext)), "")


def extract(name: str, data: bytes) -> str:
    """Text of one file, or raise ``ExtractError`` (``unsupported``, ``pdf_unavailable``, ``unreadable``)."""
    kind = kind_of(name)
    if kind in ("txt", "md"):
        return cap(_decode(data))
    if kind == "csv":
        return cap(csv_text(_decode(data)))
    if kind == "html":
        return cap(html_text(_decode(data)))
    if kind == "docx":
        return cap(_docx_text(data))
    if kind == "pdf":
        return cap(_pdf_text(data))
    raise ExtractError("unsupported", "This file type can't be imported")
