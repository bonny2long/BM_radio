from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import shutil
import sys
from typing import Iterator

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.availability import active_audiobooks, active_chapters, active_tracks, is_audiobook_available, is_chapter_available, is_track_available
from app.config import settings
from app.schema_maintenance import ensure_scan_reconciliation_columns
from app.routes import audiobooks, library, media, search, serializers


SETTING_NAMES = (
    "MUSIC_LIBRARY_ROOT",
    "MUSIC_DISCOGRAPHIES_ROOT",
    "BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN",
    "AUDIOBOOKS_ROOT",
    "BM_RADIO_AUDIOBOOK_ROOT",
)


@contextmanager
def temporary_settings(**overrides: object) -> Iterator[None]:
    original = {name: getattr(settings, name) for name in SETTING_NAMES}
    try:
        for name, value in overrides.items():
            setattr(settings, name, value)
        yield
    finally:
        for name, value in original.items():
            setattr(settings, name, value)


def make_db(base: Path):
    db_path = base / "prod1_3d1.db"
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


def expect_http(status_code: int, func, *args, **kwargs) -> HTTPException:
    try:
        func(*args, **kwargs)
    except HTTPException as exc:
        assert exc.status_code == status_code, f"expected {status_code}, got {exc.status_code}: {exc.detail}"
        return exc
    raise AssertionError(f"expected HTTPException {status_code}")


def run_async(value):
    return asyncio.run(value)


def track(db, *, path: Path, title: str, artist: str, album: str, availability: str = "available", genre: str = "Test", cover_path: Path | None = None):
    row = models.Track(path=str(path), relative_path=path.name, title=title, artist=artist, album=album, album_artist=artist, genre=genre, year=2026, duration_seconds=60, file_ext=path.suffix.lower(), library_area="Library", cover_path=str(cover_path) if cover_path else None, library_availability=availability)
    db.add(row)
    db.flush()
    return row


def book(db, *, path: Path, title: str, author: str, availability: str = "available", status: str = "available", favorite: bool = False):
    row = models.Audiobook(path=str(path), relative_path=path.name, title=title, author=author, status=status, favorite=favorite, duration_seconds=180, library_availability=availability)
    db.add(row)
    db.flush()
    return row


def chapter(db, *, audiobook_id: int, path: Path, title: str, sort_order: int, availability: str = "available"):
    row = models.AudiobookChapter(audiobook_id=audiobook_id, path=str(path), relative_path=path.name, title=title, chapter_number=sort_order, duration_seconds=60, sort_order=sort_order, library_availability=availability)
    db.add(row)
    db.flush()
    return row


def add_progress(db, *, audiobook_id: int, chapter_id: int | None, seconds: float):
    row = models.AudiobookProgress(audiobook_id=audiobook_id, chapter_id=chapter_id, position_seconds=seconds, progress_percent=50, status="in_progress", updated_at=datetime.now(timezone.utc))
    db.add(row)
    db.flush()
    return row


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_3d1_core_availability_policy"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    engine = None
    try:
        music_root = tmp / "Music" / "Library"
        music_mp3 = music_root / "MP3"
        discog_root = tmp / "Music" / "Discographies"
        audiobook_root = tmp / "Audiobooks" / "Library"
        music_mp3.mkdir(parents=True)
        discog_root.mkdir(parents=True)
        audiobook_root.mkdir(parents=True)

        engine, Session = make_db(tmp)
        db = Session()
        media_files: list[Path] = []
        try:
            available_track_path = write_file(music_mp3 / "mixed" / "available.mp3", b"available music")
            unavailable_track_path = write_file(music_mp3 / "mixed" / "unavailable.mp3", b"unavailable music")
            ghost_track_path = write_file(music_mp3 / "ghost" / "ghost.mp3", b"ghost music")
            available_cover = write_file(music_mp3 / "mixed" / "cover.jpg", b"available cover")
            unavailable_cover = write_file(music_mp3 / "mixed" / "old-cover.jpg", b"unavailable cover")
            media_files.extend([available_track_path, unavailable_track_path, ghost_track_path, available_cover, unavailable_cover])

            available_track = track(db, path=available_track_path, title="Shared Needle", artist="Mixed Artist", album="Mixed Album", cover_path=available_cover)
            unavailable_track = track(db, path=unavailable_track_path, title="Shared Needle Gone", artist="Mixed Artist", album="Mixed Album", availability="unavailable", cover_path=unavailable_cover)
            ghost_track = track(db, path=ghost_track_path, title="Ghost Needle", artist="Ghost Artist", album="Ghost Album", availability="unavailable")

            active_book_path = audiobook_root / "Author" / "Active Saga"
            ghost_book_path = audiobook_root / "Author" / "Ghost Tome"
            active_book = book(db, path=active_book_path, title="Active Saga", author="Author", status="in_progress", favorite=True)
            available_not_started = book(db, path=audiobook_root / "Author" / "Fresh Book", title="Fresh Book", author="Author", status="available")
            available_finished = book(db, path=audiobook_root / "Author" / "Done Book", title="Done Book", author="Author", status="finished", favorite=True)
            unavailable_book = book(db, path=ghost_book_path, title="Ghost Tome", author="Author", availability="unavailable", status="finished", favorite=True)

            ch1_path = write_file(active_book_path / "01.mp3", b"chapter one")
            ch2_path = write_file(active_book_path / "02.mp3", b"chapter two unavailable")
            ch3_path = write_file(active_book_path / "03.mp3", b"chapter three")
            ghost_chapter_path = write_file(ghost_book_path / "01.mp3", b"ghost chapter")
            active_cover = write_file(active_book_path / "cover.jpg", b"active audiobook cover")
            ghost_cover = write_file(ghost_book_path / "cover.jpg", b"ghost audiobook cover")
            media_files.extend([ch1_path, ch2_path, ch3_path, ghost_chapter_path, active_cover, ghost_cover])

            ch1 = chapter(db, audiobook_id=active_book.id, path=ch1_path, title="Opening FindMe", sort_order=1)
            ch2 = chapter(db, audiobook_id=active_book.id, path=ch2_path, title="LostKeyword", sort_order=2, availability="unavailable")
            ch3 = chapter(db, audiobook_id=active_book.id, path=ch3_path, title="Closing", sort_order=3)
            ghost_chapter = chapter(db, audiobook_id=unavailable_book.id, path=ghost_chapter_path, title="Ghost Chapter", sort_order=1)

            active_progress = add_progress(db, audiobook_id=active_book.id, chapter_id=ch2.id, seconds=40)
            unavailable_progress = add_progress(db, audiobook_id=unavailable_book.id, chapter_id=ghost_chapter.id, seconds=90)
            db.add(models.PlaybackEvent(audiobook_id=unavailable_book.id, event_type="start", position_seconds=90))
            db.commit()

            initial_hashes = {path: digest(path) for path in media_files}

            with temporary_settings(MUSIC_LIBRARY_ROOT=str(music_root), MUSIC_DISCOGRAPHIES_ROOT=str(discog_root), BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN=False, AUDIOBOOKS_ROOT=str(audiobook_root), BM_RADIO_AUDIOBOOK_ROOT=str(audiobook_root)):
                assert is_track_available(available_track)
                assert not is_track_available(unavailable_track)
                assert is_audiobook_available(active_book)
                assert not is_audiobook_available(unavailable_book)
                assert is_chapter_available(ch1)
                assert not is_chapter_available(ch2)
                assert active_tracks(db).count() == 1
                assert active_audiobooks(db).count() == 3
                assert active_chapters(db).count() == 3

                tracks = run_async(library.get_tracks(db=db))
                assert [row["id"] for row in tracks] == [available_track.id]
                assert db.get(models.Track, unavailable_track.id) is not None

                artists = run_async(library.get_artists(db=db))
                assert {row["name"] for row in artists} == {"Mixed Artist"}
                mixed_artist = next(row for row in artists if row["name"] == "Mixed Artist")
                assert mixed_artist["track_count"] == 1
                albums = run_async(library.get_albums(db=db))
                assert [row["title"] for row in albums] == ["Mixed Album"]
                assert albums[0]["track_count"] == 1

                library_search = run_async(library.search(q="Needle", db=db))
                assert [row["id"] for row in library_search] == [available_track.id]
                global_results = search.global_search(q="Needle", db=db)
                assert [row["id"] for row in global_results["tracks"]] == [available_track.id]
                mixed_results = search.global_search(q="Mixed", db=db)
                assert {row["name"] for row in mixed_results["artists"]} == {"Mixed Artist"}
                assert mixed_results["artists"][0]["track_count"] == 1
                assert mixed_results["albums"][0]["track_count"] == 1

                assert [row["id"] for row in search.global_search(q="Active Saga", db=db)["audiobooks"]] == [active_book.id]
                assert search.global_search(q="Ghost Tome", db=db)["audiobooks"] == []
                assert search.global_search(q="LostKeyword", db=db)["audiobooks"] == []
                assert [row["id"] for row in search.global_search(q="FindMe", db=db)["audiobooks"]] == [active_book.id]

                book_ids = {row["id"] for row in audiobooks.get_audiobooks(db=db)}
                assert unavailable_book.id not in book_ids
                assert {active_book.id, available_not_started.id, available_finished.id}.issubset(book_ids)
                assert db.get(models.Audiobook, unavailable_book.id).favorite is True
                assert db.get(models.Audiobook, unavailable_book.id).status == "finished"

                summary = audiobooks.get_summary(db=db)
                assert summary["available"] == 3
                assert summary["not_started"] == 1
                assert summary["in_progress"] == 1
                assert summary["finished"] == 1
                assert summary["favorites"] == 2
                assert summary["total_listening_seconds"] == 130

                recent = audiobooks.recent_or_progress(limit=10, db=db)
                assert unavailable_book.id not in {row["id"] for row in recent}
                assert db.get(models.AudiobookProgress, unavailable_progress.id) is not None

                detail = audiobooks.get_audiobook(active_book.id, db=db)
                assert [row["id"] for row in detail["chapters"]] == [ch1.id, ch3.id]
                assert detail["latest_progress"] is None
                db.refresh(active_progress)
                assert active_progress.chapter_id == ch2.id

                expect_http(409, audiobooks.get_audiobook, unavailable_book.id, db=db)

                before_progress_count = db.query(models.AudiobookProgress).count()
                expect_http(409, audiobooks.update_progress, unavailable_book.id, audiobooks.ProgressUpdate(chapter_id=ghost_chapter.id, position_seconds=50, progress_percent=50), db=db)
                assert db.query(models.AudiobookProgress).count() == before_progress_count
                expect_http(409, audiobooks.update_progress, active_book.id, audiobooks.ProgressUpdate(chapter_id=ch2.id, position_seconds=50, progress_percent=50), db=db)
                assert db.query(models.AudiobookProgress).count() == before_progress_count

                assert media.stream_track(available_track.id, db=db).status_code == 200
                expect_http(409, media.stream_track, unavailable_track.id, db=db)
                expect_http(409, media.track_cover, unavailable_track.id, db=db)

                response = media.album_cover("Mixed Artist", "Mixed Album", db=db)
                assert response.status_code == 200
                assert Path(response.path) == available_cover

                expect_http(409, media.stream_audiobook_chapter, unavailable_book.id, ghost_chapter.id, db=db)
                expect_http(409, media.stream_audiobook_chapter, active_book.id, ch2.id, db=db)
                assert media.stream_audiobook_chapter(active_book.id, ch1.id, db=db).status_code == 200
                expect_http(409, media.audiobook_cover, unavailable_book.id, db=db)

                assert serializers.track_item(unavailable_track)["library_availability"] == "unavailable"
                assert "unavailable_since" in serializers.track_item(unavailable_track)
                assert serializers.audiobook_item(unavailable_book)["library_availability"] == "unavailable"
                assert "unavailable_since" in serializers.audiobook_item(unavailable_book)
                assert serializers.chapter_item(ch2)["library_availability"] == "unavailable"
                assert "unavailable_since" in serializers.chapter_item(ch2)

                assert db.get(models.Track, unavailable_track.id) is not None
                assert db.get(models.Track, ghost_track.id) is not None
                assert db.get(models.Audiobook, unavailable_book.id) is not None
                assert db.get(models.AudiobookChapter, ch2.id) is not None
                assert db.get(models.AudiobookChapter, ghost_chapter.id) is not None
                assert db.get(models.AudiobookProgress, active_progress.id).chapter_id == ch2.id
                assert db.get(models.AudiobookProgress, unavailable_progress.id) is not None
                assert db.get(models.Audiobook, unavailable_book.id).favorite is True
                assert db.get(models.Audiobook, unavailable_book.id).status == "finished"

                assert {path: digest(path) for path in media_files} == initial_hashes

                assert db.query(models.Track).count() == 3
                assert db.query(models.Audiobook).count() == 4
                assert db.query(models.AudiobookChapter).count() == 4
                assert db.query(models.Track).filter_by(library_availability="unavailable").count() == 2
                assert db.query(models.Audiobook).filter_by(library_availability="unavailable").count() == 1
                assert db.query(models.AudiobookChapter).filter_by(library_availability="unavailable").count() == 1
        finally:
            db.close()
    finally:
        if engine is not None:
            engine.dispose()
        if tmp.exists():
            shutil.rmtree(tmp)

    print("PASS: BM-PROD1.3D1 core active-library availability policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())