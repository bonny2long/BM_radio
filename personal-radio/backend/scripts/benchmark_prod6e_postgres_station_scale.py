from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import random
import re
import secrets
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from typing import Any, Iterable
from urllib.parse import quote_plus
import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app import models
from app.perf import collect_perf_segments
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, fixture_counts
from app.queue_contracts import StationQueueRequest
from app.station_engine import build_station_queue
from app.station_perf_benchmark import PROD4_FIXTURE_SEED, select_station_seeds

POSTGRES_IMAGE = 'postgres:16'
PROTECTED_RESOURCES = {'bm-radio-postgres-dev', 'bm-radio-postgres-dev-data'}
DEFAULT_BUDGETS = (500, 750, 1000, 1500, 2500, 5000)
SQL_SPACE = re.compile(r'\s+')
SQL_LITERAL = re.compile(r'\b\d+(?:\.\d+)?\b')


def run(command: list[str], *, timeout: int = 120, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=str(BACKEND), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace', timeout=timeout, shell=False)
    if check and result.returncode != 0:
        visible = ' '.join(command[:2])
        raise RuntimeError(f'command failed ({visible}): {result.stdout[-1200:]}')
    return result


def docker(*args: str, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(['docker', *args], timeout=timeout, check=check)


def file_digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def protected_snapshot() -> dict[str, str | None]:
    return {'backend_env': file_digest(BACKEND / '.env'), 'sqlite_fallback': file_digest(BACKEND / 'bm_radio.db')}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999)))
    return ordered[index]


def stats(values: Iterable[float]) -> dict[str, float]:
    items = [float(value) for value in values]
    return {'min': round(min(items), 3), 'p50': round(statistics.median(items), 3), 'p95': round(percentile(items, 0.95), 3), 'max': round(max(items), 3)}


def normalize_sql(statement: str) -> str:
    return SQL_SPACE.sub(' ', SQL_LITERAL.sub('?', statement)).strip()[:500]


@dataclass
class SqlSample:
    elapsed_ms: float
    signature: str
    statement: str
    parameters: Any


class SqlProfiler:
    def __init__(self, engine):
        self.engine = engine
        self.enabled = False
        self.samples: list[SqlSample] = []
        event.listen(engine, 'before_cursor_execute', self.before)
        event.listen(engine, 'after_cursor_execute', self.after)

    def before(self, conn, cursor, statement, parameters, context, executemany):
        if self.enabled:
            context._prod6e_started = time.perf_counter()

    def after(self, conn, cursor, statement, parameters, context, executemany):
        started = getattr(context, '_prod6e_started', None)
        if self.enabled and started is not None and statement.lstrip().lower().startswith('select'):
            self.samples.append(SqlSample((time.perf_counter() - started) * 1000, normalize_sql(statement), statement, parameters))

    @contextmanager
    def capture(self):
        self.samples = []
        self.enabled = True
        try:
            yield
        finally:
            self.enabled = False

    def summary(self) -> dict[str, Any]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for sample in self.samples:
            grouped[sample.signature].append(sample.elapsed_ms)
        slow = sorted(grouped.items(), key=lambda item: sum(item[1]), reverse=True)[:5]
        return {'select_count': len(self.samples), 'total_sql_ms': round(sum(sample.elapsed_ms for sample in self.samples), 3), 'slow_signatures': [{'signature': signature, 'count': len(times), 'total_ms': round(sum(times), 3), 'max_ms': round(max(times), 3)} for signature, times in slow]}

    def explain_slowest(self, db) -> dict[str, Any] | None:
        if not self.samples:
            return None
        sample = max(self.samples, key=lambda item: item.elapsed_ms)
        row = db.connection().exec_driver_sql(
            f'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sample.statement}',
            sample.parameters,
        ).scalar_one()
        document = row[0] if isinstance(row, list) else row
        plan = document['Plan']
        return {
            'signature': sample.signature,
            'measured_query_ms': round(sample.elapsed_ms, 3),
            'planning_ms': round(float(document.get('Planning Time', 0.0)), 3),
            'execution_ms': round(float(document.get('Execution Time', 0.0)), 3),
            'node_type': plan.get('Node Type'),
            'actual_rows': int(plan.get('Actual Rows', 0)),
            'shared_hit_blocks': int(plan.get('Shared Hit Blocks', 0)),
            'shared_read_blocks': int(plan.get('Shared Read Blocks', 0)),
            'temp_read_blocks': int(plan.get('Temp Read Blocks', 0)),
            'temp_written_blocks': int(plan.get('Temp Written Blocks', 0)),
        }

    def close(self) -> None:
        event.remove(self.engine, 'before_cursor_execute', self.before)
        event.remove(self.engine, 'after_cursor_execute', self.after)


class DisposablePostgres:
    def __init__(self):
        suffix = uuid.uuid4().hex[:10]
        self.container = f'bm-prod6e1-postgres-{suffix}'
        self.volume = f'bm-prod6e1-postgres-data-{suffix}'
        self.database = 'bm_prod6e1'
        self.role = 'bm_prod6e1_app'
        self.password = secrets.token_urlsafe(24)
        self.root: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> str:
        if {self.container, self.volume} & PROTECTED_RESOURCES:
            raise RuntimeError('protected PostgreSQL resource name rejected')
        self.root = tempfile.TemporaryDirectory(prefix='bm-prod6e1-')
        env_path = Path(self.root.name) / 'postgres.env'
        env_path.write_text(f'POSTGRES_DB={self.database}\nPOSTGRES_USER={self.role}\nPOSTGRES_PASSWORD={self.password}\n', encoding='utf-8')
        docker('volume', 'create', self.volume)
        docker('run', '--detach', '--name', self.container, '--env-file', str(env_path), '--mount', f'type=volume,source={self.volume},target=/var/lib/postgresql/data', '--publish', '127.0.0.1::5432', '--health-cmd', 'pg_isready --username=$POSTGRES_USER --dbname=$POSTGRES_DB', '--health-interval', '2s', '--health-timeout', '3s', '--health-retries', '40', '--security-opt', 'no-new-privileges:true', POSTGRES_IMAGE, timeout=300)
        deadline = time.time() + 120
        while time.time() < deadline:
            health = docker('inspect', '--format', '{{.State.Health.Status}}', self.container, check=False).stdout.strip()
            if health == 'healthy':
                break
            time.sleep(1)
        else:
            raise RuntimeError('disposable PostgreSQL did not become healthy')
        port_line = docker('port', self.container, '5432/tcp').stdout.strip().splitlines()[0]
        port = int(port_line.rsplit(':', 1)[1])
        url = f'postgresql+psycopg://{quote_plus(self.role)}:{quote_plus(self.password)}@127.0.0.1:{port}/{self.database}'
        migration_env = dict(os.environ)
        migration_env['BM_RADIO_DB_URL'] = url
        run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env=migration_env, timeout=300)
        return url

    def __exit__(self, exc_type, exc, tb):
        docker('rm', '--force', self.container, check=False)
        docker('volume', 'rm', '--force', self.volume, check=False)
        if self.root is not None:
            self.root.cleanup()


def request_for(name: str, seeds, exclusions: list[int]) -> StationQueueRequest:
    station_type = 'song' if name == 'song_live' else name
    kwargs: dict[str, Any] = {'type': station_type, 'limit': 50, 'shuffle': False, 'exclude_track_ids': exclusions}
    if name == 'song':
        kwargs['seed_track_id'] = seeds.song_track_id
    elif name == 'song_live':
        kwargs['seed_track_id'] = seeds.live_song_track_id
    elif name == 'artist':
        kwargs['seed_value'] = seeds.artist_name
    elif name == 'genre':
        kwargs['seed_value'] = seeds.genre_name
    return StationQueueRequest(**kwargs)


def summarize_segments(segments: dict[str, list[float]]) -> dict[str, float]:
    return {name: round(sum(values), 3) for name, values in sorted(segments.items())}


def measure(db, profiler: SqlProfiler, *, name: str, req: StationQueueRequest, budget: int | None, warmups: int, iterations: int, explain_slowest: bool = False) -> dict[str, Any]:
    if budget is None:
        db.info.pop('station_candidate_budget_override', None)
    else:
        db.info['station_candidate_budget_override'] = budget
    for index in range(warmups):
        random.seed(91000 + index)
        build_station_queue(req, db)
        db.expire_all()
    elapsed_values: list[float] = []
    sql_runs: list[dict[str, Any]] = []
    phase_runs: list[dict[str, float]] = []
    context_runs: list[dict[str, Any]] = []
    returned: list[int] = []
    for index in range(iterations):
        random.seed(92000 + index)
        with profiler.capture(), collect_perf_segments() as segments:
            started = time.perf_counter()
            response = build_station_queue(req, db)
            elapsed_values.append((time.perf_counter() - started) * 1000)
        queue = response.get('queue', [])
        logical = [row.get('recording_id') or ('track', row.get('track_id')) for row in queue]
        physical = [row.get('effective_track_id') or row.get('track_id') for row in queue]
        if len(logical) != len(set(logical)) or len(physical) != len(set(physical)):
            raise AssertionError(f'{name} produced duplicate station rows')
        returned.append(len(queue))
        sql_runs.append(profiler.summary())
        phase_runs.append(summarize_segments(segments))
        context_runs.append(dict(db.info.get('station_request_context_metrics') or {}))
        db.expire_all()
    explain_summary = profiler.explain_slowest(db) if explain_slowest else None
    random.seed(93000)
    tracemalloc.start()
    build_station_queue(req, db)
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    db.expire_all()
    phase_names = sorted({key for run_item in phase_runs for key in run_item})
    result = {
        'name': name,
        'candidate_budget': budget if budget is not None else 'production_policy',
        'exclude_count': len(req.exclude_track_ids or []),
        'wall_time_ms': stats(elapsed_values),
        'peak_memory_bytes': int(peak_memory),
        'select_count': stats([item['select_count'] for item in sql_runs]),
        'total_sql_ms': stats([item['total_sql_ms'] for item in sql_runs]),
        'slow_signatures': sql_runs[-1]['slow_signatures'],
        'phase_ms': {phase: stats([item.get(phase, 0.0) for item in phase_runs]) for phase in phase_names},
        'returned': returned,
        'context_metrics': context_runs[-1] if context_runs else {},
    }
    if explain_summary is not None:
        result['explain_analyze_buffers'] = explain_summary
    return result


def parse_ints(value: str) -> list[int]:
    items = [int(part.strip()) for part in value.split(',') if part.strip()]
    if not items:
        raise argparse.ArgumentTypeError('at least one integer is required')
    return items


def preflight() -> dict[str, Any]:
    version = docker('version', '--format', '{{.Server.Version}}').stdout.strip()
    image = docker('image', 'inspect', POSTGRES_IMAGE, '--format', '{{.RepoTags}}').stdout.strip()
    active = docker('inspect', '--type', 'container', 'bm-radio-postgres-dev', '--format', '{{.Id}}', check=False)
    return {
        'status': 'PREFLIGHT PASS',
        'docker_server_version': version,
        'postgres_image': image,
        'protected_active_container_present': active.returncode == 0,
        'task_resource_prefix': 'bm-prod6e1-',
        'protected_resources_rejected': sorted(PROTECTED_RESOURCES),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='BM-PROD6E.1 disposable PostgreSQL 10K station scale benchmark')
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--physical-tracks', type=int, default=10000)
    parser.add_argument('--budgets', type=parse_ints, default=list(DEFAULT_BUDGETS))
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--refill-exclusions', type=parse_ints, default=[50, 100, 150, 200])
    parser.add_argument('--initial-only', action='store_true')
    parser.add_argument('--production-policy', action='store_true')
    parser.add_argument('--explain-slowest', action='store_true')
    parser.add_argument('--output', type=Path, default=PROJECT / 'tmp_tests' / 'perf' / 'prod6e1_postgres_station_scale.json')
    args = parser.parse_args()
    readiness = preflight()
    if args.preflight_only:
        print(json.dumps(readiness, indent=2, sort_keys=True))
        return 0
    budgets: list[int | None] = [None] if args.production_policy else [max(50, min(int(value), 5000)) for value in args.budgets]
    before = protected_snapshot()
    report: dict[str, Any] = {
        'benchmark': 'BM-PROD6E.1 PostgreSQL 10K Station Profile and Candidate Budget',
        'database': {'engine': 'PostgreSQL', 'major': 16, 'alembic': 'head', 'disposable': True},
        'fixture_seed': PROD4_FIXTURE_SEED,
        'physical_tracks': int(args.physical_tracks),
        'candidate_budgets': ['production_policy' if value is None else value for value in budgets],
        'iterations': max(1, int(args.iterations)),
        'warmups': max(0, int(args.warmups)),
        'preflight': readiness,
        'runs': [],
    }
    with DisposablePostgres() as url:
        engine = create_engine(url, pool_pre_ping=True)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        profiler = SqlProfiler(engine)
        try:
            build_started = time.perf_counter()
            fixture = build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=args.physical_tracks, seed=PROD4_FIXTURE_SEED))
            report['fixture'] = fixture.as_dict()
            report['fixture_counts'] = fixture_counts(db)
            report['fixture_build_ms_excluded_from_latency'] = round((time.perf_counter() - build_started) * 1000, 3)
            seeds = select_station_seeds(db)
            exclude_ids = [int(row[0]) for row in db.query(models.Track.id).order_by(models.Track.id.asc()).limit(200).all()]
            initial_names = ['song', 'song_live', 'artist', 'genre', 'favorites', 'recently_added', 'deep_cuts']
            refill_names = ['song', 'artist', 'genre', 'favorites']
            for budget in budgets:
                for name in initial_names:
                    metric = measure(db, profiler, name=f'{name}.initial', req=request_for(name, seeds, []), budget=budget, warmups=max(0, args.warmups), iterations=max(1, args.iterations), explain_slowest=args.explain_slowest)
                    report['runs'].append(metric)
                    print(json.dumps({'budget': budget, 'name': metric['name'], 'wall_time_ms': metric['wall_time_ms']}))
                if not args.initial_only:
                    for exclusion_count in args.refill_exclusions:
                        for name in refill_names:
                            metric = measure(db, profiler, name=f'{name}.refill.{exclusion_count}', req=request_for(name, seeds, exclude_ids[:exclusion_count]), budget=budget, warmups=max(0, args.warmups), iterations=max(1, args.iterations), explain_slowest=args.explain_slowest)
                            report['runs'].append(metric)
                            print(json.dumps({'budget': budget, 'name': metric['name'], 'wall_time_ms': metric['wall_time_ms']}))
        finally:
            profiler.close()
            db.close()
            engine.dispose()
    after = protected_snapshot()
    report['protected_state'] = {'before': before, 'after': after, 'unchanged': before == after, 'active_postgresql_used': False, 'real_media_accessed': False}
    if before != after:
        raise AssertionError('protected SQLite or backend/.env changed')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')
    print(f'WROTE {args.output}')
    print('PASS: disposable PostgreSQL 16 benchmark completed and cleaned up')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
