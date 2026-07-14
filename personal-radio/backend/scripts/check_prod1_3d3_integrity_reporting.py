from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import inspect
from pathlib import Path
import shutil
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.routes import library_integrity
from app.schema_maintenance import ensure_scan_reconciliation_columns


def make_db(base: Path):
    db_path = base / "prod1_3d3.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def write_file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def issue(report: dict, issue_type: str) -> dict:
    found = [row for row in report["issues"] if row["type"] == issue_type]
    assert found, f"missing issue {issue_type}: {[row['type'] for row in report['issues']]}"
    return found[0]


def add_track(db, title: str, artist: str, album: str, *, availability: str = "available", year: int = 2026, relative_path: str | None = None, duration: float = 180.0, genre: str = "Hip-Hop", unavailable_since=None, last_seen_scan_id=None, cover_path: str | None = "cover.jpg"):
    rel = relative_path or f"Music/Library/{artist}/{album}/{title}.mp3"
    row = models.Track(
        path=f"C:/host/private/{rel}",
        relative_path=rel,
        title=title,
        artist=artist,
        album=album,
        album_artist=artist,
        genre=genre,
        year=year,
        duration_seconds=duration,
        file_ext=".mp3",
        library_area="Library",
        cover_path=cover_path,
        library_availability=availability,
        unavailable_since=unavailable_since,
        last_seen_scan_id=last_seen_scan_id,
    )
    db.add(row)
    db.flush()
    return row


def add_book(db, title: str, *, availability: str = "available", author: str = "Author", narrator: str | None = None, status: str = "available", favorite: bool = False, unavailable_since=None, last_seen_scan_id=None):
    row = models.Audiobook(path=f"C:/host/private/Audiobooks/{title}", relative_path=f"Audiobooks/{title}", title=title, author=author, narrator=narrator, status=status, favorite=favorite, duration_seconds=3600, library_availability=availability, unavailable_since=unavailable_since, last_seen_scan_id=last_seen_scan_id)
    db.add(row)
    db.flush()
    return row


def add_chapter(db, book, title: str, *, availability: str = "available", sort_order: int = 1, unavailable_since=None):
    row = models.AudiobookChapter(audiobook_id=book.id, path=f"{book.path}/{title}.mp3", relative_path=f"{book.relative_path}/{title}.mp3", title=title, sort_order=sort_order, duration_seconds=600, library_availability=availability, unavailable_since=unavailable_since)
    db.add(row)
    db.flush()
    return row


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_3d3_integrity_reporting"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    fixture = write_file(tmp / "fixture.bin", b"integrity fixture")
    fixture_hash = digest(fixture)
    engine = None
    try:
        engine, Session = make_db(tmp)
        db = Session()
        try:
            # Case A - empty state.
            empty = library_integrity.library_integrity_response(db)
            assert empty["read_only"] is True
            assert empty["summary"]["total_tracks"] == 0
            assert empty["summary"]["available_tracks"] == 0
            assert empty["summary"]["unavailable_tracks"] == 0
            assert issue(empty, "clean_state")["title"] == "No indexed media yet"

            now = datetime.now(timezone.utc)
            scan_music_old = models.ScanRun(media_kind="music", status="succeeded", started_at=now - timedelta(days=3), completed_at=now - timedelta(days=3, minutes=-2), roots_json='["/music"]', items_discovered=5, items_added=1, items_updated=2, items_unavailable=0, error_count=0)
            scan_music_fail = models.ScanRun(media_kind="music", status="failed", started_at=now - timedelta(days=1), completed_at=now - timedelta(days=1, minutes=-1), roots_json='not json', items_discovered=0, error_count=3, error_summary="first line\nsecond line " + "x" * 700)
            scan_audio_running = models.ScanRun(media_kind="audiobook", status="running", started_at=now - timedelta(hours=7), roots_json='["/books"]')
            scan_audio_recent = models.ScanRun(media_kind="audiobook", status="running", started_at=now - timedelta(minutes=15), roots_json='["/books/recent"]')
            db.add_all([scan_music_old, scan_music_fail, scan_audio_running, scan_audio_recent])
            db.flush()

            # Cases B/C/D/I/P - tracks, albums, references, duplicate diagnostics.
            available_mixed = add_track(db, "Song A", "Artist", "Mixed", availability="available", year=2024)
            unavailable_mixed = add_track(db, "Song B", "Artist", "Mixed", availability="unavailable", year=2024, unavailable_since=now - timedelta(hours=4), last_seen_scan_id=scan_music_old.id)
            available_album = add_track(db, "Song C", "Artist", "Available Only", availability="available", year=2025)
            unavailable_only_1 = add_track(db, "Song D", "Ghost", "Gone", availability="unavailable", year=2026, unavailable_since=now - timedelta(hours=3), last_seen_scan_id=scan_music_old.id)
            unavailable_only_2 = add_track(db, "Song E", "Ghost", "Gone", availability="unavailable", year=2026, unavailable_since=now - timedelta(hours=2), last_seen_scan_id=scan_music_old.id)
            duplicate_1 = add_track(db, "Duplicate", "Dup Artist", "Dup Album", availability="available", year=2020, relative_path="a/Duplicate.mp3", duration=200)
            duplicate_2 = add_track(db, "Duplicate", "Dup Artist", "Dup Album", availability="available", year=2020, relative_path="b/Duplicate.mp3", duration=201)
            db.add_all([
                models.Playlist(name="Stored", kind="manual"),
                models.TrackFavorite(track_id=unavailable_mixed.id),
                models.TrackThumb(track_id=unavailable_mixed.id, value=models.ThumbValue.up),
                models.PlaybackEvent(track_id=unavailable_mixed.id, event_type="qualified_play"),
            ])
            db.flush()
            playlist = db.query(models.Playlist).one()
            db.add(models.PlaylistTrack(playlist_id=playlist.id, track_id=unavailable_mixed.id, position=1))

            # Cases E/F/G/H - audiobook totals, unavailable book, partial book, progress on unavailable chapter.
            book_available = add_book(db, "Available Book")
            add_chapter(db, book_available, "01", availability="available", sort_order=1)
            missing_book = add_book(db, "Missing Book", availability="unavailable", status="finished", favorite=True, unavailable_since=now - timedelta(hours=2), last_seen_scan_id=scan_audio_running.id)
            missing_chapter = add_chapter(db, missing_book, "01", availability="unavailable", unavailable_since=now - timedelta(hours=2))
            partial_book = add_book(db, "Partial Book", status="in_progress")
            partial_available = add_chapter(db, partial_book, "01", availability="available", sort_order=1)
            partial_missing = add_chapter(db, partial_book, "02", availability="unavailable", sort_order=2, unavailable_since=now - timedelta(hours=1))
            db.add_all([
                models.AudiobookProgress(audiobook_id=missing_book.id, chapter_id=missing_chapter.id, position_seconds=90, progress_percent=20, status="in_progress"),
                models.AudiobookProgress(audiobook_id=partial_book.id, chapter_id=partial_missing.id, position_seconds=120, progress_percent=50, status="in_progress"),
                models.PlaybackEvent(audiobook_id=missing_book.id, event_type="start"),
            ])
            db.commit()

            report = library_integrity.library_integrity_response(db)
            summary = report["summary"]
            assert summary["total_tracks"] == 7
            assert summary["available_tracks"] == 4
            assert summary["unavailable_tracks"] == 3
            assert summary["total_albums"] == 4
            assert summary["available_albums"] == 3
            assert summary["unavailable_only_albums"] == 1
            assert summary["total_audiobooks"] == 3
            assert summary["available_audiobooks"] == 2
            assert summary["unavailable_audiobooks"] == 1
            assert summary["total_audiobook_chapters"] == 4
            assert summary["available_audiobook_chapters"] == 2
            assert summary["unavailable_audiobook_chapters"] == 2
            assert summary["partial_audiobooks"] == 1
            assert summary["audiobooks_with_unavailable_progress_chapter"] == 2

            unavailable_tracks = issue(report, "unavailable_tracks")
            assert unavailable_tracks["id"] == "unavailable-tracks"
            assert unavailable_tracks["count"] == 3
            sample = unavailable_tracks["items"][0]
            assert "C:/host/private" not in str(sample.get("path"))
            assert sample["last_seen_scan_id"] == scan_music_old.id
            assert "playlist_membership_count" in sample
            assert unavailable_tracks["read_only"] is True

            unavailable_books = issue(report, "unavailable_audiobooks")
            assert unavailable_books["count"] == 1
            book_sample = unavailable_books["items"][0]
            assert book_sample["favorite"] is True
            assert book_sample["status"] == "finished"
            assert book_sample["progress_chapter_id"] == missing_chapter.id
            assert book_sample["playback_event_count"] == 1

            partial = issue(report, "partial_audiobooks")
            assert partial["severity"] == "error"
            assert partial["items"][0]["unavailable_chapter_count"] == 1
            progress_issue = issue(report, "audiobook_progress_on_unavailable_chapter")
            assert progress_issue["count"] == 2
            historical = issue(report, "historical_state_on_unavailable_tracks")
            assert historical["items"][0]["unavailable_track_playlist_memberships"] == 1
            assert historical["items"][0]["unavailable_track_favorites"] == 1
            assert historical["items"][0]["unavailable_track_thumbs"] == 1
            assert historical["items"][0]["unavailable_track_playback_events"] == 1

            # Cases J/N/O - scan history endpoint filtering, malformed roots, bounded error summary.
            all_runs = library_integrity.scan_runs(media_kind=None, status=None, limit=3, db=db)
            assert len(all_runs["items"]) == 3
            assert all_runs["items"][0]["started_at"] >= all_runs["items"][1]["started_at"]
            assert library_integrity.scan_runs(media_kind="music", status=None, limit=10, db=db)["items"][0]["media_kind"] == "music"
            assert library_integrity.scan_runs(media_kind=None, status="failed", limit=10, db=db)["items"][0]["status"] == "failed"
            assert library_integrity.scan_runs(media_kind=None, status=None, limit=500, db=db)["limit"] == 100
            failed_item = library_integrity.scan_runs(media_kind=None, status="failed", limit=1, db=db)["items"][0]
            assert failed_item["roots"] == [] and failed_item["roots_parse_error"] is True
            assert "\n" not in failed_item["error_summary"] and len(failed_item["error_summary"]) <= library_integrity.MAX_ERROR_SUMMARY_CHARS

            # Cases K/L/M - latest scan, stale running, failed issue.
            assert summary["latest_music_scan_status"] == "failed"
            assert summary["latest_audiobook_scan_status"] == "running"
            assert summary["stale_running_scan_runs"] == 1
            assert issue(report, "stale_scan_runs")["count"] == 1
            assert db.get(models.ScanRun, scan_audio_running.id).status == "running"
            assert issue(report, "failed_scan_runs")["count"] == 1

            # Cases P/Q/R/S - old diagnostics, N+1 removal, aggregate structure, stable issue IDs.
            assert issue(report, "strong_duplicate_candidate")["count"] == 2
            source = inspect.getsource(library_integrity.library_integrity_response)
            assert "chapter_count = db.query" not in source
            assert "total_tracks = scalar_count" in source
            report_again = library_integrity.library_integrity_response(db)
            new_ids = sorted(row["id"] for row in report["issues"] if row["type"] in {"unavailable_tracks", "unavailable_audiobooks", "partial_audiobooks", "audiobook_progress_on_unavailable_chapter", "historical_state_on_unavailable_tracks", "stale_scan_runs", "failed_scan_runs"})
            new_ids_again = sorted(row["id"] for row in report_again["issues"] if row["type"] in {"unavailable_tracks", "unavailable_audiobooks", "partial_audiobooks", "audiobook_progress_on_unavailable_chapter", "historical_state_on_unavailable_tracks", "stale_scan_runs", "failed_scan_runs"})
            assert new_ids == new_ids_again

            # Cases T/U - no row deletion and no media mutation.
            assert db.query(models.Track).count() == 7
            assert db.query(models.Audiobook).count() == 3
            assert db.query(models.AudiobookChapter).count() == 4
            assert db.query(models.PlaylistTrack).count() == 1
            assert db.query(models.TrackFavorite).count() == 1
            assert db.query(models.TrackThumb).count() == 1
            assert db.query(models.PlaybackEvent).count() >= 2
            assert db.query(models.ScanRun).count() == 4
            assert digest(fixture) == fixture_hash
        finally:
            db.close()
    finally:
        if engine is not None:
            engine.dispose()
        if tmp.exists():
            shutil.rmtree(tmp)

    print("PASS: BM-PROD1.3D3 integrity reporting and scan history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())