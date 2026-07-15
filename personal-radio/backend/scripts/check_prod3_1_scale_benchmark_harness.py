from __future__ import annotations

from pathlib import Path
import shutil
import sys

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.perf_benchmark import BenchmarkContext, listener_operations, run_benchmarks
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine, database_checksum, fixture_counts

REQUIRED_SQL_KEYS = {"select_count", "insert_count", "update_count", "delete_count", "total_statement_count"}
REQUIRED_WALL_KEYS = {"min", "median", "p95", "max"}


def table_counts(db) -> dict[str, int]:
    tables = [row[0] for row in db.execute(text("select name from sqlite_master where type='table' and name not like 'sqlite_%'"))]
    return {table: int(db.execute(text(f'select count(*) from "{table}"')).scalar_one() or 0) for table in tables}


def assert_metric_schema(metric: dict) -> None:
    for key in ["name", "dataset_size_physical_tracks", "dataset_size_recordings", "dataset_size_releases", "dataset_size_artists", "iterations", "warmup_iterations", "wall_time_ms", "sql", "python_peak_memory_bytes", "rows_returned", "result_checksum", "notes"]:
        assert key in metric, (metric.get("name"), key)
    assert REQUIRED_WALL_KEYS <= set(metric["wall_time_ms"]), metric
    assert REQUIRED_SQL_KEYS <= set(metric["sql"]), metric
    assert isinstance(metric["result_checksum"], str) and metric["result_checksum"]
    assert metric["python_peak_memory_bytes"] >= 0


def build_ctx(base: Path, name: str, size: int = 1000):
    engine, Session = create_temp_engine(base / f"{name}.db")
    db = Session()
    summary = build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=size))
    return engine, db, BenchmarkContext(db=db, engine=engine, temp_root=base / name, summary=summary)


def main() -> int:
    base = Path("tmp_tests") / "prod3_1_smoke"
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        engine, db, ctx = build_ctx(base, "primary", 1000)
        try:
            counts = fixture_counts(db)
            assert counts["tracks"] == 1000
            assert counts["music_releases"] == ctx.summary.releases
            assert counts["music_recordings"] == ctx.summary.recordings
            assert counts["music_track_identities"] == 1000
            assert counts["music_technical_profiles"] == 1000
            assert counts["music_recording_preferences"] > 0
            assert counts["music_recording_participation"] == ctx.summary.recordings
            assert counts["track_favorites"] > 0 and counts["track_thumbs"] > 0 and counts["playback_events"] > 0
            assert counts["playlists"] > 0 and counts["playlist_tracks"] > 0

            variant_count = db.execute(text("select count(*) from (select recording_id, count(*) c from music_track_identities group by recording_id having c >= 2)")).scalar_one()
            assert variant_count > 0
            cross_release_count = db.execute(text("select count(*) from (select i.recording_id, count(distinct e.release_id) c from music_track_identities i join music_editions e on e.id = i.edition_id group by i.recording_id having c >= 2)")).scalar_one()
            assert cross_release_count > 0
            participation_states = {row[0] for row in db.execute(text("select distinct participation_state from music_recording_participation"))}
            assert {"included", "library_only", "archived", "blocked"} <= participation_states
            preference_with_override = db.execute(text("select count(*) from music_recording_preferences where user_preferred_track_id is not null")).scalar_one()
            assert preference_with_override > 0

            first_checksum = ctx.summary.checksum
            first_db_checksum = database_checksum(db)

            before = table_counts(db)
            for _name, operation, _notes in listener_operations(ctx):
                result = operation(db)
                assert result is not None
                db.rollback()
            after = table_counts(db)
            assert before == after

            metrics = run_benchmarks(ctx, iterations=1, warmups=0, include_scanner=True, include_station_observation=False)
            names = {metric["name"] for metric in metrics}
            required_names = {
                "library.summary", "library.tracks.first", "library.tracks.deep", "library.artists.first", "library.artists.deep", "library.albums.first", "library.albums.deep", "library.search.selective", "library.search.broad", "library.recent_playback", "scanner.startup_state", "scanner.incremental.50",
            }
            assert required_names <= names
            for metric in metrics:
                assert_metric_schema(metric)
            startup = next(metric for metric in metrics if metric["name"] == "scanner.startup_state")
            assert startup["rows_returned"] > 0 and startup["sql"]["select_count"] >= 1
            incremental = next(metric for metric in metrics if metric["name"] == "scanner.incremental.50")
            assert incremental["result_checksum"] and incremental["sql"]["insert_count"] >= 1

        finally:
            db.close()
            engine.dispose()

        engine2, db2, ctx2 = build_ctx(base, "repeat", 1000)
        try:
            assert ctx2.summary.checksum == first_checksum
            assert database_checksum(db2) == first_db_checksum
        finally:
            db2.close()
            engine2.dispose()

        benchmark_source = Path("app/perf_benchmark.py").read_text(encoding="utf-8")
        fixture_source = Path("app/perf_fixtures.py").read_text(encoding="utf-8")
        runner_source = Path("scripts/benchmark_prod3_scale.py").read_text(encoding="utf-8")
        combined = benchmark_source + fixture_source + runner_source
        assert "SessionLocal" not in combined
        assert "bm_radio.db" not in combined
        assert "NAS" not in fixture_source
        assert "BM_RADIO_MUSIC_ROOT" not in benchmark_source
        assert str(base).startswith("tmp_tests")
        gate_source = Path("../scripts/check_prod0_baseline.py").read_text(encoding="utf-8")
        assert "check_prod3_1_scale_benchmark_harness.py" in gate_source
        assert Path("../.gitignore").read_text(encoding="utf-8").find("backend/tmp_tests/") >= 0
        print("PASS: BM-PROD3.1 synthetic large-library benchmark harness")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())