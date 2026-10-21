"""Enable pgvector when the server offers it, then create the 1024-dim vector table.

Never aborts the migration: if the extension is not available (or the role
cannot create it), the step records nothing and memory search reports
"Not configured" at runtime. SQLite skips the SQL entirely.
"""

from django.db import migrations, models, transaction


def enable_pgvector(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != "postgresql":
        return
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        if cur.fetchone() is None:
            return
    try:
        with transaction.atomic(using=conn.alias):
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception:
        return  # for example, missing privilege; runtime shows "Not configured"

    from knowledge.store import SUPPORTED_PGVECTOR_DIMENSIONS, ensure_pgvector_table

    with conn.cursor() as cur:
        for dim in SUPPORTED_PGVECTOR_DIMENSIONS:
            ensure_pgvector_table(cur, dim)


def drop_vector_tables(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != "postgresql":
        return
    from knowledge.store import SUPPORTED_PGVECTOR_DIMENSIONS, pgvector_table

    with conn.cursor() as cur:
        for dim in SUPPORTED_PGVECTOR_DIMENSIONS:
            cur.execute(f"DROP TABLE IF EXISTS {pgvector_table(dim)}")
    # The extension is left installed: other databases objects may use it.


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="KnowledgeVectorJSON",
            fields=[
                ("chunk_id", models.UUIDField(primary_key=True, serialize=False)),
                ("model", models.CharField(max_length=128)),
                ("dimension", models.PositiveIntegerField()),
                ("vector", models.JSONField()),
            ],
            options={"db_table": "knowledge_vectors_json"},
        ),
        migrations.RunPython(enable_pgvector, drop_vector_tables),
    ]
