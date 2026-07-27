from __future__ import annotations

from pathlib import Path
import random
import shutil
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import station_engine
from app.perf_benchmark import stable_checksum
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine
from app.queue_contracts import StationQueueRequest
from app.station_perf_benchmark import PROD4_FIXTURE_SEED, candidate_projection_metrics, select_station_seeds, station_requests


def build_ctx(base: Path, name: str, size: int):
    engine, Session = create_temp_engine(base / f'{name}.db')
    db = Session()
    build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=size, seed=PROD4_FIXTURE_SEED))
    return engine, db


def queue_identity(result: dict[str, Any]) -> str:
    return stable_checksum([(row.get('recording_id'), row.get('track_id'), row.get('effective_track_id') or row.get('track_id')) for row in result.get('queue') or []])


def debug_identity(result: dict[str, Any]) -> str:
    return stable_checksum([(row.get('recording_id'), row.get('track_id'), row.get('effective_track_id') or row.get('track_id'), row.get('tier')) for row in result.get('selected') or []])


def assert_below_cap_equivalence(base: Path) -> None:
    engine, db = build_ctx(base, 'below_cap', 1000)
    original_intent = station_engine.station_candidate_intent_for_request
    try:
        seeds = select_station_seeds(db)
        queue_reqs = station_requests(seeds)
        for index, (_, req, _) in enumerate(queue_reqs):
            random.seed(PROD4_FIXTURE_SEED + index)
            station_engine.station_candidate_intent_for_request = lambda *args, **kwargs: None
            old_result = station_engine.build_station_queue(req, db)
            db.rollback()
            random.seed(PROD4_FIXTURE_SEED + index)
            station_engine.station_candidate_intent_for_request = original_intent
            new_result = station_engine.build_station_queue(req, db)
            db.rollback()
            assert queue_identity(old_result) == queue_identity(new_result), f'below-cap queue changed for {req.type}'

        for index, req in enumerate([
            StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False),
            StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False),
            StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False),
        ]):
            random.seed(PROD4_FIXTURE_SEED + 100 + index)
            station_engine.station_candidate_intent_for_request = lambda *args, **kwargs: None
            old_debug = station_engine.build_station_debug(req, db)
            db.rollback()
            random.seed(PROD4_FIXTURE_SEED + 100 + index)
            station_engine.station_candidate_intent_for_request = original_intent
            new_debug = station_engine.build_station_debug(req, db)
            db.rollback()
            assert debug_identity(old_debug) == debug_identity(new_debug), f'below-cap debug changed for {req.type}'
            assert new_debug.get('candidate_intent', {}).get('below_cap_global_equivalent') is True
    finally:
        station_engine.station_candidate_intent_for_request = original_intent
        db.close()
        engine.dispose()


def assert_large_library_coverage(base: Path) -> None:
    engine, db = build_ctx(base, 'coverage_50k', 50000)
    try:
        seeds = select_station_seeds(db)
        artist_req = StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False)
        genre_req = StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False)
        favorites_req = StationQueueRequest(type='favorites', limit=50, shuffle=False)

        artist_metrics = candidate_projection_metrics(db, artist_req, seeds)
        genre_metrics = candidate_projection_metrics(db, genre_req, seeds)
        favorites_metrics = candidate_projection_metrics(db, favorites_req, seeds)

        assert artist_metrics['candidate_intent_mode'] == 'artist'
        assert artist_metrics['candidate_intent_bucket_query_count'] <= 5
        assert artist_metrics['seed_artist_full_fixture_count'] == 87
        assert artist_metrics['seed_artist_eligible_fixture_count'] >= 70
        assert artist_metrics['seed_artist_eligible_inside_pool_count'] == artist_metrics['seed_artist_eligible_fixture_count']
        assert artist_metrics['seed_artist_inside_pool_count'] >= 70

        assert genre_metrics['candidate_intent_mode'] == 'genre'
        assert genre_metrics['candidate_intent_bucket_query_count'] <= 3
        assert genre_metrics['target_genre_full_fixture_count'] == 7500
        assert genre_metrics['target_genre_inside_pool_count'] >= 5000
        assert genre_metrics['candidate_intent_bucket_selected_counts'].get('global_fallback', 0) == 0

        assert favorites_metrics['candidate_intent_mode'] == 'global'
        assert favorites_metrics['final_candidate_pool_size'] == 5000

        artist_debug = station_engine.build_station_debug(artist_req, db)
        db.rollback()
        genre_debug = station_engine.build_station_debug(genre_req, db)
        db.rollback()
        assert artist_debug.get('candidate_intent', {}).get('mode') == 'artist'
        assert artist_debug.get('candidate_intent', {}).get('bucket_selected_counts', {}).get('seed_artist', 0) >= 70
        assert genre_debug.get('candidate_intent', {}).get('mode') == 'genre'
        assert genre_debug.get('candidate_intent', {}).get('bucket_selected_counts', {}).get('exact_genre', 0) >= 3500
    finally:
        db.close()
        engine.dispose()


def main() -> int:
    base = Path('tmp_tests') / 'prod4_2c_intent_coverage'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    assert_below_cap_equivalence(base)
    assert_large_library_coverage(base)
    print('PASS: BM-PROD4.2C station intent-aware large-library candidate coverage')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
