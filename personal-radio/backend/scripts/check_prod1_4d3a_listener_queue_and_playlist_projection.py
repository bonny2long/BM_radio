from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import inspect
import shutil
import sys

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.listener_queue import playlist_projected_items, project_track_ids_to_listener_queue
from app.music_recording_participation import set_music_recording_participation
from app.music_source_preference import evaluate_music_recording_preference, set_music_recording_user_preference
from app.queue_contracts import AlbumQueueRequest, ArtistQueueRequest, PlaylistQueueRequest, SmartPlaylistQueueRequest
from app.routes import playlists, queue
from app.scan_runs import LIBRARY_AVAILABLE, LIBRARY_UNAVAILABLE
from app.schema_maintenance import ensure_scan_reconciliation_columns

UTC = timezone.utc


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def add_release(db, *, title: str, artist: str = "Artist", release_type: str = "album"):
    idx = db.query(models.MusicRelease).count() + 1
    row = models.MusicRelease(identity_key=f"release-{idx}-{artist}-{title}", album_artist=artist, title=title, normalized_album_artist=artist.lower(), normalized_title=title.lower(), release_type=release_type)
    db.add(row)
    db.flush()
    return row


def add_recording(db, *, title: str, artist: str = "Artist", kind: str = "studio"):
    idx = db.query(models.MusicRecording).count() + 1
    row = models.MusicRecording(identity_key=f"recording-{idx}-{artist}-{title}-{kind}", artist=artist, title=title, normalized_artist=artist.lower(), normalized_title=title.lower(), recording_type=kind, duration_bucket="180")
    db.add(row)
    db.flush()
    return row


def add_track(db, *, release, recording, suffix: str, codec: str = "mp3", is_lossless: bool | None = False, availability: str = LIBRARY_AVAILABLE, track_number: int = 1, created_offset: int = 0):
    idx = db.query(models.Track).count() + 1
    when = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=created_offset)
    edition = models.MusicEdition(identity_key=f"edition-{release.id}-{recording.id}-{suffix}-{idx}", release_id=release.id, display_title=release.title, year=2026, edition_type="standard", source_scope=f"scope-{suffix}", source_format_family="LOSSLESS" if is_lossless else "LOSSY")
    track = models.Track(path=f"C:/synthetic/d3a/{release.id}/{recording.id}/{suffix}.{codec}", relative_path=f"{release.album_artist}/{release.title}/{suffix}.{codec}", title=recording.title, artist=recording.artist, album=release.title, album_artist=release.album_artist, genre="Queue", primary_genre="Queue", year=2026, duration_seconds=180, file_ext=f".{codec}", library_area="Library", track_number=track_number, disc_number=1, library_availability=availability, created_at=when, last_indexed_at=when)
    db.add_all([edition, track])
    db.flush()
    db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=recording.id))
    db.add(models.MusicTechnicalProfile(track_id=track.id, probe_status="ok", codec=codec, container=codec, is_lossless=is_lossless, sample_rate_hz=44100, bit_depth_bits=16 if is_lossless else None, bitrate_bps=None if is_lossless else 320000, channel_count=2, file_size_bytes=1000 + idx))
    db.flush()
    return track


def add_legacy_track(db, *, title: str, availability: str = LIBRARY_AVAILABLE):
    idx = db.query(models.Track).count() + 1
    row = models.Track(path=f"C:/legacy/{idx}.mp3", relative_path=f"legacy/{idx}.mp3", title=title, artist="Legacy", album="Legacy", duration_seconds=100, file_ext=".mp3", library_availability=availability)
    db.add(row)
    db.flush()
    return row


def add_playlist(db, name: str = "List"):
    row = models.Playlist(name=name, kind="manual")
    db.add(row)
    db.flush()
    return row


def add_playlist_track(db, playlist, track, position: int):
    row = models.PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=position)
    db.add(row)
    db.flush()
    return row


def call_status(func, *args, **kwargs):
    try:
        return 200, func(*args, **kwargs)
    except HTTPException as exc:
        return exc.status_code, exc.detail


def state_counts(db):
    return {
        "preferences": db.query(models.MusicRecordingPreference).count(),
        "playlist_tracks": db.query(models.PlaylistTrack).count(),
        "tracks": db.query(models.Track).count(),
        "identities": db.query(models.MusicTrackIdentity).count(),
        "profiles": db.query(models.MusicTechnicalProfile).count(),
    }


def case_album_artist_queue(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_album_artist")
    db = Session()
    try:
        album = add_release(db, title="Shared", artist="Artist")
        rec = add_recording(db, title="Song", artist="Artist")
        mp3 = add_track(db, release=album, recording=rec, suffix="song-mp3", codec="mp3")
        flac = add_track(db, release=album, recording=rec, suffix="song-flac", codec="flac", is_lossless=True)
        evaluate_music_recording_preference(db, recording_id=rec.id)
        single = add_release(db, title="Shared", artist="Artist", release_type="single")
        single_track = add_track(db, release=single, recording=rec, suffix="song-single", codec="mp3")
        other_same_title = add_release(db, title="Shared", artist="Artist")
        other_rec = add_recording(db, title="Other", artist="Artist")
        add_track(db, release=other_same_title, recording=other_rec, suffix="other", track_number=2)

        lib_rec = add_recording(db, title="Library Only", artist="Artist")
        add_track(db, release=album, recording=lib_rec, suffix="library-only", track_number=3)
        set_music_recording_participation(db, recording_id=lib_rec.id, participation_state="library_only")
        archived = add_recording(db, title="Archived", artist="Artist")
        add_track(db, release=album, recording=archived, suffix="archived", track_number=4)
        set_music_recording_participation(db, recording_id=archived.id, participation_state="archived")
        blocked = add_recording(db, title="Blocked", artist="Artist")
        add_track(db, release=album, recording=blocked, suffix="blocked", track_number=5)
        set_music_recording_participation(db, recording_id=blocked.id, participation_state="blocked")
        db.commit()

        result = queue.album_queue(AlbumQueueRequest(release_id=album.id), db=db)["queue"]
        assert len([item for item in result if item["recording_id"] == rec.id]) == 1
        item = next(item for item in result if item["recording_id"] == rec.id)
        assert item["id"] == flac.id and item["effective_track_id"] == flac.id
        assert item["album"] == "Shared" and item["presentation_track_id"] in {mp3.id, flac.id}
        assert {row["recording_id"] for row in result}.isdisjoint({archived.id, blocked.id})
        assert lib_rec.id in {row["recording_id"] for row in result}

        assert queue.album_queue(AlbumQueueRequest(release_id=single.id), db=db)["queue"][0]["release_id"] == single.id
        compat = queue.album_queue(AlbumQueueRequest(artist="Artist", album="Shared"), db=db)["queue"]
        assert len({item["release_id"] for item in compat}) == 1

        explicit = queue.artist_queue(ArtistQueueRequest(artist="Artist", shuffle=False, limit=20), db=db)["queue"]
        shuffled = queue.artist_queue(ArtistQueueRequest(artist="Artist", shuffle=True, limit=20), db=db)["queue"]
        assert lib_rec.id in {item["recording_id"] for item in explicit}
        assert lib_rec.id not in {item["recording_id"] for item in shuffled}
        assert archived.id not in {item["recording_id"] for item in explicit}
        assert blocked.id not in {item["recording_id"] for item in explicit}
    finally:
        db.close()


def case_playlist_semantics(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_playlist")
    db = Session()
    try:
        album = add_release(db, title="Playlist Album", artist="Artist")
        rec = add_recording(db, title="Playlist Song", artist="Artist")
        mp3 = add_track(db, release=album, recording=rec, suffix="p-mp3", codec="mp3")
        flac = add_track(db, release=album, recording=rec, suffix="p-flac", codec="flac", is_lossless=True)
        evaluate_music_recording_preference(db, recording_id=rec.id)
        p = add_playlist(db)
        add_playlist_track(db, p, mp3, 1)
        db.commit()
        before_anchor = db.query(models.PlaylistTrack).filter_by(playlist_id=p.id).one().track_id
        assert before_anchor == mp3.id
        detail = playlists.detail(p, db)
        assert detail["track_count"] == 1 and detail["tracks"][0]["id"] == flac.id
        assert db.query(models.PlaylistTrack).filter_by(playlist_id=p.id).one().track_id == mp3.id

        status, _ = call_status(playlists.add_track, p.id, playlists.PlaylistTrackCreate(track_id=flac.id), db)
        assert status == 200
        assert db.query(models.PlaylistTrack).filter_by(playlist_id=p.id).count() == 1

        single = add_release(db, title="Playlist Single", artist="Artist", release_type="single")
        single_track = add_track(db, release=single, recording=rec, suffix="p-single", codec="mp3")
        db.commit()
        playlists.add_track(p.id, playlists.PlaylistTrackCreate(track_id=single_track.id), db)
        assert playlists.detail(p, db)["track_count"] == 2

        status, _ = call_status(playlists.remove_track, p.id, flac.id, db)
        assert status == 200
        remaining = playlists.detail(p, db)["tracks"]
        assert len(remaining) == 1 and remaining[0]["release_id"] == single.id

        # Reorder by current effective IDs while stored anchor differs.
        playlists.add_track(p.id, playlists.PlaylistTrackCreate(track_id=mp3.id), db)
        order_before = playlists.detail(p, db)["tracks"]
        playlists.reorder_tracks(p.id, playlists.ReorderPayload(track_ids=[flac.id, single_track.id]), db)
        order_after = playlists.detail(p, db)["tracks"]
        assert [item["recording_id"] for item in order_after] == [item["recording_id"] for item in order_before]
        assert queue.playlist_queue(PlaylistQueueRequest(playlist_id=p.id), db=db)["queue"] == order_after

        blocked = add_recording(db, title="Blocked Add", artist="Artist")
        blocked_track = add_track(db, release=album, recording=blocked, suffix="blocked-add")
        set_music_recording_participation(db, recording_id=blocked.id, participation_state="blocked")
        library_only = add_recording(db, title="Allowed Library", artist="Artist")
        library_track = add_track(db, release=album, recording=library_only, suffix="allowed-library")
        set_music_recording_participation(db, recording_id=library_only.id, participation_state="library_only")
        db.commit()
        status, _ = call_status(playlists.add_track, p.id, playlists.PlaylistTrackCreate(track_id=blocked_track.id), db)
        assert status == 409
        status, _ = call_status(playlists.add_track, p.id, playlists.PlaylistTrackCreate(track_id=library_track.id), db)
        assert status == 200
        hidden_row_count = db.query(models.PlaylistTrack).filter_by(playlist_id=p.id).count()
        set_music_recording_participation(db, recording_id=library_only.id, participation_state="archived")
        db.commit()
        assert db.query(models.PlaylistTrack).filter_by(playlist_id=p.id).count() == hidden_row_count
        assert library_only.id not in {item["recording_id"] for item in playlists.detail(p, db)["tracks"]}
    finally:
        db.close()


def case_smart_legacy_readonly_and_scope(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_smart")
    db = Session()
    try:
        release = add_release(db, title="Smart", artist="Smart Artist")
        rec = add_recording(db, title="Favorite", artist="Smart Artist")
        mp3 = add_track(db, release=release, recording=rec, suffix="fav-mp3", codec="mp3", created_offset=1)
        flac = add_track(db, release=release, recording=rec, suffix="fav-flac", codec="flac", is_lossless=True, created_offset=2)
        evaluate_music_recording_preference(db, recording_id=rec.id)
        db.add(models.TrackFavorite(track_id=mp3.id))
        db.add(models.TrackFavorite(track_id=flac.id))
        db.add(models.PlaybackEvent(track_id=mp3.id, event_type="qualified_play"))
        library_only = add_recording(db, title="Library Discovery", artist="Smart Artist")
        library_track = add_track(db, release=release, recording=library_only, suffix="lib", created_offset=3)
        set_music_recording_participation(db, recording_id=library_only.id, participation_state="library_only")
        db.add(models.TrackFavorite(track_id=library_track.id))
        db.add(models.PlaybackEvent(track_id=library_track.id, event_type="qualified_play"))
        legacy = add_legacy_track(db, title="Legacy Ok")
        legacy_gone = add_legacy_track(db, title="Legacy Gone", availability=LIBRARY_UNAVAILABLE)
        db.commit()
        before = state_counts(db)
        fav = queue.smart_playlist_queue(SmartPlaylistQueueRequest(key="favorites", limit=20), db=db)["queue"]
        assert len([item for item in fav if item.get("recording_id") == rec.id]) == 1
        assert next(item for item in fav if item.get("recording_id") == rec.id)["id"] == flac.id
        assert library_only.id in {item.get("recording_id") for item in queue.smart_playlist_queue(SmartPlaylistQueueRequest(key="recently_played", limit=20), db=db)["queue"]}
        assert library_only.id not in {item.get("recording_id") for item in queue.smart_playlist_queue(SmartPlaylistQueueRequest(key="recently_added", limit=20), db=db)["queue"]}
        assert project_track_ids_to_listener_queue(db, track_ids=[legacy.id, legacy_gone.id], allowed_participation_states={"included", "library_only"})[0]["id"] == legacy.id
        assert state_counts(db) == before

        many_ids = []
        for i in range(100):
            r = add_recording(db, title=f"Bulk {i}", artist="Bulk")
            t1 = add_track(db, release=release, recording=r, suffix=f"bulk-{i}-a")
            t2 = add_track(db, release=release, recording=r, suffix=f"bulk-{i}-b", codec="flac", is_lossless=True)
            many_ids.extend([t1.id, t2.id])
        db.commit()
        counts = {"selects": 0}
        def count_select(conn, cursor, statement, parameters, context, executemany):
            if statement.lower().lstrip().startswith("select"):
                counts["selects"] += 1
        event.listen(engine, "before_cursor_execute", count_select)
        try:
            assert len(project_track_ids_to_listener_queue(db, track_ids=many_ids, allowed_participation_states={"included", "library_only"})) == 100
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert counts["selects"] < 80, counts
    finally:
        db.close()
        engine.dispose()


def case_static_scope() -> None:
    queue_source = inspect.getsource(queue)
    assert "choose_preferred_tracks" not in queue_source
    assert "release_preferences" not in queue_source
    root = Path(__file__).resolve().parents[1]
    for rel in ["app/station_engine.py", "app/routes/stations.py", "app/routes/playback.py", "app/routes/media.py", "app/scanner/music_scanner.py"]:
        text = (root / rel).read_text(encoding="utf-8")
        assert "listener_queue" not in text
    frontend = root.parent / "frontend"
    hits = [path for path in frontend.rglob("*") if path.is_file() and path.suffix in {".js", ".jsx", ".ts", ".tsx", ".css"} and "listener_queue" in path.read_text(encoding="utf-8", errors="ignore")]
    assert not hits


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4d3a_listener_queue_playlist"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_album_artist_queue(tmp)
        case_playlist_semantics(tmp)
        case_smart_legacy_readonly_and_scope(tmp)
        case_static_scope()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.4D3A listener queue and playlist source resolution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())