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
    select_experimental_unified_intent_station_recording_ids,
    select_intent_station_recording_ids,
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
    tracemalloc.start()
    start_wall = time.perf_counter()
    with patched_selector(selector):
        with collect_perf_segments() as segments:
            with SqlCounter(ctx.engine) as sql:
                candidates = load_station_recording_candidates(
                    ctx.db,
                    limit=MAX_STATION_CANDIDATE_POOL,
                    exclude_keys=exclude_keys_for_request(ctx.db, req),
                    candidate_intent=intent,
                )
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed_ms = (time.perf_counter() - start_wall) * 1000
    ctx.db.rollback()
    recording_ids = [candidate.recording_id for candidate in candidates if candidate.recording_id is not None]
    metrics = dict(ctx.db.info.get('station_candidate_projection_metrics') or {})
    phase_metrics = {name: round(sum(values), 3) for name, values in sorted(segments.items())}
    return {
        'case': case_name,
        'selector': selector_name,
        'ordinal': ordinal,
        'wall_ms': round(elapsed_ms, 3),
        'projection_ms': phase_metrics.get('station.candidate_projection', round(elapsed_ms, 3)),
        'candidate_intent_buckets_ms': phase_metrics.get('station.candidate_intent_buckets'),
        'sql': sql.as_dict(),
        'peak_memory_bytes': int(peak),
        'candidate_count': len(candidates),
        'recording_ids_checksum': stable_checksum(recording_ids),
        'bucket_counts': metrics.get('candidate_intent_bucket_selected_counts'),
        'bucket_query_count': metrics.get('candidate_intent_bucket_query_count'),
        'projection_query_count': metrics.get('candidate_intent_projection_query_count'),
        'candidate_selector_policy': metrics.get('candidate_selector_policy'),
        'unified_projection': metrics.get('unified_projection'),
        'phase_metrics': phase_metrics,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cases = sorted({row['case'] for row in rows})
    for case in cases:
        out[case] = {}
        for selector in sorted({row['selector'] for row in rows if row['case'] == case}):
            selected = [row for row in rows if row['case'] == case and row['selector'] == selector]
            out[case][selector] = {
                'wall_ms_median': median([row['wall_ms'] for row in selected]),
                'projection_ms_median': median([row['projection_ms'] for row in selected]),
                'select_count_median': median([row['sql']['select_count'] for row in selected]),
                'checksums': sorted({row['recording_ids_checksum'] for row in selected}),
                'bucket_counts': selected[-1].get('bucket_counts') if selected else None,
                'bucket_query_count': selected[-1].get('bucket_query_count') if selected else None,
                'candidate_selector_policy': selected[-1].get('candidate_selector_policy') if selected else None,
                'unified_projection': selected[-1].get('unified_projection') if selected else None,
            }
        production_checksum = out[case].get('production_multi_bucket', {}).get('checksums')
        unified_checksum = out[case].get('unified_experimental', {}).get('checksums')
        out[case]['candidate_identity_equivalent'] = production_checksum == unified_checksum
    return out


def assert_not_timed_out(deadline: float, label: str) -> None:
    if time.perf_counter() >= deadline:
        raise TimeoutError(f'BM-PROD4.2E focused benchmark exceeded timeout before {label}')


def main() -> int:
    parser = argparse.ArgumentParser(description='BM-PROD4.2E focused candidate-projection benchmark')
    parser.add_argument('--size', type=int, default=50000)
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--timeout-seconds', type=int, default=600)
    parser.add_argument('--output', type=Path, default=Path('tmp_tests/perf/prod4_2e_focused_candidate_projection.json'))
    args = parser.parse_args()

    total_start = time.perf_counter()
    deadline = total_start + max(1, int(args.timeout_seconds))
    base = Path('tmp_tests') / 'perf' / 'prod4_2e_focused_candidate_projection'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    assert_not_timed_out(deadline, 'fixture build')
    engine, Session = create_temp_engine(base / 'benchmark_50k.db')
    db = Session()
    try:
        fixture_start = time.perf_counter()
        summary = build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=args.size, seed=PROD4_FIXTURE_SEED))
        fixture_build_ms = round((time.perf_counter() - fixture_start) * 1000, 3)
        ctx = BenchmarkContext(db=db, engine=engine, temp_root=base, summary=summary)
        seeds = select_station_seeds(db)
        before = table_counts(db)
        cases = request_cases(db, seeds)
        selectors = [
            ('production_multi_bucket', select_intent_station_recording_ids),
            ('unified_experimental', select_experimental_unified_intent_station_recording_ids),
        ]
        rows: list[dict[str, Any]] = []
        warmup_rows: list[dict[str, Any]] = []
        ordinal = 0

        for _ in range(max(0, args.warmups)):
            for case_name, req, intent in cases:
                for selector_name, selector in selectors:
                    assert_not_timed_out(deadline, f'warmup {case_name}/{selector_name}')
                    ordinal += 1
                    warmup_rows.append(measure_case(ctx, case_name=case_name, req=req, intent=intent, selector_name=selector_name, selector=selector, ordinal=ordinal))

        for iteration in range(max(1, args.iterations)):
            for case_name, req, intent in cases:
                for selector_name, selector in selectors:
                    assert_not_timed_out(deadline, f'measurement {iteration + 1} {case_name}/{selector_name}')
                    ordinal += 1
                    rows.append(measure_case(ctx, case_name=case_name, req=req, intent=intent, selector_name=selector_name, selector=selector, ordinal=ordinal))
                    assert_not_timed_out(deadline, f'after measurement {iteration + 1} {case_name}/{selector_name}')

        after = table_counts(db)
        payload = {
            'benchmark': 'BM-PROD4.2E focused production multi-bucket vs experimental unified candidate projection',
            'fixture_seed': PROD4_FIXTURE_SEED,
            'size': args.size,
            'fixture_build_ms': fixture_build_ms,
            'total_elapsed_ms': round((time.perf_counter() - total_start) * 1000, 3),
            'timeout_seconds': int(args.timeout_seconds),
            'iterations': max(1, args.iterations),
            'warmups': max(0, args.warmups),
            'station_seeds': seeds.as_dict(),
            'summary': summary.as_dict(),
            'read_only_tables_unchanged': before == after,
            'warmups_detail': warmup_rows,
            'runs': rows,
            'summary_by_case': summarize(rows),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
        print(f'fixture_build_ms {fixture_build_ms}')
        for case, summary_row in payload['summary_by_case'].items():
            if not isinstance(summary_row, dict):
                continue
            prod = summary_row.get('production_multi_bucket') or {}
            unified = summary_row.get('unified_experimental') or {}
            print(
                case,
                'production_projection_ms', prod.get('projection_ms_median'),
                'unified_projection_ms', unified.get('projection_ms_median'),
                'production_selects', prod.get('select_count_median'),
                'unified_selects', unified.get('select_count_median'),
                'equivalent', summary_row.get('candidate_identity_equivalent'),
                'production_buckets', prod.get('bucket_counts'),
                'unified_buckets', unified.get('bucket_counts'),
            )
        print(f'WROTE {args.output}')
        return 0
    finally:
        db.close()
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
