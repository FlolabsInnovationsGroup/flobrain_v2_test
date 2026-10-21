"""Read-only PostgreSQL sources.

The connection string is parsed and checked before anything connects: ``postgres://`` or
``postgresql://`` only, a host name that resolves to public addresses (private, loopback and
link-local hosts need an admin to allow them for the org), TLS required for public hosts. The
connection is pinned to the checked address (``hostaddr``) so a DNS change cannot redirect it, and
opened with ``default_transaction_read_only=on``, a ``statement_timeout`` and a read-only session.
Model queries run through a server-side cursor (``DECLARE ... CURSOR FOR``), which PostgreSQL only
accepts for a single SELECT, and only the first rows are fetched.

Use a database role that can only ``SELECT`` the tables you share: these checks are a second line.
"""

import ipaddress
import urllib.parse

from django.conf import settings

from datasets.store import QueryError

DEFAULT_PORT = 5432
MAX_TABLES = 20
ALLOWED_PARAMS = {"sslmode", "application_name", "connect_timeout"}


class DSNError(ValueError):
    def __init__(self, code, details):
        super().__init__(details)
        self.code, self.details = code, details


def parse_dsn(dsn: str) -> dict:
    """Return {host, port, dbname, user, password, sslmode} or raise DSNError."""
    if not isinstance(dsn, str) or not dsn.strip() or len(dsn) > 1000:
        raise DSNError("invalid", "Paste a connection string like postgresql://user:password@host:5432/database")
    try:
        parsed = urllib.parse.urlparse(dsn.strip())
        port = parsed.port or DEFAULT_PORT
    except ValueError as exc:
        raise DSNError("invalid", "The connection string is not valid") from exc
    if parsed.scheme not in ("postgres", "postgresql"):
        raise DSNError("invalid", "The connection string must start with postgresql://")
    host = parsed.hostname or ""
    dbname = urllib.parse.unquote(parsed.path.lstrip("/"))
    user = urllib.parse.unquote(parsed.username or "")
    if not host or not dbname or not user or "/" in dbname or "," in (parsed.netloc or ""):
        raise DSNError("invalid", "The connection string needs a user, a host and a database name")
    params = urllib.parse.parse_qs(parsed.query)
    unknown = set(params) - ALLOWED_PARAMS
    if unknown:
        raise DSNError("invalid", f"Unsupported options: {', '.join(sorted(unknown))}")
    sslmode = (params.get("sslmode") or [""])[0]
    if sslmode and sslmode not in ("disable", "allow", "prefer", "require", "verify-ca", "verify-full"):
        raise DSNError("invalid", "Unknown sslmode")
    return {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": urllib.parse.unquote(parsed.password or ""),
        "sslmode": sslmode,
    }


def mask(dsn: str) -> str:
    """postgresql://user:••••@host:5432/db (never the password)."""
    try:
        p = parse_dsn(dsn)
    except DSNError:
        return "postgresql://••••"
    secret = "••••" if p["password"] else ""
    auth = f"{p['user']}:{secret}" if secret else p["user"]
    return f"postgresql://{auth}@{p['host']}:{p['port']}/{p['dbname']}"


def _public(addr: str) -> bool:
    from platform_api.net import _public as is_public

    return is_public(addr)


def resolve_host(host: str, port: int, allow_private: bool) -> tuple[str, bool]:
    """Return (address to connect to, is_private). Raises DSNError for a blocked host."""
    from platform_api.net import resolve

    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            host.encode("idna")
            addresses = resolve(host, port)
        except (OSError, UnicodeError, ValueError) as exc:
            raise DSNError("unreachable", "The host name does not resolve") from exc
    if not addresses:
        raise DSNError("unreachable", "The host name does not resolve")
    private = not all(_public(a) for a in addresses)
    if private and not allow_private:
        raise DSNError(
            "private_host",
            "This host is on a private network. An admin can allow private hosts in data settings.",
        )
    return addresses[0], private


def statement_timeout_ms() -> int:
    return int(getattr(settings, "DATASETS_PG_STATEMENT_TIMEOUT_MS", 5000))


def connect(dsn: str, allow_private: bool):
    """Open a read-only connection (psycopg2). Raises DSNError or QueryError."""
    import psycopg2

    p = parse_dsn(dsn)
    address, private = resolve_host(p["host"], p["port"], allow_private)
    sslmode = p["sslmode"] or ("prefer" if private else "require")
    if not private and sslmode in ("disable", "allow", "prefer"):
        sslmode = "require"  # public hosts always use TLS
    timeout = statement_timeout_ms()
    try:
        conn = psycopg2.connect(
            host=p["host"],
            hostaddr=address,
            port=p["port"],
            dbname=p["dbname"],
            user=p["user"],
            password=p["password"],
            sslmode=sslmode,
            connect_timeout=5,
            application_name="flobrain-data-buddy",
            options=f"-c default_transaction_read_only=on -c statement_timeout={timeout} "
            f"-c idle_in_transaction_session_timeout={timeout * 2} -c lock_timeout=1000",
        )
    except psycopg2.OperationalError as exc:
        raise QueryError("connect_failed", "Could not connect. Check the host, the user and the password.") from exc
    conn.set_session(readonly=True, autocommit=False)
    return conn


INTROSPECT_SQL = """
SELECT c.table_schema, c.table_name, c.column_name, c.data_type
FROM information_schema.columns c
JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema') AND t.table_type IN ('BASE TABLE', 'VIEW')
ORDER BY c.table_schema, c.table_name, c.ordinal_position
"""

PG_TYPES = {
    "integer": "integer", "bigint": "integer", "smallint": "integer", "numeric": "real", "real": "real",
    "double precision": "real", "boolean": "boolean", "date": "date",
    "timestamp without time zone": "datetime", "timestamp with time zone": "datetime",
}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def introspect(conn, wanted: list[str] | None = None) -> list[dict]:
    """Tables (at most 20) with columns and 5 sample rows. ``wanted`` limits it to those names."""
    with conn.cursor() as cur:
        cur.execute(INTROSPECT_SQL)
        found: dict[str, list] = {}
        for schema, table, column, kind in cur.fetchall():
            name = table if schema == "public" else f"{schema}.{table}"
            found.setdefault(name.lower(), []).append({"name": column, "label": column, "type": PG_TYPES.get(kind, "text")})
    names = [n for n in found if wanted is None or n in {w.lower() for w in wanted}][:MAX_TABLES]
    tables = []
    for name in names:
        schema, _, table = name.rpartition(".")
        ref = (_quote(schema) + "." if schema else "") + _quote(table)
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {ref} LIMIT 5")  # noqa: S608 - names come from the catalog, quoted
            sample = [[_jsonable(v) for v in row] for row in cur.fetchall()]
        tables.append({"name": name, "label": name, "columns": found[name], "sample_rows": sample, "row_count": None})
    conn.rollback()
    return tables


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value if not isinstance(value, str) or len(value) <= 500 else value[:500] + "…"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (bytes, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    return str(value)[:500]


def run_query(conn, sql: str, max_rows: int) -> dict:
    import time

    import psycopg2

    started = time.monotonic()
    try:
        with conn.cursor(name="flo_data_q") as cur:  # DECLARE ... CURSOR FOR: one SELECT only
            cur.itersize = min(max_rows + 1, 2000)
            cur.execute(sql)
            rows = cur.fetchmany(max_rows + 1)
            columns = [d[0] for d in (cur.description or [])]
    except psycopg2.errors.QueryCanceled as exc:
        raise QueryError("timeout", f"The query took longer than {statement_timeout_ms() // 1000} seconds") from exc
    except psycopg2.errors.ReadOnlySqlTransaction as exc:
        raise QueryError("denied", "The query tried to change data") from exc
    except psycopg2.Error as exc:
        raise QueryError("sql_error", (str(exc).splitlines() or ["SQL error"])[0][:200]) from exc
    finally:
        try:
            conn.rollback()
        except psycopg2.Error:
            pass
    truncated = len(rows) > max_rows
    return {
        "columns": columns,
        "rows": [[_jsonable(v) for v in r] for r in rows[:max_rows]],
        "truncated": truncated,
        "ms": int((time.monotonic() - started) * 1000),
    }
