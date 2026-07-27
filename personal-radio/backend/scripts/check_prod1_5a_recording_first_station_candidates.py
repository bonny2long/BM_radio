from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import inspect
import asyncio
import shutil
import sys

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.music_recording_participation import set_music_recording_participation
from app.music_source_preference import evaluate_music_recording_preference, set_music_recording_user_preference
from app.queue_contracts import StationQueueRequest
from app.routes import stations
from app.scan_runs import LIBRARY_AVAILABLE, LIBRARY_UNAVAILABLE
from app.schema_maintenance import ensure_playback_identity_columns, ensure_recording_feedback_columns, ensure_scan_reconciliation_columns
from app.station_candidates import load_station_candidate_tracks, logical_station_count, station_identity_keys_for_track_ids
from app.station_engine import build_station_debug, build_station_queue

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


def add_track(db, *, release, recording=None, suffix: str, codec: str = "mp3", is_lossless: bool | None = False, availability: str = LIBRARY_AVAILABLE, created_at: datetime | None = None, genre: str = "Soul", track_number: int = 1):
    idx = db.query(models.Track).count() + 1
    when = created_at or (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=idx))
    track = models.Track(path=f"C:/synthetic/15a/{idx}-{suffix}.{codec}", relative_path=f"{idx}-{suffix}.{codec}", title=recording.title if recording else suffix, artist=recording.artist if recording else "Legacy", album=release.title if release else "Legacy", album_artist=release.album_artist if release else "Legacy", genre=genre, primary_genre=genre, year=2026, duration_seconds=180.0, file_ext=f".{codec}", library_area="Library", track_number=track_number, disc_number=1, library_availability=availability, created_at=when, last_indexed_at=when)
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


def ids(queue: dict) -> list[int]:
    return [item["id"] for item in queue.get("queue", [])]


def rec_ids(queue: dict) -> list[int | None]:
    return [item.get("recording_id") for item in queue.get("queue", [])]


def expect_http(status: int, func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except HTTPException as exc:
        assert exc.status_code == status, (exc.status_code, exc.detail)
        return exc
    raise AssertionError(f"expected HTTP {status}")


def case_candidates_and_sources(tmp: Path) -> None:
    _, Session = make_db(tmp, "candidates")
    db = Session()
    try:
        release = add_release(db, title="Album", artist="Artist")
        rec = add_recording(db, title="Song", artist="Artist")
        mp3 = add_track(db, release=release, recording=rec, suffix="song-mp3", genre="Soul")
        flac = add_track(db, release=release, recording=rec, suffix="song-flac", codec="flac", is_lossless=True, genre="Soul")
        evaluate_music_recording_preference(db, recording_id=rec.id)
        other = add_recording(db, title="Other", artist="Artist")
        other_track = add_track(db, release=release, recording=other, suffix="other", genre="Soul")
        db.commit()

        candidates = load_station_candidate_tracks(db, limit=20)
        assert len([track for track in candidates if getattr(track, "_station_recording_id", None) == rec.id]) == 1
        station = build_station_queue(StationQueueRequest(type="artist", seed_value="Artist", limit=10, shuffle=False), db)
        item = next(row for row in station["queue"] if row.get("recording_id") == rec.id)
        assert item["track_id"] == flac.id and item["effective_track_id"] == flac.id

        set_music_recording_user_preference(db, recording_id=rec.id, track_id=mp3.id)
        db.commit()
        station = build_station_queue(StationQueueRequest(type="artist", seed_value="Artist", limit=10, shuffle=False), db)
        item = next(row for row in station["queue"] if row.get("recording_id") == rec.id)
        assert item["track_id"] == mp3.id and item["effective_track_id"] == mp3.id
        assert rec_ids(station).count(rec.id) == 1

        for idx in range(5):
            add_track(db, release=release, recording=rec, suffix=f"extra-{idx}", genre="Soul")
        solo = add_recording(db, title="Solo", artist="Artist")
        solo_track = add_track(db, release=release, recording=solo, suffix="solo", genre="Soul")
        db.commit()
        candidates = load_station_candidate_tracks(db, limit=50)
        assert len([track for track in candidates if getattr(track, "_station_recording_id", None) == rec.id]) == 1
        assert len([track for track in candidates if getattr(track, "_station_recording_id", None) == solo.id]) == 1

        single = add_release(db, title="Single", artist="Artist", release_type="single")
        single_track = add_track(db, release=single, recording=rec, suffix="single", genre="Soul")
        live = add_recording(db, title="Song", artist="Artist", kind="live")
        acoustic = add_recording(db, title="Song", artist="Artist", kind="acoustic")
        remix = add_recording(db, title="Song", artist="Artist", kind="remix")
        inst = add_recording(db, title="Song", artist="Artist", kind="instrumental")
        radio = add_recording(db, title="Song", artist="Artist", kind="radio_edit")
        for recording in [live, acoustic, remix, inst, radio]:
            add_track(db, release=release, recording=recording, suffix=recording.recording_type, genre="Soul")
        db.commit()
        station = build_station_queue(StationQueueRequest(type="artist", seed_value="Artist", limit=20, shuffle=False), db)
        out = rec_ids(station)
        assert out.count(rec.id) == 1
        for recording in [live, acoustic, remix, inst, radio]:
            assert recording.id in out
    finally:
        db.close()


def case_participation_seed_and_exclusions(tmp: Path) -> None:
    _, Session = make_db(tmp, "participation")
    db = Session()
    try:
        release = add_release(db, artist="Artist")
        seed = add_recording(db, title="Seed", artist="Artist")
        seed_mp3 = add_track(db, release=release, recording=seed, suffix="seed-mp3", genre="Soul")
        seed_flac = add_track(db, release=release, recording=seed, suffix="seed-flac", codec="flac", is_lossless=True, genre="Soul")
        included = add_recording(db, title="Included", artist="Artist")
        included_track = add_track(db, release=release, recording=included, suffix="included", genre="Soul")
        lib = add_recording(db, title="Library Only", artist="Artist")
        lib_track = add_track(db, release=release, recording=lib, suffix="library", genre="Soul")
        archived = add_recording(db, title="Archived", artist="Artist")
        archived_track = add_track(db, release=release, recording=archived, suffix="archived", genre="Soul")
        blocked = add_recording(db, title="Blocked", artist="Artist")
        blocked_track = add_track(db, release=release, recording=blocked, suffix="blocked", genre="Soul")
        set_music_recording_participation(db, recording_id=lib.id, participation_state="library_only")
        set_music_recording_participation(db, recording_id=archived.id, participation_state="archived")
        set_music_recording_participation(db, recording_id=blocked.id, participation_state="blocked")
        db.commit()

        station = build_station_queue(StationQueueRequest(type="artist", seed_value="Artist", limit=20), db)
        out = set(rec_ids(station))
        assert included.id in out and seed.id in out
        assert lib.id not in out and archived.id not in out and blocked.id not in out
        for station_type in ["favorites", "recently_added", "deep_cuts", "genre"]:
            req = StationQueueRequest(type=station_type, seed_value="Soul" if station_type == "genre" else None, limit=20)
            assert lib.id not in set(rec_ids(build_station_queue(req, db)))

        station = build_station_queue(StationQueueRequest(type="song", seed_track_id=seed_mp3.id, limit=20), db)
        assert seed.id not in set(rec_ids(station)) and included.id in set(rec_ids(station))
        assert station_identity_keys_for_track_ids(db, [seed_mp3.id]) == {("recording", seed.id)}
        station = build_station_queue(StationQueueRequest(type="artist", seed_value="Artist", exclude_track_ids=[seed_mp3.id], limit=20), db)
        assert seed.id not in set(rec_ids(station))

        expect_http(409, build_station_queue, StationQueueRequest(type="song", seed_track_id=archived_track.id, limit=10), db)
        expect_http(409, build_station_queue, StationQueueRequest(type="song", seed_track_id=blocked_track.id, limit=10), db)

        legacy = add_track(db, release=None, recording=None, suffix="legacy", genre="Soul")
        missing = add_track(db, release=None, recording=None, suffix="missing", genre="Soul", availability=LIBRARY_UNAVAILABLE)
        db.commit()
        station = build_station_queue(StationQueueRequest(type="genre", seed_value="Soul", limit=50), db)
        assert legacy.id in ids(station) and missing.id not in ids(station)
    finally:
        db.close()


def case_signals_counts_debug_and_readonly(tmp: Path) -> None:
    engine, Session = make_db(tmp, "signals")
    db = Session()
    try:
        release = add_release(db, artist="Artist")
        now = datetime.now(UTC)
        fav = add_recording(db, title="Favorite", artist="Artist")
        fav_mp3 = add_track(db, release=release, recording=fav, suffix="fav-mp3", genre="Soul")
        fav_flac = add_track(db, release=release, recording=fav, suffix="fav-flac", codec="flac", is_lossless=True, genre="Soul")
        evaluate_music_recording_preference(db, recording_id=fav.id)
        db.add_all([models.TrackFavorite(track_id=fav_mp3.id, recording_id=None), models.TrackThumb(track_id=fav_flac.id, recording_id=fav.id, value=models.ThumbValue.up, created_at=now)])

        down = add_recording(db, title="Down", artist="Artist")
        down_mp3 = add_track(db, release=release, recording=down, suffix="down-mp3", genre="Soul")
        down_flac = add_track(db, release=release, recording=down, suffix="down-flac", codec="flac", is_lossless=True, genre="Soul")
        db.add(models.TrackThumb(track_id=down_mp3.id, recording_id=None, value=models.ThumbValue.down, created_at=now + timedelta(seconds=1)))

        played = add_recording(db, title="Played", artist="Artist")
        played_mp3 = add_track(db, release=release, recording=played, suffix="played-mp3", genre="Soul")
        played_flac = add_track(db, release=release, recording=played, suffix="played-flac", codec="flac", is_lossless=True, genre="Soul")
        for offset in range(5):
            db.add(models.PlaybackEvent(track_id=played_mp3.id if offset % 2 else played_flac.id, recording_id=played.id if offset >= 2 else None, event_type="qualified_play", created_at=now + timedelta(minutes=offset)))

        old = add_recording(db, title="Old", artist="Artist")
        old_mp3 = add_track(db, release=release, recording=old, suffix="old-mp3", genre="Soul", created_at=now - timedelta(days=10))
        old_flac = add_track(db, release=release, recording=old, suffix="old-flac", codec="flac", is_lossless=True, genre="Soul", created_at=now + timedelta(days=1))
        new = add_recording(db, title="New", artist="Artist")
        new_track = add_track(db, release=release, recording=new, suffix="new", genre="Soul", created_at=now - timedelta(days=1))
        db.commit()

        favorites = build_station_queue(StationQueueRequest(type="favorites", limit=20), db)
        assert rec_ids(favorites).count(fav.id) == 1
        assert down.id not in set(rec_ids(build_station_queue(StationQueueRequest(type="artist", seed_value="Artist", limit=50), db)))
        assert fav.id in set(rec_ids(build_station_queue(StationQueueRequest(type="artist", seed_value="Artist", limit=50), db)))

        deep = build_station_queue(StationQueueRequest(type="deep_cuts", limit=50), db)
        assert rec_ids(deep).count(played.id) <= 1
        recent = build_station_queue(StationQueueRequest(type="recently_added", limit=50), db)
        recent_ids = rec_ids(recent)
        assert recent_ids.index(new.id) < recent_ids.index(old.id)

        rows = asyncio.run(stations.get_stations(db))
        fav_station = next(row for row in rows if row["type"] == "favorites")
        assert fav_station["track_count"] == 1
        artist_station = next(row for row in rows if row.get("type") == "artist" and row.get("seed_value") == "Artist")
        assert artist_station["track_count"] >= 4
        assert logical_station_count(db, station_type="artist", seed_value="Artist") == artist_station["track_count"]

        debug = build_station_debug(StationQueueRequest(type="artist", seed_value="Artist", limit=20), db)
        assert debug["selected"]
        row = debug["selected"][0]
        for key in ["recording_id", "recording_type", "effective_track_id", "profile_track_id", "participation_state", "source_resolution", "source_confidence", "source_reason_code"]:
            assert key in row
        normal = build_station_queue(StationQueueRequest(type="artist", seed_value="Artist", limit=20), db)
        assert set(rec_ids(normal)) == {row.get("recording_id") for row in debug["selected"] if row.get("recording_id") is not None}

        before = {
            "preferences": db.query(models.MusicRecordingPreference).count(),
            "participation": db.query(models.MusicRecordingParticipation).count(),
            "favorites": db.query(models.TrackFavorite).count(),
            "thumbs": db.query(models.TrackThumb).count(),
            "events": db.query(models.PlaybackEvent).count(),
        }
        build_station_queue(StationQueueRequest(type="genre", seed_value="Soul", limit=20), db)
        after = {
            "preferences": db.query(models.MusicRecordingPreference).count(),
            "participation": db.query(models.MusicRecordingParticipation).count(),
            "favorites": db.query(models.TrackFavorite).count(),
            "thumbs": db.query(models.TrackThumb).count(),
            "events": db.query(models.PlaybackEvent).count(),
        }
        assert before == after

        select_count = 0
        for idx in range(100):
            rec = add_recording(db, title=f"Bulk {idx}", artist="Artist")
            add_track(db, release=release, recording=rec, suffix=f"bulk-{idx}", genre="Soul")
            add_track(db, release=release, recording=rec, suffix=f"bulk-{idx}-flac", codec="flac", is_lossless=True, genre="Soul")
        db.commit()

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            nonlocal select_count
            if statement.lstrip().upper().startswith("SELECT"):
                select_count += 1

        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            result = build_station_queue(StationQueueRequest(type="genre", seed_value="Soul", limit=25), db)
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
        assert len(result["queue"]) <= 25 and select_count < 80, select_count
    finally:
        db.close()


def case_structural_scope() -> None:
    source = Path("app/station_engine.py").read_text(encoding="utf-8")
    assert "choose_preferred_tracks" not in source
    assert "quality_rank" not in source and "rank_recording_variant" not in source
    assert "recording_mode" not in source
    assert "seed_recording_id" not in source
    request_source = Path("app/queue_contracts.py").read_text(encoding="utf-8")
    assert "version_affinity" not in request_source and "recording_mode" not in request_source
    assert "frontend" not in source.lower()
    assert "write_bytes" not in source
    assert "avoid_title_dups=True" in source
    for station_type in ["song", "artist", "genre", "favorites", "recently_added", "deep_cuts"]:
        assert station_type in source


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_5a_recording_first_station_candidates"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_candidates_and_sources(tmp)
        case_participation_seed_and_exclusions(tmp)
        case_signals_counts_debug_and_readonly(tmp)
        case_structural_scope()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.5A recording-first station candidate foundation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())