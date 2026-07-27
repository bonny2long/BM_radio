from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.scan_runs import complete_scan_run, fail_scan_run, mark_audiobook_seen, mark_track_seen, start_scan_run
from app.schema_maintenance import ensure_scan_reconciliation_columns


REQUIRED_TRACK_COLUMNS = {"library_availability", "last_seen_scan_id", "unavailable_since"}
REQUIRED_AUDIOBOOK_COLUMNS = {"library_availability", "last_seen_scan_id", "unavailable_since"}
REQUIRED_INDEXES = {
    "tracks": {"ix_tracks_library_availability", "ix_tracks_last_seen_scan_id"},
    "audiobooks": {"ix_audiobooks_library_availability", "ix_audiobooks_last_seen_scan_id"},
    "scan_runs": {"ix_scan_runs_media_kind", "ix_scan_runs_status", "ix_scan_runs_started_at"},
}


def sqlite_engine(db_path: Path):
    return create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})


def create_fresh_db(db_path: Path):
    engine = sqlite_engine(db_path)
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def table_columns(engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def table_indexes(engine, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes(table_name)}


def case_a_new_schema_exists(tmp: Path) -> None:
    engine, _ = create_fresh_db(tmp / "case_a.db")
    assert "scan_runs" in inspect(engine).get_table_names()
    assert REQUIRED_TRACK_COLUMNS.issubset(table_columns(engine, "tracks"))
    assert REQUIRED_AUDIOBOOK_COLUMNS.issubset(table_columns(engine, "audiobooks"))


def case_b_new_row_defaults(tmp: Path) -> None:
    _, Session = create_fresh_db(tmp / "case_b.db")
    db = Session()
    try:
        track = models.Track(path="/music/default.flac", title="Default Track")
        audiobook = models.Audiobook(path="/books/default", title="Default Book", author="Author")
        db.add_all([track, audiobook])
        db.commit()
        db.refresh(track)
        db.refresh(audiobook)
        assert track.library_availability == "available"
        assert track.last_seen_scan_id is None
        assert track.unavailable_since is None
        assert audiobook.library_availability == "available"
        assert audiobook.last_seen_scan_id is None
        assert audiobook.unavailable_since is None
        assert audiobook.status == "available"
    finally:
        db.close()


def case_c_scan_run_lifecycle(tmp: Path) -> None:
    _, Session = create_fresh_db(tmp / "case_c.db")
    db = Session()
    try:
        scan_run = start_scan_run(db, media_kind="music", roots=["/Music/Library/FLAC", "/Music/Library/MP3"])
        db.commit()
        db.refresh(scan_run)
        assert scan_run.media_kind == "music"
        assert scan_run.status == "running"
        assert scan_run.started_at is not None
        assert scan_run.completed_at is None
        assert json.loads(scan_run.roots_json) == ["/Music/Library/FLAC", "/Music/Library/MP3"]

        complete_scan_run(db, scan_run, items_discovered=12, items_added=3, items_updated=9, items_unavailable=0, error_count=0)
        db.commit()
        db.refresh(scan_run)
        assert scan_run.status == "succeeded"
        assert scan_run.completed_at is not None
        assert scan_run.items_discovered == 12
        assert scan_run.items_added == 3
        assert scan_run.items_updated == 9
        assert scan_run.items_unavailable == 0
        assert scan_run.error_count == 0
    finally:
        db.close()


def case_d_failed_scan_lifecycle(tmp: Path) -> None:
    _, Session = create_fresh_db(tmp / "case_d.db")
    db = Session()
    try:
        audiobook = models.Audiobook(path="/books/fail", title="Failure Book", author="Author", library_availability="available")
        db.add(audiobook)
        scan_run = start_scan_run(db, media_kind="audiobook", roots=["/Audiobooks/Library"])
        fail_scan_run(db, scan_run, error_summary="scanner stopped before completion", error_count=2)
        db.commit()
        db.refresh(scan_run)
        db.refresh(audiobook)
        assert scan_run.status == "failed"
        assert scan_run.completed_at is not None
        assert scan_run.error_count == 2
        assert scan_run.error_summary == "scanner stopped before completion"
        assert audiobook.library_availability == "available"
        assert audiobook.unavailable_since is None
    finally:
        db.close()


def case_e_mark_track_seen(tmp: Path) -> None:
    _, Session = create_fresh_db(tmp / "case_e.db")
    db = Session()
    try:
        old_timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
        track = models.Track(
            path="/music/returned.flac",
            title="Returned Track",
            library_availability="unavailable",
            unavailable_since=old_timestamp,
        )
        favorite = models.TrackFavorite(track=track)
        thumb = models.TrackThumb(track=track, value=models.ThumbValue.up)
        db.add_all([track, favorite, thumb])
        scan_run = start_scan_run(db, media_kind="music", roots=["/Music/Library/FLAC"])
        db.flush()
        favorite_id = favorite.id
        thumb_id = thumb.id
        mark_track_seen(track, scan_run_id=scan_run.id)
        db.commit()
        db.refresh(track)
        assert track.library_availability == "available"
        assert track.last_seen_scan_id == scan_run.id
        assert track.unavailable_since is None
        assert db.get(models.TrackFavorite, favorite_id).track_id == track.id
        assert db.get(models.TrackThumb, thumb_id).value == models.ThumbValue.up
    finally:
        db.close()


def case_f_mark_audiobook_seen(tmp: Path) -> None:
    _, Session = create_fresh_db(tmp / "case_f.db")
    db = Session()
    try:
        old_timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
        audiobook = models.Audiobook(
            path="/books/returned",
            title="Returned Book",
            author="Author",
            status="in_progress",
            library_availability="unavailable",
            unavailable_since=old_timestamp,
        )
        db.add(audiobook)
        scan_run = start_scan_run(db, media_kind="audiobook", roots=["/Audiobooks/Library"])
        db.flush()
        mark_audiobook_seen(audiobook, scan_run_id=scan_run.id)
        db.commit()
        db.refresh(audiobook)
        assert audiobook.status == "in_progress"
        assert audiobook.library_availability == "available"
        assert audiobook.last_seen_scan_id == scan_run.id
        assert audiobook.unavailable_since is None
    finally:
        db.close()


def case_g_existing_sqlite_upgrade(tmp: Path) -> None:
    engine = sqlite_engine(tmp / "case_g_legacy.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tracks (id INTEGER PRIMARY KEY, path VARCHAR UNIQUE, title VARCHAR)"))
        conn.execute(text("CREATE TABLE audiobooks (id INTEGER PRIMARY KEY, path VARCHAR UNIQUE, title VARCHAR, author VARCHAR, status VARCHAR)"))
        conn.execute(text("INSERT INTO tracks (id, path, title) VALUES (1, '/legacy/music.flac', 'Legacy Track')"))
        conn.execute(text("INSERT INTO audiobooks (id, path, title, author, status) VALUES (1, '/legacy/book', 'Legacy Book', 'Author', 'in_progress')"))

    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    ensure_scan_reconciliation_columns(engine)

    assert REQUIRED_TRACK_COLUMNS.issubset(table_columns(engine, "tracks"))
    assert REQUIRED_AUDIOBOOK_COLUMNS.issubset(table_columns(engine, "audiobooks"))
    with engine.begin() as conn:
        track = conn.execute(text("SELECT path, library_availability, last_seen_scan_id, unavailable_since FROM tracks WHERE id = 1")).one()
        audiobook = conn.execute(text("SELECT path, status, library_availability, last_seen_scan_id, unavailable_since FROM audiobooks WHERE id = 1")).one()
    assert track.path == "/legacy/music.flac"
    assert track.library_availability == "available"
    assert track.last_seen_scan_id is None
    assert track.unavailable_since is None
    assert audiobook.path == "/legacy/book"
    assert audiobook.status == "in_progress"
    assert audiobook.library_availability == "available"
    assert audiobook.last_seen_scan_id is None
    assert audiobook.unavailable_since is None


def case_h_no_reconciliation_yet(tmp: Path) -> None:
    _, Session = create_fresh_db(tmp / "case_h.db")
    db = Session()
    try:
        seen = models.Track(path="/music/seen.flac", title="Seen", library_availability="available")
        unseen = models.Track(path="/music/unseen.flac", title="Unseen", library_availability="available")
        db.add_all([seen, unseen])
        scan_run = start_scan_run(db, media_kind="music", roots=["/Music/Library/FLAC"])
        db.flush()
        mark_track_seen(seen, scan_run_id=scan_run.id)
        complete_scan_run(db, scan_run, items_discovered=1, items_added=0, items_updated=1)
        db.commit()
        db.refresh(unseen)
        assert unseen.library_availability == "available"
        assert unseen.last_seen_scan_id is None
        assert unseen.unavailable_since is None
    finally:
        db.close()


def case_i_indexes(tmp: Path) -> None:
    engine, _ = create_fresh_db(tmp / "case_i.db")
    for table_name, expected_indexes in REQUIRED_INDEXES.items():
        actual = table_indexes(engine, table_name)
        assert expected_indexes.issubset(actual), (table_name, expected_indexes, actual)


def case_j_audiobook_progress_separation(tmp: Path) -> None:
    _, Session = create_fresh_db(tmp / "case_j.db")
    db = Session()
    try:
        audiobook = models.Audiobook(
            path="/books/progress",
            title="Progress Book",
            author="Author",
            status="in_progress",
            library_availability="unavailable",
        )
        progress = models.AudiobookProgress(
            audiobook=audiobook,
            position_seconds=123.0,
            progress_percent=12.5,
            status="in_progress",
        )
        db.add_all([audiobook, progress])
        scan_run = start_scan_run(db, media_kind="audiobook", roots=["/Audiobooks/Library"])
        db.flush()
        progress_id = progress.id
        mark_audiobook_seen(audiobook, scan_run_id=scan_run.id)
        complete_scan_run(db, scan_run, items_discovered=1, items_added=0, items_updated=1)
        db.commit()
        db.refresh(audiobook)
        saved_progress = db.get(models.AudiobookProgress, progress_id)
        assert audiobook.status == "in_progress"
        assert audiobook.library_availability == "available"
        assert saved_progress is not None
        assert saved_progress.audiobook_id == audiobook.id
        assert saved_progress.position_seconds == 123.0
        assert saved_progress.status == "in_progress"
    finally:
        db.close()


def main() -> None:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_3a_scan_run_foundation"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_new_schema_exists(tmp)
        case_b_new_row_defaults(tmp)
        case_c_scan_run_lifecycle(tmp)
        case_d_failed_scan_lifecycle(tmp)
        case_e_mark_track_seen(tmp)
        case_f_mark_audiobook_seen(tmp)
        case_g_existing_sqlite_upgrade(tmp)
        case_h_no_reconciliation_yet(tmp)
        case_i_indexes(tmp)
        case_j_audiobook_progress_separation(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.3A scan-run foundation")


if __name__ == "__main__":
    main()
