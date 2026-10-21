"""CSV/XLSX limits and type inference, sheet URL validation and fetching, DSN parsing, masking and host checks."""

import io
import zipfile
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from datasets import ingest, pg, sheets

SHEET = "https://docs.google.com/spreadsheets/d/e/2PACX-1vT_abcdefghijklmnopqrstuvwxyz0123/pub"


class CsvTests(SimpleTestCase):
    def test_types_are_inferred(self):
        data = (
            "Id,Price,Active,Day,When,Name,Mixed,Empty\n"
            "1,2.5,yes,2026-10-01,2026-10-01T10:00:00,Alpha,1,\n"
            "2,3,no,2026-10-02,2026-10-02 11:30,Beta,1.5,\n"
            "3,,true,2026-10-03,2026-10-03,Gamma,,\n"
        ).encode()
        columns, rows = ingest.parse_csv(data)
        types = {c["name"]: c["type"] for c in columns}
        self.assertEqual(types, {"id": "integer", "price": "real", "active": "boolean", "day": "date", "col_when": "datetime",
                                 "name": "text", "mixed": "real", "empty": "text"})
        self.assertEqual(rows[0][:4], [1, 2.5, 1, "2026-10-01"])
        self.assertIsNone(rows[2][1])
        self.assertEqual(rows[2][4], "2026-10-03 00:00:00")

    def test_semicolon_and_bom(self):
        columns, rows = ingest.parse_csv("﻿a;b\n1;x\n".encode("utf-8"))
        self.assertEqual([c["name"] for c in columns], ["a", "b"])
        self.assertEqual(rows, [[1, "x"]])

    def test_header_names_are_safe_and_unique(self):
        names = ingest.column_names(["Ticket ID", "ticket id", "1st", "", "Select", "pg_secret", "Prix (€)"])
        self.assertEqual(names, ["ticket_id", "ticket_id_2", "c_1st", "column_4", "col_select", "col_pg_secret", "prix"])

    @override_settings(DATASETS_MAX_UPLOAD_MB=0)
    def test_size_limit(self):
        with self.assertRaises(ingest.IngestError) as ctx:
            ingest.parse_csv(b"a\n1\n")
        self.assertEqual(ctx.exception.code, "too_large")

    @override_settings(DATASETS_MAX_ROWS=5)
    def test_row_limit(self):
        with self.assertRaises(ingest.IngestError) as ctx:
            ingest.parse_csv(("a\n" + "1\n" * 6).encode())
        self.assertEqual(ctx.exception.code, "too_many_rows")
        self.assertEqual(len(ingest.parse_csv(("a\n" + "1\n" * 5).encode())[1]), 5)

    @override_settings(DATASETS_MAX_COLUMNS=3)
    def test_column_limit(self):
        with self.assertRaises(ingest.IngestError) as ctx:
            ingest.parse_csv(b"a,b,c,d\n1,2,3,4\n")
        self.assertEqual(ctx.exception.code, "too_many_columns")

    def test_binary_and_unknown_files_refused(self):
        with self.assertRaises(ingest.IngestError):
            ingest.parse_csv(b"\x00\x01\x02")
        with self.assertRaises(ingest.IngestError) as ctx:
            ingest.parse_file("evil.exe", b"MZ")
        self.assertEqual(ctx.exception.code, "unsupported")


def _xlsx(rows_xml, shared=("Week", "Channel", "Web")):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   '<sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        z.writestr("xl/styles.xml", '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   f"<sheetData>{rows_xml}</sheetData></worksheet>")
    return buf.getvalue()


class XlsxTests(SimpleTestCase):
    def test_reads_strings_numbers_and_dates(self):
        data = _xlsx(
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="inlineStr"><is><t>Signups</t></is></c></row>'
            '<row r="2"><c r="A2" s="1"><v>46300</v></c><c r="B2" t="s"><v>2</v></c><c r="C2"><v>12</v></c></row>'
            '<row r="3"><c r="A3" s="1"><v>46307</v></c><c r="C3"><v>15.0</v></c></row>'
        )
        columns, rows = ingest.parse_file("book.xlsx", data)
        self.assertEqual([(c["name"], c["type"]) for c in columns], [("week", "date"), ("channel", "text"), ("signups", "integer")])
        self.assertEqual(rows[0], ["2026-10-05", "Web", 12])
        self.assertEqual(rows[1], ["2026-10-12", None, 15])

    def test_not_a_zip(self):
        with self.assertRaises(ingest.IngestError):
            ingest.parse_xlsx(b"not a zip")


class SheetUrlTests(SimpleTestCase):
    def test_published_csv_links_accepted(self):
        self.assertEqual(sheets.normalize_url(SHEET + "?output=csv"), SHEET + "?output=csv")
        self.assertEqual(sheets.normalize_url(SHEET + "?gid=0&single=true&output=csv"), SHEET + "?output=csv&gid=0&single=true")

    def test_other_links_refused(self):
        for url in (
            "http://docs.google.com/spreadsheets/d/e/2PACX-1vT_abcdefghijklmnopqrstuvwxyz0123/pub?output=csv",
            "https://docs.google.com.evil.example/spreadsheets/d/e/2PACX-1vT_abcdefghijklmnopqrstuvwxyz0123/pub?output=csv",
            "https://evil.example/spreadsheets/d/e/2PACX-1vT_abcdefghijklmnopqrstuvwxyz0123/pub?output=csv",
            "https://user:pw@docs.google.com/spreadsheets/d/e/2PACX-1vT_abcdefghijklmnopqrstuvwxyz0123/pub?output=csv",
            "https://docs.google.com:8443/spreadsheets/d/e/2PACX-1vT_abcdefghijklmnopqrstuvwxyz0123/pub?output=csv",
            SHEET + "?output=html",
            SHEET,
            SHEET + "?output=csv&url=http://169.254.169.254/",
            "https://docs.google.com/spreadsheets/d/1abcdefghijklmnopqrstuvwxyz/edit#gid=0",
            "https://docs.google.com/spreadsheets/d/1abcdefghijklmnopqrstuvwxyz/export?format=csv",
            "https://docs.google.com/document/d/e/2PACX-1vT_abcdefghijklmnopqrstuvwxyz0123/pub?output=csv",
            "",
            None,
        ):
            with self.assertRaises(sheets.SheetError, msg=url):
                sheets.normalize_url(url)

    def test_fetch_follows_one_google_redirect_only(self):
        calls = []

        def fake(method, url, body=b"", headers=None, timeout=10, max_bytes=4096):
            calls.append(url)
            if "docs.google.com" in url:
                return 307, {"location": "https://doc-0s-sheets.googleusercontent.com/pub/x?output=csv"}, b""
            return 200, {"content-type": "text/csv"}, b"a,b\n1,2\n"

        with patch("platform_api.net.fetch_full", side_effect=fake):
            self.assertEqual(sheets.fetch_csv(SHEET + "?output=csv"), b"a,b\n1,2\n")
        self.assertEqual(len(calls), 2)

        def evil(method, url, body=b"", headers=None, timeout=10, max_bytes=4096):
            return 302, {"location": "https://169.254.169.254/latest/meta-data"}, b""

        with patch("platform_api.net.fetch_full", side_effect=evil):
            with self.assertRaises(sheets.SheetError):
                sheets.fetch_csv(SHEET + "?output=csv")

    def test_fetch_refuses_html(self):
        with patch("platform_api.net.fetch_full", return_value=(200, {"content-type": "text/html"}, b"<html>")):
            with self.assertRaises(sheets.SheetError) as ctx:
                sheets.fetch_csv(SHEET + "?output=csv")
        self.assertEqual(ctx.exception.code, "not_published")


class DsnTests(SimpleTestCase):
    DSN = "postgresql://reader:s3cr3t-pa55@db.example.com:5433/sales?sslmode=require"

    def test_parse_and_mask(self):
        parsed = pg.parse_dsn(self.DSN)
        self.assertEqual((parsed["host"], parsed["port"], parsed["dbname"], parsed["user"]), ("db.example.com", 5433, "sales", "reader"))
        masked = pg.mask(self.DSN)
        self.assertEqual(masked, "postgresql://reader:••••@db.example.com:5433/sales")
        self.assertNotIn("s3cr3t", masked)
        self.assertNotIn("s3cr3t", pg.mask("garbage s3cr3t"))

    def test_bad_dsns(self):
        for dsn in ("", "mysql://u:p@h/db", "postgresql://h/db", "postgresql://u@h/", "postgresql://u:p@h/db?host=/tmp",
                    "postgresql://u:p@h1,h2/db", "postgresql://u:p@h/db?sslmode=bogus", None):
            with self.assertRaises(pg.DSNError, msg=dsn):
                pg.parse_dsn(dsn)

    def test_private_hosts_blocked_unless_allowed(self):
        for host in ("127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.169.254", "::1"):
            with self.assertRaises(pg.DSNError) as ctx:
                pg.resolve_host(host, 5432, allow_private=False)
            self.assertEqual(ctx.exception.code, "private_host")
        self.assertEqual(pg.resolve_host("10.0.0.5", 5432, allow_private=True), ("10.0.0.5", True))
        with patch("platform_api.net.resolve", return_value=["10.1.2.3"]):
            with self.assertRaises(pg.DSNError):
                pg.resolve_host("db.internal.example", 5432, allow_private=False)
        with patch("platform_api.net.resolve", return_value=["8.8.8.8", "10.0.0.1"]):
            with self.assertRaises(pg.DSNError):
                pg.resolve_host("rebind.example", 5432, allow_private=False)
        with patch("platform_api.net.resolve", return_value=["93.184.216.34"]):
            self.assertEqual(pg.resolve_host("db.example.com", 5432, allow_private=False), ("93.184.216.34", False))

    def test_connect_is_pinned_read_only_with_timeout(self):
        import psycopg2

        with patch("platform_api.net.resolve", return_value=["93.184.216.34"]), patch.object(psycopg2, "connect") as connect:
            pg.connect("postgresql://reader:pw@db.example.com/sales?sslmode=disable", allow_private=False)
        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs["hostaddr"], "93.184.216.34")
        self.assertEqual(kwargs["host"], "db.example.com")
        self.assertEqual(kwargs["sslmode"], "require")  # public hosts always use TLS
        self.assertIn("default_transaction_read_only=on", kwargs["options"])
        self.assertIn("statement_timeout=", kwargs["options"])
        connect.return_value.set_session.assert_called_with(readonly=True, autocommit=False)

    def test_run_query_uses_a_server_side_cursor_and_rolls_back(self):
        from unittest.mock import MagicMock

        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchmany.return_value = [(i,) for i in range(4)]
        cursor.description = [("n",)]
        result = pg.run_query(conn, "SELECT n FROM orders", 3)
        conn.cursor.assert_called_with(name="flo_data_q")
        cursor.fetchmany.assert_called_with(4)
        self.assertEqual(result["rows"], [[0], [1], [2]])
        self.assertTrue(result["truncated"])
        conn.rollback.assert_called()
