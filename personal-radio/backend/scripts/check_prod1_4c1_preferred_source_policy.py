from __future__ import annotations

import inspect
from pathlib import Path
import shutil
import sys

from sqlalchemy import create_engine, event, inspect as sqlalchemy_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.music_source_preference import (
    PREFERENCE_BATCH_CHUNK_SIZE,
    evaluate_music_recording_preference,
    evaluate_music_recording_preferences,
    resolve_effective_music_source,
    set_music_recording_user_preference,
)
from app.schema_maintenance import ensure_scan_reconciliation_columns
from app.scan_runs import LIBRARY_AVAILABLE, LIBRARY_UNAVAILABLE


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def add_recording(db, title: str = "Song") -> models.MusicRecording:
    row = models.MusicRecording(identity_key=f"recording-{title}-{db.query(models.MusicRecording).count()}", artist="Artist", title=title, normalized_artist="artist", normalized_title=title.lower(), recording_type="unknown", duration_bucket="180")
    db.add(row)
    db.flush()
    return row


def add_track_candidate(
    db,
    recording: models.MusicRecording,
    *,
    title: str = "Song",
    availability: str = LIBRARY_AVAILABLE,
    is_lossless: bool | None = None,
    codec: str | None = None,
    probe_status: str | None = "ok",
    bitrate: int | None = None,
    sample_rate: int | None = None,
    bit_depth: int | None = None,
    file_size: int | None = None,
) -> models.Track:
    index = db.query(models.Track).count() + 1
    track = models.Track(
        path=f"C:/synthetic/{recording.id}/{index:03d}-{title}.mp3",
        relative_path=f"synthetic/{recording.id}/{index:03d}-{title}.mp3",
        title=title,
        artist="Artist",
        album="Album",
        album_artist="Artist",
        duration_seconds=180,
        file_ext=".mp3",
        library_availability=availability,
    )
    db.add(track)
    db.flush()
    edition = models.MusicEdition(identity_key=f"edition-{recording.id}-{index}", release_id=ensure_release(db).id, display_title="Album", source_scope=f"scope-{recording.id}-{index}")
    db.add(edition)
    db.flush()
    db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=recording.id))
    db.add(models.MusicTechnicalProfile(track_id=track.id, probe_status=probe_status or "partial", codec=codec, is_lossless=is_lossless, bitrate_bps=bitrate, sample_rate_hz=sample_rate, bit_depth_bits=bit_depth, file_size_bytes=file_size))
    db.flush()
    return track


def ensure_release(db) -> models.MusicRelease:
    row = db.query(models.MusicRelease).filter_by(identity_key="test-release").one_or_none()
    if row is None:
        row = models.MusicRelease(identity_key="test-release", album_artist="Artist", title="Album", normalized_album_artist="artist", normalized_title="album")
        db.add(row)
        db.flush()
    return row


def pref(db, recording: models.MusicRecording) -> models.MusicRecordingPreference:
    return evaluate_music_recording_preference(db, recording_id=recording.id)


def case_a_schema(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_a")
    inspector = sqlalchemy_inspect(engine)
    assert "music_recording_preferences" in inspector.get_table_names()
    indexes = {tuple(index["column_names"]) for index in inspector.get_indexes("music_recording_preferences")}
    assert ("recording_id",) in indexes
    assert ("auto_preferred_track_id",) in indexes
    assert ("user_preferred_track_id",) in indexes
    assert ("decision_state",) in indexes
    db = Session()
    try:
        recording = add_recording(db)
        db.add_all([models.MusicRecordingPreference(recording_id=recording.id), models.MusicRecordingPreference(recording_id=recording.id)])
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("recording_id unique constraint missing")
    finally:
        db.close()
        engine.dispose()


def case_b_to_k_policy_rules(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_rules")
    db = Session()
    try:
        one = add_recording(db, "one")
        only = add_track_candidate(db, one, probe_status="failed")
        row = pref(db, one)
        assert row.decision_state == "preferred" and row.auto_preferred_track_id == only.id and row.confidence == "high" and row.reason_code == "single_available_source"

        rec = add_recording(db, "lossless")
        flac = add_track_candidate(db, rec, is_lossless=True, codec="flac", sample_rate=44100, bit_depth=16)
        add_track_candidate(db, rec, is_lossless=False, codec="mp3", bitrate=320000)
        row = pref(db, rec)
        assert row.auto_preferred_track_id == flac.id and row.reason_code == "unique_lossless_source" and row.confidence == "high"

        rec = add_recording(db, "lossless_unknown")
        known = add_track_candidate(db, rec, is_lossless=True, codec="flac")
        add_track_candidate(db, rec, is_lossless=None, codec="unknown", probe_status="partial")
        assert pref(db, rec).auto_preferred_track_id == known.id

        rec = add_recording(db, "two_lossless")
        add_track_candidate(db, rec, is_lossless=True, codec="flac", sample_rate=96000, bit_depth=24, file_size=999999)
        add_track_candidate(db, rec, is_lossless=True, codec="flac", sample_rate=44100, bit_depth=16, file_size=111111)
        row = pref(db, rec)
        assert row.decision_state == "ambiguous" and row.auto_preferred_track_id is None and row.reason_code == "multiple_lossless_sources_ambiguous"

        rec = add_recording(db, "two_lossless_reversed")
        add_track_candidate(db, rec, is_lossless=True, codec="flac", sample_rate=44100, bit_depth=16, file_size=1)
        add_track_candidate(db, rec, is_lossless=True, codec="flac", sample_rate=192000, bit_depth=24, file_size=999999999)
        row = pref(db, rec)
        assert row.decision_state == "ambiguous" and row.auto_preferred_track_id is None

        rec = add_recording(db, "healthy")
        ok = add_track_candidate(db, rec, is_lossless=None, codec="unknown", probe_status="ok")
        add_track_candidate(db, rec, is_lossless=None, codec="unknown", probe_status="partial")
        add_track_candidate(db, rec, is_lossless=None, codec="unknown", probe_status="failed")
        row = pref(db, rec)
        assert row.auto_preferred_track_id == ok.id and row.confidence == "medium" and row.reason_code == "unique_healthy_probe"

        rec = add_recording(db, "bitrate")
        add_track_candidate(db, rec, is_lossless=False, codec="mp3", bitrate=128000)
        high = add_track_candidate(db, rec, is_lossless=False, codec="mp3", bitrate=320000)
        row = pref(db, rec)
        assert row.auto_preferred_track_id == high.id and row.reason_code == "higher_bitrate_same_lossy_codec"

        rec = add_recording(db, "mixed_lossy")
        add_track_candidate(db, rec, is_lossless=False, codec="mp3", bitrate=320000)
        add_track_candidate(db, rec, is_lossless=False, codec="aac", bitrate=256000)
        row = pref(db, rec)
        assert row.decision_state == "ambiguous" and row.reason_code == "mixed_lossy_codecs_ambiguous"

        rec = add_recording(db, "none_available")
        add_track_candidate(db, rec, availability=LIBRARY_UNAVAILABLE, is_lossless=True, codec="flac")
        row = pref(db, rec)
        assert row.decision_state == "no_eligible_source" and row.auto_preferred_track_id is None and row.confidence == "none"

        rec = add_recording(db, "unavailable_flac")
        old = add_track_candidate(db, rec, availability=LIBRARY_UNAVAILABLE, is_lossless=True, codec="flac")
        active = add_track_candidate(db, rec, is_lossless=False, codec="mp3", bitrate=128000)
        row = pref(db, rec)
        assert row.auto_preferred_track_id == active.id and row.reason_code == "single_available_source"
        assert db.get(models.Track, old.id) is not None and db.get(models.MusicTechnicalProfile, old.technical_profile.id) is not None
    finally:
        db.close()


def case_l_to_p_resolver_and_overrides(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_resolver")
    db = Session()
    try:
        rec = add_recording(db, "fallback")
        a = add_track_candidate(db, rec, is_lossless=True, codec="flac")
        b = add_track_candidate(db, rec, is_lossless=True, codec="flac")
        row = pref(db, rec)
        assert row.auto_preferred_track_id is None
        first = resolve_effective_music_source(db, recording_id=rec.id)
        second = resolve_effective_music_source(db, recording_id=rec.id)
        assert first.track_id == min(a.id, b.id) and second.track_id == first.track_id
        assert first.source == "deterministic_fallback" and first.confidence == "low"

        rec = add_recording(db, "override")
        flac = add_track_candidate(db, rec, is_lossless=True, codec="flac")
        mp3 = add_track_candidate(db, rec, is_lossless=False, codec="mp3", bitrate=320000)
        row = pref(db, rec)
        assert row.auto_preferred_track_id == flac.id
        set_music_recording_user_preference(db, recording_id=rec.id, track_id=mp3.id)
        resolution = resolve_effective_music_source(db, recording_id=rec.id)
        assert resolution.track_id == mp3.id and resolution.source == "user_override" and resolution.reason_code == "user_override"
        assert db.query(models.MusicRecordingPreference).filter_by(recording_id=rec.id).one().auto_preferred_track_id == flac.id

        other = add_recording(db, "other")
        other_track = add_track_candidate(db, other, is_lossless=False, codec="mp3")
        db.commit()
        before = db.query(models.MusicRecordingPreference).filter_by(recording_id=rec.id).one().user_preferred_track_id
        try:
            set_music_recording_user_preference(db, recording_id=rec.id, track_id=other_track.id)
        except ValueError:
            db.rollback()
        else:
            raise AssertionError("cross-recording override accepted")
        assert db.query(models.MusicRecordingPreference).filter_by(recording_id=rec.id).one().user_preferred_track_id == before

        set_music_recording_user_preference(db, recording_id=rec.id, track_id=mp3.id)
        mp3.library_availability = LIBRARY_UNAVAILABLE
        db.commit()
        resolution = resolve_effective_music_source(db, recording_id=rec.id)
        assert db.query(models.MusicRecordingPreference).filter_by(recording_id=rec.id).one().user_preferred_track_id == mp3.id
        assert resolution.track_id == flac.id and resolution.reason_code == "user_override_unavailable_fallback"
        mp3.library_availability = LIBRARY_AVAILABLE
        db.commit()
        assert resolve_effective_music_source(db, recording_id=rec.id).track_id == mp3.id

        stale = db.query(models.MusicRecordingPreference).filter_by(recording_id=rec.id).one()
        stale.user_preferred_track_id = None
        stale.auto_preferred_track_id = flac.id
        flac.library_availability = LIBRARY_UNAVAILABLE
        db.commit()
        resolution = resolve_effective_music_source(db, recording_id=rec.id)
        assert resolution.track_id == mp3.id and resolution.source == "deterministic_fallback"
    finally:
        db.close()


def case_q_r_idempotency_counts(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_counts")
    db = Session()
    try:
        rec = add_recording(db, "counts")
        available = add_track_candidate(db, rec, is_lossless=False, codec="mp3")
        unavailable = add_track_candidate(db, rec, availability=LIBRARY_UNAVAILABLE, is_lossless=True, codec="flac")
        row1 = pref(db, rec)
        first = (row1.id, row1.decision_state, row1.auto_preferred_track_id, row1.reason_code, row1.candidate_count, row1.eligible_candidate_count)
        row2 = pref(db, rec)
        second = (row2.id, row2.decision_state, row2.auto_preferred_track_id, row2.reason_code, row2.candidate_count, row2.eligible_candidate_count)
        assert first == second
        assert row2.candidate_count == 2 and row2.eligible_candidate_count == 1
        assert row2.auto_preferred_track_id == available.id
        assert db.get(models.Track, unavailable.id) is not None
    finally:
        db.close()


def case_s_t_batch_behavior(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_batch")
    db = Session()
    try:
        recording_ids = []
        for i in range(120):
            rec = add_recording(db, f"batch-{i}")
            recording_ids.append(rec.id)
            add_track_candidate(db, rec, is_lossless=True, codec="flac")
            add_track_candidate(db, rec, is_lossless=False, codec="mp3", bitrate=320000)
        db.commit()
        counts = {"selects": 0}
        def count_select(conn, cursor, statement, parameters, context, executemany):
            lowered = statement.lower()
            if lowered.lstrip().startswith("select") and any(name in lowered for name in ["music_track_identities", "music_technical_profiles", "music_recording_preferences"]):
                counts["selects"] += 1
        event.listen(engine, "before_cursor_execute", count_select)
        try:
            result = evaluate_music_recording_preferences(db, recording_ids=recording_ids)
            db.commit()
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert result["recordings_seen"] == 120
        assert counts["selects"] < 20, counts
        assert db.query(models.MusicRecordingPreference).count() == 120

        more_ids = []
        for i in range(PREFERENCE_BATCH_CHUNK_SIZE + 5):
            rec = add_recording(db, f"chunk-{i}")
            more_ids.append(rec.id)
            add_track_candidate(db, rec, is_lossless=False, codec="mp3", bitrate=128000)
        db.commit()
        result = evaluate_music_recording_preferences(db, recording_ids=more_ids)
        db.commit()
        assert result["recordings_seen"] == PREFERENCE_BATCH_CHUNK_SIZE + 5
    finally:
        db.close()
        engine.dispose()


def case_u_v_w_x_non_goals_and_state(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_non_goals")
    db = Session()
    try:
        columns = {column.name for column in models.MusicRecordingPreference.__table__.columns}
        assert "quality_score" not in columns and "bm_score" not in columns and "winner_score" not in columns
        assert "preferred_track_id" not in columns and "preferred_edition_id" not in columns

        rec = add_recording(db, "lossless_nonranking")
        add_track_candidate(db, rec, is_lossless=True, codec="flac", sample_rate=44100, bit_depth=16, bitrate=800000, file_size=10)
        add_track_candidate(db, rec, is_lossless=True, codec="flac", sample_rate=192000, bit_depth=24, bitrate=9000000, file_size=999999)
        row = pref(db, rec)
        assert row.decision_state == "ambiguous" and row.auto_preferred_track_id is None

        rec = add_recording(db, "state")
        track = add_track_candidate(db, rec, is_lossless=False, codec="mp3")
        db.add_all([models.TrackFavorite(track_id=track.id), models.TrackThumb(track_id=track.id, value=models.ThumbValue.up), models.PlaybackEvent(track_id=track.id, event_type="qualified_play")])
        playlist = models.Playlist(name="State", kind="manual")
        db.add(playlist)
        db.flush()
        db.add(models.PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=1))
        db.commit()
        pref(db, rec)
        set_music_recording_user_preference(db, recording_id=rec.id, track_id=track.id)
        assert db.query(models.TrackFavorite).filter_by(track_id=track.id).count() == 1
        assert db.query(models.TrackThumb).filter_by(track_id=track.id).count() == 1
        assert db.query(models.PlaybackEvent).filter_by(track_id=track.id).count() == 1
        assert db.query(models.PlaylistTrack).filter_by(track_id=track.id).count() == 1
        assert db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).count() == 1
        assert db.query(models.MusicTechnicalProfile).filter_by(track_id=track.id).count() == 1

        source = inspect.getsource(__import__("app.music_source_preference", fromlist=["dummy"]))
        for forbidden in ["open(", "read_bytes", "write_bytes", "Mutagen", "mutagen"]:
            assert forbidden not in source
    finally:
        db.close()


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4c1_preferred_source_policy"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_schema(tmp)
        case_b_to_k_policy_rules(tmp)
        case_l_to_p_resolver_and_overrides(tmp)
        case_q_r_idempotency_counts(tmp)
        case_s_t_batch_behavior(tmp)
        case_u_v_w_x_non_goals_and_state(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.4C1 conservative preferred-source policy foundation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())