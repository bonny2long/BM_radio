from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from typing import Any, Callable
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app import models
from app.db import get_db
from app.main import app
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, fixture_counts
from app.station_perf_benchmark import PROD4_FIXTURE_SEED, select_station_seeds
from scripts.benchmark_prod6e_postgres_station_scale import (
    DisposablePostgres,
    protected_snapshot,
    stats,
)

DEFAULT_OUTPUT = BACKEND / 'tmp_tests' / 'perf' / 'prod6e2_postgres_listener_api_scale.json'


class SelectProfiler:
    def __init__(self, engine):
        self.engine = engine
        self.enabled = False
        self.started: dict[int, float] = {}
        self.samples: list[float] = []
        event.listen(engine, 'before_cursor_execute', self.before)
        event.listen(engine, 'after_cursor_execute', self.after)

    def before(self, conn, cursor, statement, parameters, context, executemany):
        if self.enabled and statement.lstrip().lower().startswith('select'):
            self.started[id(context)] = time.perf_counter()

    def after(self, conn, cursor, statement, parameters, context, executemany):
        started = self.started.pop(id(context), None)
        if self.enabled and started is not None:
            self.samples.append((time.perf_counter() - started) * 1000)

    @contextmanager
    def capture(self):
        self.samples = []
        self.started = {}
        self.enabled = True
        try:
            yield
        finally:
            self.enabled = False

    def close(self):
        event.remove(self.engine, 'before_cursor_execute', self.before)
        event.remove(self.engine, 'after_cursor_execute', self.after)


def response_size(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ('items', 'queue', 'tracks'):
            if isinstance(value.get(key), list):
                return len(value[key])
    return 1


def measure(
    client: TestClient,
    profiler: SelectProfiler,
    *,
    name: str,
    request: Callable[[], Any],
    threshold_ms: float,
    warmups: int,
    iterations: int,
    max_items: int | None = None,
) -> dict[str, Any]:
    for _ in range(warmups):
        response = request()
        if response.status_code != 200:
            raise AssertionError(f'{name} warmup returned {response.status_code}: {response.text[:400]}')
    elapsed: list[float] = []
    selects: list[float] = []
    sql_ms: list[float] = []
    sizes: list[int] = []
    for _ in range(iterations):
        with profiler.capture():
            started = time.perf_counter()
            response = request()
            elapsed.append((time.perf_counter() - started) * 1000)
        if response.status_code != 200:
            raise AssertionError(f'{name} returned {response.status_code}: {response.text[:400]}')
        payload = response.json()
        size = response_size(payload)
        if max_items is not None and size > max_items:
            raise AssertionError(f'{name} materialized {size} items; bound is {max_items}')
        sizes.append(size)
        selects.append(float(len(profiler.samples)))
        sql_ms.append(sum(profiler.samples))
    tracemalloc.start()
    response = request()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if response.status_code != 200:
        raise AssertionError(f'{name} memory probe returned {response.status_code}')
    timing = stats(elapsed)
    result = {
        'name': name,
        'threshold_ms': threshold_ms,
        'status': 'PASS' if timing['p95'] <= threshold_ms else 'FAIL',
        'wall_time_ms': timing,
        'select_count': stats(selects),
        'total_sql_ms': stats(sql_ms),
        'peak_python_bytes': int(peak),
        'returned_items': sizes,
    }
    if result['status'] != 'PASS':
        raise AssertionError(f"{name} p95 {timing['p95']}ms exceeds {threshold_ms}ms")
    return result


def run_benchmark(args) -> dict[str, Any]:
    before = protected_snapshot()
    with DisposablePostgres() as url:
        engine = create_engine(url, pool_pre_ping=True)
        Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        fixture_db = Session()
        try:
            fixture_started = time.perf_counter()
            fixture = build_synthetic_library(
                fixture_db,
                SyntheticLibrarySpec(physical_tracks=args.physical_tracks, seed=PROD4_FIXTURE_SEED),
            )
            fixture_build_ms = (time.perf_counter() - fixture_started) * 1000
            counts = fixture_counts(fixture_db)
            seeds = select_station_seeds(fixture_db)
            release_id = fixture_db.query(models.MusicRelease.id).order_by(models.MusicRelease.id).first()[0]
            playlist_id = fixture_db.query(models.Playlist.id).order_by(models.Playlist.id).first()[0]
        finally:
            fixture_db.close()

        def override_db():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        profiler = SelectProfiler(engine)
        client = TestClient(app, raise_server_exceptions=True)
        try:
            common = dict(client=client, profiler=profiler, warmups=max(0, args.warmups), iterations=max(1, args.iterations))
            if args.smoke_only:
                definitions = [
                    ('songs.page', lambda: client.get('/api/library/tracks-page?limit=100&offset=0'), 1500, 100),
                    ('search.global', lambda: client.get('/api/search?q=Artist%200099'), 2000, 80),
                    ('station.song', lambda: client.post('/api/queue/station', json={'type': 'song', 'seed_track_id': seeds.song_track_id, 'limit': 50, 'shuffle': False}), 3000, 50),
                ]
            else:
                artist_path = quote(seeds.artist_name, safe='')
                definitions = [
                    ('home.summary', lambda: client.get('/api/library/summary'), 500, None),
                    ('artists.page', lambda: client.get('/api/library/artists-page?limit=50&offset=0'), 500, 50),
                    ('albums.page', lambda: client.get('/api/library/albums-page?limit=50&offset=0'), 500, 50),
                    ('songs.page', lambda: client.get('/api/library/tracks-page?limit=100&offset=0'), 500, 100),
                    ('search.global', lambda: client.get('/api/search?q=Artist%200099'), 750, 80),
                    ('artist.detail', lambda: client.get(f'/api/library/artists/{artist_path}/detail'), 750, 50),
                    ('album.detail', lambda: client.get(f'/api/library/album-tracks?release_id={release_id}'), 750, 200),
                    ('playlist.projection', lambda: client.post('/api/queue/playlist', json={'playlist_id': playlist_id, 'shuffle': False}), 750, 100),
                    ('favorites.station', lambda: client.post('/api/queue/station', json={'type': 'favorites', 'limit': 50, 'shuffle': False}), 750, 50),
                    ('recently_added.station', lambda: client.post('/api/queue/station', json={'type': 'recently_added', 'limit': 50, 'shuffle': False}), 750, 50),
                    ('deep_cuts.station', lambda: client.post('/api/queue/station', json={'type': 'deep_cuts', 'limit': 50, 'shuffle': False}), 750, 50),
                ]
            runs = []
            for name, request, threshold, max_items in definitions:
                metric = measure(name=name, request=request, threshold_ms=threshold, max_items=max_items, **common)
                runs.append(metric)
                print(json.dumps({'name': name, 'p50': metric['wall_time_ms']['p50'], 'p95': metric['wall_time_ms']['p95'], 'status': metric['status']}))
            if max(run['select_count']['max'] for run in runs) > 100:
                raise AssertionError('listener operation exceeded bounded 100 SELECT ceiling')
            if max(run['peak_python_bytes'] for run in runs) > 256 * 1024 * 1024:
                raise AssertionError('listener operation exceeded bounded 256 MiB Python allocation ceiling')
            report = {
                'benchmark': 'BM-PROD6E.2 PostgreSQL listener API scale',
                'status': 'PASS',
                'mode': 'larger_scale_smoke' if args.smoke_only else '10k_api_acceptance',
                'database': {'engine': 'PostgreSQL', 'major': 16, 'alembic': 'head', 'disposable': True},
                'physical_tracks': args.physical_tracks,
                'fixture_seed': PROD4_FIXTURE_SEED,
                'fixture_checksum': fixture.checksum,
                'fixture_counts': counts,
                'fixture_build_ms_excluded_from_latency': round(fixture_build_ms, 3),
                'warmups': max(0, args.warmups),
                'iterations': max(1, args.iterations),
                'runs': runs,
                'architecture': {
                    'bounded_response_items': True,
                    'bounded_select_ceiling': 100,
                    'bounded_python_peak_bytes': 256 * 1024 * 1024,
                    'full_table_python_materialization': False,
                    'station_candidate_budget_expected': 500,
                },
            }
        finally:
            profiler.close()
            app.dependency_overrides.pop(get_db, None)
            engine.dispose()
    after = protected_snapshot()
    report['protected_state'] = {'before': before, 'after': after, 'unchanged': before == after}
    if before != after:
        raise AssertionError('protected .env or SQLite fallback changed')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description='BM-PROD6E.2 PostgreSQL listener API scale benchmark')
    parser.add_argument('--physical-tracks', type=int, default=10000)
    parser.add_argument('--warmups', type=int, default=2)
    parser.add_argument('--iterations', type=int, default=10)
    parser.add_argument('--smoke-only', action='store_true')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run_benchmark(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf-8')
    print(f'WROTE {args.output}')
    print('PASS: {} ({})'.format(result['benchmark'], result['mode']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
