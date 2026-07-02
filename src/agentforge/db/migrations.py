"""Migration runner.

Applies the versioned SQL migrations in the top-level ``migrations/`` directory on
startup (Req 4.2). The runner:

* Templates ``${EMBEDDING_DIMENSION}`` from the Configuration_Manager so the vector
  column is sized to the configured embedding dimension (Req 4.3).
* Tracks applied migrations in a ``schema_migrations`` table so re-running is safe.
* Halts on the first failure and reports the failing migration identifier via
  ``MigrationError`` (Req 4.4).
"""

from __future__ import annotations

from pathlib import Path
from string import Template

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# migrations/ lives at the repository root: <repo>/migrations, and this file is at
# <repo>/src/agentforge/db/migrations.py -> parents[3] is the repo root.
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"

_CREATE_TRACKING = text(
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        id          TEXT PRIMARY KEY,
        applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """
)

_SELECT_APPLIED = text("SELECT id FROM schema_migrations")
_INSERT_APPLIED = text("INSERT INTO schema_migrations (id) VALUES (:id)")


class MigrationError(RuntimeError):
    """Raised when a migration fails; identifies the failing migration id (Req 4.4)."""

    def __init__(self, migration_id: str, cause: Exception) -> None:
        self.migration_id = migration_id
        self.cause = cause
        super().__init__(f"Migration '{migration_id}' failed: {cause}")


def discover_migrations(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> list[Path]:
    """Return migration files sorted by their numeric prefix / filename."""
    if not migrations_dir.is_dir():
        return []
    return sorted(migrations_dir.glob("*.sql"), key=lambda p: p.name)


def render_migration(sql: str, embedding_dimension: int) -> str:
    """Substitute template variables (currently the embedding dimension)."""
    return Template(sql).safe_substitute(EMBEDDING_DIMENSION=str(embedding_dimension))


async def run_migrations(
    engine: AsyncEngine,
    embedding_dimension: int,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> list[str]:
    """Apply pending migrations in order.

    Returns the list of migration ids applied during this run. Halts on the first
    failure, raising ``MigrationError`` naming the failing migration (Req 4.4).
    """
    migrations = discover_migrations(migrations_dir)
    applied: list[str] = []

    async with engine.begin() as conn:
        await conn.execute(_CREATE_TRACKING)
        rows = await conn.execute(_SELECT_APPLIED)
        already = {r[0] for r in rows}

    for path in migrations:
        migration_id = path.stem
        if migration_id in already:
            continue
        raw = path.read_text(encoding="utf-8")
        rendered = render_migration(raw, embedding_dimension)
        try:
            async with engine.begin() as conn:
                # exec_driver_sql runs the full script (multiple statements) as-is.
                await conn.exec_driver_sql(rendered)
                await conn.execute(_INSERT_APPLIED, {"id": migration_id})
        except Exception as exc:  # noqa: BLE001 - re-wrapped with the failing id
            raise MigrationError(migration_id, exc) from exc
        applied.append(migration_id)

    return applied
