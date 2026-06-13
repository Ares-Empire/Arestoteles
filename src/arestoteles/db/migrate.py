"""Tiny forward-only migration runner: applies migrations/*.sql in lexical order.

Each file runs in one transaction and is recorded in schema_migrations. No down
migrations — this is an append-only ledger of schema changes, matching the
fail-closed philosophy (a half-applied migration rolls back and the run stops).

Usage: python -m arestoteles.db.migrate
"""

from pathlib import Path

from sqlalchemy import Engine, text

from arestoteles.config import REPO_ROOT
from arestoteles.log import get_logger, setup_logging

log = get_logger(__name__)

MIGRATIONS_DIR = REPO_ROOT / "migrations"


def applied_versions(engine: Engine) -> set[str]:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version    text PRIMARY KEY,"
            "  applied_at timestamptz NOT NULL DEFAULT now()"
            ")"
        )
        rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {r[0] for r in rows}


def migrate(engine: Engine, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations; returns the versions applied this call."""
    done = applied_versions(engine)
    applied: list[str] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.stem
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        with engine.begin() as conn:
            conn.exec_driver_sql(sql)
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": version}
            )
        log.info("migration applied", version=version)
        applied.append(version)
    if not applied:
        log.info("schema up to date", versions=len(done))
    return applied


if __name__ == "__main__":
    from arestoteles.db.engine import get_engine

    setup_logging()
    migrate(get_engine())
