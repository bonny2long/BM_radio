from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import inspect
import random
import shutil
import sys

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.music_recording_participation import set_music_recording_participation
from app.music_source_preference import evaluate_music_recording_preference, set_music_recording_user_preference
from app.queue_contracts import StationQueueRequest
from app.scan_runs import LIBRARY_AVAILABLE
from app.schema_maintenance import ensure_playback_identity_columns, ensure_recording_feedback_columns, ensure_scan_reconciliation_columns
from app.station_candidates import load_station_candidate_tracks
from app.station_engine import build_station_debug, build_station_queue
from app.station_version_affinity import (
    ADJACENT_BOOST,
    OTHER_PENALTY,
    PRIMARY_BOOST,
    affinity_summary,
    classify_affinity_tier,
    derive_version_affinity_intent,
)

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


def add_release(db, *, title: str = "Affinity Album", artist: str = "Seed Artist"):
    idx = db.query(models.MusicRelease).count() + 1
    row = models.MusicRelease(identity_key=f"release-15b-{idx}-{artist}-{title}", album_artist=artist, title=title, normalized_album_artist=artist.lower(), normalized_title=title.lower(), release_type="album")
    db.add(row)
    db.flush()
    return row


def add_recording(db, *, title: str, artist: str, kind: str):
    idx = db.query(models.MusicRecording).count() + 1
    row = models.MusicRecording(identity_key=f"recording-15b-{idx}-{artist}-{title}-{kind}", artist=artist, title=title, normalized_artist=artist.lower(), normalized_title=title.lower(), recording_type=kind, version_hint=kind, duration_bucket="180")
    db.add(row)
    db.flush()
    return row


def add_track(db, *, release, recording=None, suffix: str, artist: str | None = None, title: str | None = None, genre: str = "Soul", codec: str = "mp3", is_lossless: bool = False, created_at: datetime | None = None, sample_rate: int = 44100):
    idx = db.query(models.Track).count() + 1
    when = created_at or (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=idx))
    track_artist = artist or (recording.artist if recording is not None else "Legacy")
    track_title = title or (recording.title if recording is not None else suffix)
    track = models.Track(path=f"C:/synthetic/15b/{idx}-{suffix}.{codec}", relative_path=f"{idx}-{suffix}.{codec}", title=track_title, artist=track_artist, album=release.title if release else "Legacy", album_artist=release.album_artist if release else track_artist, genre=genre, primary_genre=genre, year=2026, duration_seconds=180.0, file_ext=f".{codec}", library_area="Library", track_number=idx, disc_number=1, library_availability=LIBRARY_AVAILABLE, created_at=when, last_indexed_at=when)
    db.add(track)
    db.flush()
    if recording is not None:
        edition = models.MusicEdition(identity_key=f"edition-15b-{idx}-{release.id}-{recording.id}-{suffix}", release_id=release.id, display_title=release.title, year=2026, edition_type="standard", source_scope=f"scope-{suffix}", source_format_family="LOSSLESS" if is_lossless else "LOSSY")
        db.add(edition)
        db.flush()
        db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=recording.id))
        db.add(models.MusicTechnicalProfile(track_id=track.id, probe_status="ok", codec=codec, container=codec, is_lossless=is_lossless, sample_rate_hz=sample_rate, bit_depth_bits=24 if is_lossless and sample_rate > 44100 else 16 if is_lossless else None, bitrate_bps=None if is_lossless else 320000, channel_count=2, file_size_bytes=1000 + idx))
        db.flush()
    db.add(models.TrackRadioProfile(track_id=track.id, primary_genre=genre, subgenres_json='["soul"]' if genre == "Soul" else '["rock"]', moods_json='["warm"]', energy="medium", source="synthetic"))
    db.flush()
    return track


def seed_with_candidate_pool(db, *, seed_kind: str = "live", primary: int = 8, adjacent: int = 3, neutral: int = 8, other: int = 3, genre: str = "Soul"):
    release = add_release(db)
    seed_rec = add_recording(db, title="Seed", artist="Seed Artist", kind=seed_kind)
    seed_track = add_track(db, release=release, recording=seed_rec, suffix=f"seed-{seed_kind}", genre=genre)
    made: dict[str, list[tuple[models.MusicRecording, models.Track]]] = {"primary": [], "adjacent": [], "neutral": [], "other": []}
    for idx in range(primary):
        rec = add_recording(db, title=f"Live Candidate {idx}", artist=f"Live Artist {idx}", kind="live")
        made["primary"].append((rec, add_track(db, release=release, recording=rec, suffix=f"live-{idx}", genre=genre)))
    for idx in range(adjacent):
        rec = add_recording(db, title=f"Acoustic Candidate {idx}", artist=f"Acoustic Artist {idx}", kind="acoustic")
        made["adjacent"].append((rec, add_track(db, release=release, recording=rec, suffix=f"acoustic-{idx}", genre=genre)))
    for idx in range(neutral):
        rec = add_recording(db, title=f"Neutral Candidate {idx}", artist=f"Neutral Artist {idx}", kind="unknown")
        made["neutral"].append((rec, add_track(db, release=release, recording=rec, suffix=f"neutral-{idx}", genre=genre)))
    for idx in range(other):
        rec = add_recording(db, title=f"Remix Candidate {idx}", artist=f"Remix Artist {idx}", kind="remix")
        made["other"].append((rec, add_track(db, release=release, recording=rec, suffix=f"remix-{idx}", genre=genre)))
    db.commit()
    return release, seed_rec, seed_track, made


def queue_rec_ids(queue: dict) -> list[int | None]:
    return [item.get("recording_id") for item in queue.get("queue", [])]


def selected_tiers(debug: dict) -> Counter:
    return Counter(row.get("version_affinity_tier") for row in debug.get("selected", []))


def case_affinity_derivation_and_matrix(tmp: Path) -> None:
    _, Session = make_db(tmp, "derive")
    db = Session()
    try:
        release = add_release(db)
        tracks = {}
        for kind in ["live", "acoustic", "remix", "instrumental", "unknown", "radio_edit"]:
            rec = add_recording(db, title=f"{kind} seed", artist="Seed Artist", kind=kind)
            tracks[kind] = add_track(db, release=release, recording=rec, suffix=kind, title="Live Forever" if kind == "unknown" else None)
        identityless = add_track(db, release=None, recording=None, suffix="Song (Live)", title="Song (Live)")
        db.commit()
        assert derive_version_affinity_intent(db, tracks["live"]).mode == "live"
        assert derive_version_affinity_intent(db, tracks["acoustic"]).mode == "acoustic"
        assert derive_version_affinity_intent(db, tracks["remix"]).mode == "remix"
        assert derive_version_affinity_intent(db, tracks["instrumental"]).mode == "instrumental"
        assert derive_version_affinity_intent(db, tracks["unknown"]).mode == "balanced"
        assert derive_version_affinity_intent(db, tracks["radio_edit"]).mode == "balanced"
        assert derive_version_affinity_intent(db, identityless).mode == "balanced"
        assert derive_version_affinity_intent(db, tracks["unknown"]).source == "default"

        candidates = load_station_candidate_tracks(db, limit=20, seed_track_id=tracks["live"].id)
        by_type = {getattr(track, "_station_recording_type", None): track for track in candidates if getattr(track, "_station_recording_type", None)}
        live_intent = derive_version_affinity_intent(db, tracks["live"])
        assert classify_affinity_tier(by_type["acoustic"], live_intent) == "adjacent"
        assert classify_affinity_tier(by_type["unknown"], live_intent) == "neutral"
        assert classify_affinity_tier(by_type["radio_edit"], live_intent) == "neutral"
        assert classify_affinity_tier(by_type["remix"], live_intent) == "other"
        assert classify_affinity_tier(by_type["instrumental"], live_intent) == "other"

        acoustic_candidates = load_station_candidate_tracks(db, limit=20, seed_track_id=tracks["acoustic"].id)
        acoustic_by_type = {getattr(track, "_station_recording_type", None): track for track in acoustic_candidates if getattr(track, "_station_recording_type", None)}
        acoustic_intent = derive_version_affinity_intent(db, tracks["acoustic"])
        assert classify_affinity_tier(acoustic_by_type["live"], acoustic_intent) == "adjacent"
        remix_intent = derive_version_affinity_intent(db, tracks["remix"])
        assert classify_affinity_tier(by_type["instrumental"], remix_intent) == "other"
        instrumental_intent = derive_version_affinity_intent(db, tracks["instrumental"])
        assert classify_affinity_tier(by_type["acoustic"], instrumental_intent) == "adjacent"
    finally:
        db.close()


def case_focused_affinity_and_fallback(tmp: Path) -> None:
    _, Session = make_db(tmp, "focused")
    db = Session()
    try:
        _, _, seed_track, made = seed_with_candidate_pool(db, primary=10, adjacent=4, neutral=8, other=3)
        random.seed(15)
        debug = build_station_debug(StationQueueRequest(type="song", seed_track_id=seed_track.id, limit=20), db)
        summary = debug["version_affinity"]
        tiers = selected_tiers(debug)
        assert summary["mode"] == "live" and summary["source"] == "seed_recording_type"
        assert tiers["primary"] == max(tiers.values()), tiers
        assert tiers["adjacent"] > 0, tiers
        assert summary["fallback_used"] is True
        assert any(row.get("version_affinity_tier") == "primary" for row in debug["selected"])
        assert any(part["label"] == "version_affinity_primary" and part["value"] == PRIMARY_BOOST for row in debug["selected"] for part in row["score_parts"])

        station = build_station_queue(StationQueueRequest(type="song", seed_track_id=seed_track.id, limit=20), db)
        assert all(item.get("version_affinity_mode") == "live" for item in station["queue"])
        assert any(item.get("version_affinity_tier") == "adjacent" for item in station["queue"])

        first_live_rec, first_live_track = made["primary"][0]
        for idx in range(4):
            add_track(db, release=add_release(db, title=f"Variant {idx}"), recording=first_live_rec, suffix=f"live-source-{idx}", genre="Soul")
        db.commit()
        candidates = load_station_candidate_tracks(db, limit=100, seed_track_id=seed_track.id)
        intent = derive_version_affinity_intent(db, seed_track)
        dist = affinity_summary(intent, candidates, candidates)["candidate_distribution"]
        assert dist["primary"] == 10, dist

        mp3 = first_live_track
        flac = add_track(db, release=add_release(db, title="Override"), recording=first_live_rec, suffix="live-flac", codec="flac", is_lossless=True, genre="Soul")
        evaluate_music_recording_preference(db, recording_id=first_live_rec.id)
        db.commit()
        auto = build_station_queue(StationQueueRequest(type="song", seed_track_id=seed_track.id, limit=20), db)
        auto_item = next(item for item in auto["queue"] if item.get("recording_id") == first_live_rec.id)
        assert auto_item["version_affinity_tier"] == "primary"
        set_music_recording_user_preference(db, recording_id=first_live_rec.id, track_id=mp3.id)
        db.commit()
        override = build_station_queue(StationQueueRequest(type="song", seed_track_id=seed_track.id, limit=20), db)
        override_item = next(item for item in override["queue"] if item.get("recording_id") == first_live_rec.id)
        assert override_item["track_id"] == mp3.id and override_item["version_affinity_tier"] == "primary"
    finally:
        db.close()


def case_small_library_and_precedence(tmp: Path) -> None:
    _, Session = make_db(tmp, "fallback")
    db = Session()
    try:
        release, seed_rec, seed_track, made = seed_with_candidate_pool(db, primary=0, adjacent=0, neutral=14, other=2)
        unrelated_live = add_recording(db, title="Unrelated Live", artist="Rock Artist", kind="live")
        add_track(db, release=release, recording=unrelated_live, suffix="unrelated-live", genre="Rock")
        down_live = add_recording(db, title="Down Live", artist="Down Artist", kind="live")
        down_track = add_track(db, release=release, recording=down_live, suffix="down-live", genre="Soul")
        db.add(models.TrackThumb(track_id=down_track.id, recording_id=down_live.id, value=models.ThumbValue.down, created_at=datetime.now(UTC)))
        lib_live = add_recording(db, title="Library Live", artist="Library Artist", kind="live")
        lib_track = add_track(db, release=release, recording=lib_live, suffix="library-live", genre="Soul")
        set_music_recording_participation(db, recording_id=lib_live.id, participation_state="library_only")
        seed_alt = add_track(db, release=release, recording=seed_rec, suffix="seed-alt", genre="Soul")
        queued_rec, queued_track = made["neutral"][0]
        db.commit()

        debug = build_station_debug(StationQueueRequest(type="song", seed_track_id=seed_track.id, limit=10, exclude_track_ids=[queued_track.id]), db)
        recs = {row.get("recording_id") for row in debug["selected"]}
        assert len(debug["selected"]) == 10
        assert debug["version_affinity"]["candidate_distribution"]["primary"] == 0
        assert "version_affinity_no_primary_candidates" in debug["warnings"]
        assert unrelated_live.id not in recs
        assert down_live.id not in recs
        assert lib_live.id not in recs
        assert seed_rec.id not in recs
        assert queued_rec.id not in recs
        assert seed_alt.id not in [row.get("track_id") for row in debug["selected"]]
    finally:
        db.close()


def case_balanced_non_song_and_structural(tmp: Path) -> None:
    _, Session = make_db(tmp, "balanced")
    db = Session()
    try:
        release = add_release(db)
        seed_rec = add_recording(db, title="Live Forever", artist="Seed Artist", kind="unknown")
        seed_track = add_track(db, release=release, recording=seed_rec, suffix="unknown-seed", title="Song (Live)")
        for kind in ["live", "acoustic", "remix", "instrumental", "unknown"]:
            for idx in range(2):
                rec = add_recording(db, title=f"{kind} {idx}", artist=f"{kind} Artist {idx}", kind=kind)
                add_track(db, release=release, recording=rec, suffix=f"{kind}-{idx}")
        legacy = add_track(db, release=None, recording=None, suffix="legacy-live-title", title="Legacy (Live)")
        db.commit()
        debug = build_station_debug(StationQueueRequest(type="song", seed_track_id=seed_track.id, limit=8), db)
        assert debug["version_affinity"]["mode"] == "balanced"
        assert {part["value"] for row in debug["selected"] for part in row["score_parts"] if part["label"].startswith("version_affinity_")} == {0.0}

        artist = build_station_queue(StationQueueRequest(type="artist", seed_value="live Artist 0", limit=5), db)
        assert all(item.get("version_affinity_mode") is None for item in artist["queue"])
        for station_type in ["genre", "favorites", "recently_added", "deep_cuts"]:
            req = StationQueueRequest(type=station_type, seed_value="Soul" if station_type == "genre" else None, limit=5)
            assert all(item.get("version_affinity_mode") is None for item in build_station_queue(req, db)["queue"])

        source = Path("app/station_version_affinity.py").read_text(encoding="utf-8").lower()
        assert "filename" not in source and "path" not in source and "album title" not in source
        contracts = Path("app/queue_contracts.py").read_text(encoding="utf-8").lower()
        assert "version_mode" not in contracts and "version_affinity" not in contracts and "recording_mode" not in contracts
        station_columns = {column.name for column in models.Station.__table__.columns}
        assert not ({"version_mode", "version_affinity", "recording_mode", "fallback_policy"} & station_columns)
        preference_source = Path("app/music_source_preference.py").read_text(encoding="utf-8")
        assert "station_version_affinity" not in preference_source
    finally:
        db.close()


def case_quality_separation_distinct_versions_nplus1_readonly(tmp: Path) -> None:
    engine, Session = make_db(tmp, "scale")
    db = Session()
    try:
        release = add_release(db)
        seed_rec = add_recording(db, title="Shared Song", artist="Seed Artist", kind="live")
        seed_track = add_track(db, release=release, recording=seed_rec, suffix="seed")
        live = add_recording(db, title="Same Song", artist="Live Artist", kind="live")
        live_track = add_track(db, release=release, recording=live, suffix="live-low", sample_rate=44100)
        standard = add_recording(db, title="Same Song", artist="Standard Artist", kind="unknown")
        standard_track = add_track(db, release=release, recording=standard, suffix="standard-hi", codec="flac", is_lossless=True, sample_rate=96000)
        for kind in ["acoustic", "remix", "instrumental", "unknown"]:
            rec = add_recording(db, title="Same Song", artist=f"{kind} Artist", kind=kind)
            add_track(db, release=release, recording=rec, suffix=kind)
        for idx in range(100):
            kind = "live" if idx % 4 == 0 else "unknown"
            rec = add_recording(db, title=f"Scale {idx}", artist=f"Scale Artist {idx}", kind=kind)
            add_track(db, release=release, recording=rec, suffix=f"scale-{idx}")
        db.commit()

        before_counts = table_counts(db)
        queries: list[str] = []
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)
        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            station = build_station_queue(StationQueueRequest(type="song", seed_track_id=seed_track.id, limit=25), db)
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
        after_counts = table_counts(db)
        assert before_counts == after_counts
        assert len(queries) < 80, len(queries)
        recs = queue_rec_ids(station)
        assert len(recs) == len(set(recs))
        assert live.id in recs
        live_item = next(item for item in station["queue"] if item.get("recording_id") == live.id)
        assert live_item["track_id"] == live_track.id
        assert standard.id in recs or standard_track.id not in [item["track_id"] for item in station["queue"] if item.get("recording_id") == live.id]
        assert {live.id, standard.id}.issubset(set(load_rec_ids_from_candidates(db, seed_track.id)))
    finally:
        db.close()


def table_counts(db) -> dict[str, int]:
    names = [row[0] for row in db.execute(text("select name from sqlite_master where type='table' and name not like 'sqlite_%'"))]
    return {name: db.execute(text(f'select count(*) from "{name}"')).scalar_one() for name in names}


def load_rec_ids_from_candidates(db, seed_track_id: int) -> list[int | None]:
    return [getattr(track, "_station_recording_id", None) for track in load_station_candidate_tracks(db, limit=200, seed_track_id=seed_track_id)]


def case_existing_15a_regression_still_referenced() -> None:
    path = Path("scripts/check_prod1_5a_recording_first_station_candidates.py")
    assert path.exists()
    source = Path("../scripts/check_prod0_baseline.py").read_text(encoding="utf-8")
    assert "check_prod1_5a_recording_first_station_candidates.py" in source


def main() -> None:
    base = Path("tmp_prod1_5b_checks")
    if base.exists():
        shutil.rmtree(base)
    base.mkdir()
    try:
        case_affinity_derivation_and_matrix(base)
        case_focused_affinity_and_fallback(base)
        case_small_library_and_precedence(base)
        case_balanced_non_song_and_structural(base)
        case_quality_separation_distinct_versions_nplus1_readonly(base)
        case_existing_15a_regression_still_referenced()
        engine_source = Path("app/station_version_affinity.py").read_text(encoding="utf-8")
        assert "PRIMARY_BOOST = 1.2" in engine_source
        assert "ADJACENT_BOOST = 0.55" in engine_source
        assert "OTHER_PENALTY = -0.2" in engine_source
        print("PASS: BM-PROD1.5B seed version affinity and adaptive fallback")
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()