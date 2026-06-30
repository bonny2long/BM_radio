from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def _existing_columns(engine: Engine, table_name: str) -> set[str]:
    try:
        return {column["name"] for column in inspect(engine).get_columns(table_name)}
    except Exception:
        return set()


def _add_missing_columns(engine: Engine, table_name: str, columns: dict[str, str]) -> None:
    existing = _existing_columns(engine, table_name)
    missing = [(name, ddl) for name, ddl in columns.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"))


def ensure_manifest_ingestion_columns(engine: Engine) -> None:
    """Add lightweight SQLite columns introduced by manifest-first ingestion.

    SQLAlchemy create_all() creates missing tables, but it does not migrate existing
    tables. BM Radio is still pre-migration-tooling, so keep this intentionally
    narrow and additive for local SQLite DBs.
    """
    if engine.dialect.name != "sqlite":
        return

    _add_missing_columns(engine, "tracks", {
        "metadata_source": "VARCHAR",
        "source_manifest_path": "VARCHAR",
        "source_manifest_version": "VARCHAR",
        "source_metadata_version": "VARCHAR",
        "track_number": "INTEGER",
        "disc_number": "INTEGER",
        "primary_genre": "VARCHAR",
    })
    _add_missing_columns(engine, "audiobooks", {
        "metadata_source": "VARCHAR",
        "source_manifest_path": "VARCHAR",
        "source_manifest_version": "VARCHAR",
        "source_metadata_version": "VARCHAR",
    })