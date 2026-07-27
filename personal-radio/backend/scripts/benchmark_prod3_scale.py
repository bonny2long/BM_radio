from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import platform
import sqlite3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.perf_benchmark import BenchmarkContext, classify_scaling, run_benchmarks, table_rows
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine, database_checksum


def parse_sizes(value: str) -> list[int]:
    sizes = []
    for item in str(value or "").split(","):
        item = item.strip().lower().replace("k", "000")
        if not item:
            continue
        sizes.append(int(item))
    if not sizes:
        raise argparse.ArgumentTypeError("at least one size is required")
    return sizes


def environment_summary() -> dict:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "sqlite_version": sqlite3.sqlite_version,
    }


def run_for_size(size: int, *, args, base_dir: Path) -> dict:
    size_dir = base_dir / f"size_{size}"
    if size_dir.exists():
        shutil.rmtree(size_dir)
    size_dir.mkdir(parents=True, exist_ok=True)
    engine, Session = create_temp_engine(size_dir / "synthetic.db")
    db = Session()
    try:
        summary = build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=size))
        ctx = BenchmarkContext(db=db, engine=engine, temp_root=size_dir, summary=summary)
        metrics = run_benchmarks(
            ctx,
            iterations=args.iterations,
            warmups=args.warmups,
            include_scanner=args.include_scanner,
            include_station_observation=args.include_station_observation,
        )
        return {
            "size": size,
            "fixture": summary.as_dict(),
            "database_checksum": database_checksum(db),
            "metrics": metrics,
        }
    finally:
        db.close()
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD3.1 synthetic scale benchmark runner")
    parser.add_argument("--sizes", type=parse_sizes, default=parse_sizes("1000"), help="Comma-separated physical Track counts, e.g. 1000,10000,50000,100000")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--include-scanner", action="store_true")
    parser.add_argument("--include-station-observation", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args()

    base_dir = Path("tmp_tests") / "perf" / "prod3_scale"
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    results = []
    all_metrics_by_size = {}
    try:
        for size in args.sizes:
            result = run_for_size(size, args=args, base_dir=base_dir)
            results.append(result)
            all_metrics_by_size[size] = result["metrics"]
            for line in table_rows(result["metrics"]):
                print(line)
            print("")

        payload = {
            "benchmark": "BM-PROD3.1 synthetic large-library baseline",
            "environment": environment_summary(),
            "sizes": args.sizes,
            "iterations": args.iterations,
            "warmups": args.warmups,
            "include_scanner": args.include_scanner,
            "include_station_observation": args.include_station_observation,
            "results": results,
            "scaling_classification": classify_scaling(all_metrics_by_size),
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
            print(f"wrote {args.output}")
        return 0
    finally:
        if not args.keep_temp:
            shutil.rmtree(base_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())