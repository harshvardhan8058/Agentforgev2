"""Unit tests for migration-runner logic that does not require a live DB."""

from __future__ import annotations

from agentforge.db.migrations import (
    DEFAULT_MIGRATIONS_DIR,
    discover_migrations,
    render_migration,
)


def test_render_migration_substitutes_embedding_dimension():
    rendered = render_migration(
        "CREATE TABLE t (embedding vector(${EMBEDDING_DIMENSION}) NOT NULL);", 384
    )
    assert "vector(384)" in rendered
    assert "${EMBEDDING_DIMENSION}" not in rendered


def test_render_migration_leaves_untemplated_sql_untouched():
    sql = "CREATE EXTENSION IF NOT EXISTS vector;"
    assert render_migration(sql, 768) == sql


def test_discover_migrations_are_ordered_by_name():
    migrations = discover_migrations(DEFAULT_MIGRATIONS_DIR)
    names = [p.name for p in migrations]
    assert names == sorted(names)
    # The two Phase 1 migrations should be present and in order.
    assert names[0] == "0001_enable_pgvector.sql"
    assert names[1] == "0002_create_core_tables.sql"
