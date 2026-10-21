"""SQL guard, SQLite authorizer, row and time limits, chart-spec validation (no network, no API)."""

import uuid

from django.test import SimpleTestCase

from datasets import services, sqlguard, store

DATA = {"data"}


class SqlGuardTests(SimpleTestCase):
    def rejects(self, sql, tables=DATA, dialect="sqlite"):
        with self.assertRaises(sqlguard.SQLRejected, msg=sql):
            sqlguard.check(sql, tables, dialect)

    def test_plain_selects_pass(self):
        for sql in (
            "SELECT * FROM data",
            "select week, sum(signups) as s from data group by week order by week desc limit 2;",
            "WITH t AS (SELECT * FROM data) SELECT count(*) FROM t",
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 3) SELECT x FROM n",
            "SELECT week, signups FROM (SELECT week, SUM(signups) AS signups FROM data GROUP BY week) ORDER BY week",
            "SELECT a.x FROM data a JOIN data b ON a.id = b.id WHERE a.x IN (1, 2) ORDER BY a.x, b.y",
            "SELECT '--not a comment; DROP TABLE data /*' AS text FROM data",
            'SELECT "update" FROM data',
        ):
            self.assertTrue(sqlguard.check(sql, DATA))

    def test_trailing_semicolon_stripped(self):
        self.assertEqual(sqlguard.check("SELECT 1 FROM data;", DATA), "SELECT 1 FROM data")

    def test_writes_and_ddl_denied(self):
        for sql in (
            "INSERT INTO data VALUES (1)",
            "UPDATE data SET x = 1",
            "DELETE FROM data",
            "DROP TABLE data",
            "ATTACH DATABASE '/etc/passwd' AS p",
            "PRAGMA table_info(data)",
            "WITH x AS (DELETE FROM data RETURNING *) SELECT * FROM x",
            "WITH x AS (SELECT 1) INSERT INTO data SELECT * FROM x",
            "SELECT * INTO copy FROM data",
            "SELECT * FROM data FOR UPDATE",
            "VACUUM",
            "REPLACE INTO data VALUES (1)",
        ):
            self.rejects(sql)

    def test_multiple_statements_denied(self):
        self.rejects("SELECT 1 FROM data; DROP TABLE data")
        self.rejects("SELECT 1 FROM data;; SELECT 2 FROM data")
        self.rejects("SELECT 1 FROM data; ATTACH 'x' AS y;")

    def test_comment_tricks_denied(self):
        for sql in (
            "SELECT * FROM data -- ; DROP TABLE data",
            "SELECT * FROM data /* hidden */",
            "SELECT * FROM data/**/WHERE 1=1",
            "SELECT * FROM data # mysql comment",
            "SELECT $$; DROP TABLE data$$",
            "SELECT * FROM `data`",
            "SELECT * FROM [data]",
        ):
            self.rejects(sql)

    def test_dangerous_functions_and_catalogs_denied(self):
        for sql in (
            "SELECT load_extension('/tmp/evil.so')",
            "SELECT LOAD_EXTENSION ('x') FROM data",
            "SELECT readfile('/etc/passwd')",
            "SELECT * FROM sqlite_master",
            'SELECT * FROM "sqlite_master"',
            "SELECT * FROM main.sqlite_schema",
            "SELECT pg_sleep(30)",
            "SELECT * FROM pg_catalog.pg_user",
            "SELECT * FROM information_schema.tables",
            "SELECT current_setting('data_directory')",
            "SELECT current_user",
        ):
            self.rejects(sql)

    def test_other_tables_denied(self):
        for sql in (
            "SELECT * FROM other",
            "SELECT * FROM data, other",
            "SELECT * FROM data JOIN other ON 1 = 1",
            "SELECT * FROM (SELECT * FROM secret) s",
            "SELECT * FROM data UNION SELECT * FROM other",
            "SELECT * FROM data WHERE id IN (SELECT id FROM other)",
            "SELECT * FROM aux.data",
        ):
            self.rejects(sql)

    def test_only_select_or_with(self):
        self.rejects("EXPLAIN SELECT * FROM data")
        self.rejects("VALUES (1)")
        self.rejects("")
        self.rejects("x" * (sqlguard.MAX_SQL_CHARS + 1))

    def test_postgres_function_allow_list(self):
        tables = {"orders", "public.orders"}
        self.assertTrue(sqlguard.check("SELECT date_trunc('week', created_at), count(*) FROM orders GROUP BY 1", tables, "postgres"))
        self.assertTrue(sqlguard.check("SELECT extract(month FROM created_at) FROM public.orders", tables, "postgres"))
        self.rejects("SELECT my_side_effect() FROM orders", tables, "postgres")
        self.rejects("SELECT public.f() FROM orders", tables, "postgres")
        self.rejects("SELECT dblink('host=x', 'select 1')", tables, "postgres")
        self.rejects("SELECT * FROM customers", tables, "postgres")


class StoreTests(SimpleTestCase):
    def setUp(self):
        self.org, self.ds = uuid.uuid4(), uuid.uuid4()
        columns = [{"name": "n", "type": "integer"}, {"name": "label", "type": "text"}]
        self.key = store.write_table(self.org, self.ds, columns, [[i, f"row {i}"] for i in range(50)])

    def tearDown(self):
        store.delete_file(self.key)

    def run_sql(self, sql, rows=100, seconds=2):
        return store.run_query(self.key, sql, rows, seconds)

    def test_select_runs(self):
        result = self.run_sql("SELECT count(*) AS c FROM data")
        self.assertEqual(result["columns"], ["c"])
        self.assertEqual(result["rows"], [[50]])

    def test_row_limit(self):
        result = self.run_sql("SELECT * FROM data", rows=10)
        self.assertEqual(len(result["rows"]), 10)
        self.assertTrue(result["truncated"])

    def test_time_limit(self):
        forever = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT count(*) FROM n"
        with self.assertRaises(store.QueryError) as ctx:
            self.run_sql(forever, seconds=0.2)
        self.assertEqual(ctx.exception.code, "timeout")

    def test_authorizer_denies_even_without_the_text_guard(self):
        for sql in (
            "SELECT * FROM sqlite_master",
            "PRAGMA table_info(data)",
            "ATTACH DATABASE ':memory:' AS other",
            "INSERT INTO data VALUES (1, 'x')",
            "DELETE FROM data",
            "SELECT load_extension('x')",
            "CREATE TABLE t (x)",
            "SELECT 1; DELETE FROM data",
        ):
            with self.assertRaises(store.QueryError, msg=sql) as ctx:
                self.run_sql(sql)
            self.assertIn(ctx.exception.code, ("denied", "sql_error"), sql)
        self.assertEqual(self.run_sql("SELECT count(*) FROM data")["rows"], [[50]])

    def test_keys_cannot_escape_the_folder(self):
        self.assertEqual(store.path_for("../etc/passwd"), "")
        self.assertEqual(store.path_for("a/../../x"), "")
        with self.assertRaises(store.QueryError):
            store.run_query("../../etc/passwd", "SELECT 1", 1, 1)


class ChartSpecTests(SimpleTestCase):
    cols = ["week", "channel", "signups", "revenue"]
    rows = [["2026-10-05", "Web", 10, 1.5], ["2026-10-12", "Web", 12, 2.0]]

    def test_valid_specs_kept(self):
        chart, fixed = services.validate_chart({"type": "line", "x": "week", "y": ["signups"], "series": "channel"}, self.cols, self.rows)
        self.assertFalse(fixed)
        self.assertEqual(chart, {"type": "line", "x": "week", "y": ["signups"], "series": "channel"})
        chart, fixed = services.validate_chart({"type": "bar", "x": "channel", "y": "revenue"}, self.cols, self.rows)
        self.assertEqual((chart["y"], fixed), (["revenue"], False))
        self.assertFalse(services.validate_chart({"type": "table"}, self.cols, self.rows)[1])

    def test_invalid_specs_replaced(self):
        for spec in (
            None,
            {"type": "pie", "x": "week", "y": ["signups"]},
            {"type": "bar", "x": "nope", "y": ["signups"]},
            {"type": "bar", "x": "week", "y": ["channel"]},  # not numeric
            {"type": "bar", "x": "week", "y": ["DROP TABLE"]},
            {"type": "line", "x": "week", "y": ["signups", "revenue"], "series": "channel"},
            {"type": "line", "x": "week", "y": ["signups"], "series": "week"},
            {"type": "number", "y": ["signups", "revenue"]},
        ):
            chart, fixed = services.validate_chart(spec, self.cols, self.rows)
            self.assertTrue(fixed, spec)
            self.assertIn(chart["type"], services.CHART_TYPES)

    def test_default_chart(self):
        self.assertEqual(services.default_chart(["total"], [[5]])["type"], "number")
        self.assertEqual(services.default_chart(["week", "n"], [["2026-01-05", 1]])["type"], "line")
        self.assertEqual(services.default_chart(["channel", "n"], [["Web", 1]])["type"], "bar")
        self.assertEqual(services.default_chart(["a", "b"], [["x", "y"]])["type"], "table")
