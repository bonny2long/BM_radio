from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
import random
import shutil
import sys
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models, station_candidates
from app.perf_benchmark import stable_checksum
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine
from app.queue_contracts import StationQueueRequest
from app.routes.stations import get_stations
from app.station_candidate_intent import artist_intent, genre_intent, song_intent
from app.station_candidates import (
    MAX_STATION_CANDIDATE_POOL,
    load_station_recording_candidates,
    select_experimental_unified_intent_station_recording_ids,
    select_intent_station_recording_ids,
    select_intent_station_recording_ids_reference,
    station_identity_keys_for_track_ids,
)
from app.station_engine import build_station_debug, build_station_queue
from app.station_perf_benchmark import (
    PROD4_FIXTURE_SEED,
    STATION_WRITE_TABLES,
    candidate_projection_metrics,
    queue_checksum,
    request_with_exclusions,
    select_station_seeds,
    table_counts,
    track_ids_from_queue,
)


@contextmanager
def patched_selector(selector: Callable):
    original = station_candidates.select_intent_station_recording_ids
    station_candidates.select_intent_station_recording_ids = selector
    try:
        yield
    finally:
        station_candidates.select_intent_station_recording_ids = original


def build_ctx(base: Path, name: str, size: int):
    engine, Session = create_temp_engine(base / f'{name}.db')
    db = Session()
    build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=size, seed=PROD4_FIXTURE_SEED))
    return engine, db


def request_cases(db, seeds) -> list[tuple[str, StationQueueRequest, Any]]:
    song_track = db.get(models.Track, seeds.song_track_id)
    live_track = db.get(models.Track, seeds.live_song_track_id)
    return [
        ('song', StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), song_intent(db, seed_track=song_track, requested_queue_limit=50, candidate_limit=MAX_STATION_CANDIDATE_POOL)),
        ('song_live', StationQueueRequest(type='song', seed_track_id=seeds.live_song_track_id, limit=50, shuffle=False), song_intent(db, seed_track=live_track, requested_queue_limit=50, candidate_limit=MAX_STATION_CANDIDATE_POOL)),
        ('artist', StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False), artist_intent(db, seed_artist=seeds.artist_name, requested_queue_limit=50, candidate_limit=MAX_STATION_CANDIDATE_POOL)),
        ('genre', StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False), genre_intent(target_genre=seeds.genre_name, requested_queue_limit=50, candidate_limit=MAX_STATION_CANDIDATE_POOL)),
    ]


def excluded_recording_ids_for_req(db, req: StationQueueRequest) -> set[int]:
    keys = station_identity_keys_for_track_ids(db, req.exclude_track_ids or [])
    if req.type == 'song' and req.seed_track_id is not None:
        keys |= station_identity_keys_for_track_ids(db, [req.seed_track_id])
    return {int(value) for kind, value in keys if kind == 'recording'}


def candidate_ids(db, req: StationQueueRequest, intent, selector: Callable) -> list[int]:
    excluded = excluded_recording_ids_for_req(db, req)
    ids, _ = selector(db, limit=MAX_STATION_CANDIDATE_POOL, excluded_recording_ids=excluded, intent=intent)
    return ids


def selected_debug_identity(result: dict[str, Any]) -> str:
    return stable_checksum([(row.get('recording_id'), row.get('track_id'), row.get('effective_track_id'), row.get('tier')) for row in result.get('selected') or []])


def assert_reference_equivalence(db, seeds, *, include_queue: bool) -> None:
    for name, req, intent in request_cases(db, seeds):
        ref_ids = candidate_ids(db, req, intent, select_intent_station_recording_ids_reference)
        production_ids = candidate_ids(db, req, intent, select_intent_station_recording_ids)
        unified_ids = candidate_ids(db, req, intent, select_experimental_unified_intent_station_recording_ids)
        assert ref_ids == production_ids == unified_ids, (name, len(ref_ids), len(production_ids), len(unified_ids), next((i for i, pair in enumerate(zip(ref_ids, unified_ids)) if pair[0] != pair[1]), None))
        if include_queue:
            random.seed(PROD4_FIXTURE_SEED)
            with patched_selector(select_intent_station_recording_ids_reference):
                ref_queue = build_station_queue(req, db)
                db.rollback()
                ref_debug = build_station_debug(req, db)
                db.rollback()
            random.seed(PROD4_FIXTURE_SEED)
            with patched_selector(select_experimental_unified_intent_station_recording_ids):
                unified_queue = build_station_queue(req, db)
                db.rollback()
                unified_debug = build_station_debug(req, db)
                db.rollback()
            assert queue_checksum(ref_queue) == queue_checksum(unified_queue), name
            assert selected_debug_identity(ref_debug) == selected_debug_identity(unified_debug), name


def assert_refill_equivalence(db, seeds) -> None:
    for name, base_req, _intent in request_cases(db, seeds)[:3]:
        with patched_selector(select_intent_station_recording_ids_reference):
            random.seed(PROD4_FIXTURE_SEED)
            ref_initial = build_station_queue(base_req, db)
            db.rollback()
        with patched_selector(select_experimental_unified_intent_station_recording_ids):
            random.seed(PROD4_FIXTURE_SEED)
            unified_initial = build_station_queue(base_req, db)
            db.rollback()
        assert queue_checksum(ref_initial) == queue_checksum(unified_initial), name
        history = track_ids_from_queue(unified_initial)
        for refill_number in range(1, 5):
            req = request_with_exclusions(base_req, history[-200:])
            with patched_selector(select_intent_station_recording_ids_reference):
                random.seed(PROD4_FIXTURE_SEED + refill_number)
                ref_result = build_station_queue(req, db)
                db.rollback()
            with patched_selector(select_experimental_unified_intent_station_recording_ids):
                random.seed(PROD4_FIXTURE_SEED + refill_number)
                unified_result = build_station_queue(req, db)
                db.rollback()
            assert queue_checksum(ref_result) == queue_checksum(unified_result), (name, refill_number)
            returned_keys = {row.get('recording_id') for row in unified_result.get('queue') or [] if row.get('recording_id') is not None}
            excluded = {value for kind, value in station_identity_keys_for_track_ids(db, req.exclude_track_ids or []) if kind == 'recording'}
            assert not (returned_keys & excluded), (name, refill_number)
            assert len(returned_keys) == len(unified_result.get('queue') or []), (name, refill_number)
            history.extend(track_ids_from_queue(unified_result))


def assert_non_seeded_preserved(db) -> None:
    before = table_counts(db, STATION_WRITE_TABLES)
    for req in [
        StationQueueRequest(type='favorites', limit=50, shuffle=False),
        StationQueueRequest(type='recently_added', limit=50, shuffle=False),
        StationQueueRequest(type='deep_cuts', limit=50, shuffle=False),
    ]:
        result = build_station_queue(req, db)
        db.rollback()
        assert result.get('queue'), req
        metrics = candidate_projection_metrics(db, req, None)
        assert metrics['candidate_intent_mode'] == 'global', req
    stations = asyncio.run(get_stations(db))
    db.rollback()
    assert stations
    listing_metrics = candidate_projection_metrics(db, None, None)
    assert listing_metrics['candidate_intent_mode'] == 'global'
    assert table_counts(db, STATION_WRITE_TABLES) == before


def assert_large_metrics(db, seeds) -> None:
    for name, req, _intent in request_cases(db, seeds):
        metrics = candidate_projection_metrics(db, req, seeds)
        bucket_queries = int(metrics.get('candidate_intent_bucket_query_count') or 0)
        max_bucket_queries = 3 if req.type == 'genre' else 5
        assert 1 <= bucket_queries <= max_bucket_queries, (name, bucket_queries)
        assert metrics['candidate_selector_policy'] == 'multi_bucket', name
        assert metrics['unified_projection'] is False, name
        assert metrics['candidate_intent_unified_projection'] is False, name
        assert metrics['recording_ids_source_resolved'] <= MAX_STATION_CANDIDATE_POOL, name

        excluded = excluded_recording_ids_for_req(db, req)
        unified_ids, unified_metrics = select_experimental_unified_intent_station_recording_ids(
            db,
            limit=MAX_STATION_CANDIDATE_POOL,
            excluded_recording_ids=excluded,
            intent=_intent,
        )
        production_ids, _ = select_intent_station_recording_ids(
            db,
            limit=MAX_STATION_CANDIDATE_POOL,
            excluded_recording_ids=excluded,
            intent=_intent,
        )
        assert production_ids == unified_ids, name
        assert unified_metrics['bucket_query_count'] == 1, name
        assert unified_metrics['projection_query_count'] == 1, name
        assert unified_metrics['unified_projection'] is True, name
        assert unified_metrics['selector_policy'] == 'unified_experimental', name
        if req.type == 'artist':
            assert metrics['seed_artist_eligible_inside_pool_count'] == metrics['seed_artist_eligible_fixture_count'], metrics
        if req.type == 'genre':
            assert metrics['target_genre_inside_pool_count'] >= 5000, metrics


def main() -> int:
    base = Path('tmp_tests') / 'prod4_2d_unified_projection'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        for size in (1000, 10000, 50000):
            engine, db = build_ctx(base, f'size_{size}', size)
            try:
                seeds = select_station_seeds(db)
                if size == 1000:
                    metrics = candidate_projection_metrics(db, StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50), seeds)
                    assert metrics.get('candidate_intent_below_cap_global_equivalent') is True
                else:
                    assert_reference_equivalence(db, seeds, include_queue=size == 10000)
                if size == 10000:
                    assert_refill_equivalence(db, seeds)
                    assert_non_seeded_preserved(db)
                if size == 50000:
                    assert_large_metrics(db, seeds)
            finally:
                db.close()
                engine.dispose()
        gate_source = Path('../scripts/check_prod0_baseline.py').read_text(encoding='utf-8')
        for script in [
            'check_prod4_2d_unified_intent_projection.py',
            'check_prod4_2c_1_station_refill_closure.py',
            'check_prod4_2c_station_intent_candidate_coverage.py',
            'check_prod4_2b_station_candidate_projection_scope.py',
            'check_prod4_2a_scoped_station_profiles.py',
            'check_prod4_1_station_scale_benchmark.py',
        ]:
            assert script in gate_source, script
        print('PASS: BM-PROD4.2D unified intent candidate projection')
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
