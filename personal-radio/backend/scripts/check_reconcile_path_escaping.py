from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.models import Audiobook, Track
from app.scan_runs import _path_prefix_filters, reconcile_unseen_audiobooks, reconcile_unseen_tracks

SCRATCH_DATABASE = "bm_radio_scratch_reconcile_check"


def case_a_prefix_filter_carries_an_explicit_escape() -> None:
    root = Path(r"C:\NAS-Local\nas-data\Audiobooks\Library")
    (condition,) = _path_prefix_filters(Audiobook.path, [root])
    sql = str(condition.compile(dialect=postgresql.dialect()))
    assert "ESCAPE" in sql.upper(), sql


def run_scenario(engine, root: Path) -> None:
    """Files that disappeared are marked unavailable; seen files and files outside the root are not."""
    other = root.parent / "AudioXbooksY" / "Library"
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            Audiobook(path=str(root / "Author" / "Seen Book"), title="Seen", library_availability="available", last_seen_scan_id=5),
            Audiobook(path=str(root / "Author" / "Gone Book_ (1) 100%"), title="Gone", library_availability="available", last_seen_scan_id=4),
            Audiobook(path=str(other / "Author" / "Elsewhere"), title="Elsewhere", library_availability="available", last_seen_scan_id=4),
            Track(path=str(root / "Artist" / "Album" / "01 Seen.flac"), title="Seen", library_availability="available", last_seen_scan_id=5),
            Track(path=str(root / "Artist" / "Album" / "02 Gone_.flac"), title="Gone", library_availability="available", last_seen_scan_id=4),
            Track(path=str(other / "Artist" / "Album" / "03 Elsewhere.flac"), title="Elsewhere", library_availability="available", last_seen_scan_id=4),
        ])
        db.commit()
        books, _chapters = reconcile_unseen_audiobooks(db, scan_run_id=5, scanned_root=root, unavailable_at=datetime.now(timezone.utc))
        tracks = reconcile_unseen_tracks(db, scan_run_id=5, scanned_roots=[root])
        db.commit()
        book_state = {book.title: book.library_availability for book in db.query(Audiobook).all()}
        track_state = {track.title: track.library_availability for track in db.query(Track).all()}
    assert (books, tracks) == (1, 1), (books, tracks)
    assert book_state == {"Seen": "available", "Gone": "unavailable", "Elsewhere": "available"}, book_state
    assert track_state == {"Seen": "available", "Gone": "unavailable", "Elsewhere": "available"}, track_state


def case_b_sqlite() -> None:
    with tempfile.TemporaryDirectory(prefix="bm-reconcile-") as tmp:
        engine = create_engine("sqlite:///:memory:")
        run_scenario(engine, Path(tmp) / "Audio_books%" / "Library")


def case_c_postgresql_scratch_database() -> str:
    url = make_url(settings.BM_RADIO_DB_URL)
    if not url.drivername.startswith("postgresql"):
        return "SKIP not configured for PostgreSQL"
    assert url.database != SCRATCH_DATABASE
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{SCRATCH_DATABASE}" WITH (FORCE)')
            connection.exec_driver_sql(f'CREATE DATABASE "{SCRATCH_DATABASE}"')
    except Exception as exc:  # database not reachable: the other cases still cover the logic
        admin.dispose()
        return f"SKIP PostgreSQL not reachable ({type(exc).__name__})"
    scratch = create_engine(url.set(database=SCRATCH_DATABASE))
    try:
        with tempfile.TemporaryDirectory(prefix="bm-reconcile-") as tmp:
            run_scenario(scratch, Path(tmp) / "Audio_books%" / "Library")
    finally:
        scratch.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{SCRATCH_DATABASE}" WITH (FORCE)')
        admin.dispose()
    return "PASS"


def main() -> int:
    case_a_prefix_filter_carries_an_explicit_escape()
    print("PASS case_a_prefix_filter_carries_an_explicit_escape")
    case_b_sqlite()
    print("PASS case_b_sqlite")
    print(f"{case_c_postgresql_scratch_database()} case_c_postgresql_scratch_database")
    print("reconcile path escaping checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
