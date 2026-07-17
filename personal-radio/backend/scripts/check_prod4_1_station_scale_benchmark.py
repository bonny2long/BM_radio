from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.migration_contract import BASELINE_REVISION
from app.sqlite_adoption import snapshot_sqlite_database

from app.perf_benchmark import BenchmarkContext
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine, fixture_counts
from app.queue_contracts import StationQueueRequest
from app.station_candidates import MAX_STATION_CANDIDATE_POOL, load_station_candidate_tracks, station_identity_keys_for_track_ids
from app.station_engine import build_station_queue
from app.station_perf_benchmark import (
    PROD4_FIXTURE_SEED,
    STATION_WRITE_TABLES,
    candidate_projection_metrics,
    queue_checksum,
    run_station_benchmarks,
    select_station_seeds,
    table_counts,
)

REQUIRED_SQL_KEYS = {"select_count", "insert_count", "update_count", "delete_count", "total_statement_count"}
REQUIRED_WALL_KEYS = {"min", "median", "p95", "max"}
REQUIRED_METRIC_KEYS = {
    "name",
    "station_type",
    "dataset_size_physical_tracks",
    "dataset_size_recordings",
    "candidate_cap",
    "request_limit",
    "exclude_count",
    "refill_number",
    "iterations",
    "warmup_iterations",
    "wall_time_ms",
    "sql",
    "python_peak_memory_bytes",
    "candidate_count",
    "returned",
    "unique_recording_count",
    "excluded_recording_overlap",
    "queue_checksum",
    "effective_track_ids_checksum",
    "exhausted",
    "remaining_estimate",
    "phase_metrics",
    "candidate_projection_metrics",
    "profile_cache_metrics",
    "listener_signal_metrics",
    "notes",
}
REQUIRED_PHASE_KEYS = {
    "station.total",
    "station.profile_cache",
    "station.candidate_projection",
    "station.candidate_identity_query",
    "station.source_resolution",
    "station.profile_track_resolution",
    "station.listener_signals.feedback",
    "station.listener_signals.favorites",
    "station.payload_serialization",
}


def assert_metric_schema(metric: dict) -> None:
    missing = REQUIRED_METRIC_KEYS - set(metric)
    assert not missing, (metric.get("name"), missing)
    assert REQUIRED_WALL_KEYS <= set(metric["wall_time_ms"]), metric["name"]
    assert REQUIRED_SQL_KEYS <= set(metric["sql"]), metric["name"]
    assert metric["candidate_cap"] == MAX_STATION_CANDIDATE_POOL
    assert metric["python_peak_memory_bytes"] >= 0
    assert metric["queue_checksum"]
    cpm = metric["candidate_projection_metrics"]
    for key in ["physical_tracks_in_fixture", "logical_recordings_in_fixture", "recording_ids_loaded", "effective_sources_resolved", "profile_tracks_loaded", "final_candidate_pool_size"]:
        assert key in cpm, (metric["name"], key)
    pcm = metric["profile_cache_metrics"]
    assert "radio_profile_rows_loaded" in pcm and "cache_lookup_coverage" in pcm, metric["name"]
    lsm = metric["listener_signal_metrics"]
    for key in ["station.listener_signals.feedback", "station.listener_signals.favorites", "station.listener_signals.play_counts", "station.listener_signals.recent"]:
        assert key in lsm, (metric["name"], key)


def metric_by_name(metrics: list[dict], name: str) -> dict:
    return next(metric for metric in metrics if metric["name"] == name)


def real_db_state() -> dict:
    snapshot = snapshot_sqlite_database(Path("bm_radio.db"), logical_path="bm_radio.db")
    return snapshot.as_dict(include_schema=False, issue_limit=20)


def assert_real_db_ready(state: dict) -> None:
    assert state["integrity_check"] == "ok", state
    assert state["quick_check"] == "ok", state
    assert state["compatibility"] == "PASS", state
    assert state["readiness_status"] == "ready", state
    assert state["current_revision"] == BASELINE_REVISION, state
    assert state["head_revision"] == BASELINE_REVISION, state

def run_prior_station_regression(script: str) -> None:
    result = subprocess.run([sys.executable, script], cwd=Path(__file__).resolve().parents[1], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, f"{script} failed\n{result.stdout}\n{result.stderr}"


def assert_physical_variant_exclusion(db) -> None:
    rows = db.execute(text("select recording_id from music_track_identities group by recording_id having count(*) >= 2 order by recording_id limit 50")).all()
    assert rows, "fixture lacks physical-source variants"
    for row in rows:
        track_ids = [int(item[0]) for item in db.execute(text("select track_id from music_track_identities where recording_id=:rid order by track_id"), {"rid": row[0]}).all()]
        if len(track_ids) < 2:
            continue
        excluded_key = station_identity_keys_for_track_ids(db, [track_ids[1]])
        tracks = load_station_candidate_tracks(db, limit=MAX_STATION_CANDIDATE_POOL, exclude_track_ids=[track_ids[1]])
        returned_keys = {key for key in (station_identity_keys_for_track_ids(db, [track.id for track in tracks]))}
        assert not (excluded_key & returned_keys), (row[0], track_ids)
        return
    raise AssertionError("no usable physical-source variant found")


def main() -> int:
    base = Path("tmp_tests") / "prod4_1_smoke"
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        before_real = real_db_state()
        assert_real_db_ready(before_real)
        engine, Session = create_temp_engine(base / "station_scale.db")
        db = Session()
        try:
            summary = build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=1000, seed=PROD4_FIXTURE_SEED))
            ctx = BenchmarkContext(db=db, engine=engine, temp_root=base, summary=summary)
            counts = fixture_counts(db)
            assert counts["tracks"] == 1000
            assert counts["stations"] >= 5
            assert counts["music_recordings"] > 0
            assert counts["music_track_identities"] == 1000
            assert counts["music_recording_preferences"] > 0
            assert counts["music_recording_participation"] == summary.recordings
            assert counts["track_favorites"] > 0 and counts["track_thumbs"] > 0 and counts["playback_events"] > 0

            seeds = select_station_seeds(db)
            assert seeds.song_track_id and seeds.live_song_track_id and seeds.artist_name and seeds.genre_name
            for req in [
                StationQueueRequest(type="song", seed_track_id=seeds.song_track_id, limit=50, shuffle=False),
                StationQueueRequest(type="song", seed_track_id=seeds.live_song_track_id, limit=50, shuffle=False),
                StationQueueRequest(type="artist", seed_value=seeds.artist_name, limit=50, shuffle=False),
                StationQueueRequest(type="genre", seed_value=seeds.genre_name, limit=50, shuffle=False),
                StationQueueRequest(type="favorites", limit=50, shuffle=False),
                StationQueueRequest(type="recently_added", limit=50, shuffle=False),
                StationQueueRequest(type="deep_cuts", limit=50, shuffle=False),
            ]:
                result = build_station_queue(req, db)
                db.rollback()
                assert result["queue"], req

            before = table_counts(db, STATION_WRITE_TABLES)
            run = run_station_benchmarks(ctx, iterations=1, warmups=0, refill_count=4, include_debug=True, include_listing=True)
            after = table_counts(db, STATION_WRITE_TABLES)
            assert before == after, "station benchmark operations changed fixture tables"
            metrics = run["metrics"]
            names = {metric["name"] for metric in metrics}
            required_names = {
                "station.song.initial",
                "station.song_live.initial",
                "station.artist.initial",
                "station.genre.initial",
                "station.favorites.initial",
                "station.recently_added.initial",
                "station.deep_cuts.initial",
                "station.song.refill.1",
                "station.song.refill.4",
                "station.artist.refill.4",
                "station.genre.refill.4",
                "station.favorites.refill.4",
                "station.song.debug",
                "station.artist.debug",
                "station.genre.debug",
                "stations.list",
                "station_count.favorites",
                "station_count.recently_added",
                "station_count.deep_cuts",
                "station_count.artist",
                "station_count.genre",
            }
            assert required_names <= names, required_names - names
            for metric in metrics:
                assert_metric_schema(metric)
                assert metric["sql"]["insert_count"] == 0 and metric["sql"]["update_count"] == 0 and metric["sql"]["delete_count"] == 0, metric["name"]
                assert metric["sql"]["select_count"] < max(80, metric["candidate_count"] // 10), metric["name"]

            song_initial = metric_by_name(metrics, "station.song.initial")
            song_repeat = run_station_benchmarks(ctx, iterations=1, warmups=0, refill_count=0, include_debug=False, include_listing=False)["metrics"]
            assert queue_checksum(build_station_queue(StationQueueRequest(type="song", seed_track_id=seeds.song_track_id, limit=50, shuffle=False), db))
            db.rollback()
            assert metric_by_name(song_repeat, "station.song.initial")["queue_checksum"] == song_initial["queue_checksum"]
            assert metric_by_name(metrics, "station.song_live.initial")["queue_checksum"]
            assert metric_by_name(metrics, "station.artist.initial")["queue_checksum"]
            assert metric_by_name(metrics, "station.genre.initial")["queue_checksum"]

            for metric in metrics:
                if ".refill." in metric["name"]:
                    assert metric["exclude_count"] <= 200
                    assert metric["excluded_recording_overlap"] == 0, metric["name"]
                    assert "exhausted" in metric and "remaining_estimate" in metric
            assert metric_by_name(metrics, "station.song.refill.1")["exclude_count"] >= 1
            assert metric_by_name(metrics, "station.song.refill.4")["exclude_count"] <= 200
            assert metric_by_name(metrics, "station.song.refill.1")["name"] != metric_by_name(metrics, "station.song.initial")["name"]

            phase_keys = set().union(*(set(metric["phase_metrics"]) for metric in metrics if metric["name"].endswith(".initial") or ".refill." in metric["name"]))
            assert REQUIRED_PHASE_KEYS <= phase_keys, REQUIRED_PHASE_KEYS - phase_keys
            assert metric_by_name(metrics, "station.song.debug")["selected_count"] > 0
            assert metric_by_name(metrics, "station.artist.debug")["selected_count"] > 0
            assert metric_by_name(metrics, "station.genre.debug")["selected_count"] > 0
            assert metric_by_name(metrics, "stations.list")["returned"] > 0
            assert metric_by_name(metrics, "station_count.favorites")["sql"]["select_count"] > 0

            cpm = candidate_projection_metrics(db, StationQueueRequest(type="artist", seed_value=seeds.artist_name, limit=50), seeds)
            assert cpm["seed_artist_full_fixture_count"] >= cpm["seed_artist_inside_pool_count"] >= 1
            cpm_genre = candidate_projection_metrics(db, StationQueueRequest(type="genre", seed_value=seeds.genre_name, limit=50), seeds)
            assert cpm_genre["target_genre_full_fixture_count"] >= cpm_genre["target_genre_inside_pool_count"] >= 1
            assert_physical_variant_exclusion(db)

            source_text = Path("app/station_perf_benchmark.py").read_text(encoding="utf-8") + Path("scripts/benchmark_prod4_station_scale.py").read_text(encoding="utf-8")
            assert "SessionLocal" not in source_text and "bm_radio.db" not in source_text
            assert "open(" not in source_text and "scan_music" not in source_text
            gate_source = Path("../scripts/check_prod0_baseline.py").read_text(encoding="utf-8")
            assert "check_prod4_1_station_scale_benchmark.py" in gate_source
        finally:
            db.close()
            engine.dispose()

        run_prior_station_regression("scripts/check_prod1_5a_recording_first_station_candidates.py")
        run_prior_station_regression("scripts/check_prod1_5b_station_version_affinity.py")
        after_real = real_db_state()
        assert before_real == after_real, {'before': before_real, 'after': after_real}
        print("PASS: BM-PROD4.1 station generation and refill scale benchmark baseline")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
