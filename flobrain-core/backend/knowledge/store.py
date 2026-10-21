"""Vector store interface (Decision E16a).

Production uses pgvector on the existing PostgreSQL, one table per vector
dimension (``knowledge_vec_<dim>``) so each HNSW index has a fixed width.
Local dev and tests can use the JSON store. When pgvector is missing, the store
reports itself unavailable and memory search shows "Not configured".

Retrieval filters first, then ranks: ``search`` only scores the chunk ids the
caller has already authorized.
"""

import math
import re
import uuid

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.models import QuerySet

SUPPORTED_PGVECTOR_DIMENSIONS = (1024,)
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64


def pgvector_table(dimension: int) -> str:
    if dimension not in SUPPORTED_PGVECTOR_DIMENSIONS:
        raise ValueError(f"no pgvector table for dimension {dimension}")
    return f"knowledge_vec_{int(dimension)}"


def _vector_literal(vector) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


def ensure_pgvector_table(cursor, dimension: int) -> None:
    table = pgvector_table(dimension)
    cursor.execute(
        f"CREATE TABLE IF NOT EXISTS {table} ("
        " chunk_id uuid PRIMARY KEY,"
        " model varchar(128) NOT NULL,"
        f" embedding vector({int(dimension)}) NOT NULL)"
    )
    cursor.execute(
        f"CREATE INDEX IF NOT EXISTS {table}_hnsw ON {table} "
        f"USING hnsw (embedding vector_cosine_ops) WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})"
    )
    cursor.execute(f"CREATE INDEX IF NOT EXISTS {table}_model ON {table} (model)")


def pgvector_installed() -> bool:
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        return cur.fetchone() is not None


class PgVectorStore:
    name = "pgvector"

    def __init__(self, dimension: int):
        self.dimension = int(dimension)
        self.table = pgvector_table(self.dimension)

    def available(self) -> bool:
        if not pgvector_installed():
            return False
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", [self.table])
            return cur.fetchone()[0] is not None

    def _check(self, vector):
        if len(vector) != self.dimension:
            raise ValueError(f"expected {self.dimension} dimensions, got {len(vector)}")

    def upsert(self, chunk_id, vector, model: str) -> None:
        self._check(vector)
        with connection.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self.table} (chunk_id, model, embedding) VALUES (%s, %s, %s::vector) "
                "ON CONFLICT (chunk_id) DO UPDATE SET model = EXCLUDED.model, embedding = EXCLUDED.embedding",
                [str(chunk_id), model, _vector_literal(vector)],
            )

    def delete(self, chunk_ids) -> None:
        ids = [str(c) for c in chunk_ids]
        if not ids:
            return
        with connection.cursor() as cur:
            cur.execute(f"DELETE FROM {self.table} WHERE chunk_id = ANY(%s::uuid[])", [ids])

    def search(self, vector, model: str, allowed_chunk_ids, k: int = 8):
        """Rank only the allowed chunk ids. Returns [(chunk_id, score)] with score in [-1, 1].

        ``allowed_chunk_ids`` is a list of ids or a QuerySet of ids. A QuerySet
        becomes a SQL subquery, so a large org never ships its id list to Python.
        The filter is exact: a row outside the allowed set is never scored.
        """
        self._check(vector)
        literal = _vector_literal(vector)
        if isinstance(allowed_chunk_ids, QuerySet):
            sub_sql, sub_params = allowed_chunk_ids.query.sql_with_params()
            where, params = f"chunk_id IN ({sub_sql})", list(sub_params)
        else:
            ids = [str(c) for c in allowed_chunk_ids]
            if not ids:
                return []
            where, params = "chunk_id = ANY(%s::uuid[])", [ids]
        with transaction.atomic(), connection.cursor() as cur:
            # pgvector >= 0.8 keeps scanning the HNSW index until k rows pass the
            # filter. Older versions ignore the setting (savepoint keeps the tx usable).
            try:
                with transaction.atomic():
                    cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
            except DatabaseError:
                pass
            cur.execute(
                f"SELECT chunk_id, 1 - (embedding <=> %s::vector) AS score FROM {self.table} "
                f"WHERE model = %s AND {where} "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                [literal, model, *params, literal, int(k)],
            )
            rows = cur.fetchall()
        rows.sort(key=lambda row: float(row[1]), reverse=True)
        return [(uuid.UUID(str(row[0])), float(row[1])) for row in rows]


class JsonVectorStore:
    """Dev/test store: cosine similarity in Python over the allowed ids only."""

    name = "json"

    def __init__(self, dimension: int):
        self.dimension = int(dimension)

    def available(self) -> bool:
        return True

    def _check(self, vector):
        if len(vector) != self.dimension:
            raise ValueError(f"expected {self.dimension} dimensions, got {len(vector)}")

    def upsert(self, chunk_id, vector, model: str) -> None:
        from knowledge.models import KnowledgeVectorJSON

        self._check(vector)
        KnowledgeVectorJSON.objects.update_or_create(
            chunk_id=chunk_id,
            defaults={"model": model, "dimension": self.dimension, "vector": [float(v) for v in vector]},
        )

    def delete(self, chunk_ids) -> None:
        from knowledge.models import KnowledgeVectorJSON

        KnowledgeVectorJSON.objects.filter(chunk_id__in=list(chunk_ids)).delete()

    def search(self, vector, model: str, allowed_chunk_ids, k: int = 8):
        from knowledge.models import KnowledgeVectorJSON

        self._check(vector)
        ids = list(allowed_chunk_ids)  # a QuerySet of ids evaluates here
        if not ids:
            return []
        qn = math.sqrt(sum(v * v for v in vector)) or 1.0
        scored = []
        for row in KnowledgeVectorJSON.objects.filter(
            chunk_id__in=ids, model=model, dimension=self.dimension
        ).iterator():
            vec = row.vector
            dot = sum(a * b for a, b in zip(vector, vec))
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            scored.append((row.chunk_id, dot / (qn * norm)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: int(k)]


def get_store(dimension: int):
    """The configured store for this dimension, or None when it cannot be used."""
    kind = (getattr(settings, "KNOWLEDGE_VECTOR_STORE", "") or "pgvector").strip()
    if kind == "json":
        return JsonVectorStore(dimension)
    if kind != "pgvector" or int(dimension) not in SUPPORTED_PGVECTOR_DIMENSIONS:
        return None
    store = PgVectorStore(dimension)
    return store if store.available() else None


_SAFE_NAME = re.compile(r"^knowledge_vec_\d+$")
assert all(_SAFE_NAME.match(pgvector_table(d)) for d in SUPPORTED_PGVECTOR_DIMENSIONS)
