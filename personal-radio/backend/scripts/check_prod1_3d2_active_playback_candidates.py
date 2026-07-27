from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import inspect
import shutil
import sys

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.queue_contracts import AlbumQueueRequest, ArtistQueueRequest, PlaylistQueueRequest, SmartPlaylistQueueRequest, StationQueueRequest
from app.routes import playback, playlists, queue, stations
from app.schema_maintenance import ensure_scan_reconciliation_columns
from app.station_engine import build_station_debug, build_station_queue


def make_db(base: Path):
    db_path = base / "prod1_3d2.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def expect_http(status_code: int, func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except HTTPException as exc:
        assert exc.status_code == status_code, f"expected {status_code}, got {exc.status_code}: {exc.detail}"
        return exc
    raise AssertionError(f"expected HTTPException {status_code}")


def run_async(value):
    return asyncio.run(value)


def write_file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def add_track(db, title: str, artist: str, album: str, *, availability: str = "available", genre: str = "Hip-Hop", created_offset: int = 0, duration: float = 100.0):
    now = datetime.now(timezone.utc) + timedelta(seconds=created_offset)
    track = models.Track(
        path=f"/tmp/{artist}/{album}/{title}.mp3",
        relative_path=f"{artist}/{album}/{title}.mp3",
        title=title,
        artist=artist,
        album=album,
        album_artist=artist,
        genre=genre,
        year=2026,
        duration_seconds=duration,
        file_ext=".mp3",
        library_area="Library",
        library_availability=availability,
        created_at=now,
        last_indexed_at=now,
    )
    db.add(track)
    db.flush()
    return track


def add_book(db, title: str, *, availability: str = "available"):
    book = models.Audiobook(path=f"/tmp/audiobooks/{title}", relative_path=title, title=title, author="Author", status="available", library_availability=availability)
    db.add(book)
    db.flush()
    return book


def add_chapter(db, book, title: str, *, availability: str = "available"):
    chapter = models.AudiobookChapter(audiobook_id=book.id, path=f"{book.path}/{title}.mp3", relative_path=f"{title}.mp3", title=title, sort_order=1, duration_seconds=60, library_availability=availability)
    db.add(chapter)
    db.flush()
    return chapter


def event_count(db) -> int:
    return db.query(models.PlaybackEvent).count()


def queue_ids(response: dict) -> list[int]:
    return [row["id"] for row in response.get("queue", [])]


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_3d2_active_playback_candidates"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    engine = None
    try:
        fixture = write_file(tmp / "fixture.mp3", b"d2 fixture bytes")
        fixture_hash = digest(fixture)
        engine, Session = make_db(tmp)
        db = Session()
        try:
            album_ok = add_track(db, "Album Available", "Album Artist", "Mixed Album", created_offset=1)
            album_missing = add_track(db, "Album Missing", "Album Artist", "Mixed Album", availability="unavailable", created_offset=2)
            artist_ok = add_track(db, "Artist Available", "Queue Artist", "Queue Album", created_offset=3)
            artist_missing = add_track(db, "Artist Missing", "Queue Artist", "Queue Album", availability="unavailable", created_offset=4)
            fav_ok = add_track(db, "Fav Available", "Fav Artist", "Fav Album", created_offset=5)
            fav_missing = add_track(db, "Fav Missing", "Fav Artist", "Fav Album", availability="unavailable", created_offset=6)
            thumb_ok = add_track(db, "Thumb Available", "Thumb Artist", "Thumb Album", created_offset=7)
            thumb_missing = add_track(db, "Thumb Missing", "Thumb Artist", "Thumb Album", availability="unavailable", created_offset=8)
            played_ok = add_track(db, "Played Available", "Played Artist", "Played Album", created_offset=9)
            played_missing = add_track(db, "Played Missing", "Played Artist", "Played Album", availability="unavailable", created_offset=10)
            never_ok = add_track(db, "Never Available", "Never Artist", "Never Album", created_offset=11)
            never_missing = add_track(db, "Never Missing", "Never Artist", "Never Album", availability="unavailable", created_offset=12)
            station_seed = add_track(db, "Station Seed", "Station Artist", "Station Album", genre="Electronic", created_offset=13)
            station_candidate = add_track(db, "Station Candidate", "Station Artist", "Station Album 2", genre="Electronic", created_offset=14)
            station_missing = add_track(db, "Station Missing", "Station Artist", "Station Album 3", genre="Electronic", availability="unavailable", created_offset=15)
            ghost_artist = add_track(db, "Only Ghost", "Ghost Station", "Ghost Album", genre="Rock", availability="unavailable", created_offset=16)

            db.add_all([
                models.TrackFavorite(track_id=fav_ok.id),
                models.TrackFavorite(track_id=fav_missing.id),
                models.TrackThumb(track_id=thumb_ok.id, value=models.ThumbValue.up),
                models.TrackThumb(track_id=thumb_missing.id, value=models.ThumbValue.up),
                models.PlaybackEvent(track_id=played_ok.id, event_type="qualified_play", created_at=datetime.now(timezone.utc) - timedelta(minutes=10)),
                models.PlaybackEvent(track_id=played_missing.id, event_type="qualified_play", created_at=datetime.now(timezone.utc) - timedelta(minutes=9)),
            ])
            db.commit()

            # Case A/B - album and artist queues exclude unavailable rows.
            assert queue_ids(queue.album_queue(AlbumQueueRequest(artist="Album Artist", album="Mixed Album"), db=db)) == [album_ok.id]
            assert db.get(models.Track, album_missing.id) is not None
            assert queue_ids(queue.artist_queue(ArtistQueueRequest(artist="Queue Artist", limit=10), db=db)) == [artist_ok.id]

            # Case C - manual playlist preserves membership but active output hides unavailable until restore.
            playlist = models.Playlist(name="Manual", kind="manual")
            db.add(playlist)
            db.flush()
            membership = models.PlaylistTrack(playlist_id=playlist.id, track_id=album_ok.id, position=4)
            db.add(membership)
            db.commit()
            membership_id = membership.id
            album_ok.library_availability = "unavailable"
            db.commit()
            detail = playlists.get_playlist(playlist.id, db=db)
            assert detail["track_count"] == 0
            assert detail["tracks"] == []
            assert queue.playlist_queue(PlaylistQueueRequest(playlist_id=playlist.id), db=db)["queue"] == []
            assert db.get(models.PlaylistTrack, membership_id) is not None
            album_ok.library_availability = "available"
            db.commit()
            restored_detail = playlists.get_playlist(playlist.id, db=db)
            assert [row["id"] for row in restored_detail["tracks"]] == [album_ok.id]
            restored_membership = db.get(models.PlaylistTrack, membership_id)
            assert restored_membership.position == 4

            # Case D/E - unavailable playlist membership conflicts and create-from-track-list is atomic.
            before_memberships = db.query(models.PlaylistTrack).count()
            expect_http(409, playlists.add_track, playlist.id, playlists.PlaylistTrackCreate(track_id=album_missing.id), db=db)
            assert db.query(models.PlaylistTrack).count() == before_memberships
            before_playlists = db.query(models.Playlist).count()
            expect_http(409, playlists.create_from_track_list, playlists.TrackListPlaylistCreate(name="Atomic", track_ids=[album_ok.id, album_missing.id]), db=db)
            assert db.query(models.Playlist).count() == before_playlists
            assert db.query(models.PlaylistTrack).count() == before_memberships

            # Case F/G - smart favorites/thumbs preserve state and restore automatically.
            assert queue.smart_track_ids(db, "favorites", 10) == [fav_ok.id]
            assert playlists.smart_count(db, "favorites") == 1
            assert db.query(models.TrackFavorite).count() == 2
            fav_missing.library_availability = "available"
            db.commit()
            assert set(queue.smart_track_ids(db, "favorites", 10)) == {fav_ok.id, fav_missing.id}
            fav_missing.library_availability = "unavailable"
            db.commit()
            assert queue.smart_track_ids(db, "thumbs_up", 10) == [thumb_ok.id]
            assert playlists.smart_count(db, "thumbs_up") == 1
            assert db.query(models.TrackThumb).count() == 2
            thumb_missing.library_availability = "available"
            db.commit()
            assert set(queue.smart_track_ids(db, "thumbs_up", 10)) == {thumb_ok.id, thumb_missing.id}
            thumb_missing.library_availability = "unavailable"
            db.commit()

            # Case H/I - history-based and library-based smart collections are active only.
            assert queue.smart_track_ids(db, "most_played", 10) == [played_ok.id]
            assert queue.smart_track_ids(db, "recently_played", 10) == [played_ok.id]
            assert played_missing.id not in queue.smart_track_ids(db, "recently_added", 100)
            assert never_ok.id in queue.smart_track_ids(db, "never_played", 100)
            assert never_missing.id not in queue.smart_track_ids(db, "never_played", 100)

            # Case J - smart queue bulk-loads selected Tracks rather than db.get per ID.
            source = inspect.getsource(queue.smart_playlist_queue)
            assert "db.get(models.Track" not in source
            assert queue_ids(queue.smart_playlist_queue(SmartPlaylistQueueRequest(key="favorites", limit=10), db=db)) == [fav_ok.id]

            # Case K - station listing counts exclude unavailable Tracks and feedback favorites.
            station_rows = run_async(stations.get_stations(db=db))
            by_name = {row["name"]: row for row in station_rows}
            assert by_name["Favorites Radio"]["track_count"] == 2  # fav_ok and thumb_ok only
            assert by_name["Recently Added"]["track_count"] == db.query(models.Track).filter_by(library_availability="available").count()
            assert by_name["Deep Cuts"]["track_count"] == by_name["Recently Added"]["track_count"]
            assert by_name["Station Artist Radio"]["track_count"] == 2
            genre_rows = [row for row in station_rows if row.get("type") == "genre"]
            assert all(row["track_count"] <= by_name["Recently Added"]["track_count"] for row in genre_rows)

            # Case L/M/N/O/P - station candidates, song seed conflict, empty fallback, saved station preservation.
            genre_queue = build_station_queue(StationQueueRequest(type="genre", seed_value="Electronic", limit=10, shuffle=False), db)
            assert station_missing.id not in queue_ids(genre_queue)
            genre_debug = build_station_debug(StationQueueRequest(type="genre", seed_value="Electronic", limit=10, shuffle=False), db)
            assert station_missing.id not in [row["track_id"] for row in genre_debug["selected"]]
            expect_http(409, build_station_queue, StationQueueRequest(type="song", seed_track_id=station_missing.id, limit=5), db)
            expect_http(409, build_station_debug, StationQueueRequest(type="song", seed_track_id=station_missing.id, limit=5), db)
            song_queue = build_station_queue(StationQueueRequest(type="song", seed_track_id=station_seed.id, limit=5, shuffle=False, allow_exploration=True), db)
            assert station_candidate.id in queue_ids(song_queue)
            assert build_station_queue(StationQueueRequest(type="artist", seed_value="Ghost Station", limit=5, shuffle=False), db)["queue"] == []
            saved = models.Station(name="Ghost Station Radio", type="artist", seed_value="Ghost Station", favorite=True)
            db.add(saved)
            db.commit()
            rows = run_async(stations.get_stations(db=db))
            saved_row = next(row for row in rows if row.get("id") == saved.id)
            assert saved_row["favorite"] is True and saved_row["track_count"] == 0
            ghost_artist.library_availability = "available"
            db.commit()
            rows = run_async(stations.get_stations(db=db))
            saved_row = next(row for row in rows if row.get("id") == saved.id)
            assert saved_row["favorite"] is True and saved_row["track_count"] == 1
            assert queue_ids(build_station_queue(StationQueueRequest(type="artist", seed_value="Ghost Station", limit=5, shuffle=False), db)) == [ghost_artist.id]
            ghost_artist.library_availability = "unavailable"
            db.commit()

            # Case Q/R - music playback event policy and qualification behavior.
            before_events = event_count(db)
            expect_http(409, playback.register_event, playback.PlaybackEventCreate(event_type="finish", track_id=album_missing.id, mode="music"), db=db)
            assert event_count(db) == before_events
            result = playback.register_event(playback.PlaybackEventCreate(event_type="finish", track_id=artist_ok.id, mode="music", position_seconds=100), db=db)
            assert result["event_type"] == "finish"
            assert db.query(models.PlaybackEvent).filter_by(track_id=artist_ok.id, event_type="qualified_play").count() == 1

            # Case S/T/U - audiobook playback event policy.
            book_ok = add_book(db, "Book OK")
            book_missing = add_book(db, "Book Missing", availability="unavailable")
            chapter_ok = add_chapter(db, book_ok, "Chapter OK")
            chapter_missing = add_chapter(db, book_ok, "Chapter Missing", availability="unavailable")
            other_book = add_book(db, "Other Book")
            other_chapter = add_chapter(db, other_book, "Other Chapter")
            db.commit()
            before_events = event_count(db)
            expect_http(409, playback.register_event, playback.PlaybackEventCreate(event_type="start", audiobook_id=book_missing.id), db=db)
            assert event_count(db) == before_events
            expect_http(409, playback.register_event, playback.PlaybackEventCreate(event_type="start", audiobook_id=book_ok.id, audiobook_chapter_id=chapter_missing.id), db=db)
            assert event_count(db) == before_events
            expect_http(422, playback.register_event, playback.PlaybackEventCreate(event_type="start", audiobook_id=book_ok.id, audiobook_chapter_id=other_chapter.id), db=db)
            assert event_count(db) == before_events
            playback.register_event(playback.PlaybackEventCreate(event_type="start", audiobook_id=book_ok.id, audiobook_chapter_id=chapter_ok.id, position_seconds=12), db=db)

            # Case V/W/X - recent playback hides unavailable media and scans past it.
            newer = datetime.now(timezone.utc)
            db.add_all([
                models.PlaybackEvent(track_id=album_missing.id, event_type="qualified_play", created_at=newer + timedelta(seconds=3)),
                models.PlaybackEvent(audiobook_id=book_missing.id, event_type="start", created_at=newer + timedelta(seconds=2)),
                models.PlaybackEvent(track_id=played_ok.id, event_type="qualified_play", created_at=newer + timedelta(seconds=1)),
            ])
            db.add(models.AudiobookProgress(audiobook_id=book_ok.id, chapter_id=chapter_missing.id, position_seconds=45, progress_percent=50, status="in_progress", updated_at=newer + timedelta(seconds=4)))
            db.add(models.PlaybackEvent(audiobook_id=book_ok.id, event_type="progress", created_at=newer + timedelta(seconds=4)))
            db.commit()
            recent = playback.recent_playback(limit=2, db=db)["items"]
            assert len(recent) == 2
            assert all(item.get("track_id") != album_missing.id for item in recent)
            assert all(item.get("audiobook_id") != book_missing.id for item in recent)
            book_item = next(item for item in recent if item["mode"] == "audiobook")
            assert book_item["chapter_id"] is None
            assert any(item.get("track_id") == played_ok.id for item in recent)

            # Case Y/Z - durable rows/state and media bytes remain.
            assert db.query(models.Track).count() >= 16
            assert db.query(models.Audiobook).count() >= 3
            assert db.query(models.AudiobookChapter).count() >= 3
            assert db.query(models.PlaylistTrack).filter_by(id=membership_id).count() == 1
            assert db.query(models.TrackFavorite).count() == 2
            assert db.query(models.TrackThumb).count() == 2
            assert db.query(models.PlaybackEvent).count() > 0
            assert db.query(models.Station).filter_by(id=saved.id).count() == 1
            assert digest(fixture) == fixture_hash
        finally:
            db.close()
    finally:
        if engine is not None:
            engine.dispose()
        if tmp.exists():
            shutil.rmtree(tmp)

    print("PASS: BM-PROD1.3D2 active queues, stations, playlists, and playback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())