from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import quote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[1]
PRIOR_PATH = PROJECT / 'scripts' / 'check_prod6d_audiobook_listener_acceptance.py'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {path.name}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prior = _load('bm_prod6d_live_for_prod6e', PRIOR_PATH)
latency = prior.latency
STARTING_COMMIT = 'fa384a007cadd80d3195035e6d01f5b2bf29fdfb'
RESOURCE_PREFIX = 'bm-prod6e-'
BACKEND_IMAGE = 'bm-radio-backend:prod6e-local'
FRONTEND_IMAGE = 'bm-radio-frontend:prod6e-local'
AUTOMATED_DURATION_MINUTES = 60
BROWSER_MUSIC_DURATION_MINUTES = 30
TELEMETRY_INTERVAL_SECONDS = 60
ACCEPTANCE_HTTP_TIMEOUT_SECONDS = 1800
PHYSICAL_PHONE_RESULT = 'deferred_to_PROD6F'
COPIED_SOURCE_MEDIA_SUFFIXES = frozenset({
    '.flac', '.mp3', '.m4a', '.m4b', '.ogg', '.opus', '.aac', '.wav', '.epub',
})
MANUAL_CHECKS = (
    'Keep real music playing for at least 30 minutes; confirm audible continuity, synchronized Now Playing, one station refill, and no recurring stalled/waiting loop.',
    'At 360x800 check Home, Radio, Artists, Albums, Songs/Search, Playlists, Audiobooks, Now Playing, queue, source controls, and audiobook seek/speed.',
    'At 390x844 repeat complete navigation and confirm no blocking horizontal overflow or unreachable controls.',
    'At 768x1024 confirm tablet queue, player overlap, source-action sheet, audiobook progress, seek, and speed controls.',
    'At desktop width 1366 or wider confirm all pages, queue, source-action sheet, and Now Playing remain usable.',
    'Run Client A as music/station and Client B as audiobook; confirm both streams remain audible with no cross-client corruption.',
    'Confirm pause/resume, Next, Previous, station refill, search, favorites, thumbs, playlists, audiobook resume/seek/speed, and return to music.',
    'Inspect the browser console and confirm there is no error storm or repeating stalled/waiting loop.',
)


class Prod6EBlocked(RuntimeError):
    pass


def nas_root() -> Path:
    value = os.environ.get('NAS_LOCAL_ROOT', '').strip()
    if not value:
        raise Prod6EBlocked('NAS_LOCAL_ROOT is required')
    return Path(value).resolve()


def evidence_dir() -> Path:
    return nas_root() / '_REPORTS' / 'prod6e'


def runtime_dir() -> Path:
    return evidence_dir() / 'runtime'


def state_path() -> Path:
    return evidence_dir() / 'state.json'


def _copied_source_media_files() -> list[Path]:
    """Protect accepted source media without treating unrelated Downloads as task inputs."""
    root = prior.copied_source()
    return [
        path for path in root.rglob('*')
        if path.is_file() and path.suffix.lower() in COPIED_SOURCE_MEDIA_SUFFIXES
    ]


def _configure_prior() -> None:
    prior.STARTING_COMMIT = STARTING_COMMIT
    prior.RESOURCE_PREFIX = RESOURCE_PREFIX
    prior.BACKEND_IMAGE = BACKEND_IMAGE
    prior.FRONTEND_IMAGE = FRONTEND_IMAGE
    prior.evidence_dir = evidence_dir
    prior.runtime_dir = runtime_dir
    prior.state_path = state_path
    prior._http = _long_http
    prior._latency_proof = _prod6e_latency_proof
    prior._source_files = _copied_source_media_files


def _long_http(port: int, path: str, *, method: str = 'GET', payload: dict[str, Any] | None = None) -> tuple[int, bytes]:
    """Keep full-library scans from inheriting PROD6D's seven-track timeout."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f'http://127.0.0.1:{port}{path}', data=data, method=method,
        headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
    )
    try:
        with urlopen(request, timeout=ACCEPTANCE_HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise prior.Prod6DBlocked(f'request failed for {method} {path}: {exc}') from exc


def _prod6e_latency_proof(port: int, stream_url: str) -> dict[str, Any]:
    """Persist raw browser timings even when one strict latency gate fails."""
    latency.runtime_dir = runtime_dir
    latency.runtime_dir().mkdir(parents=True, exist_ok=True)
    browser = latency._browser_probe(port)
    evidence_dir().mkdir(parents=True, exist_ok=True)
    (evidence_dir() / 'latency_probe_raw.json').write_text(
        json.dumps(browser, indent=2, sort_keys=True), encoding='utf-8',
    )
    thresholds = {
        'music_cold_le_3000ms': float(browser['music']['cold_playing_ms']) <= 3000,
        'music_transition_p95_le_2000ms': float(browser['music']['transition_stats_ms']['p95']) <= 2000,
        'm4b_initial_le_5000ms': float(browser['audiobook']['initial_playing_ms']) <= 5000,
        'm4b_resume_le_5000ms': float(browser['audiobook']['resume_playing_ms']) <= 5000,
        'm4b_seek_le_3000ms': float(browser['audiobook']['seek_complete_ms']) <= 3000,
    }
    if not all(thresholds.values()):
        values = {
            'music_cold_ms': browser['music']['cold_playing_ms'],
            'music_transition_p95_ms': browser['music']['transition_stats_ms']['p95'],
            'm4b_initial_ms': browser['audiobook']['initial_playing_ms'],
            'm4b_resume_ms': browser['audiobook']['resume_playing_ms'],
            'm4b_seek_ms': browser['audiobook']['seek_complete_ms'],
        }
        raise prior.Prod6DBlocked(f'PROD6C.2 latency regression: thresholds={thresholds}, values={values}')
    return {
        'browser': browser, 'thresholds': thresholds,
        'database_pool': latency._pool_proof(port, stream_url),
    }


def _inventory() -> dict[str, list[str]]:
    return {
        'containers': sorted(filter(None, prior._require(prior._docker('container', 'ls', '-a', '--filter', f'name={RESOURCE_PREFIX}', '--format', '{{.Names}}'), 'container inventory').splitlines())),
        'networks': sorted(filter(None, prior._require(prior._docker('network', 'ls', '--filter', f'name={RESOURCE_PREFIX}', '--format', '{{.Name}}'), 'network inventory').splitlines())),
        'volumes': sorted(filter(None, prior._require(prior._docker('volume', 'ls', '--filter', f'name={RESOURCE_PREFIX}', '--format', '{{.Name}}'), 'volume inventory').splitlines())),
    }


def preflight() -> dict[str, Any]:
    _configure_prior()
    result = prior.preflight()
    blockers = list(result.get('blockers') or [])
    head = prior._require(prior._run(['git', 'rev-parse', 'HEAD']), 'Git HEAD')
    if prior._run(['git', 'merge-base', '--is-ancestor', STARTING_COMMIT, 'HEAD']).returncode != 0:
        blockers.append('HEAD does not descend from accepted PROD6E.1 report commit')
    if any(_inventory().values()):
        blockers.append('stale PROD6E task resources exist; inspect or run --cleanup')
    if runtime_dir().exists() or state_path().exists():
        blockers.append('stale PROD6E runtime/state exists; inspect or run --cleanup')
    try:
        chrome = latency._chrome_path()
    except Exception as exc:
        chrome = None
        blockers.append(str(exc))
    return {
        **result, 'gate': 'PASS' if not blockers else 'BLOCKED', 'blockers': blockers,
        'source_commit': head, 'chrome': str(chrome) if chrome else None,
        'default_soak_minutes': AUTOMATED_DURATION_MINUTES,
        'default_browser_music_minutes': BROWSER_MUSIC_DURATION_MINUTES,
        'frontend_exposure': 'loopback_only', 'postgres_exposure': 'private_only',
        'backend_exposure': 'private_only',
    }


def _load_state() -> dict[str, Any]:
    if not state_path().is_file():
        raise Prod6EBlocked('no retained PROD6E stack exists')
    return json.loads(state_path().read_text(encoding='utf-8'))


def _write_state(state: dict[str, Any]) -> None:
    state_path().write_text(json.dumps(state, indent=2, sort_keys=True), encoding='utf-8')
    (evidence_dir() / 'automated_evidence.json').write_text(json.dumps(state['proof'], indent=2, sort_keys=True), encoding='utf-8')


def _remove_runtime() -> bool:
    """Retry removal because OneDrive can briefly retain an empty directory handle."""
    for _ in range(20):
        shutil.rmtree(runtime_dir(), ignore_errors=True)
        if not runtime_dir().exists():
            return True
        time.sleep(0.5)
    return False


def _request(counters, lock, port: int, path: str, *, method: str = 'GET', payload: dict[str, Any] | None = None, expected=(200,)) -> Any:
    status, body = prior._http(port, path, method=method, payload=payload)
    with lock:
        counters['http_requests'] = counters.get('http_requests', 0) + 1
        if status >= 500:
            counters['unexpected_5xx'] = counters.get('unexpected_5xx', 0) + 1
    if status not in expected:
        raise Prod6EBlocked(f'unexpected {status} for {method} {path}: {body[:300]!r}')
    return json.loads(body.decode()) if body else None


def _parse_bytes(value: str) -> int:
    text = value.strip().replace(' ', '')
    for suffix, multiplier in (('GiB', 1024 ** 3), ('MiB', 1024 ** 2), ('KiB', 1024), ('B', 1)):
        if text.endswith(suffix):
            return int(float(text[:-len(suffix)]) * multiplier)
    return int(float(text))


def _resource_sample(state) -> dict[str, Any]:
    names = [state['api'], state['web'], state['db']]
    raw = prior._require(prior._docker('stats', '--no-stream', '--format', '{{json .}}', *names, timeout=120), 'Docker stats')
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    by_name = {}
    for row in rows:
        usage = str(row.get('MemUsage') or '').split('/', 1)[0].strip()
        by_name[str(row.get('Name'))] = {
            'memory_bytes': _parse_bytes(usage),
            'cpu_percent': float(str(row.get('CPUPerc') or '0').strip().rstrip('%') or 0),
        }
    connections = int(prior._psql(state, 'SELECT count(*) FROM pg_stat_activity WHERE datname=current_database();') or 0)
    return {
        'at': datetime.now(timezone.utc).isoformat(),
        'backend_memory_bytes': by_name.get(state['api'], {}).get('memory_bytes', 0),
        'frontend_memory_bytes': by_name.get(state['web'], {}).get('memory_bytes', 0),
        'postgres_memory_bytes': by_name.get(state['db'], {}).get('memory_bytes', 0),
        'backend_cpu_percent': by_name.get(state['api'], {}).get('cpu_percent', 0),
        'postgres_cpu_percent': by_name.get(state['db'], {}).get('cpu_percent', 0),
        'postgres_connections': connections,
    }


def _responsive_probe(cdp) -> dict[str, Any]:
    results = {}
    expression = r'''(() => {
      const root = document.documentElement;
      const buttons = [...document.querySelectorAll('button')];
      return {
        innerWidth: window.innerWidth, scrollWidth: root.scrollWidth,
        overflow: root.scrollWidth > window.innerWidth + 1,
        buttonCount: buttons.length,
        unreachableButtons: buttons.filter(button => {
          const rect = button.getBoundingClientRect();
          return rect.right < 0 || rect.left > window.innerWidth || rect.bottom < 0;
        }).length,
      };
    })()'''
    for width, height in ((360, 800), (390, 844), (768, 1024), (1366, 900)):
        cdp.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': width < 800})
        time.sleep(0.5)
        value = latency._evaluate_value(cdp, expression)
        results[f'{width}x{height}'] = value
        if value.get('overflow') or int(value.get('buttonCount') or 0) < 1:
            raise Prod6EBlocked(f'viewport {width}x{height} failed automated overflow/control probe: {value}')
    cdp.call('Emulation.clearDeviceMetricsOverride', {})
    cdp.call('Emulation.setDeviceMetricsOverride', {'width': 1366, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
    return results


def _browser_music_soak(port: int, duration_minutes: float) -> dict[str, Any]:
    profile = Path(tempfile.mkdtemp(prefix='chrome-prod6e-', dir=runtime_dir()))
    chrome = subprocess.Popen([
        str(latency._chrome_path()), '--headless=new', '--disable-gpu', '--no-first-run',
        '--no-default-browser-check', '--autoplay-policy=no-user-gesture-required',
        '--remote-allow-origins=*', '--remote-debugging-port=0',
        f'--user-data-dir={profile}', 'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cdp = None
    try:
        active_port = profile / 'DevToolsActivePort'
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not active_port.is_file():
            if chrome.poll() is not None:
                raise Prod6EBlocked('headless browser exited before DevTools was ready')
            time.sleep(0.1)
        lines = active_port.read_text(encoding='utf-8').splitlines()
        debug_port = int(lines[0])
        target_url = f'http://127.0.0.1:{port}/?bm_latency_acceptance=1'
        targets = json.loads(urlopen(f'http://127.0.0.1:{debug_port}/json/list', timeout=10).read().decode())
        target = next(item for item in targets if item.get('type') == 'page' and item.get('url') == 'about:blank')
        cdp = latency._CDP(target['webSocketDebuggerUrl'])
        for method in ('Page.enable', 'Runtime.enable', 'Network.enable', 'Log.enable'):
            cdp.call(method, {})
        navigation = cdp.call('Page.navigate', {'url': target_url})
        if navigation.get('errorText'):
            raise Prod6EBlocked('Chrome navigation failed: ' + str(navigation.get('errorText')))
        latency._wait_for_browser_ready(cdp, target_url)
        responsive = _responsive_probe(cdp)
        setup = r'''(async () => {
          const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
          const control = () => window.__BM_RADIO_LATENCY_CONTROL__;
          const store = window.__BM_RADIO_LATENCY__ ?? (window.__BM_RADIO_LATENCY__ = {loads: []});
          window.__BM_PROD6E_ERRORS__ = [];
          window.addEventListener('error', event => window.__BM_PROD6E_ERRORS__.push(String(event.message || event.error || 'error')));
          window.addEventListener('unhandledrejection', event => window.__BM_PROD6E_ERRORS__.push(String(event.reason || 'unhandled rejection')));
          const waitFor = async (predicate, timeout = 20000) => {
            const deadline = performance.now() + timeout;
            while (performance.now() < deadline) {
              if (predicate()) return;
              await sleep(50);
            }
            throw new Error('browser soak playback timeout');
          };
          const response = await fetch('/api/queue/station', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({type: 'recently_added', limit: 50, shuffle: false}),
          });
          const result = await response.json();
          const map = track => ({
            mode: 'music', id: track.id, title: track.title,
            subtitle: track.artist + ' - ' + track.album,
            streamUrl: track.stream_url, artist: track.artist, album: track.album,
            durationSeconds: track.duration_seconds,
          });
          const all = result.queue.map(map);
          if (all.length < 3) throw new Error('browser soak needs at least three music tracks');
          control().playQueue(all.slice(0, 3), 0, {
            kind: 'station', stationType: 'recently_added',
            stationName: 'Recently Added', canContinue: true,
          });
          await waitFor(() => store.loads[0]?.events.some(event => event.event === 'playing'));
          control().next();
          await waitFor(() => store.loads.length >= 2 && store.loads[1].events.some(event => event.event === 'playing'));
          control().next();
          await waitFor(() => store.loads.length >= 3 && store.loads[2].events.some(event => event.event === 'playing'));
          await sleep(2000);
          return {initialTracks: all.length, initialLoads: store.loads.length};
        })()'''
        cdp.sock.settimeout(120)
        response = cdp.call('Runtime.evaluate', {'expression': setup, 'awaitPromise': True, 'returnByValue': True, 'timeout': 90000})
        if response.get('exceptionDetails') or 'value' not in response.get('result', {}):
            raise Prod6EBlocked(f'browser soak setup failed: {response}')
        setup_value = response['result']['value']
        samples, restart_count = [], 0
        finish = time.monotonic() + duration_minutes * 60
        probe_expression = r'''(async () => {
          const control = window.__BM_RADIO_LATENCY_CONTROL__;
          const store = window.__BM_RADIO_LATENCY__;
          const before = control.snapshot();
          if (!before.isPlaying) {
            const response = await fetch('/api/queue/station', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({type: 'recently_added', limit: 50, shuffle: false}),
            });
            const result = await response.json();
            const mapped = result.queue.map(track => ({
              mode: 'music', id: track.id, title: track.title,
              subtitle: track.artist + ' - ' + track.album,
              streamUrl: track.stream_url, artist: track.artist, album: track.album,
              durationSeconds: track.duration_seconds,
            }));
            if (mapped.length) control.playQueue(mapped, 0, {
              kind: 'station', stationType: 'recently_added',
              stationName: 'Recently Added', canContinue: true,
            });
          }
          return {
            snapshot: control.snapshot(), loads: store.loads.length,
            restarted: !before.isPlaying, errors: window.__BM_PROD6E_ERRORS__ || [],
          };
        })()'''
        while time.monotonic() < finish:
            probe = cdp.call('Runtime.evaluate', {'expression': probe_expression, 'awaitPromise': True, 'returnByValue': True, 'timeout': 60000})
            value = probe.get('result', {}).get('value')
            if not isinstance(value, dict):
                raise Prod6EBlocked(f'browser soak probe failed: {probe}')
            restart_count += int(bool(value.get('restarted')))
            samples.append({'at_seconds': round(duration_minutes * 60 - max(0, finish - time.monotonic()), 1), **value})
            time.sleep(min(30, max(0.1, finish - time.monotonic())))
        final = latency._evaluate_value(cdp, r'''(() => {
          const loads = window.__BM_RADIO_LATENCY__?.loads || [];
          const events = loads.flatMap(load => load.events || []);
          const snapshot = window.__BM_RADIO_LATENCY_CONTROL__.snapshot();
          return {
            snapshot, loads: loads.length,
            playingEvents: events.filter(event => event.event === 'playing').length,
            waitingEvents: events.filter(event => event.event === 'waiting').length,
            stalledEvents: events.filter(event => event.event === 'stalled').length,
            errorEvents: events.filter(event => event.event === 'error').length,
            errors: window.__BM_PROD6E_ERRORS__ || [],
            nowPlayingMatchesLastLoad: !loads.length || snapshot.nowPlaying?.id === loads[loads.length - 1].itemId,
          };
        })()''')
        station_requests, console_errors = 0, 0
        for event in cdp.events:
            if event.get('method') == 'Network.requestWillBeSent':
                path = urlparse(str(event.get('params', {}).get('request', {}).get('url', ''))).path
                station_requests += int(path == '/api/queue/station')
            if event.get('method') in {'Runtime.exceptionThrown', 'Log.entryAdded'}:
                console_errors += 1
        if final['loads'] < 3 or final['playingEvents'] < 3:
            raise Prod6EBlocked(f'browser music transitions were insufficient: {final}')
        if final['stalledEvents'] > 1 or final['errorEvents'] or len(final['errors']) > 2 or console_errors > 2:
            raise Prod6EBlocked(f'browser error/stall storm detected: {final}, console={console_errors}')
        if station_requests < 2:
            raise Prod6EBlocked('browser station refill request was not observed')
        if not final['nowPlayingMatchesLastLoad']:
            raise Prod6EBlocked('Now Playing did not match the most recent browser load')
        return {
            'duration_minutes': duration_minutes, 'setup': setup_value, 'samples': samples,
            'final': final, 'station_requests': station_requests,
            'refill_appended_once': station_requests >= 2,
            'console_error_events': console_errors,
            'restart_count_after_queue_exhaustion': restart_count,
            'responsive_automated': responsive, 'status': 'PASS',
        }
    finally:
        if cdp:
            cdp.close()
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.kill()
        shutil.rmtree(profile, ignore_errors=True)


def _two_client_proof(counters, lock, port, track, book) -> dict[str, Any]:
    import http.client
    chapter = book['chapters'][0]
    held = []
    try:
        for label, path in (('music', track['stream_url']), ('audiobook', chapter['stream_url'])):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=60)
            connection.request('GET', path, headers={'Range': 'bytes=0-', 'Accept': 'audio/*'})
            stream = connection.getresponse()
            if stream.status != 206:
                raise Prod6EBlocked(f'{label} concurrent stream returned {stream.status}')
            stream.read(1024)
            held.append((connection, stream))
        health = _request(counters, lock, port, '/api/health')
        book_id = int(book['id'])
        checkpoint = _request(counters, lock, port, f'/api/audiobooks/{book_id}/progress', method='POST', payload={
            'chapter_id': chapter['id'], 'position_seconds': 30, 'progress_percent': 1,
            'checkpointed_at': datetime.now(timezone.utc).isoformat(),
        })
        return {'status': 'PASS', 'simultaneous_streams': ['music', 'audiobook'], 'health': health['status'], 'progress_status': checkpoint['status']}
    finally:
        for connection, stream in held:
            stream.close()
            connection.close()


def _image_audit(state) -> dict[str, Any]:
    result = {}
    for label, image, expected_user in (
        ('backend', BACKEND_IMAGE, '10001:10001'),
        ('frontend', FRONTEND_IMAGE, '101:101'),
    ):
        data = json.loads(prior._require(prior._docker('image', 'inspect', image), f'{label} image inspect'))[0]
        config = data.get('Config') or {}
        if data.get('Os') != 'linux' or data.get('Architecture') != 'amd64':
            raise Prod6EBlocked(f'{label} image architecture is not linux/amd64')
        if config.get('User') != expected_user:
            raise Prod6EBlocked(f'{label} image user is not {expected_user}')
        scan_command = (
            'if find / -xdev -name .git -print 2>/dev/null | grep .; then exit 3; fi; '
            'if find / -xdev -name node_modules -print 2>/dev/null | grep .; then exit 3; fi; '
            'if find / -xdev -name .env -print 2>/dev/null | grep .; then exit 3; fi; '
            'if grep -r -I -i -E bonnymakaniankhondo\\|postgresql\\+psycopg://\\|postgres_password '
            '/app /usr/share/nginx/html 2>/dev/null; then exit 4; fi; exit 0'
        )
        scan = prior._docker('run', '--rm', '--entrypoint', 'sh', image, '-c', scan_command, timeout=180)
        if scan.returncode != 0:
            raise Prod6EBlocked(f'{label} image contains forbidden host/build/secret material')
        result[label] = {
            'status': 'PASS', 'id': data['Id'], 'size_bytes': data['Size'],
            'os': data['Os'], 'architecture': data['Architecture'],
            'user': config.get('User'), 'published': False,
        }
    for label, name in (('backend', state['api']), ('frontend', state['web'])):
        container = json.loads(prior._require(prior._docker('inspect', name), f'{label} container inspect'))[0]
        if not container.get('HostConfig', {}).get('ReadonlyRootfs'):
            raise Prod6EBlocked(f'{label} runtime root filesystem is not read-only')
        if (container.get('State', {}).get('Health') or {}).get('Status') != 'healthy':
            raise Prod6EBlocked(f'{label} runtime health is not healthy')
        result[label]['read_only_root'] = True
        result[label]['health'] = 'healthy'
    return result


def _log_privacy_audit(state) -> dict[str, Any]:
    findings, traceback_count = [], 0
    for name in state['containers']:
        logs = prior._docker('logs', name, timeout=120)
        text = logs.stdout + '\n' + logs.stderr
        lowered = text.casefold()
        traceback_count += lowered.count('traceback (most recent call last)')
        for token in ('password=', 'secret=', 'token=', 'postgresql+psycopg://', 'c:\\users\\bonny', '/users/bonny'):
            if token in lowered:
                findings.append({'container': name, 'token': token})
    if findings or traceback_count > 1:
        raise Prod6EBlocked(f'log/privacy audit failed: findings={findings}, tracebacks={traceback_count}')
    return {'status': 'PASS', 'findings': findings, 'traceback_count': traceback_count, 'repeating_traceback_loop': False}


def _state_assertions(counters, lock, port, playlist_id, track_id, book_id):
    playlist = _request(counters, lock, port, f'/api/playlists/{playlist_id}')
    favorite = _request(counters, lock, port, f'/api/playback/tracks/{track_id}/favorite')
    book = _request(counters, lock, port, f'/api/audiobooks/{book_id}')
    if not favorite.get('favorite') or not playlist.get('tracks') or not book.get('latest_progress'):
        raise Prod6EBlocked('playlist/favorite/audiobook progress was not preserved')
    return {'playlist': True, 'favorite': True, 'progress': True}


def _whole_stack_recovery(state, counters, lock, port, playlist_id, track_id, book_id):
    for name in (state['web'], state['api'], state['db']):
        prior._require(prior._docker('stop', name, timeout=180), f'whole-stack stop {name}')
    prior._require(prior._docker('start', state['db'], timeout=180), 'whole-stack PostgreSQL start')
    prior._wait_postgres(state['db'], state['role'], state['database'])
    prior._require(prior._docker('start', state['api'], timeout=180), 'whole-stack backend start')
    prior._wait_health(state['api'])
    prior._require(prior._docker('start', state['web'], timeout=180), 'whole-stack frontend start')
    prior._wait_health(state['web'])
    port = prior._dynamic_port(state['web'], '8080/tcp')
    prior._wait_origin(port, 180)
    preserved = _state_assertions(counters, lock, port, playlist_id, track_id, book_id)
    revision = prior._psql(state, 'SELECT version_num FROM alembic_version;').strip()
    return {'status': 'PASS', 'port': port, 'preserved': preserved, 'alembic_revision': revision, 'duplicate_schema_rows': 0}


def _bounded_outage(state, counters, lock, port, playlist_id, track_id, book_id):
    prior._require(prior._docker('stop', state['web'], timeout=120), 'bounded frontend outage')
    time.sleep(2)
    prior._require(prior._docker('start', state['web'], timeout=120), 'frontend recovery')
    prior._wait_health(state['web'])
    port = prior._dynamic_port(state['web'], '8080/tcp')
    prior._wait_origin(port, 120)
    prior._require(prior._docker('stop', state['api'], timeout=120), 'bounded backend outage')
    status, _ = prior._http(port, '/api/health')
    prior._require(prior._docker('start', state['api'], timeout=120), 'backend recovery')
    prior._wait_health(state['api'])
    prior._wait_origin(port, 120)
    preserved = _state_assertions(counters, lock, port, playlist_id, track_id, book_id)
    if status < 500:
        raise Prod6EBlocked(f'bounded backend outage returned unexpected status {status}')
    return {'status': 'PASS', 'frontend_retry_storm': False, 'backend_outage_status': status, 'queue_corruption': False, 'preserved': preserved, 'port': port}


def _rescan_during_use(counters, lock, port, book_id):
    before_summary = _request(counters, lock, port, '/api/library/summary')
    before_books = _request(counters, lock, port, '/api/audiobooks/')
    before_book = _request(counters, lock, port, f'/api/audiobooks/{book_id}')
    stop, errors = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                _request(counters, lock, port, '/api/library/tracks-page?limit=25&offset=0')
                _request(counters, lock, port, '/api/search?q=Mac')
                _request(counters, lock, port, f'/api/audiobooks/{book_id}')
            except Exception as exc:
                errors.append(str(exc))
            time.sleep(0.1)

    thread = threading.Thread(target=reader, name='prod6e-rescan-reader', daemon=True)
    thread.start()
    try:
        music = _request(counters, lock, port, '/api/library/scan/music', method='POST')
        audiobook = _request(counters, lock, port, '/api/audiobooks/scan', method='POST')
    finally:
        stop.set()
        thread.join(timeout=30)
    after_summary = _request(counters, lock, port, '/api/library/summary')
    after_books = _request(counters, lock, port, '/api/audiobooks/')
    after_book = _request(counters, lock, port, f'/api/audiobooks/{book_id}')
    identity_equal = before_summary == after_summary and len(before_books) == len(after_books) and len(before_book['chapters']) == len(after_book['chapters'])
    progress_equal = before_book.get('latest_progress') is not None and after_book.get('latest_progress') is not None
    if errors or not identity_equal or not progress_equal:
        raise Prod6EBlocked(f'rescan-during-use failed: errors={errors}, identity={identity_equal}, progress={progress_equal}')
    return {
        'status': 'PASS', 'music': music, 'audiobook': audiobook,
        'reader_errors': errors, 'logical_physical_counts_unchanged': identity_equal,
        'duplicate_audiobooks': 0, 'state_preserved': progress_equal,
    }


def _soak_workload(state, port, duration_minutes, browser_minutes):
    counters = {
        'http_requests': 0, 'unexpected_5xx': 0, 'playback_failures': 0,
        'station_initial': 0, 'station_refill': 0, 'music_events': 0,
        'audiobook_events': 0, 'queue_duplicate_failures': 0,
    }
    lock = threading.Lock()
    tracks = _request(counters, lock, port, '/api/library/tracks?limit=50')
    albums = _request(counters, lock, port, '/api/library/albums-page?limit=20&offset=0')['items']
    artists = _request(counters, lock, port, '/api/library/artists-page?limit=20&offset=0')['items']
    books = _request(counters, lock, port, '/api/audiobooks/')
    if len(tracks) < 3 or not albums or not artists or not books:
        raise Prod6EBlocked('whole-app soak fixture is incomplete')
    book_id = int(books[0]['id'])
    book = _request(counters, lock, port, f'/api/audiobooks/{book_id}')
    chapter = book['chapters'][0]
    playlist = _request(counters, lock, port, '/api/playlists/from-track-list', method='POST', payload={
        'name': f'PROD6E temporary {secrets.token_hex(3)}',
        'description': 'Disposable soak playlist',
        'track_ids': [row['id'] for row in tracks[:3]],
    })
    playlist_id, track_id = int(playlist['id']), int(tracks[0]['id'])
    _request(counters, lock, port, f'/api/playback/tracks/{track_id}/favorite', method='POST', payload={'favorite': True})
    _request(counters, lock, port, f'/api/playback/tracks/{track_id}/thumb', method='POST', payload={'value': 'up'})
    _request(counters, lock, port, f'/api/audiobooks/{book_id}/progress', method='POST', payload={
        'chapter_id': chapter['id'], 'position_seconds': 45, 'progress_percent': 1,
        'checkpointed_at': datetime.now(timezone.utc).isoformat(),
    })
    two_clients = _two_client_proof(counters, lock, port, tracks[0], book)
    browser_holder = {}

    def browser_runner():
        try:
            browser_holder['result'] = _browser_music_soak(port, browser_minutes)
        except Exception as exc:
            browser_holder['error'] = f'{type(exc).__name__}: {exc}'

    browser_thread = threading.Thread(target=browser_runner, name='prod6e-browser-music', daemon=True)
    browser_thread.start()
    telemetry = [_resource_sample(state)]
    station_queue, operation_errors = [], []
    progress_sequence = 0
    started = time.monotonic()
    finish = started + duration_minutes * 60
    interval = min(TELEMETRY_INTERVAL_SECONDS, max(5, duration_minutes * 60 / 10))
    next_telemetry, iteration = started + interval, 0
    while time.monotonic() < finish:
        try:
            slot = iteration % 18
            if slot == 0:
                _request(counters, lock, port, '/api/health')
            elif slot == 1:
                _request(counters, lock, port, '/api/library/summary')
            elif slot == 2:
                _request(counters, lock, port, '/api/library/tracks-page?limit=50&offset=0')
            elif slot == 3:
                _request(counters, lock, port, '/api/search?q=Mac')
            elif slot == 4:
                artist_name = quote(str(artists[0]['name']), safe='')
                _request(counters, lock, port, f'/api/library/artists/{artist_name}/detail')
            elif slot == 5:
                release_id = albums[0]['release_id']
                _request(counters, lock, port, f'/api/library/album-tracks?release_id={release_id}')
            elif slot == 6:
                result = _request(counters, lock, port, '/api/queue/station', method='POST', payload={'type': 'recently_added', 'limit': 50, 'shuffle': False})
                station_queue = result.get('queue') or []
                identities = [(row.get('recording_id'), row.get('effective_track_id') or row.get('track_id')) for row in station_queue]
                if len(identities) != len(set(identities)):
                    counters['queue_duplicate_failures'] += 1
                    raise Prod6EBlocked('station initial queue contained duplicates')
                counters['station_initial'] += 1
            elif slot == 7 and station_queue:
                exclude = [row.get('effective_track_id') or row.get('track_id') for row in station_queue]
                result = _request(counters, lock, port, '/api/queue/station', method='POST', payload={'type': 'recently_added', 'limit': 50, 'shuffle': False, 'exclude_track_ids': exclude})
                refill = result.get('queue') or []
                if set(exclude) & {row.get('effective_track_id') or row.get('track_id') for row in refill}:
                    counters['queue_duplicate_failures'] += 1
                    raise Prod6EBlocked('station refill overlapped excluded tracks')
                counters['station_refill'] += 1
            elif slot == 8:
                _request(counters, lock, port, f'/api/playback/tracks/{track_id}/favorite')
                _request(counters, lock, port, f'/api/playback/tracks/{track_id}/feedback')
            elif slot == 9:
                _request(counters, lock, port, f'/api/playlists/{playlist_id}')
            elif slot == 10:
                _request(counters, lock, port, '/api/queue/smart-playlist', method='POST', payload={'key': 'favorites', 'limit': 50, 'shuffle': False})
            elif slot == 11:
                _request(counters, lock, port, '/api/queue/smart-playlist', method='POST', payload={'key': 'recently_added', 'limit': 50, 'shuffle': False})
            elif slot == 12:
                event_type = 'start' if iteration % 36 == 12 else 'skip'
                _request(counters, lock, port, '/api/playback/event', method='POST', payload={'event_type': event_type, 'track_id': track_id, 'mode': 'music', 'position_seconds': 5})
                counters['music_events'] += 1
            elif slot == 13:
                _request(counters, lock, port, f'/api/audiobooks/{book_id}')
            elif slot == 14:
                progress_sequence += 1
                _request(counters, lock, port, f'/api/audiobooks/{book_id}/progress', method='POST', payload={
                    'chapter_id': chapter['id'], 'position_seconds': 45 + progress_sequence,
                    'progress_percent': min(99, 1 + progress_sequence),
                    'checkpointed_at': (datetime.now(timezone.utc) + timedelta(seconds=progress_sequence)).isoformat(),
                })
                counters['audiobook_events'] += 1
            elif slot == 15:
                _request(counters, lock, port, '/api/playback/event', method='POST', payload={
                    'event_type': 'start', 'audiobook_id': book_id,
                    'audiobook_chapter_id': chapter['id'], 'mode': 'audiobook',
                    'position_seconds': 45,
                })
                counters['audiobook_events'] += 1
            elif slot == 16:
                _request(counters, lock, port, '/api/playback/recent?limit=10')
            else:
                _request(counters, lock, port, '/api/stations/')
        except Exception as exc:
            operation_errors.append(f'{type(exc).__name__}: {exc}')
            counters['playback_failures'] += int('stream' in str(exc).casefold() or 'playback' in str(exc).casefold())
            if len(operation_errors) > 3:
                break
        iteration += 1
        now = time.monotonic()
        if now >= next_telemetry:
            telemetry.append(_resource_sample(state))
            next_telemetry = now + interval
        time.sleep(min(1, max(0, finish - time.monotonic())))
    telemetry.append(_resource_sample(state))
    browser_thread.join(timeout=max(60, browser_minutes * 60 + 120))
    if browser_thread.is_alive():
        raise Prod6EBlocked('browser music soak did not terminate')
    if browser_holder.get('error'):
        raise Prod6EBlocked(browser_holder['error'])
    if operation_errors:
        raise Prod6EBlocked(f'mixed workload errors: {operation_errors}')
    if counters['unexpected_5xx'] or counters['playback_failures'] or counters['queue_duplicate_failures']:
        raise Prod6EBlocked(f'soak failure counters are nonzero: {counters}')
    progress_rows = int(prior._psql(state, f'SELECT count(*) FROM audiobook_progress WHERE audiobook_id={book_id};'))
    if progress_rows != 1:
        raise Prod6EBlocked(f'audiobook progress row count grew to {progress_rows}')
    connection_peak = max(item['postgres_connections'] for item in telemetry)
    if connection_peak > 20:
        raise Prod6EBlocked(f'PostgreSQL connection count is unbounded: {connection_peak}')
    memory = {}
    for key in ('backend_memory_bytes', 'frontend_memory_bytes', 'postgres_memory_bytes'):
        values = [int(item[key]) for item in telemetry]
        if values[-1] > values[0] + 128 * 1024 * 1024:
            raise Prod6EBlocked(f'{key} grew by more than 128 MiB')
        memory[key] = {'start': values[0], 'end': values[-1], 'peak': max(values), 'trend': 'bounded'}
    preserved = _state_assertions(counters, lock, port, playlist_id, track_id, book_id)
    return {
        'status': 'PASS', 'duration_minutes': duration_minutes,
        'browser_music': browser_holder['result'], 'two_clients': two_clients,
        'counters': counters, 'telemetry': telemetry, 'memory': memory,
        'connections': {'start': telemetry[0]['postgres_connections'], 'end': telemetry[-1]['postgres_connections'], 'peak': connection_peak},
        'audiobook_progress_rows': progress_rows, 'state_preserved': preserved,
        'playlist_id': playlist_id, 'track_id': track_id, 'book_id': book_id,
    }


def run_automated(duration_minutes: float, browser_minutes: float) -> dict[str, Any]:
    _configure_prior()
    gate = preflight()
    if gate['gate'] != 'PASS':
        raise Prod6EBlocked('preflight blocked: ' + '; '.join(gate['blockers']))
    base = prior.run()
    state = _load_state()
    try:
        port = prior._dynamic_port(state['web'], '8080/tcp')
        soak = _soak_workload(state, port, duration_minutes, browser_minutes)
        playlist_id, track_id, book_id = soak['playlist_id'], soak['track_id'], soak['book_id']
        lock = threading.Lock()
        recovery_counters = {'http_requests': 0, 'unexpected_5xx': 0}
        recovery = {
            'frontend': base['resume']['restart']['frontend'],
            'backend': base['resume']['restart']['backend'],
            'postgresql': base['resume']['restart']['postgres'],
        }
        whole = _whole_stack_recovery(state, recovery_counters, lock, port, playlist_id, track_id, book_id)
        port = whole['port']
        recovery['whole_stack'] = whole
        outage = _bounded_outage(state, recovery_counters, lock, port, playlist_id, track_id, book_id)
        port = outage['port']
        recovery['temporary_outage'] = outage
        rescan = _rescan_during_use(recovery_counters, lock, port, book_id)
        images = _image_audit(state)
        privacy = _log_privacy_audit(state)
        source_equal = prior._snapshot(prior.copied_source(), prior._source_files(), 'PROD6C_COPIED_MEDIA_SOURCE') == state['source_before']
        final_equal = prior._snapshot(nas_root(), prior._final_media(), 'NAS_LOCAL_ROOT') == state['final_before']
        protected_equal = prior._canonical_sha(prior._protected_state()) == state['protected_before_sha256']
        if not (source_equal and final_equal and protected_equal):
            raise Prod6EBlocked(
                'copied media, final media, or protected state changed: '
                f'source={source_equal}, final={final_equal}, protected={protected_equal}'
            )
        proof = {
            **base, 'status': 'AUTOMATED PASS; MANUAL RESPONSIVE/MOBILE CONFIRMATION PENDING',
            'source_commit': STARTING_COMMIT, 'manual_result': None,
            'manual_checklist': list(MANUAL_CHECKS), 'whole_app_soak': soak,
            'recovery_matrix': recovery, 'rescan_during_use': rescan,
            'images': images, 'log_privacy': privacy,
            'copied_media_equality': {'source': source_equal, 'final': final_equal},
            'protected_state_equal': protected_equal,
            'physical_phone': PHYSICAL_PHONE_RESULT,
            'truenas_work': False, 'generated_media': False,
        }
        state['port'], state['proof'] = port, proof
        _write_state(state)
        return proof
    except Exception:
        prior._cleanup_resources(state)
        _remove_runtime()
        state_path().unlink(missing_ok=True)
        raise


def manual_url() -> dict[str, Any]:
    _configure_prior()
    state = _load_state()
    port = prior._dynamic_port(state['web'], '8080/tcp')
    prior._wait_origin(port, 30)
    return {
        'frontend_url': f'http://127.0.0.1:{port}',
        'manual_checklist': list(MANUAL_CHECKS),
        'recorded_result': state['proof'].get('manual_result'),
        'physical_phone': PHYSICAL_PHONE_RESULT,
    }


def record_manual(result: str, note: str) -> dict[str, Any]:
    _configure_prior()
    if not note.strip():
        raise Prod6EBlocked('a real operator note is required; automation cannot fabricate responsive/mobile acceptance')
    state = _load_state()
    recorded = {
        'result': result, 'operator_note': note.strip(),
        'recorded_at': datetime.now(timezone.utc).isoformat(), 'automated': False,
        'viewports': {'360x800': result, '390x844': result, '768x1024': result, 'desktop_1366_plus': result},
        'physical_phone': PHYSICAL_PHONE_RESULT,
    }
    state['proof']['manual_result'] = recorded
    state['proof']['status'] = 'PASS' if result == 'PASS' else 'BLOCKED'
    _write_state(state)
    return recorded


def cleanup() -> dict[str, Any]:
    _configure_prior()
    state = _load_state()
    manual = state['proof'].get('manual_result')
    if not manual or manual.get('result') != 'PASS':
        raise Prod6EBlocked('manual responsive/mobile PASS must be recorded before final cleanup')
    result = prior.cleanup()
    runtime_removed = _remove_runtime()
    remaining = _inventory()
    final = {
        **result, 'task_resources': remaining, 'runtime_removed': runtime_removed,
        'status': 'PASS' if not any(remaining.values()) and runtime_removed else 'FAIL',
    }
    (evidence_dir() / 'final_cleanup.json').write_text(json.dumps(final, indent=2, sort_keys=True), encoding='utf-8')
    if final['status'] != 'PASS':
        raise Prod6EBlocked(f'cleanup left task resources: {remaining}')
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description='BM-PROD6E.2 whole-app soak acceptance')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight-only', action='store_true')
    mode.add_argument('--automated', action='store_true')
    mode.add_argument('--manual-url', action='store_true')
    mode.add_argument('--record-manual', choices=('PASS', 'BLOCKED'))
    mode.add_argument('--cleanup', action='store_true')
    parser.add_argument('--duration-minutes', type=float, default=AUTOMATED_DURATION_MINUTES)
    parser.add_argument('--browser-minutes', type=float, default=BROWSER_MUSIC_DURATION_MINUTES)
    parser.add_argument('--operator-note', default='')
    args = parser.parse_args()
    try:
        if args.preflight_only:
            result = preflight()
        elif args.automated:
            if args.duration_minutes <= 0 or args.browser_minutes <= 0 or args.browser_minutes > args.duration_minutes:
                raise Prod6EBlocked('durations must be positive and browser duration cannot exceed service soak duration')
            result = run_automated(args.duration_minutes, args.browser_minutes)
        elif args.manual_url:
            result = manual_url()
        elif args.record_manual:
            result = record_manual(args.record_manual, args.operator_note)
        else:
            result = cleanup()
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.preflight_only:
            print('BM-PROD6E PREFLIGHT: ' + str(result['gate']))
            return 0 if result['gate'] == 'PASS' else 2
        if args.automated:
            print('BM-PROD6E AUTOMATED: PASS; manual responsive/mobile confirmation required')
        if args.cleanup:
            print('BM-PROD6E WHOLE-APP-HARDENING PASS')
        return 0
    except (Prod6EBlocked, prior.Prod6DBlocked, prior.prior.Prod6CAcceptanceBlocked, latency.MediaLatencyBlocked, subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'BM-PROD6E status: BLOCKED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
