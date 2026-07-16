from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from pathlib import Path
import random
import shutil
import statistics
import sys
import time
import tracemalloc
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models, station_candidates
from app.perf import collect_perf_segments
from app.perf_benchmark import BenchmarkContext, SqlCounter, stable_checksum
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine
from app.queue_contracts import StationQueueRequest
from app.station_candidate_intent import artist_intent, genre_intent, song_intent
from app.station_candidates import (
    MAX_STATION_CANDIDATE_POOL,
    load_station_recording_candidates,
    select_intent_station_recording_ids,
    select_intent_station_recording_ids_reference,
    station_identity_keys_for_track_ids,
)
from app.station_perf_benchmark import PROD4_FIXTURE_SEED, select_station_seeds, table_counts


@contextmanager
def patched_selector(selector: Callable):
    original = station_candidates.select_intent_station_recording_ids
    station_candidates.select_intent_station_recording_ids = selector
    try:
        yield
    finally:
        station_candidates.select_intent_station_recording_ids = original


def median(values: list[float]) -> float:
    return round(statistics.median(values), 3) if values else 0.0


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


def measure_case(ctx: BenchmarkContext, *, case_name: str, req: StationQueueRequest, intent, selector_name: str, selector: Callable, ordinal: int) -> dict[str, Any]:
    random.seed(PROD4_FIXTURE_SEED + ordinal)
    start_process = time.process_time()
    start_wall = time.perf_counter()
    tracemalloc.start()
    with patched_selector(selector):
        with collect_perf_segments() as segments:
            with SqlCounter(ctx.engine) as sql:
                candidates = load_station_recording_candidates(ctx.db, limit=MAX_STATION_CANDIDATE_POOL, exclude_keys=exclude_keys_for_request(ctx.db, req), candidate_intent=intent)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    ctx.db.rollback()
    elapsed = (time.perf_counter() - start_wall) * 1000
    process_elapsed = (time.process_time() - start_process) * 1000
    recording_ids = [candidate.recording_id for candidate in candidates if candidate.recording_id is not None]
    metrics = dict(ctx.db.info.get('station_candidate_projection_metrics') or {})
    return {
        'case': case_name,
        'selector': selector_name,
        'ordinal': ordinal,
        'wall_ms': round(elapsed, 3),
        'process_cpu_ms': round(process_elapsed, 3),
        'sql': sql.as_dict(),
        'peak_memory_bytes': int(peak),
        'candidate_count': len(candidates),
        'recording_ids_checksum': stable_checksum(recording_ids),
        'effective_track_ids_checksum': stable_checksum([candidate.effective_track.id for candidate in candidates]),
        'bucket_counts': metrics.get('candidate_intent_bucket_selected_counts'),
        'bucket_query_count': metrics.get('candidate_intent_bucket_query_count'),
        'projection_query_count': metrics.get('candidate_intent_projection_query_count'),
        'phase_metrics': {name: round(sum(values), 3) for name, values in sorted(segments.items())},
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for case in sorted({row['case'] for row in rows}):
        out[case] = {}
        for selector in sorted({row['selector'] for row in rows if row['case'] == case}):
            selected = [row for row in rows if row['case'] == case and row['selector'] == selector]
            out[case][selector] = {
                'wall_ms_median': median([row['wall_ms'] for row in selected]),
                'process_cpu_ms_median': median([row['process_cpu_ms'] for row in selected]),
                'select_count_median': median([row['sql']['select_count'] for row in selected]),
                'candidate_intent_buckets_ms_median': median([row['phase_metrics'].get('station.candidate_intent_buckets', 0.0) for row in selected]),
                'candidate_projection_ms_median': median([row['phase_metrics'].get('station.candidate_projection', 0.0) for row in selected]),
                'source_resolution_ms_median': median([row['phase_metrics'].get('station.source_resolution', 0.0) for row in selected]),
                'checksums': sorted({row['recording_ids_checksum'] for row in selected}),
                'bucket_counts': selected[-1].get('bucket_counts'),
            }
        reference_checksum = out[case].get('reference', {}).get('checksums')
        unified_checksum = out[case].get('unified', {}).get('checksums')
        out[case]['candidate_identity_equivalent'] = reference_checksum == unified_checksum
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description='BM-PROD4.2D unified candidate projection A/B benchmark')
    parser.add_argument('--size', type=int, default=50000)
    parser.add_argument('--iterations', type=int, default=5)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--output', type=Path, default=Path('tmp_tests/perf/prod4_2d_candidate_projection_ab.json'))
    args = parser.parse_args()

    base = Path('tmp_tests') / 'perf' / 'prod4_2d_candidate_projection_ab'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    engine, Session = create_temp_engine(base / 'benchmark.db')
    db = Session()
    try:
        summary = build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=args.size, seed=PROD4_FIXTURE_SEED))
        ctx = BenchmarkContext(db=db, engine=engine, temp_root=base, summary=summary)
        seeds = select_station_seeds(db)
        before = table_counts(db)
        cases = request_cases(db, seeds)
        rows: list[dict[str, Any]] = []
        selectors = [('reference', select_intent_station_recording_ids_reference), ('unified', select_intent_station_recording_ids)]
        ordinal = 0
        for _ in range(max(0, args.warmups)):
            for case_name, req, intent in cases:
                for selector_name, selector in selectors:
                    ordinal += 1
                    measure_case(ctx, case_name=case_name, req=req, intent=intent, selector_name=selector_name, selector=selector, ordinal=ordinal)
        order = ['unified', 'reference', 'reference', 'unified', 'unified', 'reference']
        selector_by_name = dict(selectors)
        for iteration in range(max(1, args.iterations)):
            for case_name, req, intent in cases:
                for selector_name in order[iteration % len(order):] + order[:iteration % len(order)]:
                    ordinal += 1
                    rows.append(measure_case(ctx, case_name=case_name, req=req, intent=intent, selector_name=selector_name, selector=selector_by_name[selector_name], ordinal=ordinal))
        after = table_counts(db)
        payload = {
            'benchmark': 'BM-PROD4.2D unified intent candidate projection A/B',
            'fixture_seed': PROD4_FIXTURE_SEED,
            'size': args.size,
            'iterations': max(1, args.iterations),
            'warmups': max(0, args.warmups),
            'station_seeds': seeds.as_dict(),
            'summary': summary.as_dict(),
            'read_only_tables_unchanged': before == after,
            'runs': rows,
            'summary_by_case': summarize(rows),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
        for case, summary_row in payload['summary_by_case'].items():
            if not isinstance(summary_row, dict) or 'reference' not in summary_row or 'unified' not in summary_row:
                continue
            print(case, 'reference_buckets_ms', summary_row['reference']['candidate_intent_buckets_ms_median'], 'unified_buckets_ms', summary_row['unified']['candidate_intent_buckets_ms_median'], 'equivalent', summary_row['candidate_identity_equivalent'])
        print(f'WROTE {args.output}')
        return 0
    finally:
        db.close()
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
