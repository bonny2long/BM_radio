from __future__ import annotations

from pathlib import Path
import random
import shutil
import sqlite3
import sys
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine
from app.queue_contracts import StationQueueRequest
from app.station_candidates import (
    MAX_STATION_CANDIDATE_POOL,
    load_station_candidate_tracks,
    seed_recording_id_for_track,
    station_identity_keys_for_track_ids,
)
from app.station_engine import build_station_debug, build_station_queue
from app.station_perf_benchmark import (
    PROD4_FIXTURE_SEED,
    STATION_WRITE_TABLES,
    _eligible_matching_recording_ids,
    candidate_projection_metrics,
    queue_checksum,
    request_with_exclusions,
    select_station_seeds,
    table_counts,
    track_ids_from_queue,
)


def build_ctx(base: Path, name: str, size: int = 10000):
    engine, Session = create_temp_engine(base / f'{name}.db')
    db = Session()
    build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=size, seed=PROD4_FIXTURE_SEED))
    return engine, db


def row_recording_key(row: dict[str, Any]) -> tuple[str, int] | None:
    if row.get('recording_id') is not None:
        return ('recording', int(row['recording_id']))
    if row.get('track_id') is not None:
        return ('track', int(row['track_id']))
    return None


def queue_recording_keys(result: dict[str, Any]) -> set[tuple[str, int]]:
    return {key for key in (row_recording_key(row) for row in result.get('queue') or []) if key is not None}


def queue_physical_ids(result: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    for row in result.get('queue') or []:
        for key in ('track_id', 'effective_track_id', 'profile_track_id'):
            value = row.get(key)
            if value is not None:
                ids.add(int(value))
    return ids


def assert_queue_safe(db, req: StationQueueRequest, result: dict[str, Any], *, seed_recording_id: int | None = None) -> None:
    rows = result.get('queue') or []
    keys = [row_recording_key(row) for row in rows]
    keys = [key for key in keys if key is not None]
    assert len(keys) == len(set(keys)), req
    assert all(row.get('participation_state') == 'included' for row in rows), req
    excluded_keys = station_identity_keys_for_track_ids(db, req.exclude_track_ids or [])
    returned_keys = queue_recording_keys(result)
    assert not (excluded_keys & returned_keys), (req, excluded_keys & returned_keys)
    excluded_physical = {int(value) for value in (req.exclude_track_ids or [])}
    assert not (excluded_physical & queue_physical_ids(result)), (req, excluded_physical & queue_physical_ids(result))
    if seed_recording_id is not None:
        assert ('recording', int(seed_recording_id)) not in returned_keys, req


def assert_deterministic_queue(db, req: StationQueueRequest, seed: int) -> dict[str, Any]:
    random.seed(seed)
    first = build_station_queue(req, db)
    db.rollback()
    random.seed(seed)
    second = build_station_queue(req, db)
    db.rollback()
    assert queue_checksum(first) == queue_checksum(second), req
    return first


def assert_debug_agrees(db, req: StationQueueRequest, expected_mode: str) -> None:
    first = build_station_debug(req, db)
    db.rollback()
    second = build_station_debug(req, db)
    db.rollback()
    assert first.get('candidate_intent', {}).get('mode') == expected_mode, req
    assert first.get('candidate_intent', {}).get('mode') == second.get('candidate_intent', {}).get('mode'), req
    assert first.get('candidate_intent', {}).get('bucket_selected_counts') == second.get('candidate_intent', {}).get('bucket_selected_counts'), req


def assert_physical_variant_exclusion(db) -> None:
    row = db.execute(text('select recording_id from music_track_identities group by recording_id having count(*) >= 2 order by recording_id limit 1')).first()
    assert row is not None, 'fixture lacks alternate physical sources'
    track_ids = [int(item[0]) for item in db.execute(text('select track_id from music_track_identities where recording_id=:rid order by track_id'), {'rid': row[0]}).all()]
    assert len(track_ids) >= 2
    excluded_keys = station_identity_keys_for_track_ids(db, [track_ids[0]])
    tracks = load_station_candidate_tracks(db, limit=MAX_STATION_CANDIDATE_POOL, exclude_track_ids=[track_ids[0]])
    returned_keys = station_identity_keys_for_track_ids(db, [track.id for track in tracks])
    assert not (excluded_keys & returned_keys), (row[0], track_ids)


def assert_real_db_empty() -> None:
    db_path = Path('bm_radio.db')
    if not db_path.exists():
        return
    conn = sqlite3.connect(f'file:{db_path.resolve().as_posix()}?mode=ro', uri=True)
    try:
        tables = [row[0] for row in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall()]
        nonzero = {}
        for table in tables:
            count = int(conn.execute(f'select count(*) from "{table}"').fetchone()[0] or 0)
            if count:
                nonzero[table] = count
        assert not nonzero, nonzero
    finally:
        conn.close()


def assert_refill_chain(db, base_req: StationQueueRequest, *, expected_mode: str, seeds, operation_seed: int) -> list[dict[str, Any]]:
    seed_recording_id = seed_recording_id_for_track(db, base_req.seed_track_id) if base_req.type == 'song' and base_req.seed_track_id else None
    initial = assert_deterministic_queue(db, base_req, operation_seed)
    assert_queue_safe(db, base_req, initial, seed_recording_id=seed_recording_id)
    history = track_ids_from_queue(initial)
    metrics: list[dict[str, Any]] = []
    previous_checksums: set[str] = set()
    for refill_number in range(1, 5):
        req = request_with_exclusions(base_req, history[-200:])
        result = assert_deterministic_queue(db, req, operation_seed + refill_number)
        assert_queue_safe(db, req, result, seed_recording_id=seed_recording_id)
        checksum = queue_checksum(result)
        assert checksum not in previous_checksums or result.get('exhausted'), (base_req.type, refill_number, checksum)
        previous_checksums.add(checksum)
        cpm = candidate_projection_metrics(db, req, seeds)
        assert cpm['candidate_intent_mode'] == expected_mode, (req, cpm.get('candidate_intent_mode'))
        assert cpm['recording_ids_source_resolved'] <= MAX_STATION_CANDIDATE_POOL, req
        bucket_queries = int(cpm.get('candidate_intent_bucket_query_count') or 0)
        if expected_mode == 'song':
            assert bucket_queries <= 5, cpm
            assert cpm.get('candidate_intent_bucket_selected_counts', {}).get('global_fallback', 0) < MAX_STATION_CANDIDATE_POOL
        elif expected_mode == 'artist':
            assert bucket_queries <= 5, cpm
            assert cpm.get('seed_artist_eligible_inside_pool_count', 0) >= 1, cpm
        elif expected_mode == 'genre':
            assert bucket_queries <= 3, cpm
            assert cpm.get('target_genre_inside_pool_count', 0) >= 1000, cpm
        else:
            assert cpm.get('candidate_intent_bucket_selected_counts', {}).get('global', 0) > 0, cpm
        metrics.append({
            'refill_number': refill_number,
            'exclude_count': len(req.exclude_track_ids or []),
            'returned': int(result.get('returned', 0) or 0),
            'unique_recording_count': len(queue_recording_keys(result)),
            'excluded_recording_overlap': len(station_identity_keys_for_track_ids(db, req.exclude_track_ids or []) & queue_recording_keys(result)),
            'physical_source_overlap': len({int(value) for value in (req.exclude_track_ids or [])} & queue_physical_ids(result)),
            'exhausted': bool(result.get('exhausted', False)),
            'remaining_estimate': int(result.get('remaining_estimate', 0) or 0),
            'candidate_intent_mode': cpm.get('candidate_intent_mode'),
            'candidate_intent_bucket_query_count': bucket_queries,
            'candidate_intent_bucket_selected_counts': cpm.get('candidate_intent_bucket_selected_counts', {}),
            'recording_ids_source_resolved': cpm.get('recording_ids_source_resolved'),
            'queue_checksum': checksum,
        })
        history.extend(track_ids_from_queue(result))
    return metrics


def assert_artist_distribution(db, seeds) -> None:
    req = StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False)
    result = assert_deterministic_queue(db, req, PROD4_FIXTURE_SEED + 900)
    rows = result.get('queue') or []
    seed_count = sum(1 for row in rows if row.get('artist') == seeds.artist_name or row.get('album_artist') == seeds.artist_name)
    unique_artists = {row.get('artist') for row in rows if row.get('artist')}
    assert 0 < seed_count < len(rows), {'seed_count': seed_count, 'returned': len(rows)}
    assert len(unique_artists) >= 3, unique_artists


def assert_thumbs_down_authoritative(db, seeds) -> None:
    req = StationQueueRequest(type='favorites', limit=50, shuffle=False)
    result = assert_deterministic_queue(db, req, PROD4_FIXTURE_SEED + 901)
    ids = [int(row['track_id']) for row in result.get('queue') or [] if row.get('track_id') is not None]
    if not ids:
        return
    down_rows = db.query(models.TrackThumb.track_id).filter(models.TrackThumb.value == 'down', models.TrackThumb.track_id.in_(ids)).all()
    assert not down_rows, down_rows


def main() -> int:
    assert_real_db_empty()
    base = Path('tmp_tests') / 'prod4_2c_1_refill_closure'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    engine, db = build_ctx(base, 'closure', 10000)
    try:
        seeds = select_station_seeds(db)
        before = table_counts(db, STATION_WRITE_TABLES)
        requests = [
            ('song', StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), 'song'),
            ('artist', StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False), 'artist'),
            ('genre', StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False), 'genre'),
            ('favorites', StationQueueRequest(type='favorites', limit=50, shuffle=False), 'global'),
        ]
        closure_metrics = {}
        for index, (name, req, expected_mode) in enumerate(requests):
            closure_metrics[name] = assert_refill_chain(db, req, expected_mode=expected_mode, seeds=seeds, operation_seed=PROD4_FIXTURE_SEED + index * 100)
        assert_physical_variant_exclusion(db)
        assert_artist_distribution(db, seeds)
        assert_thumbs_down_authoritative(db, seeds)
        for req, mode in [
            (StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), 'song'),
            (StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False), 'artist'),
            (StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False), 'genre'),
        ]:
            assert_debug_agrees(db, req, mode)
        after = table_counts(db, STATION_WRITE_TABLES)
        assert before == after, {'before': before, 'after': after}
        gate_source = Path('../scripts/check_prod0_baseline.py').read_text(encoding='utf-8')
        for script in [
            'check_prod4_1_station_scale_benchmark.py',
            'check_prod4_2a_scoped_station_profiles.py',
            'check_prod4_2b_station_candidate_projection_scope.py',
            'check_prod4_2c_station_intent_candidate_coverage.py',
            'check_prod4_2c_1_station_refill_closure.py',
        ]:
            assert script in gate_source, script
        assert_real_db_empty()
        print('PASS: BM-PROD4.2C.1 station refill closure')
        for name, rows in closure_metrics.items():
            last = rows[-1]
            print(f"{name}: refill4 returned={last['returned']} excluded_overlap={last['excluded_recording_overlap']} physical_overlap={last['physical_source_overlap']} intent={last['candidate_intent_mode']} bucket_queries={last['candidate_intent_bucket_query_count']}")
        return 0
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
