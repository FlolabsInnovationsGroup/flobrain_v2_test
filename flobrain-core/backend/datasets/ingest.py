"""Read CSV and XLSX files into typed columns, within limits.

Limits (settings can lower or raise them): ``DATASETS_MAX_UPLOAD_MB`` (10), ``DATASETS_MAX_ROWS``
(200 000), ``DATASETS_MAX_COLUMNS`` (100). XLSX is read with the standard library: only the first
sheet, cell values (no formulas re-computed), dates detected from the cell's number format.
"""

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta

from django.conf import settings

TYPES = ("integer", "real", "boolean", "date", "datetime", "text")
MAX_CELL_CHARS = 2000
MAX_XLSX_UNCOMPRESSED = 200 * 1024 * 1024  # zip bombs stop here
INT_RE = re.compile(r"^[+-]?\d{1,18}$")
REAL_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
BOOLS = {"true": 1, "false": 0, "yes": 1, "no": 0}
IDENT_RE = re.compile(r"[^a-z0-9_]+")
# Header names that would read as SQL get a suffix, so a model can use every column without quotes.
RESERVED = {
    "select", "from", "where", "group", "order", "by", "limit", "offset", "having", "union", "all", "distinct",
    "insert", "update", "delete", "merge", "into", "values", "set", "table", "create", "drop", "alter", "join",
    "on", "as", "and", "or", "not", "null", "is", "in", "like", "between", "exists", "case", "when", "then",
    "else", "end", "with", "for", "to", "desc", "asc", "user", "default", "check", "primary", "key", "index",
    "references", "grant", "copy", "call", "lock", "attach", "pragma", "execute", "returning", "window", "cast",
    "current_user", "session_user", "current_role", "current_schema", "current_database", "current_catalog",
}


class IngestError(ValueError):
    def __init__(self, code, details):
        super().__init__(details)
        self.code, self.details = code, details


def max_bytes() -> int:
    return int(getattr(settings, "DATASETS_MAX_UPLOAD_MB", 10)) * 1024 * 1024


def max_rows() -> int:
    return int(getattr(settings, "DATASETS_MAX_ROWS", 200_000))


def max_columns() -> int:
    return int(getattr(settings, "DATASETS_MAX_COLUMNS", 100))


# --- column names -----------------------------------------------------------------


def column_names(labels) -> list[str]:
    """Safe, unique SQL names (lower case, a-z 0-9 _) for the header labels."""
    out, seen = [], set()
    for i, label in enumerate(labels):
        base = IDENT_RE.sub("_", str(label or "").strip().lower()).strip("_")[:50] or f"column_{i + 1}"
        if not base[0].isalpha():
            base = "c_" + base
        if base in RESERVED or base.startswith(("pg_", "lo_", "sqlite_", "xml", "dblink")):
            base = "col_" + base
        name, n = base, 2
        while name in seen:
            name = f"{base}_{n}"
            n += 1
        seen.add(name)
        out.append(name)
    return out


# --- type inference ---------------------------------------------------------------


def _kind(value: str) -> str:
    if INT_RE.match(value):
        return "integer"
    if REAL_RE.match(value):
        return "real"
    if value.lower() in BOOLS:
        return "boolean"
    if DATE_RE.match(value):
        try:
            date.fromisoformat(value)
            return "date"
        except ValueError:
            return "text"
    if DATETIME_RE.match(value):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return "datetime"
        except ValueError:
            return "text"
    return "text"


def infer_type(values) -> str:
    kinds = {_kind(v) for v in values if v != ""}
    if not kinds:
        return "text"
    if len(kinds) == 1:
        return kinds.pop()
    if kinds <= {"integer", "real"}:
        return "real"
    if kinds <= {"date", "datetime"}:
        return "datetime"
    return "text"


def coerce(value: str, kind: str):
    if value == "":
        return None
    if kind == "integer":
        return int(value)
    if kind == "real":
        return float(value)
    if kind == "boolean":
        return BOOLS[value.lower()]
    if kind == "datetime" and DATE_RE.match(value):
        return value + " 00:00:00"
    if kind == "datetime":
        return value.replace("T", " ")
    return value


def typed_table(header, rows) -> tuple[list[dict], list[list]]:
    """(columns, rows) with each column's inferred type and every value converted."""
    if not header:
        raise IngestError("empty", "The file has no header row")
    if len(header) > max_columns():
        raise IngestError("too_many_columns", f"At most {max_columns()} columns")
    width = len(header)
    cleaned = []
    for row in rows:
        row = [("" if v is None else str(v).strip())[:MAX_CELL_CHARS] for v in row[:width]]
        row += [""] * (width - len(row))
        if any(row):
            cleaned.append(row)
    names = column_names(header)
    kinds = [infer_type(r[i] for r in cleaned) for i in range(width)]
    columns = [{"name": n, "label": str(l or n)[:120], "type": k} for n, l, k in zip(names, header, kinds)]
    typed = [[coerce(v, k) for v, k in zip(r, kinds)] for r in cleaned]
    return columns, typed


# --- CSV ----------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse_csv(data: bytes) -> tuple[list[dict], list[list]]:
    if len(data) > max_bytes():
        raise IngestError("too_large", f"Files can be at most {max_bytes() // (1024 * 1024)} MB")
    if b"\x00" in data[:4096]:
        raise IngestError("not_csv", "This does not look like a CSV file")
    text = _decode(data)
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    csv.field_size_limit(MAX_CELL_CHARS * 4)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader, None)
        rows = []
        for row in reader:
            rows.append(row)
            if len(rows) > max_rows():
                raise IngestError("too_many_rows", f"At most {max_rows():,} rows")
    except csv.Error as exc:
        raise IngestError("not_csv", "The CSV could not be read") from exc
    return typed_table(header, rows)


# --- XLSX ---------------------------------------------------------------------------

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
DATE_FORMAT_IDS = set(range(14, 23)) | {45, 46, 47}
CELL_REF = re.compile(r"^([A-Z]{1,3})\d+$")


def _col_index(ref: str) -> int:
    match = CELL_REF.match(ref or "")
    if not match:
        return -1
    n = 0
    for ch in match.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _excel_date(serial: float) -> str:
    base = datetime(1899, 12, 30) + timedelta(days=serial)
    return base.date().isoformat() if serial == int(serial) else base.isoformat(sep=" ", timespec="seconds")


def parse_xlsx(data: bytes) -> tuple[list[dict], list[list]]:
    from defusedxml import ElementTree as ET

    if len(data) > max_bytes():
        raise IngestError("too_large", f"Files can be at most {max_bytes() // (1024 * 1024)} MB")
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
        infos = book.infolist()
    except (zipfile.BadZipFile, ValueError) as exc:
        raise IngestError("not_xlsx", "This does not look like an Excel file") from exc
    if len(infos) > 2000 or sum(i.file_size for i in infos) > MAX_XLSX_UNCOMPRESSED:
        raise IngestError("too_large", "The Excel file is too large once unpacked")
    names = {i.filename for i in infos}
    try:
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        first = workbook.find("m:sheets/m:sheet", NS)
        target = None
        for rel in rels:
            if first is not None and rel.get("Id") == first.get(REL_NS):
                target = rel.get("Target", "")
        if not target:
            raise IngestError("not_xlsx", "The Excel file has no sheet")
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        strings = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(book.read("xl/sharedStrings.xml")).findall("m:si", NS):
                strings.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
        date_styles = set()
        if "xl/styles.xml" in names:
            styles = ET.fromstring(book.read("xl/styles.xml"))
            custom = {
                int(f.get("numFmtId")): f.get("formatCode", "").lower()
                for f in styles.findall("m:numFmts/m:numFmt", NS)
            }
            for i, xf in enumerate(styles.findall("m:cellXfs/m:xf", NS)):
                fmt = int(xf.get("numFmtId", "0"))
                code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom.get(fmt, ""))
                if fmt in DATE_FORMAT_IDS or (fmt in custom and re.search(r"[dy]", code)):
                    date_styles.add(i)
        sheet = ET.fromstring(book.read(path))
    except KeyError as exc:
        raise IngestError("not_xlsx", "The Excel file is missing a part") from exc
    except ET.ParseError as exc:
        raise IngestError("not_xlsx", "The Excel file could not be read") from exc
    table = []
    for row in sheet.iterfind("m:sheetData/m:row", NS):
        values = {}
        for i, cell in enumerate(row.findall("m:c", NS)):
            col = _col_index(cell.get("r", "")) if cell.get("r") else i
            if col < 0 or col >= max_columns() + 1:
                continue
            kind, v = cell.get("t", "n"), cell.find("m:v", NS)
            raw = v.text if v is not None else None
            if kind == "s" and raw is not None:
                value = strings[int(raw)] if raw.isdigit() and int(raw) < len(strings) else ""
            elif kind == "inlineStr":
                value = "".join(t.text or "" for t in cell.iter("{%s}t" % NS["m"]))
            elif kind == "b":
                value = "true" if raw == "1" else "false"
            elif raw is None:
                value = ""
            elif kind == "n" and int(cell.get("s", "0") or 0) in date_styles:
                try:
                    value = _excel_date(float(raw))
                except (ValueError, OverflowError):
                    value = raw
            else:
                value = raw
                if kind == "n" and re.match(r"^-?\d+\.0$", value):
                    value = value[:-2]
            values[col] = value
        width = (max(values) + 1) if values else 0
        table.append([values.get(i, "") for i in range(width)])
        if len(table) > max_rows() + 1:
            raise IngestError("too_many_rows", f"At most {max_rows():,} rows")
    if not table:
        raise IngestError("empty", "The first sheet is empty")
    header = table[0]
    while header and header[-1] == "":
        header = header[:-1]
    return typed_table(header, table[1:])


def parse_file(name: str, data: bytes):
    lower = (name or "").lower()
    if lower.endswith(".xlsx"):
        return parse_xlsx(data)
    if lower.endswith((".csv", ".tsv", ".txt")):
        return parse_csv(data)
    raise IngestError("unsupported", "Upload a .csv or .xlsx file")
