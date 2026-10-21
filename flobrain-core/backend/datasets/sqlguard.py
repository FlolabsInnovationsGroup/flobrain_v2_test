"""Check the text of a model-written query before it runs (both SQLite and PostgreSQL).

This is the first of several layers: one statement, ``SELECT`` or ``WITH`` only, no comments, no
dollar quoting, no write or session keywords, no dangerous functions, and every table in ``FROM`` or
``JOIN`` must be the dataset's own (or a name the query defines with ``WITH``). On PostgreSQL only
functions on an allow list may be called, since a database can hold its own functions. Execution
adds the SQLite authorizer (``datasets.store``) or a read-only PostgreSQL transaction with a
statement timeout and a server-side cursor (``datasets.pg``), so a gap here is not enough to write.
"""

MAX_SQL_CHARS = 8000

DENIED_KEYWORDS = {
    "insert", "update", "delete", "merge", "upsert", "create", "drop", "alter", "truncate", "attach", "detach",
    "pragma", "vacuum", "reindex", "grant", "revoke", "copy", "call", "execute", "exec", "prepare", "deallocate",
    "lock", "listen", "unlisten", "notify", "into", "begin", "commit", "rollback", "savepoint", "returning",
}
DENIED_FUNCTIONS = {
    "load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "zeroblob", "randomblob",
    "set_config", "current_setting", "query_to_xml", "cursor_to_xml", "table_to_xml", "schema_to_xml",
    "database_to_xml", "nextval", "setval", "currval", "lastval", "txid_current", "version",
    "inet_server_addr", "inet_server_port", "sqlite_version", "sqlite_source_id", "sqlite_compileoption_used",
}
DENIED_PREFIXES = ("pg_", "lo_", "dblink", "sqlite_", "xml", "ts_debug")
DENIED_NAMES = {
    "information_schema", "pg_catalog", "sqlite_master", "sqlite_schema", "sqlite_temp_master",
    "current_user", "session_user", "current_role", "current_schema", "current_database", "current_catalog",
}
# Words that may be followed by "(" without being a function call.
PAREN_KEYWORDS = {
    "in", "exists", "over", "filter", "as", "and", "or", "not", "any", "all", "some", "values", "using", "on",
    "when", "then", "else", "select", "from", "where", "join", "lateral", "by", "with", "recursive", "between",
    "is", "distinct", "union", "except", "intersect", "having", "like", "ilike", "within", "partition", "rows",
    "range", "group", "order", "limit", "offset", "array", "row", "case", "end", "materialized", "interval",
}
PG_FUNCTIONS = {
    "count", "sum", "avg", "min", "max", "round", "floor", "ceil", "ceiling", "abs", "trunc", "coalesce", "nullif",
    "greatest", "least", "lower", "upper", "length", "char_length", "trim", "ltrim", "rtrim", "btrim", "substring",
    "substr", "replace", "concat", "concat_ws", "left", "right", "position", "strpos", "split_part", "initcap",
    "lpad", "rpad", "reverse", "to_char", "to_date", "to_timestamp", "to_number", "date_trunc", "date_part",
    "extract", "age", "now", "make_date", "make_timestamp", "cast", "stddev", "stddev_samp", "stddev_pop",
    "variance", "var_samp", "var_pop", "percentile_cont", "percentile_disc", "mode", "string_agg", "array_agg",
    "bool_and", "bool_or", "every", "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile",
    "lag", "lead", "first_value", "last_value", "nth_value", "generate_series", "sqrt", "power", "exp", "ln",
    "log", "mod", "sign", "corr", "covar_pop", "covar_samp", "regr_slope", "regr_intercept", "width_bucket",
    "date", "timestamp", "numeric", "decimal", "float", "integer", "int", "bigint", "text", "varchar", "boolean",
}
# Functions whose arguments use FROM as a keyword, not a table.
FROM_FUNCTIONS = {"extract", "substring", "trim", "overlay", "position"}
FROM_END = {"where", "group", "order", "limit", "having", "union", "intersect", "except", "window", "offset", "fetch"}
JOINISH = {"join", "inner", "left", "right", "full", "cross", "natural", "on", "using", "lateral", "outer", "as"}


class SQLRejected(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _tokens(sql: str):
    """Yield (kind, text) with kind in word/qident/string/number/punct. Raises on comments etc."""
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
            continue
        if sql.startswith("--", i) or sql.startswith("/*", i) or ch == "#":
            raise SQLRejected("comments are not allowed")
        if ch == "'":
            j = i + 1
            while True:
                k = sql.find("'", j)
                if k < 0:
                    raise SQLRejected("unterminated string")
                if sql.startswith("''", k):
                    j = k + 2
                    continue
                break
            yield "string", sql[i + 1 : k]
            i = k + 1
            continue
        if ch == '"':
            k = sql.find('"', i + 1)
            if k < 0:
                raise SQLRejected("unterminated identifier")
            name = sql[i + 1 : k]
            if not name:
                raise SQLRejected("bad identifier")
            yield "qident", name.lower()
            i = k + 1
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            yield "word", sql[i:j].lower()
            i = j
            continue
        if ch.isdigit():
            j = i
            while j < n and (sql[j].isalnum() or sql[j] in "._"):
                j += 1
            yield "number", sql[i:j]
            i = j
            continue
        if ch in "(),.;*+-/%<>=!|&~:^":
            yield "punct", ch
            i += 1
            continue
        raise SQLRejected(f"the character {ch!r} is not allowed")


def check(sql: str, allowed_tables, dialect: str = "sqlite") -> str:
    """Return the query without a trailing semicolon, or raise ``SQLRejected``.

    ``allowed_tables`` holds lower-case names: ``data`` for files, ``schema.table`` (and the bare
    ``table`` for the ``public`` schema) for PostgreSQL.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise SQLRejected("empty query")
    if len(sql) > MAX_SQL_CHARS:
        raise SQLRejected("the query is too long")
    if "\x00" in sql:
        raise SQLRejected("bad character")
    text = sql.strip()
    if text.endswith(";"):
        text = text[:-1].rstrip()
    tokens = list(_tokens(text))
    if not tokens:
        raise SQLRejected("empty query")
    if ("punct", ";") in tokens:
        raise SQLRejected("only one statement is allowed")
    if tokens[0] not in (("word", "select"), ("word", "with")):
        raise SQLRejected("only SELECT queries are allowed")
    allowed = {t.lower() for t in allowed_tables}
    ctes = _cte_names(tokens)
    for index, (kind, value) in enumerate(tokens):
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if kind == "word" and value in DENIED_KEYWORDS:
            raise SQLRejected(f"{value.upper()} is not allowed")
        if kind in ("word", "qident") and (value in DENIED_NAMES or value.startswith(DENIED_PREFIXES)):
            raise SQLRejected(f"{value} is not allowed")
        if kind == "word" and following == ("punct", "("):
            if value in DENIED_FUNCTIONS:
                raise SQLRejected(f"{value}() is not allowed")
            if dialect == "postgres" and value not in PG_FUNCTIONS and value not in PAREN_KEYWORDS and value not in ctes:
                raise SQLRejected(f"the function {value}() is not allowed")
        if (kind, value) == ("word", "for") and following and following[1] in ("update", "share", "no", "key"):
            raise SQLRejected("row locks are not allowed")
    if dialect == "postgres":
        for index in range(len(tokens) - 2):  # schema.function(
            if tokens[index + 1] == ("punct", ".") and tokens[index + 2][0] in ("word", "qident"):
                after = tokens[index + 3] if index + 3 < len(tokens) else None
                if after == ("punct", "("):
                    raise SQLRejected("schema functions are not allowed")
    for name in _table_refs(tokens):
        if name not in allowed and name not in ctes:
            raise SQLRejected(f"the table {name} is not part of this dataset")
    return text


def _cte_names(tokens) -> set:
    names = set()
    for i, (kind, value) in enumerate(tokens):
        if kind not in ("word", "qident"):
            continue
        prev = tokens[i - 1] if i else None
        if prev not in (("word", "with"), ("word", "recursive"), ("punct", ",")):
            continue
        j = i + 1
        if j < len(tokens) and tokens[j] == ("punct", "("):  # name(col, ...) AS (
            depth = 0
            while j < len(tokens):
                if tokens[j] == ("punct", "("):
                    depth += 1
                elif tokens[j] == ("punct", ")"):
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            j += 1
        if j + 1 < len(tokens) and tokens[j] == ("word", "as"):
            nxt = tokens[j + 1]
            if nxt == ("punct", "(") or nxt in (("word", "materialized"), ("word", "not")):
                names.add(value)
    return names


def _read_name(tokens, i):
    """Read ``name`` or ``schema.name`` at i. Returns (name, next index) or (None, i)."""
    if i >= len(tokens) or tokens[i][0] not in ("word", "qident"):
        return None, i
    name = tokens[i][1]
    i += 1
    while i + 1 < len(tokens) and tokens[i] == ("punct", ".") and tokens[i + 1][0] in ("word", "qident"):
        name += "." + tokens[i + 1][1]
        i += 2
    return name, i


def _table_refs(tokens):
    """Every table name that follows FROM or JOIN, including comma lists after FROM."""
    refs = []
    stack = []  # one entry per open "(": True when it is a FROM-keyword function like extract(
    from_open = []  # paren depths with an open FROM list
    i = 0
    while i < len(tokens):
        kind, value = tokens[i]
        depth = len(stack)
        if (kind, value) == ("punct", "("):
            prev = tokens[i - 1] if i else None
            stack.append(bool(prev and prev[0] == "word" and prev[1] in FROM_FUNCTIONS))
        elif (kind, value) == ("punct", ")"):
            if stack:
                stack.pop()
            from_open = [d for d in from_open if d <= len(stack)]
        elif kind == "word" and value in ("from", "join") and not (stack and stack[-1]):
            if value == "from":
                from_open = [d for d in from_open if d != depth] + [depth]
            name, j = _read_name(tokens, i + 1)
            if name is not None and not (j < len(tokens) and tokens[j] == ("punct", "(")):
                refs.append(name)  # a name followed by "(" is a table function, checked as a function
            i = j if name is not None else i + 1
            continue
        elif kind == "word" and from_open and from_open[-1] == depth and (value in FROM_END or value == "select"):
            from_open.pop()
        elif (kind, value) == ("punct", ",") and from_open and from_open[-1] == depth:
            name, j = _read_name(tokens, i + 1)
            if name is not None and name not in JOINISH and not (j < len(tokens) and tokens[j] == ("punct", "(")):
                refs.append(name)
            i = j if name is not None else i + 1
            continue
        i += 1
    return refs
