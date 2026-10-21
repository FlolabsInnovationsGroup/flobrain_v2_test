"""One SQLite file per uploaded or synced dataset, kept outside the main database.

Files live under ``DATASETS_DIR`` (default ``<backend>/media/private/datasets``, a temp folder in
tests), one folder per org. Each file holds a single table named ``data``. Queries open the file
read-only and run under an authorizer that allows only reading that table and calling functions,
with a row cap and a time limit (``datasets.sqlguard`` checks the text first).
"""

import os
import sqlite3
import tempfile
import time
import uuid

from django.conf import settings

TABLE = "data"
SQLITE_TYPES = {"integer": "INTEGER", "real": "REAL", "boolean": "INTEGER", "date": "TEXT", "datetime": "TEXT", "text": "TEXT"}
DENIED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "zeroblob", "randomblob"}
_TEST_ROOT = None


class QueryError(Exception):
    def __init__(self, code, details=""):
        super().__init__(details or code)
        self.code, self.details = code, details or code


def root() -> str:
    global _TEST_ROOT
    configured = getattr(settings, "DATASETS_DIR", "") or os.environ.get("DATASETS_DIR", "")
    if configured:
        return configured
    if getattr(settings, "TESTING", False):
        if _TEST_ROOT is None:
            _TEST_ROOT = tempfile.mkdtemp(prefix="flobrain-datasets-test-")
        return _TEST_ROOT
    return os.path.join(str(settings.BASE_DIR), "media", "private", "datasets")


def path_for(key: str) -> str:
    """The absolute file for a stored key, or "" when the key would leave the data folder."""
    if not key or "\\" in key or "\x00" in key or ".." in key.split("/"):
        return ""
    real_root = os.path.realpath(root())
    path = os.path.realpath(os.path.join(real_root, *key.split("/")))
    return path if path.startswith(real_root + os.sep) else ""


def write_table(org_id, dataset_id, columns, rows) -> str:
    """Write a fresh file atomically and return its key (``<org>/<dataset>-<n>.sqlite3``)."""
    key = f"{org_id}/{dataset_id}-{uuid.uuid4().hex[:8]}.sqlite3"
    path = path_for(key)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp)
    try:
        cols = ", ".join(f'"{c["name"]}" {SQLITE_TYPES.get(c["type"], "TEXT")}' for c in columns)
        conn.execute(f"CREATE TABLE {TABLE} ({cols})")
        marks = ", ".join("?" for _ in columns)
        conn.executemany(f"INSERT INTO {TABLE} VALUES ({marks})", rows)
        conn.commit()
    finally:
        conn.close()
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return key


def delete_file(key: str):
    path = path_for(key)
    if path and os.path.exists(path):
        os.remove(path)


def _authorizer(action, arg1, arg2, db_name, trigger):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        # arg1 is the table or a CTE name. The file holds only ``data`` and nothing can be attached,
        # so what is left to refuse is SQLite's own catalog and the temp schema.
        name = (arg1 or "").lower()
        if name.startswith("sqlite_") or db_name not in (None, "main"):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or "").lower() in DENIED_FUNCTIONS else sqlite3.SQLITE_OK
    if action == getattr(sqlite3, "SQLITE_RECURSIVE", 33):
        return sqlite3.SQLITE_OK  # WITH RECURSIVE; bounded by the time limit
    return sqlite3.SQLITE_DENY  # ATTACH, PRAGMA, INSERT, UPDATE, DELETE, CREATE, transactions, ...


def _clean(value):
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def run_query(key: str, sql: str, max_rows: int, timeout_seconds: float) -> dict:
    """Run one checked SELECT on the dataset file. Returns {"columns", "rows", "truncated", "ms"}."""
    path = path_for(key)
    if not path or not os.path.exists(path):
        raise QueryError("missing", "The data file is missing; refresh or upload it again")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1, check_same_thread=False)
    started = time.monotonic()
    deadline = started + timeout_seconds
    try:
        conn.execute("PRAGMA query_only = ON")  # before the authorizer, which denies pragmas
        if hasattr(conn, "setlimit"):
            conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        conn.set_authorizer(_authorizer)
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 2000)
        try:
            cursor = conn.execute(sql)
            columns = [d[0] for d in (cursor.description or [])]
            rows = cursor.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as exc:
            message = str(exc)
            if "interrupted" in message:
                raise QueryError("timeout", f"The query took longer than {timeout_seconds:g} seconds") from exc
            if "not authorized" in message or "prohibited" in message:
                raise QueryError("denied", "The query tried to do something other than read this dataset") from exc
            if "one statement" in message:
                raise QueryError("denied", "Only one statement is allowed") from exc
            raise QueryError("sql_error", message[:200]) from exc
        except sqlite3.Warning as exc:  # more than one statement
            raise QueryError("denied", "Only one statement is allowed") from exc
    finally:
        conn.close()
    truncated = len(rows) > max_rows
    rows = [[_clean(v) for v in r] for r in rows[:max_rows]]
    return {"columns": columns, "rows": rows, "truncated": truncated, "ms": int((time.monotonic() - started) * 1000)}
