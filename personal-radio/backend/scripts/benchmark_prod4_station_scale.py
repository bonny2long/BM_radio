from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.perf_benchmark import BenchmarkContext
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine, fixture_counts
from app.station_perf_benchmark import (
    PROD4_FIXTURE_SEED,
    grouped_table,
    run_station_benchmarks,
    table_counts,
    write_report,
)


def parse_sizes(value: str) -> list[int]:
    sizes = []
    for part in value.split(','):
        part = part.strip()
        if not part:
            continue
        sizes.append(int(part))
    if not sizes:
        raise argparse.ArgumentTypeError('at least one size is required')
    return sizes


def main() -> int:
    parser = argparse.ArgumentParser(description='BM-PROD4.1 station generation/refill scale benchmark')
    parser.add_argument('--sizes', type=parse_sizes, default=parse_sizes('1000,10000,50000'))
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--output', type=Path, default=Path('tmp_tests/perf/prod4_1_station_baseline.json'))
    parser.add_argument('--include-debug', action='store_true')
    parser.add_argument('--include-listing', action='store_true')
    parser.add_argument('--refill-count', type=int, default=4)
    args = parser.parse_args()

    base = Path('tmp_tests') / 'perf' / 'prod4_1_station_scale'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    all_runs = []
    try:
        for size in args.sizes:
            size_dir = base / f'{size}'
            engine, Session = create_temp_engine(size_dir / 'benchmark.db')
            db = Session()
            try:
                summary = build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=size, seed=PROD4_FIXTURE_SEED))
                ctx = BenchmarkContext(db=db, engine=engine, temp_root=size_dir, summary=summary)
                before = table_counts(db)
                result = run_station_benchmarks(
                    ctx,
                    iterations=max(1, args.iterations),
                    warmups=max(0, args.warmups),
                    refill_count=max(0, args.refill_count),
                    include_debug=args.include_debug,
                    include_listing=args.include_listing,
                )
                after = table_counts(db)
                result['fixture_counts'] = fixture_counts(db)
                result['read_only_tables_unchanged_after_benchmarks'] = before == after
                result['status'] = 'COMPLETED'
                all_runs.append(result)

                print()
                print(f'SIZE {size}')
                print('INITIAL')
                print('\n'.join(grouped_table(result['metrics'], 'initial')))
                print('REFILL')
                print('\n'.join(grouped_table(result['metrics'], 'refill')))
                if args.include_debug or args.include_listing:
                    print('DEBUG/LISTING')
                    print('\n'.join(grouped_table(result['metrics'], 'other')))
            finally:
                db.close()
                engine.dispose()

        payload = {
            'benchmark': 'BM-PROD4.1 Station Generation and Refill Scale Benchmark Baseline',
            'fixture_seed': PROD4_FIXTURE_SEED,
            'sizes_requested': args.sizes,
            'iterations': max(1, args.iterations),
            'warmups': max(0, args.warmups),
            'refill_count': max(0, args.refill_count),
            'runs': all_runs,
        }
        write_report(args.output, payload)
        print()
        print(f'WROTE {args.output}')
        return 0
    except KeyboardInterrupt:
        partial = {
            'benchmark': 'BM-PROD4.1 Station Generation and Refill Scale Benchmark Baseline',
            'fixture_seed': PROD4_FIXTURE_SEED,
            'sizes_requested': args.sizes,
            'status': 'ABORTED DUE RUNTIME',
            'runs': all_runs,
        }
        write_report(args.output, partial)
        print(json.dumps({'status': 'ABORTED DUE RUNTIME', 'output': str(args.output)}, indent=2))
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
