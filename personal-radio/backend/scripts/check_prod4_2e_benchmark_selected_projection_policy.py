from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
import random
import shutil
import sqlite3
import sys
from typing import Any, Callable

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.migration_contract import BASELINE_REVISION
from app.sqlite_adoption import snapshot_sqlite_database

from app import models, station_candidates
from app.perf import collect_perf_segments
from app.perf_benchmark import SqlCounter, stable_checksum
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine
from app.queue_contracts import StationQueueRequest
from app.routes.stations import get_stations
from app.station_candidate_intent import artist_intent, genre_intent, song_intent
from app.station_candidates import (
    MAX_STATION_CANDIDATE_POOL,
    load_station_recording_candidates,
    seed_recording_id_for_track,
    select_experimental_unified_intent_station_recording_ids,
    select_intent_station_recording_ids,
    select_intent_station_recording_ids_reference,
    select_production_multi_bucket_intent_station_recording_ids,
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


CHECKS: set[str] = set()


def mark(name: str) -> None:
    CHECKS.add(name)


@contextmanager
def patched_unified_raises():
    original = station_candidates.select_unified_intent_station_recording_ids

    def broken(*args, **kwargs):
        raise AssertionError('production path called experimental unified selector')

    station_candidates.select_unified_intent_station_recording_ids = broken
    try:
        yield
    finally:
        station_candidates.select_unified_intent_station_recording_ids = original


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


def exclude_keys_for_request(db, req: StationQueueRequest) -> set[tuple[str, int]]:
    keys = station_identity_keys_for_track_ids(db, req.exclude_track_ids or [])
    if req.type == 'song' and req.seed_track_id is not None:
        keys |= station_identity_keys_for_track_ids(db, [req.seed_track_id])
    return keys


def excluded_recording_ids_for_request(db, req: StationQueueRequest) -> set[int]:
    return {int(value) for kind, value in exclude_keys_for_request(db, req) if kind == 'recording'}


def selector_ids(db, req: StationQueueRequest, intent, selector: Callable) -> tuple[list[int], dict[str, Any]]:
    return selector(
        db,
        limit=MAX_STATION_CANDIDATE_POOL,
        excluded_recording_ids=excluded_recording_ids_for_request(db, req),
        intent=intent,
    )


def debug_identity(result: dict[str, Any]) -> str:
    return stable_checksum([(row.get('recording_id'), row.get('track_id'), row.get('effective_track_id'), row.get('tier')) for row in result.get('selected') or []])


def real_db_state() -> dict[str, Any]:
    snapshot = snapshot_sqlite_database(Path('bm_radio.db'), logical_path='bm_radio.db')
    return snapshot.as_dict(include_schema=False, issue_limit=20)


def assert_real_db_ready(state: dict[str, Any]) -> None:
    assert state['integrity_check'] == 'ok', state
    assert state['quick_check'] == 'ok', state
    assert state['compatibility'] == 'PASS', state
    assert state['readiness_status'] == 'ready', state
    assert state['current_revision'] == BASELINE_REVISION, state
    assert state['head_revision'] == BASELINE_REVISION, state
    mark('real db is ready and migration-current')

def assert_selector_policy(db, engine, seeds) -> None:
    before = table_counts(db, STATION_WRITE_TABLES)
    for name, req, intent in request_cases(db, seeds):
        reference_ids, reference_metrics = selector_ids(db, req, intent, select_intent_station_recording_ids_reference)
        production_ids, production_metrics = selector_ids(db, req, intent, select_intent_station_recording_ids)
        explicit_ids, explicit_metrics = selector_ids(db, req, intent, select_production_multi_bucket_intent_station_recording_ids)
        unified_ids, unified_metrics = selector_ids(db, req, intent, select_experimental_unified_intent_station_recording_ids)
        assert reference_ids == production_ids == explicit_ids == unified_ids, name
        assert reference_metrics['selector_policy'] == 'multi_bucket', name
        assert production_metrics['selector_policy'] == 'multi_bucket', name
        assert production_metrics['unified_projection'] is False, name
        assert explicit_metrics['selector_policy'] == 'multi_bucket', name
        assert unified_metrics['selector_policy'] == 'unified_experimental', name
        assert unified_metrics['unified_projection'] is True, name
        assert unified_metrics['projection_query_count'] == 1, name
        max_queries = 3 if req.type == 'genre' else 5
        assert 1 <= int(production_metrics['bucket_query_count']) <= max_queries, (name, production_metrics)
        with patched_unified_raises():
            patched_ids, patched_metrics = selector_ids(db, req, intent, select_intent_station_recording_ids)
        assert patched_ids == reference_ids, name
        assert patched_metrics['selector_policy'] == 'multi_bucket', name

        exclude_keys = exclude_keys_for_request(db, req)
        with collect_perf_segments() as segments:
            with SqlCounter(engine) as sql:
                candidates = load_station_recording_candidates(db, limit=MAX_STATION_CANDIDATE_POOL, exclude_keys=exclude_keys, candidate_intent=intent)
        db.rollback()
        sql_counts = sql.as_dict()
        metrics = dict(db.info.get('station_candidate_projection_metrics') or {})
        assert metrics['candidate_selector_policy'] == 'multi_bucket', name
        assert metrics['unified_projection'] is False, name
        assert metrics['candidate_intent_unified_projection'] is False, name
        assert int(metrics['candidate_intent_bucket_query_count']) <= max_queries, name
        assert len(candidates) <= MAX_STATION_CANDIDATE_POOL, name
        assert metrics['recording_ids_source_resolved'] <= MAX_STATION_CANDIDATE_POOL, name
        assert metrics['profile_track_ids_selected'] <= MAX_STATION_CANDIDATE_POOL, name
        assert metrics['track_rows_hydrated'] <= MAX_STATION_CANDIDATE_POOL * 2, name
        assert sql_counts['insert_count'] == sql_counts['update_count'] == sql_counts['delete_count'] == 0, (name, sql_counts)
        assert sql_counts['select_count'] <= 80, (name, sql_counts)
        assert 'station.source_resolution' in segments, name
        assert all(candidate.participation_state == 'included' for candidate in candidates), name
    assert table_counts(db, STATION_WRITE_TABLES) == before
    mark('production uses multi-bucket selector')
    mark('experimental unified remains benchmark-accessible')
    mark('candidate identity and order exact')
    mark('production metrics expose selector policy')
    mark('production metrics expose unified false')
    mark('intent bucket query counts capped')
    mark('final candidate hydration bounded')
    mark('source resolution bounded')
    mark('candidate scoped profiles bounded')
    mark('participation and exclusions preserved')
    mark('source resolution read-only')
    mark('no selector n plus one')


def assert_normal_paths_do_not_call_unified(db, seeds) -> None:
    for name, req, expected_mode in [
        ('song', StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), 'song'),
        ('artist', StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False), 'artist'),
        ('genre', StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False), 'genre'),
    ]:
        with patched_unified_raises():
            random.seed(PROD4_FIXTURE_SEED)
            first = build_station_queue(req, db)
            db.rollback()
            random.seed(PROD4_FIXTURE_SEED)
            second = build_station_queue(req, db)
            db.rollback()
            random.seed(PROD4_FIXTURE_SEED)
            debug_first = build_station_debug(req, db)
            db.rollback()
            random.seed(PROD4_FIXTURE_SEED)
            debug_second = build_station_debug(req, db)
            db.rollback()
        assert queue_checksum(first) == queue_checksum(second), name
        assert debug_identity(debug_first) == debug_identity(debug_second), name
        assert debug_first.get('candidate_intent', {}).get('mode') == expected_mode, name
        assert debug_first.get('candidate_intent', {}).get('selector_policy') == 'multi_bucket', debug_first.get('candidate_intent')
    mark('normal generation and debug avoid unified selector')
    mark('normal generation deterministic')
    mark('debug payload deterministic')


def assert_below_cap_and_non_seeded(db, seeds) -> None:
    below_req = StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False)
    metrics = candidate_projection_metrics(db, below_req, seeds)
    assert metrics.get('candidate_intent_below_cap_global_equivalent') is True, metrics
    mark('below-cap seeded requests keep global equivalence')

    before = table_counts(db, STATION_WRITE_TABLES)
    with patched_unified_raises():
        for req in [
            StationQueueRequest(type='favorites', limit=50, shuffle=False),
            StationQueueRequest(type='recently_added', limit=50, shuffle=False),
            StationQueueRequest(type='deep_cuts', limit=50, shuffle=False),
        ]:
            result = build_station_queue(req, db)
            db.rollback()
            assert result.get('queue'), req
            metrics = candidate_projection_metrics(db, req, seeds)
            assert metrics.get('candidate_intent_mode') == 'global', req
        stations = asyncio.run(get_stations(db))
        db.rollback()
    assert stations
    listing_metrics = candidate_projection_metrics(db, None, seeds)
    assert listing_metrics.get('candidate_intent_mode') == 'global', listing_metrics
    assert table_counts(db, STATION_WRITE_TABLES) == before
    mark('favorites recently-added deep-cuts stay global')
    mark('stations.list stays global')
    mark('non-seeded paths read-only')


def assert_refill_and_exclusion(db, seeds) -> None:
    for index, base_req in enumerate([
        StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False),
        StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False),
        StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False),
    ]):
        history: list[int] = []
        previous_checksums: set[str] = set()
        for refill_number in range(0, 5):
            req = base_req if refill_number == 0 else request_with_exclusions(base_req, history[-200:])
            random.seed(PROD4_FIXTURE_SEED + index * 100 + refill_number)
            result = build_station_queue(req, db)
            db.rollback()
            checksum = queue_checksum(result)
            if refill_number > 0:
                assert checksum not in previous_checksums or result.get('exhausted'), (base_req.type, refill_number)
            previous_checksums.add(checksum)
            returned_keys = {('recording', int(row['recording_id'])) for row in result.get('queue') or [] if row.get('recording_id') is not None}
            excluded_keys = station_identity_keys_for_track_ids(db, req.exclude_track_ids or [])
            assert not (returned_keys & excluded_keys), (base_req.type, refill_number, returned_keys & excluded_keys)
            history.extend(track_ids_from_queue(result))
    mark('four-refill seeded chains safe')
    mark('queue exclusions authoritative')


def assert_identity_edges(db, seeds) -> None:
    regular_recording_id = seed_recording_id_for_track(db, seeds.song_track_id)
    live_recording_id = seed_recording_id_for_track(db, seeds.live_song_track_id)
    assert regular_recording_id is not None and live_recording_id is not None
    assert regular_recording_id != live_recording_id
    rows = db.query(models.MusicRecording).filter(models.MusicRecording.id.in_([regular_recording_id, live_recording_id])).all()
    assert len(rows) == 2
    assert any(row.recording_type == 'live' for row in rows), [(row.id, row.recording_type) for row in rows]
    mark('distinct versions remain distinct')

    row = db.execute(text('select recording_id from music_track_identities group by recording_id having count(*) >= 2 order by recording_id limit 1')).first()
    assert row is not None, 'fixture lacks physical variants'
    recording_id = int(row[0])
    track_ids = [int(item[0]) for item in db.execute(text('select track_id from music_track_identities where recording_id=:rid order by track_id'), {'rid': recording_id}).all()]
    assert len(track_ids) >= 2
    excluded = station_identity_keys_for_track_ids(db, [track_ids[0]])
    candidates = load_station_recording_candidates(db, limit=MAX_STATION_CANDIDATE_POOL, exclude_keys=excluded)
    db.rollback()
    returned_recording_ids = {int(candidate.recording_id) for candidate in candidates if candidate.recording_id is not None}
    assert recording_id not in returned_recording_ids
    mark('physical and cross-release collapse preserved')


def assert_docs_and_gate() -> None:
    gate_source = Path('../scripts/check_prod0_baseline.py').read_text(encoding='utf-8')
    for script in [
        'check_prod4_2e_benchmark_selected_projection_policy.py',
        'check_prod4_2d_unified_intent_projection.py',
        'check_prod4_2c_1_station_refill_closure.py',
        'check_prod4_2c_station_intent_candidate_coverage.py',
        'check_prod4_2b_station_candidate_projection_scope.py',
        'check_prod4_2a_scoped_station_profiles.py',
        'check_prod4_1_station_scale_benchmark.py',
    ]:
        assert script in gate_source, script
    d_source = Path('scripts/check_prod4_2d_unified_intent_projection.py').read_text(encoding='utf-8')
    assert 'select_experimental_unified_intent_station_recording_ids' in d_source
    assert "candidate_selector_policy'] == 'multi_bucket'" in d_source
    mark('4.2D regression expectation updated')
    mark('PROD0 baseline includes 4.2E and earlier PROD4 gates')


def main() -> int:
    before_real = real_db_state()
    assert_real_db_ready(before_real)
    base = Path('tmp_tests') / 'prod4_2e_projection_policy'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        small_engine, small_db = build_ctx(base, 'below_cap_1000', 1000)
        try:
            assert_below_cap_and_non_seeded(small_db, select_station_seeds(small_db))
        finally:
            small_db.close()
            small_engine.dispose()

        engine, db = build_ctx(base, 'large_50000', 50000)
        try:
            seeds = select_station_seeds(db)
            assert_selector_policy(db, engine, seeds)
            assert_normal_paths_do_not_call_unified(db, seeds)
            assert_refill_and_exclusion(db, seeds)
            assert_identity_edges(db, seeds)
        finally:
            db.close()
            engine.dispose()
        assert_docs_and_gate()
        after_real = real_db_state()
        assert before_real == after_real, {'before': before_real, 'after': after_real}
        required = 24
        assert len(CHECKS) >= required, sorted(CHECKS)
        print(f'PASS: BM-PROD4.2E benchmark-selected projection policy ({len(CHECKS)} checks)')
        for item in sorted(CHECKS):
            print(f' - {item}')
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
