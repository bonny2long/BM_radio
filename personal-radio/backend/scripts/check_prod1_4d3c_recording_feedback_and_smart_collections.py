from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import inspect
import shutil
import sys

from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.music_recording_participation import set_music_recording_participation
from app.music_source_preference import evaluate_music_recording_preference, set_music_recording_user_preference
from app.routes import playback, playlists, queue
from app.scan_runs import LIBRARY_AVAILABLE, LIBRARY_UNAVAILABLE
from app.schema_maintenance import ensure_playback_identity_columns, ensure_recording_feedback_columns, ensure_scan_reconciliation_columns

UTC = timezone.utc


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    ensure_playback_identity_columns(engine)
    ensure_recording_feedback_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def add_release(db, *, title: str = "Album", artist: str = "Artist", release_type: str = "album"):
    idx = db.query(models.MusicRelease).count() + 1
    row = models.MusicRelease(identity_key=f"release-{idx}-{artist}-{title}", album_artist=artist, title=title, normalized_album_artist=artist.lower(), normalized_title=title.lower(), release_type=release_type)
    db.add(row)
    db.flush()
    return row


def add_recording(db, *, title: str = "Song", artist: str = "Artist", kind: str = "studio"):
    idx = db.query(models.MusicRecording).count() + 1
    row = models.MusicRecording(identity_key=f"recording-{idx}-{artist}-{title}-{kind}", artist=artist, title=title, normalized_artist=artist.lower(), normalized_title=title.lower(), recording_type=kind, version_hint=kind, duration_bucket="180")
    db.add(row)
    db.flush()
    return row


def add_track(db, *, release, recording=None, suffix: str, codec: str = "mp3", is_lossless: bool | None = False, availability: str = LIBRARY_AVAILABLE, created_at: datetime | None = None, track_number: int = 1):
    idx = db.query(models.Track).count() + 1
    when = created_at or (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=idx))
    track = models.Track(path=f"C:/synthetic/d3c/{idx}-{suffix}.{codec}", relative_path=f"{idx}-{suffix}.{codec}", title=recording.title if recording else suffix, artist=recording.artist if recording else "Legacy", album=release.title if release else "Legacy", album_artist=release.album_artist if release else "Legacy", genre="Test", primary_genre="Test", year=2026, duration_seconds=180.0, file_ext=f".{codec}", library_area="Library", track_number=track_number, disc_number=1, library_availability=availability, created_at=when, last_indexed_at=when)
    db.add(track)
    db.flush()
    if recording is not None:
        edition = models.MusicEdition(identity_key=f"edition-{idx}-{release.id}-{recording.id}-{suffix}", release_id=release.id, display_title=release.title, year=2026, edition_type="standard", source_scope=f"scope-{suffix}", source_format_family="LOSSLESS" if is_lossless else "LOSSY")
        db.add(edition)
        db.flush()
        db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=recording.id))
        db.add(models.MusicTechnicalProfile(track_id=track.id, probe_status="ok", codec=codec, container=codec, is_lossless=is_lossless, sample_rate_hz=44100, bit_depth_bits=16 if is_lossless else None, bitrate_bps=None if is_lossless else 320000, channel_count=2, file_size_bytes=1000 + idx))
        db.flush()
    return track


def case_schema(tmp: Path) -> None:
    engine, _ = make_db(tmp, "fresh")
    insp = sa_inspect(engine)
    assert "recording_id" in {column["name"] for column in insp.get_columns("track_favorites")}
    assert "recording_id" in {column["name"] for column in insp.get_columns("track_thumbs")}
    assert "ix_track_favorites_recording_id" in {idx["name"] for idx in insp.get_indexes("track_favorites")}
    assert "ix_track_thumbs_recording_id" in {idx["name"] for idx in insp.get_indexes("track_thumbs")}

    old_path = tmp / "old_feedback.db"
    old_engine = create_engine(f"sqlite:///{old_path}", connect_args={"check_same_thread": False})
    with old_engine.begin() as conn:
        conn.execute(text("CREATE TABLE track_favorites (id INTEGER PRIMARY KEY, track_id INTEGER, created_at DATETIME)"))
        conn.execute(text("CREATE TABLE track_thumbs (id INTEGER PRIMARY KEY, track_id INTEGER, station_id INTEGER, value VARCHAR, created_at DATETIME)"))
        conn.execute(text("INSERT INTO track_favorites (id, track_id, created_at) VALUES (1, 10, '2026-01-01')"))
        conn.execute(text("INSERT INTO track_thumbs (id, track_id, station_id, value, created_at) VALUES (1, 10, 3, 'up', '2026-01-01')"))
    ensure_recording_feedback_columns(old_engine)
    ensure_recording_feedback_columns(old_engine)
    insp = sa_inspect(old_engine)
    assert "recording_id" in {column["name"] for column in insp.get_columns("track_favorites")}
    assert "recording_id" in {column["name"] for column in insp.get_columns("track_thumbs")}
    with old_engine.connect() as conn:
        fav = conn.execute(text("SELECT id, track_id, recording_id FROM track_favorites")).mappings().one()
        thumb = conn.execute(text("SELECT id, track_id, recording_id FROM track_thumbs")).mappings().one()
    assert fav["id"] == 1 and fav["recording_id"] is None
    assert thumb["id"] == 1 and thumb["recording_id"] is None


def case_favorite_and_feedback_routes(tmp: Path) -> None:
    _, Session = make_db(tmp, "routes")
    db = Session()
    try:
        release = add_release(db)
        rec = add_recording(db, title="Cross Source")
        mp3 = add_track(db, release=release, recording=rec, suffix="mp3")
        flac = add_track(db, release=release, recording=rec, suffix="flac", codec="flac", is_lossless=True)
        evaluate_music_recording_preference(db, recording_id=rec.id)
        db.commit()

        response = playback.track_favorite(mp3.id, playback.FavoritePayload(favorite=True), db=db)
        assert response["track_id"] == mp3.id and response["recording_id"] == rec.id and response["favorite"] is True
        assert playback.get_track_favorite(flac.id, db=db)["favorite"] is True
        assert db.query(models.TrackFavorite).filter_by(recording_id=rec.id).count() == 1
        set_music_recording_user_preference(db, recording_id=rec.id, track_id=flac.id)
        db.commit()
        fav_ids = queue.smart_track_ids(db, "favorites", 10)
        assert fav_ids == [flac.id]
        assert playback.get_track_favorite(mp3.id, db=db)["favorite"] is True and playback.get_track_favorite(flac.id, db=db)["favorite"] is True

        playback.track_favorite(flac.id, None, db=db)
        assert playback.get_track_favorite(mp3.id, db=db)["favorite"] is False
        db.add_all([models.TrackFavorite(track_id=mp3.id, recording_id=None), models.TrackFavorite(track_id=flac.id, recording_id=rec.id)])
        db.commit()
        playback.track_favorite(mp3.id, playback.FavoritePayload(favorite=False), db=db)
        assert playback.get_track_favorite(flac.id, db=db)["favorite"] is False
        assert db.query(models.TrackFavorite).count() == 0

        legacy_a = add_track(db, release=None, recording=None, suffix="legacy-a")
        legacy_b = add_track(db, release=None, recording=None, suffix="legacy-b")
        db.commit()
        playback.track_favorite(legacy_a.id, playback.FavoritePayload(favorite=True), db=db)
        assert playback.get_track_favorite(legacy_a.id, db=db)["favorite"] is True
        assert playback.get_track_favorite(legacy_b.id, db=db)["favorite"] is False

        response = playback.track_thumb(mp3.id, playback.TrackThumbCreate(value="thumbs_up", station_id=7), db=db)
        assert response["recording_id"] == rec.id and response["value"] == "up"
        stored = db.query(models.TrackThumb).filter_by(recording_id=rec.id).order_by(models.TrackThumb.id.desc()).first()
        assert stored.track_id == mp3.id and stored.station_id == 7 and stored.value == models.ThumbValue.up
        assert playback.get_track_feedback(flac.id, db=db)["value"] == "up"
        playback.track_thumb(flac.id, playback.TrackThumbCreate(value="down"), db=db)
        assert playback.get_track_feedback(mp3.id, db=db)["value"] == "down"
        set_music_recording_user_preference(db, recording_id=rec.id, track_id=mp3.id)
        db.commit()
        assert playback.get_track_feedback(flac.id, db=db)["value"] == "down"
        playback.track_thumb(mp3.id, playback.TrackThumbCreate(value="neutral"), db=db)
        assert playback.get_track_feedback(mp3.id, db=db)["value"] == "neutral"
        assert playback.get_track_feedback(flac.id, db=db)["value"] == "neutral"

        playback.track_thumb(legacy_a.id, playback.TrackThumbCreate(value="up"), db=db)
        assert playback.get_track_feedback(legacy_a.id, db=db)["value"] == "up"
        assert playback.get_track_feedback(legacy_b.id, db=db)["value"] == "neutral"
    finally:
        db.close()


def case_smart_collections(tmp: Path) -> None:
    engine, Session = make_db(tmp, "smart")
    db = Session()
    try:
        release = add_release(db)
        now = datetime.now(UTC)

        fav = add_recording(db, title="Favorite")
        fav_mp3 = add_track(db, release=release, recording=fav, suffix="fav-mp3")
        fav_flac = add_track(db, release=release, recording=fav, suffix="fav-flac", codec="flac", is_lossless=True)
        evaluate_music_recording_preference(db, recording_id=fav.id)
        db.add_all([models.TrackFavorite(track_id=fav_mp3.id, recording_id=fav.id, created_at=now), models.TrackFavorite(track_id=fav_flac.id, recording_id=fav.id, created_at=now + timedelta(seconds=1))])

        thumb = add_recording(db, title="Thumb")
        thumb_a = add_track(db, release=release, recording=thumb, suffix="thumb-a")
        thumb_b = add_track(db, release=release, recording=thumb, suffix="thumb-b", codec="flac", is_lossless=True)
        db.add_all([
            models.TrackThumb(track_id=thumb_a.id, recording_id=thumb.id, value=models.ThumbValue.down, created_at=now),
            models.TrackThumb(track_id=thumb_b.id, recording_id=thumb.id, value=models.ThumbValue.up, created_at=now + timedelta(seconds=2)),
        ])

        played = add_recording(db, title="Played")
        played_mp3 = add_track(db, release=release, recording=played, suffix="played-mp3")
        played_flac = add_track(db, release=release, recording=played, suffix="played-flac", codec="flac", is_lossless=True)
        for offset in range(3):
            db.add(models.PlaybackEvent(track_id=played_flac.id, recording_id=played.id, event_type="qualified_play", created_at=now + timedelta(minutes=offset)))
        for offset in range(3, 5):
            db.add(models.PlaybackEvent(track_id=played_mp3.id, recording_id=played.id, event_type="qualified_play", created_at=now + timedelta(minutes=offset)))

        old_rec = add_recording(db, title="Old Recording")
        old_mp3 = add_track(db, release=release, recording=old_rec, suffix="old-mp3", created_at=now - timedelta(days=10))
        old_flac = add_track(db, release=release, recording=old_rec, suffix="old-flac", codec="flac", is_lossless=True, created_at=now + timedelta(days=1))
        newer_rec = add_recording(db, title="Newer Recording")
        newer_track = add_track(db, release=release, recording=newer_rec, suffix="newer", created_at=now - timedelta(days=1))

        never = add_recording(db, title="Never")
        never_track = add_track(db, release=release, recording=never, suffix="never")
        played_once = add_recording(db, title="Played Once")
        played_once_mp3 = add_track(db, release=release, recording=played_once, suffix="played-once-mp3")
        played_once_flac = add_track(db, release=release, recording=played_once, suffix="played-once-flac", codec="flac", is_lossless=True)
        db.add(models.PlaybackEvent(track_id=played_once_mp3.id, recording_id=None, event_type="qualified_play", created_at=now + timedelta(minutes=10)))

        lib_only = add_recording(db, title="Library Only")
        lib_track = add_track(db, release=release, recording=lib_only, suffix="lib")
        set_music_recording_participation(db, recording_id=lib_only.id, participation_state="library_only")
        archived = add_recording(db, title="Archived")
        archived_track = add_track(db, release=release, recording=archived, suffix="archived")
        set_music_recording_participation(db, recording_id=archived.id, participation_state="archived")
        blocked = add_recording(db, title="Blocked")
        blocked_track = add_track(db, release=release, recording=blocked, suffix="blocked")
        set_music_recording_participation(db, recording_id=blocked.id, participation_state="blocked")
        db.add_all([
            models.TrackFavorite(track_id=lib_track.id, recording_id=lib_only.id, created_at=now + timedelta(minutes=20)),
            models.TrackFavorite(track_id=archived_track.id, recording_id=archived.id, created_at=now + timedelta(minutes=21)),
            models.TrackFavorite(track_id=blocked_track.id, recording_id=blocked.id, created_at=now + timedelta(minutes=22)),
        ])

        no_source = add_recording(db, title="No Source")
        no_source_track = add_track(db, release=release, recording=no_source, suffix="no-source", availability=LIBRARY_UNAVAILABLE)
        db.add(models.TrackFavorite(track_id=no_source_track.id, recording_id=no_source.id, created_at=now + timedelta(minutes=23)))
        db.commit()

        assert queue.smart_track_ids(db, "favorites", 50).count(fav_flac.id) == 1
        fav_items = queue.smart_playlist_queue(type("Req", (), {"key": "favorites", "limit": 50, "shuffle": False})(), db=db)["queue"]
        fav_recordings = {item.get("recording_id") for item in fav_items}
        assert fav.id in fav_recordings and lib_only.id in fav_recordings
        assert archived.id not in fav_recordings and blocked.id not in fav_recordings and no_source.id not in fav_recordings
        assert playlists.smart_count(db, "favorites") >= 4

        thumbs = queue.smart_playlist_queue(type("Req", (), {"key": "thumbs_up", "limit": 20, "shuffle": False})(), db=db)["queue"]
        assert [item["recording_id"] for item in thumbs if item["recording_id"] == thumb.id] == [thumb.id]

        most = queue.smart_playlist_queue(type("Req", (), {"key": "most_played", "limit": 20, "shuffle": False})(), db=db)["queue"]
        assert len([item for item in most if item["recording_id"] == played.id]) == 1
        assert most[0]["recording_id"] in {played_once.id, played.id}
        recent = queue.smart_playlist_queue(type("Req", (), {"key": "recently_played", "limit": 20, "shuffle": False})(), db=db)["queue"]
        assert len([item for item in recent if item["recording_id"] == played.id]) == 1
        assert played_once.id in {item["recording_id"] for item in recent}

        added = queue.smart_playlist_queue(type("Req", (), {"key": "recently_added", "limit": 50, "shuffle": False})(), db=db)["queue"]
        added_ids = [item["recording_id"] for item in added]
        assert added_ids.index(newer_rec.id) < added_ids.index(old_rec.id)
        assert lib_only.id not in added_ids
        assert old_flac.id in {item["id"] for item in added}

        never_ids = {item["recording_id"] for item in queue.smart_playlist_queue(type("Req", (), {"key": "never_played", "limit": 100, "shuffle": False})(), db=db)["queue"]}
        assert never.id in never_ids and played_once.id not in never_ids and played.id not in never_ids

        set_music_recording_user_preference(db, recording_id=fav.id, track_id=fav_mp3.id)
        db.commit()
        assert fav_mp3.id in queue.smart_track_ids(db, "favorites", 20)

        before = {
            "participation": db.query(models.MusicRecordingParticipation).count(),
            "preferences": db.query(models.MusicRecordingPreference).count(),
        }
        playback.track_favorite(fav_flac.id, playback.FavoritePayload(favorite=True), db=db)
        playback.track_thumb(fav_flac.id, playback.TrackThumbCreate(value="up"), db=db)
        after = {
            "participation": db.query(models.MusicRecordingParticipation).count(),
            "preferences": db.query(models.MusicRecordingPreference).count(),
        }
        assert before == after

        source = inspect.getsource(playlists.smart_count)
        assert "100000" not in source and "len(smart_track_ids" not in source
        source = inspect.getsource(queue.smart_track_ids) + inspect.getsource(playlists.smart_track_ids)
        assert "latest_thumb_values" not in source

        select_count = 0

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            nonlocal select_count
            if statement.lstrip().upper().startswith("SELECT"):
                select_count += 1

        for idx in range(100):
            rec = add_recording(db, title=f"Bulk {idx}")
            track = add_track(db, release=release, recording=rec, suffix=f"bulk-{idx}")
            db.add(models.TrackFavorite(track_id=track.id, recording_id=rec.id))
        db.commit()
        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            ids = queue.smart_track_ids(db, "favorites", 100)
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
        assert len(ids) == 100 and select_count < 20, select_count
    finally:
        db.close()


def case_boundaries(tmp: Path) -> None:
    _, Session = make_db(tmp, "boundaries")
    db = Session()
    try:
        station = models.Station(name="Station", type="artist", seed_value="Artist", favorite=False)
        db.add(station)
        db.commit()
        station.favorite = True
        db.commit()
        assert db.get(models.Station, station.id).favorite is True
        assert "music_recording_feedback" not in Path("app/station_engine.py").read_text(encoding="utf-8")
        assert "music_recording_feedback" not in Path("app/routes/stations.py").read_text(encoding="utf-8")
        assert "write_bytes" not in inspect.getsource(playback.track_favorite)
        assert "write_bytes" not in inspect.getsource(playback.track_thumb)
    finally:
        db.close()


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4d3c_recording_feedback_and_smart_collections"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_schema(tmp)
        case_favorite_and_feedback_routes(tmp)
        case_smart_collections(tmp)
        case_boundaries(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.4D3C recording-level favorites, feedback, and smart collections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())