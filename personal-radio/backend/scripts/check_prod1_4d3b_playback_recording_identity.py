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
from app.routes import media, playback
from app.scan_runs import LIBRARY_AVAILABLE, LIBRARY_UNAVAILABLE
from app.schema_maintenance import ensure_playback_identity_columns, ensure_scan_reconciliation_columns

UTC = timezone.utc


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    ensure_playback_identity_columns(engine)
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


def add_track(
    db,
    root: Path,
    *,
    release,
    recording=None,
    suffix: str,
    codec: str = "mp3",
    is_lossless: bool | None = False,
    availability: str = LIBRARY_AVAILABLE,
    created_offset: int = 0,
    track_number: int = 1,
):
    idx = db.query(models.Track).count() + 1
    path = root / f"{idx}-{suffix}.{codec}"
    path.write_bytes(b"synthetic audio")
    when = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=created_offset)
    track = models.Track(path=str(path), relative_path=path.name, title=(recording.title if recording else suffix), artist=(recording.artist if recording else "Legacy"), album=release.title if release else "Legacy", album_artist=release.album_artist if release else "Legacy", genre="Test", primary_genre="Test", year=2026, duration_seconds=180.0, file_ext=f".{codec}", library_area="Library", track_number=track_number, disc_number=1, library_availability=availability, created_at=when, last_indexed_at=when)
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


def expect_http(status: int, detail: str | None, func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except HTTPException as exc:
        assert exc.status_code == status, (exc.status_code, exc.detail)
        if detail is not None:
            assert exc.detail == detail, exc.detail
        return exc
    raise AssertionError(f"expected HTTP {status}")


def qualified_count(db, recording_id: int | None = None) -> int:
    query = db.query(models.PlaybackEvent).filter_by(event_type="qualified_play")
    if recording_id is not None:
        query = query.filter_by(recording_id=recording_id)
    return query.count()


def case_schema(tmp: Path) -> None:
    engine, _ = make_db(tmp, "fresh_schema")
    insp = sa_inspect(engine)
    assert "recording_id" in {column["name"] for column in insp.get_columns("playback_events")}
    assert "ix_playback_events_recording_id" in {idx["name"] for idx in insp.get_indexes("playback_events")}

    old_path = tmp / "old_schema.db"
    old_engine = create_engine(f"sqlite:///{old_path}", connect_args={"check_same_thread": False})
    with old_engine.begin() as conn:
        conn.execute(text("CREATE TABLE playback_events (id INTEGER PRIMARY KEY, track_id INTEGER, event_type VARCHAR, created_at DATETIME)"))
        conn.execute(text("INSERT INTO playback_events (id, track_id, event_type, created_at) VALUES (1, 7, 'qualified_play', '2026-01-01 00:00:00')"))
    ensure_playback_identity_columns(old_engine)
    ensure_playback_identity_columns(old_engine)
    insp = sa_inspect(old_engine)
    assert "recording_id" in {column["name"] for column in insp.get_columns("playback_events")}
    assert "ix_playback_events_recording_id" in {idx["name"] for idx in insp.get_indexes("playback_events")}
    with old_engine.connect() as conn:
        row = conn.execute(text("SELECT id, track_id, recording_id FROM playback_events")).mappings().one()
    assert row["id"] == 1 and row["track_id"] == 7 and row["recording_id"] is None


def case_events_and_qualification(tmp: Path) -> None:
    _, Session = make_db(tmp, "events")
    root = tmp / "media-events"
    root.mkdir()
    db = Session()
    try:
        release = add_release(db)
        rec = add_recording(db)
        flac = add_track(db, root, release=release, recording=rec, suffix="song-flac", codec="flac", is_lossless=True)
        mp3 = add_track(db, root, release=release, recording=rec, suffix="song-mp3")
        db.commit()

        result = playback.register_event(playback.PlaybackEventCreate(event_type="start", track_id=flac.id, mode="music"), db=db)
        event = db.get(models.PlaybackEvent, result["id"])
        assert event.track_id == flac.id and event.recording_id == rec.id

        playback.register_event(playback.PlaybackEventCreate(event_type="finish", track_id=flac.id, mode="music", position_seconds=180), db=db)
        qp = db.query(models.PlaybackEvent).filter_by(event_type="qualified_play", recording_id=rec.id).one()
        assert qp.track_id == flac.id and qp.recording_id == rec.id

        playback.register_event(playback.PlaybackEventCreate(event_type="finish", track_id=mp3.id, mode="music", position_seconds=180), db=db)
        assert qualified_count(db, rec.id) == 1

        other = add_recording(db, title="Song", kind="live")
        other_track = add_track(db, root, release=release, recording=other, suffix="song-live")
        db.commit()
        playback.register_event(playback.PlaybackEventCreate(event_type="finish", track_id=other_track.id, mode="music", position_seconds=180), db=db)
        assert qualified_count(db, rec.id) == 1 and qualified_count(db, other.id) == 1

        legacy_variant = add_track(db, root, release=release, recording=rec, suffix="legacy-null")
        db.add(models.PlaybackEvent(track_id=flac.id, recording_id=None, event_type="qualified_play", created_at=datetime.now(UTC)))
        db.commit()
        before = qualified_count(db)
        playback.register_event(playback.PlaybackEventCreate(event_type="finish", track_id=legacy_variant.id, mode="music", position_seconds=180), db=db)
        assert qualified_count(db) == before

        legacy = add_track(db, root, release=None, recording=None, suffix="identityless")
        db.commit()
        playback.register_event(playback.PlaybackEventCreate(event_type="finish", track_id=legacy.id, mode="music", position_seconds=180), db=db)
        row = db.query(models.PlaybackEvent).filter_by(track_id=legacy.id, event_type="finish").one()
        assert row.recording_id is None
        assert db.query(models.PlaybackEvent).filter_by(track_id=legacy.id, event_type="qualified_play", recording_id=None).count() == 1
    finally:
        db.close()


def case_stream_and_participation(tmp: Path) -> None:
    _, Session = make_db(tmp, "stream")
    root = tmp / "media-stream"
    root.mkdir()
    db = Session()
    original_safe = media.safe_file
    original_roots = media.music_media_roots
    calls: list[str] = []
    try:
        media.music_media_roots = lambda: [root]

        def fake_safe(path_value, roots, types):
            calls.append(str(path_value))
            return {"served": str(path_value)}

        media.safe_file = fake_safe
        release = add_release(db)
        blocked = add_recording(db, title="Blocked")
        blocked_track = add_track(db, root, release=release, recording=blocked, suffix="blocked")
        set_music_recording_participation(db, recording_id=blocked.id, participation_state="blocked")
        db.commit()
        expect_http(409, "Recording is blocked from playback", media.stream_track, blocked_track.id, db=db)
        assert calls == []
        expect_http(409, "Recording is blocked from playback", playback.register_event, playback.PlaybackEventCreate(event_type="finish", track_id=blocked_track.id, mode="music", position_seconds=180), db=db)
        assert db.query(models.PlaybackEvent).count() == 0

        for state in ["included", "library_only", "archived"]:
            rec = add_recording(db, title=state)
            track = add_track(db, root, release=release, recording=rec, suffix=state)
            if state != "included":
                set_music_recording_participation(db, recording_id=rec.id, participation_state=state)
            db.commit()
            assert media.stream_track(track.id, db=db)["served"] == track.path
            playback.register_event(playback.PlaybackEventCreate(event_type="finish", track_id=track.id, mode="music", position_seconds=180), db=db)
            assert db.query(models.PlaybackEvent).filter_by(track_id=track.id, event_type="finish").one().recording_id == rec.id

        rec = add_recording(db, title="Alternate")
        one = add_track(db, root, release=release, recording=rec, suffix="alt-one")
        two = add_track(db, root, release=release, recording=rec, suffix="alt-two", codec="flac", is_lossless=True)
        evaluate_music_recording_preference(db, recording_id=rec.id)
        db.commit()
        media.stream_track(one.id, db=db)
        media.stream_track(two.id, db=db)
        assert calls[-2:] == [one.path, two.path]
    finally:
        media.safe_file = original_safe
        media.music_media_roots = original_roots
        db.close()


def case_recent_projection(tmp: Path) -> None:
    _, Session = make_db(tmp, "recent")
    root = tmp / "media-recent"
    root.mkdir()
    db = Session()
    try:
        release = add_release(db, title="Album")
        rec = add_recording(db, title="Recent")
        mp3 = add_track(db, root, release=release, recording=rec, suffix="recent-mp3", created_offset=1)
        flac = add_track(db, root, release=release, recording=rec, suffix="recent-flac", codec="flac", is_lossless=True, created_offset=2)
        evaluate_music_recording_preference(db, recording_id=rec.id)
        now = datetime.now(UTC)
        db.add_all([
            models.PlaybackEvent(track_id=flac.id, recording_id=rec.id, event_type="qualified_play", created_at=now - timedelta(minutes=5)),
            models.PlaybackEvent(track_id=mp3.id, recording_id=rec.id, event_type="qualified_play", created_at=now),
        ])
        db.commit()
        item = playback.recent_playback(limit=5, db=db)["items"][0]
        assert item["recording_id"] == rec.id
        assert item["played_track_id"] == mp3.id
        assert item["track_id"] == flac.id and item["effective_track_id"] == flac.id
        assert item["stream_url"] == f"/api/media/tracks/{flac.id}/stream"

        set_music_recording_user_preference(db, recording_id=rec.id, track_id=mp3.id)
        db.commit()
        item = playback.recent_playback(limit=5, db=db)["items"][0]
        assert item["track_id"] == mp3.id and item["played_track_id"] == mp3.id
        assert db.query(models.PlaybackEvent).filter_by(recording_id=rec.id).count() == 2

        ambiguous = add_recording(db, title="Ambiguous")
        a = add_track(db, root, release=release, recording=ambiguous, suffix="amb-a", codec="flac", is_lossless=True)
        b = add_track(db, root, release=release, recording=ambiguous, suffix="amb-b", codec="flac", is_lossless=True)
        pref_count = db.query(models.MusicRecordingPreference).count()
        db.add(models.PlaybackEvent(track_id=b.id, recording_id=ambiguous.id, event_type="qualified_play", created_at=now + timedelta(minutes=1)))
        db.commit()
        item = playback.recent_playback(limit=5, db=db)["items"][0]
        assert item["recording_id"] == ambiguous.id and item["source_resolution"] == "deterministic_fallback" and item["track_id"] == a.id
        assert db.query(models.MusicRecordingPreference).count() == pref_count

        unavailable_played = add_recording(db, title="Unavailable Played")
        old = add_track(db, root, release=release, recording=unavailable_played, suffix="old", availability=LIBRARY_UNAVAILABLE)
        current = add_track(db, root, release=release, recording=unavailable_played, suffix="current")
        db.add(models.PlaybackEvent(track_id=old.id, recording_id=unavailable_played.id, event_type="qualified_play", created_at=now + timedelta(minutes=2)))
        db.commit()
        item = playback.recent_playback(limit=5, db=db)["items"][0]
        assert item["recording_id"] == unavailable_played.id and item["played_track_id"] == old.id and item["track_id"] == current.id

        no_source = add_recording(db, title="No Source")
        hidden_track = add_track(db, root, release=release, recording=no_source, suffix="no-source", availability=LIBRARY_UNAVAILABLE)
        db.add(models.PlaybackEvent(track_id=hidden_track.id, recording_id=no_source.id, event_type="qualified_play", created_at=now + timedelta(minutes=3)))
        db.commit()
        assert no_source.id not in {row.get("recording_id") for row in playback.recent_playback(limit=10, db=db)["items"]}

        archived = add_recording(db, title="Archived")
        archived_track = add_track(db, root, release=release, recording=archived, suffix="archived")
        blocked = add_recording(db, title="Blocked Recent")
        blocked_track = add_track(db, root, release=release, recording=blocked, suffix="blocked-recent")
        visible = add_recording(db, title="Library Visible")
        visible_track = add_track(db, root, release=release, recording=visible, suffix="library-visible")
        set_music_recording_participation(db, recording_id=archived.id, participation_state="archived")
        set_music_recording_participation(db, recording_id=blocked.id, participation_state="blocked")
        set_music_recording_participation(db, recording_id=visible.id, participation_state="library_only")
        db.add_all([
            models.PlaybackEvent(track_id=archived_track.id, recording_id=archived.id, event_type="qualified_play", created_at=now + timedelta(minutes=4)),
            models.PlaybackEvent(track_id=blocked_track.id, recording_id=blocked.id, event_type="qualified_play", created_at=now + timedelta(minutes=5)),
            models.PlaybackEvent(track_id=visible_track.id, recording_id=visible.id, event_type="qualified_play", created_at=now + timedelta(minutes=6)),
        ])
        db.commit()
        ids = {row.get("recording_id") for row in playback.recent_playback(limit=10, db=db)["items"]}
        assert visible.id in ids and archived.id not in ids and blocked.id not in ids

        single = add_release(db, title="Single", release_type="single")
        single_track = add_track(db, root, release=single, recording=rec, suffix="recent-single")
        db.add(models.PlaybackEvent(track_id=single_track.id, recording_id=rec.id, event_type="qualified_play", created_at=now + timedelta(minutes=7)))
        live = add_recording(db, title="Recent", kind="live")
        live_track = add_track(db, root, release=release, recording=live, suffix="recent-live")
        db.add(models.PlaybackEvent(track_id=live_track.id, recording_id=live.id, event_type="qualified_play", created_at=now + timedelta(minutes=8)))
        legacy = add_track(db, root, release=None, recording=None, suffix="legacy-recent")
        db.add(models.PlaybackEvent(track_id=legacy.id, recording_id=None, event_type="qualified_play", created_at=now + timedelta(minutes=9)))
        db.commit()
        items = playback.recent_playback(limit=20, db=db)["items"]
        assert len([row for row in items if row.get("recording_id") == rec.id]) == 1
        assert live.id in {row.get("recording_id") for row in items}
        legacy_item = next(row for row in items if row.get("played_track_id") == legacy.id)
        assert legacy_item["recording_id"] is None and legacy_item["track_id"] == legacy.id
    finally:
        db.close()


def case_audiobook_and_scope(tmp: Path) -> None:
    _, Session = make_db(tmp, "audiobook")
    db = Session()
    try:
        book = models.Audiobook(path="C:/books/book", title="Book", author="Author", library_availability=LIBRARY_AVAILABLE)
        db.add(book)
        db.flush()
        chapter = models.AudiobookChapter(audiobook_id=book.id, path="C:/books/book/01.m4b", title="One", sort_order=1, library_availability=LIBRARY_AVAILABLE)
        db.add(chapter)
        db.flush()
        db.add(models.AudiobookProgress(audiobook_id=book.id, chapter_id=chapter.id, position_seconds=12, progress_percent=10, status="in_progress"))
        db.add(models.PlaybackEvent(audiobook_id=book.id, event_type="progress", created_at=datetime.now(UTC)))
        db.commit()
        item = playback.recent_playback(limit=1, db=db)["items"][0]
        assert item["mode"] == "audiobook" and item["audiobook_id"] == book.id and "recording_id" not in item

        assert "music_playback_policy" not in Path("app/station_engine.py").read_text(encoding="utf-8")
        assert "MusicRecording" not in Path("app/routes/stations.py").read_text(encoding="utf-8")
        assert "write_bytes" not in inspect.getsource(playback.recent_playback)
    finally:
        db.close()


def case_recent_query_bounds_and_readonly(tmp: Path) -> None:
    engine, Session = make_db(tmp, "bounds")
    root = tmp / "media-bounds"
    root.mkdir()
    db = Session()
    try:
        release = add_release(db)
        now = datetime.now(UTC)
        tracks = []
        for idx in range(120):
            rec = add_recording(db, title=f"Song {idx}")
            track = add_track(db, root, release=release, recording=rec, suffix=f"song-{idx}")
            tracks.append(track)
            db.add(models.PlaybackEvent(track_id=track.id, recording_id=rec.id, event_type="qualified_play", created_at=now - timedelta(seconds=idx)))
        db.commit()
        before_counts = {
            "preferences": db.query(models.MusicRecordingPreference).count(),
            "participation": db.query(models.MusicRecordingParticipation).count(),
            "events": db.query(models.PlaybackEvent).count(),
            "identities": db.query(models.MusicTrackIdentity).count(),
        }
        select_count = 0
        playback_selects: list[str] = []

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            nonlocal select_count
            if statement.lstrip().upper().startswith("SELECT"):
                select_count += 1
                if "playback_events" in statement:
                    playback_selects.append(statement)

        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            items = playback.recent_playback(limit=5, db=db)["items"]
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
        after_counts = {
            "preferences": db.query(models.MusicRecordingPreference).count(),
            "participation": db.query(models.MusicRecordingParticipation).count(),
            "events": db.query(models.PlaybackEvent).count(),
            "identities": db.query(models.MusicTrackIdentity).count(),
        }
        assert len(items) == 5
        assert select_count < 20, select_count
        assert playback_selects and any("LIMIT" in statement.upper() for statement in playback_selects)
        assert before_counts == after_counts
    finally:
        db.close()


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4d3b_playback_recording_identity"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_schema(tmp)
        case_events_and_qualification(tmp)
        case_stream_and_participation(tmp)
        case_recent_projection(tmp)
        case_audiobook_and_scope(tmp)
        case_recent_query_bounds_and_readonly(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.4D3B playback safety and recording-aware history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
