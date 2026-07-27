from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


SCAN_RECONCILIATION_COLUMNS = {
    "tracks": {
        "library_availability": "VARCHAR DEFAULT 'available'",
        "last_seen_scan_id": "INTEGER",
        "unavailable_since": "DATETIME",
    },
    "audiobooks": {
        "library_availability": "VARCHAR DEFAULT 'available'",
        "last_seen_scan_id": "INTEGER",
        "unavailable_since": "DATETIME",
    },
    "audiobook_chapters": {
        "library_availability": "VARCHAR DEFAULT 'available'",
        "last_seen_scan_id": "INTEGER",
        "unavailable_since": "DATETIME",
    },
}


PLAYBACK_IDENTITY_COLUMNS = {
    "playback_events": {
        "recording_id": "INTEGER",
    },
}

PLAYBACK_IDENTITY_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_playback_events_recording_id ON playback_events (recording_id)",
]


RECORDING_FEEDBACK_COLUMNS = {
    "track_favorites": {
        "recording_id": "INTEGER",
    },
    "track_thumbs": {
        "recording_id": "INTEGER",
    },
}

RECORDING_FEEDBACK_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_track_favorites_recording_id ON track_favorites (recording_id)",
    "CREATE INDEX IF NOT EXISTS ix_track_thumbs_recording_id ON track_thumbs (recording_id)",
]

SCAN_RECONCILIATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_tracks_library_availability ON tracks (library_availability)",
    "CREATE INDEX IF NOT EXISTS ix_tracks_last_seen_scan_id ON tracks (last_seen_scan_id)",
    "CREATE INDEX IF NOT EXISTS ix_audiobooks_library_availability ON audiobooks (library_availability)",
    "CREATE INDEX IF NOT EXISTS ix_audiobooks_last_seen_scan_id ON audiobooks (last_seen_scan_id)",
    "CREATE INDEX IF NOT EXISTS ix_audiobook_chapters_library_availability ON audiobook_chapters (library_availability)",
    "CREATE INDEX IF NOT EXISTS ix_audiobook_chapters_last_seen_scan_id ON audiobook_chapters (last_seen_scan_id)",
    "CREATE INDEX IF NOT EXISTS ix_scan_runs_media_kind ON scan_runs (media_kind)",
    "CREATE INDEX IF NOT EXISTS ix_scan_runs_status ON scan_runs (status)",
    "CREATE INDEX IF NOT EXISTS ix_scan_runs_started_at ON scan_runs (started_at)",
]


def _require_sqlite_engine(engine: Engine) -> None:
    if engine.dialect.name != 'sqlite':
        raise ValueError('legacy schema maintenance is SQLite-only')


def _existing_tables(engine: Engine) -> set[str]:
    try:
        return set(inspect(engine).get_table_names())
    except Exception:
        return set()


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


def _backfill_available(engine: Engine, table_name: str) -> None:
    if "library_availability" not in _existing_columns(engine, table_name):
        return
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE {table_name} SET library_availability = 'available' WHERE library_availability IS NULL"))


def _create_indexes(engine: Engine, statements: list[str]) -> None:
    existing_tables = _existing_tables(engine)
    with engine.begin() as conn:
        for statement in statements:
            table_name = statement.split(" ON ", 1)[1].split(" ", 1)[0]
            if table_name in existing_tables:
                conn.execute(text(statement))


def ensure_manifest_ingestion_columns(engine: Engine) -> None:
    """Add lightweight SQLite columns introduced by manifest-first ingestion.

    SQLAlchemy create_all() creates missing tables, but it does not migrate existing
    tables. BM Radio is still pre-migration-tooling, so keep this intentionally
    narrow and additive for local SQLite DBs.
    """
    _require_sqlite_engine(engine)
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


def ensure_scan_reconciliation_columns(engine: Engine) -> None:
    """Add scan-run reconciliation fields for existing SQLite databases.

    BM Radio is additive here: preserve existing rows, backfill library
    availability as available, and create the narrow indexes needed for later
    reconciliation queries.
    """
    _require_sqlite_engine(engine)
    existing_tables = _existing_tables(engine)
    for table_name, columns in SCAN_RECONCILIATION_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        _add_missing_columns(engine, table_name, columns)
        _backfill_available(engine, table_name)

    _create_indexes(engine, SCAN_RECONCILIATION_INDEXES)

def ensure_playback_identity_columns(engine: Engine) -> None:
    """Add recording identity to existing SQLite playback event tables."""
    _require_sqlite_engine(engine)
    existing_tables = _existing_tables(engine)
    for table_name, columns in PLAYBACK_IDENTITY_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        _add_missing_columns(engine, table_name, columns)

    _create_indexes(engine, PLAYBACK_IDENTITY_INDEXES)

def ensure_recording_feedback_columns(engine: Engine) -> None:
    """Add recording identity to existing SQLite favorite/thumb tables."""
    _require_sqlite_engine(engine)
    existing_tables = _existing_tables(engine)
    for table_name, columns in RECORDING_FEEDBACK_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        _add_missing_columns(engine, table_name, columns)

    _create_indexes(engine, RECORDING_FEEDBACK_INDEXES)
