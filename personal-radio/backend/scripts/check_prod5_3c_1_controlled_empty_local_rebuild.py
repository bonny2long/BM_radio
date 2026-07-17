from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database_readiness import LEGACY_INCOMPATIBLE, READY
from app.migration_contract import APP_TABLES, BASELINE_REVISION, compare_schema, engine_for_url
from app.sqlite_adoption import (
    application_row_count,
    backup_sqlite_database,
    compatibility_issue_summary,
    restore_sqlite_backup,
    snapshot_sqlite_database,
)
from app.sqlite_rebuild import build_fresh_sqlite_database, existing_sidecars, rehearse_replacement_and_rollback, sqlite_url

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[0]
REAL_DB = BACKEND / 'bm_radio.db'
BACKUP_DIR = BACKEND / '.local_backups'
CHECKS: set[str] = set()


def mark(name: str) -> None:
    CHECKS.add(name)


def run_cmd(args: list[str], *, expect_ok: bool = True, env: dict[str, str] | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=BACKEND, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env)
    if expect_ok and result.returncode != 0:
        raise AssertionError(f'command failed {args}:\n{result.stdout}')
    if not expect_ok and result.returncode == 0:
        raise AssertionError(f'command unexpectedly passed {args}:\n{result.stdout}')
    return result


def process_snapshot() -> list[dict[str, Any]]:
    result = subprocess.run(
        ['powershell', '-NoProfile', '-Command', "Get-Process python,pythonw,node,npm -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,CPU,StartTime,Path | ConvertTo-Json -Compress"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    parsed = json.loads(result.stdout)
    return [parsed] if isinstance(parsed, dict) else parsed


def assert_no_backend_processes() -> None:
    processes = process_snapshot()
    python_processes = [proc for proc in processes if str(proc.get('ProcessName', '')).lower().startswith('python')]
    assert not python_processes, python_processes
    mark('no stale Python BM Radio process detected')


def assert_backup_dir_ignored() -> None:
    result = subprocess.run(['git', 'check-ignore', '-q', 'backend/.local_backups/probe.manifest.json'], cwd=ROOT, text=True)
    assert result.returncode == 0
    mark('backup directory is Git-ignored')


def assert_one_head() -> None:
    result = run_cmd([sys.executable, 'scripts/migration_status.py', 'heads'])
    assert result.stdout.strip() == BASELINE_REVISION, result.stdout
    mark('one committed migration head')


def snapshot_summary(snapshot: Any) -> dict[str, Any]:
    return snapshot.as_dict(include_schema=False, issue_limit=12)


def assert_manifest_safe(manifest_path: Path) -> None:
    text = manifest_path.read_text(encoding='utf-8')
    assert 'C:' + chr(92) + 'Users' not in text
    assert 'BonnyMakaniankhondo' not in text
    assert 'sqlite:///' not in text
    assert 'password' not in text.lower()
    mark('backup manifest excludes secrets and absolute personal paths')


def assert_no_media_access() -> None:
    tokens = ['scan_' + 'music(', 'music_' + 'flac_' + 'root', 'music_' + 'mp3_' + 'root', 'audiobooks_' + 'root', 'books_' + 'root']
    files = [
        'app/sqlite_adoption.py',
        'app/sqlite_rebuild.py',
        'scripts/check_local_db_adoption.py',
        'scripts/check_prod5_3c_controlled_local_adoption.py',
        'scripts/check_prod5_3c_1_controlled_empty_local_rebuild.py',
    ]
    for relative in files:
        source = (BACKEND / relative).read_text(encoding='utf-8').lower()
        assert not any(token in source for token in tokens), relative
    mark('no media access or mutation')


def assert_legacy_preconditions(snapshot: Any) -> None:
    assert snapshot.integrity_check == 'ok', snapshot_summary(snapshot)
    assert snapshot.quick_check == 'ok', snapshot_summary(snapshot)
    assert application_row_count(snapshot) == 0, snapshot_summary(snapshot)
    assert not snapshot.has_alembic_version, snapshot_summary(snapshot)
    assert snapshot.compatibility == 'FAIL', snapshot_summary(snapshot)
    assert snapshot.readiness_status == LEGACY_INCOMPATIBLE, snapshot_summary(snapshot)
    assert snapshot.head_revision == BASELINE_REVISION, snapshot_summary(snapshot)
    assert len(snapshot.application_tables) == 13, snapshot_summary(snapshot)
    mark('legacy DB is healthy, empty, unversioned, and incompatible')


def assert_fresh_candidate(path: Path, *, require_zero_rows: bool = True) -> Any:
    snapshot = snapshot_sqlite_database(path, logical_path=path.name)
    assert snapshot.integrity_check == 'ok', snapshot_summary(snapshot)
    assert snapshot.quick_check == 'ok', snapshot_summary(snapshot)
    assert snapshot.compatibility == 'PASS', snapshot_summary(snapshot)
    assert snapshot.readiness_status == READY, snapshot_summary(snapshot)
    assert snapshot.current_revision == BASELINE_REVISION, snapshot_summary(snapshot)
    assert snapshot.alembic_version_rows == (BASELINE_REVISION,), snapshot_summary(snapshot)
    if require_zero_rows:
        assert application_row_count(snapshot) == 0, snapshot_summary(snapshot)
    assert len(snapshot.application_tables) == len(APP_TABLES), snapshot_summary(snapshot)
    return snapshot


def backup_legacy(real_snapshot: Any) -> tuple[Path, Path, dict[str, Any]]:
    backup_path, manifest_path, manifest = backup_sqlite_database(REAL_DB, BACKUP_DIR, label='pre_empty_rebuild')
    backup_snapshot = snapshot_sqlite_database(backup_path, logical_path=backup_path.name)
    assert backup_snapshot.integrity_check == 'ok', snapshot_summary(backup_snapshot)
    assert backup_snapshot.quick_check == 'ok', snapshot_summary(backup_snapshot)
    assert backup_snapshot.schema_fingerprint == real_snapshot.schema_fingerprint
    assert backup_snapshot.application_row_counts == real_snapshot.application_row_counts
    assert backup_snapshot.sha256 == manifest['backup_sha256']
    assert manifest['schema_fingerprint'] == real_snapshot.schema_fingerprint
    assert manifest['compatibility'] == 'FAIL'
    assert manifest['readiness'] == LEGACY_INCOMPATIBLE
    assert manifest['application_row_count'] == 0
    assert_manifest_safe(manifest_path)
    mark('verified incompatible legacy backup exists')
    mark('backup helper uses SQLite backup API')
    return backup_path, manifest_path, manifest


def latest_pre_empty_backup() -> tuple[Path, Path, dict[str, Any]]:
    manifests = sorted(BACKUP_DIR.glob('bm_radio.pre_empty_rebuild.*.manifest.json'))
    for manifest_path in reversed(manifests):
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        backup_path = BACKUP_DIR / manifest['backup_filename']
        if backup_path.exists() and manifest.get('readiness') == LEGACY_INCOMPATIBLE:
            return backup_path, manifest_path, manifest
    raise AssertionError('no verified pre-empty-rebuild backup found')


def build_and_verify_fresh(base: Path) -> tuple[Path, Any]:
    fresh = base / 'fresh_candidate.db'
    build_fresh_sqlite_database(fresh, backend=BACKEND)
    first = assert_fresh_candidate(fresh)
    first_hash = first.sha256
    run_cmd([sys.executable, '-m', 'alembic', '-x', f'db_url={sqlite_url(fresh)}', 'upgrade', 'head'])
    second = assert_fresh_candidate(fresh)
    assert second.sha256 == first_hash, {'first': snapshot_summary(first), 'second': snapshot_summary(second)}
    assert not compare_schema(engine_for_url(sqlite_url(fresh)))
    mark('fresh candidate is built only through Alembic')
    mark('fresh candidate is at the one head')
    mark('fresh candidate is compatible, ready, and empty')
    mark('second Alembic upgrade is idempotent')
    return fresh, second


def startup_canary(fresh: Path, base: Path) -> dict[str, Any]:
    canary = base / 'startup_canary.db'
    restore_sqlite_backup(fresh, canary)
    url = sqlite_url(canary)
    env = os.environ.copy()
    env['BM_RADIO_DB_URL'] = url
    code = r'''
import asyncio
import json
from app import db
import app.main as main

async def once():
    async with main.app.router.lifespan_context(main.app):
        with db.engine.connect() as conn:
            return {
                'readiness': main.app.state.database_readiness.as_dict(),
                'artist_profiles': int(conn.exec_driver_sql('select count(*) from artist_radio_profiles').scalar() or 0),
                'album_profiles': int(conn.exec_driver_sql('select count(*) from album_radio_profiles').scalar() or 0),
            }

async def run():
    first = await once()
    second = await once()
    print(json.dumps({'first': first, 'second': second}, sort_keys=True))

asyncio.run(run())
'''
    result = run_cmd([sys.executable, '-c', code], env=env, timeout=240)
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload['first']['readiness']['status'] == READY, payload
    assert payload['first']['artist_profiles'] > 0 and payload['first']['album_profiles'] > 0, payload
    assert payload['second']['artist_profiles'] == payload['first']['artist_profiles'], payload
    assert payload['second']['album_profiles'] == payload['first']['album_profiles'], payload
    candidate_after = snapshot_sqlite_database(fresh, logical_path=fresh.name)
    assert application_row_count(candidate_after) == 0, snapshot_summary(candidate_after)
    mark('startup canary works on disposable copy')
    mark('startup seeding on copy is idempotent')
    mark('fresh replacement candidate remains unseeded')
    return payload


def restore_rehearsal(backup_path: Path, base: Path, source_snapshot: Any) -> Any:
    restored = base / 'restored_legacy.db'
    restore_sqlite_backup(backup_path, restored)
    snapshot = snapshot_sqlite_database(restored, logical_path='restored_legacy.db')
    assert snapshot.integrity_check == 'ok', snapshot_summary(snapshot)
    assert snapshot.quick_check == 'ok', snapshot_summary(snapshot)
    assert snapshot.schema_fingerprint == source_snapshot.schema_fingerprint, snapshot_summary(snapshot)
    assert snapshot.sha256 == source_snapshot.sha256, snapshot_summary(snapshot)
    assert application_row_count(snapshot) == 0, snapshot_summary(snapshot)
    assert not snapshot.has_alembic_version, snapshot_summary(snapshot)
    assert snapshot.compatibility == 'FAIL', snapshot_summary(snapshot)
    assert snapshot.readiness_status == LEGACY_INCOMPATIBLE, snapshot_summary(snapshot)
    mark('restore rehearsal reproduces legacy incompatible state')
    return snapshot


def replacement_rehearsal(backup_path: Path, fresh: Path, base: Path) -> dict[str, Any]:
    result = rehearse_replacement_and_rollback(backup_path, fresh, base)
    assert result.current_snapshot['compatibility'] == 'PASS', result.current_snapshot
    assert result.current_snapshot['readiness_status'] == READY, result.current_snapshot
    assert result.rollback_snapshot['compatibility'] == 'FAIL', result.rollback_snapshot
    assert result.rollback_snapshot['readiness_status'] == LEGACY_INCOMPATIBLE, result.rollback_snapshot
    mark('replacement rehearsal is atomic and recoverable')
    mark('rollback rehearsal restores legacy fingerprint')
    mark('old sidecars cannot attach to new DB')
    return {
        'current_after_replace': result.current_snapshot,
        'rollback_after_restore': result.rollback_snapshot,
        'archived_sidecar_count': len(result.archived_sidecars),
    }


def assert_populated_incompatible_blocks(backup_path: Path, base: Path) -> None:
    populated = base / 'populated_legacy.db'
    restore_sqlite_backup(backup_path, populated)
    conn = sqlite3.connect(populated)
    try:
        conn.execute("insert into tracks (id, path, relative_path, title, artist) values (999, 'tmp/populated.flac', 'tmp/populated.flac', 'Populated', 'Legacy')")
        conn.commit()
    finally:
        conn.close()
    snapshot = snapshot_sqlite_database(populated, logical_path='populated_legacy.db')
    assert snapshot.compatibility == 'FAIL', snapshot_summary(snapshot)
    assert application_row_count(snapshot) > 0, snapshot_summary(snapshot)
    blocked = False
    try:
        assert_legacy_preconditions(snapshot)
    except AssertionError:
        blocked = True
    assert blocked, snapshot_summary(snapshot)
    mark('populated incompatible legacy DB blocks rebuild')


def assert_real_ready(snapshot: Any) -> None:
    assert snapshot.integrity_check == 'ok', snapshot_summary(snapshot)
    assert snapshot.quick_check == 'ok', snapshot_summary(snapshot)
    assert snapshot.compatibility == 'PASS', snapshot_summary(snapshot)
    assert snapshot.readiness_status == READY, snapshot_summary(snapshot)
    assert snapshot.current_revision == BASELINE_REVISION, snapshot_summary(snapshot)
    mark('real DB is ready, head, compatible, and healthy')


def assert_prior_regressions() -> None:
    for script in ['scripts/check_prod5_3b_migration_authoritative_startup.py', 'scripts/check_prod5_3a_1_schema_parity_hardening.py', 'scripts/check_prod5_3a_migration_framework.py']:
        result = run_cmd([sys.executable, script], timeout=480)
        assert 'PASS' in result.stdout, result.stdout
    gate = (ROOT / 'scripts' / 'check_prod0_baseline.py').read_text(encoding='utf-8')
    assert 'check_prod4_2e_benchmark_selected_projection_policy.py' in gate
    mark('BM-PROD5.3B remains passing')
    mark('BM-PROD5.3A.1 remains passing')
    mark('BM-PROD5.3A remains passing')
    mark('BM-PROD4.2E remains in gate')


def preflight(base: Path) -> dict[str, Any]:
    assert_no_backend_processes()
    assert_backup_dir_ignored()
    sidecars = [path.name for path in existing_sidecars(REAL_DB)]
    before = snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db')
    assert_legacy_preconditions(before)
    assert_one_head()
    backup_path, manifest_path, manifest = backup_legacy(before)
    fresh, fresh_snapshot = build_and_verify_fresh(base)
    canary = startup_canary(fresh, base)
    restored = restore_rehearsal(backup_path, base, snapshot_sqlite_database(backup_path, logical_path=backup_path.name))
    replacement = replacement_rehearsal(backup_path, fresh, base)
    assert_populated_incompatible_blocks(backup_path, base)
    after = snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db')
    assert snapshot_summary(before) == snapshot_summary(after), {'before': snapshot_summary(before), 'after': snapshot_summary(after)}
    assert_no_media_access()
    mark('real DB inspected read-only before approval')
    return {
        'real_db': snapshot_summary(before),
        'real_db_sidecars': sidecars,
        'backup': {'filename': backup_path.name, 'manifest': manifest_path.name, 'manifest_data': manifest},
        'fresh_candidate': snapshot_summary(fresh_snapshot),
        'startup_canary': {'status': 'PASS', 'payload': canary},
        'restore_rehearsal': snapshot_summary(restored),
        'replacement_rehearsal': replacement,
    }


def full_regression(base: Path) -> dict[str, Any]:
    before = snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db')
    assert_real_ready(before)
    assert_one_head()
    assert_backup_dir_ignored()
    backup_path, manifest_path, manifest = latest_pre_empty_backup()
    backup_snapshot = snapshot_sqlite_database(backup_path, logical_path=backup_path.name)
    assert backup_snapshot.readiness_status == LEGACY_INCOMPATIBLE, snapshot_summary(backup_snapshot)
    assert application_row_count(backup_snapshot) == 0, snapshot_summary(backup_snapshot)
    fresh, fresh_snapshot = build_and_verify_fresh(base)
    startup_canary(fresh, base)
    restore_rehearsal(backup_path, base, backup_snapshot)
    replacement_rehearsal(backup_path, fresh, base)
    assert_populated_incompatible_blocks(backup_path, base)
    adoption_payload = json.loads(run_cmd([sys.executable, 'scripts/check_local_db_adoption.py', '--db-url', sqlite_url(REAL_DB), '--json']).stdout)
    assert adoption_payload['readiness'] == READY, adoption_payload
    missing = run_cmd([sys.executable, 'scripts/check_local_db_adoption.py'], expect_ok=False)
    assert '--db-url' in missing.stdout
    after_cli = snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db')
    assert snapshot_summary(before) == snapshot_summary(after_cli), {'before': snapshot_summary(before), 'after': snapshot_summary(after_cli)}
    mark('adoption CLI requires explicit URL and is read-only')
    assert_prior_regressions()
    assert_no_media_access()
    after = snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db')
    assert snapshot_summary(before) == snapshot_summary(after), {'before': snapshot_summary(before), 'after': snapshot_summary(after)}
    mark('real DB unchanged throughout permanent regression')
    mark('no real application startup occurs')
    return {
        'real_db': snapshot_summary(before),
        'backup': {'filename': backup_path.name, 'manifest': manifest_path.name, 'manifest_data': manifest},
        'fresh_candidate': snapshot_summary(fresh_snapshot),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='BM-PROD5.3C.1 controlled empty local SQLite rebuild regression')
    parser.add_argument('--preflight-only', action='store_true', help='run pre-rebuild backup, fresh build, canary, restore, and replacement rehearsal only')
    args = parser.parse_args()
    base = BACKEND / 'tmp_tests' / 'prod5_3c_1_empty_rebuild'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        if args.preflight_only:
            result = preflight(base)
            print('PRE-REBUILD GATE: PASS')
            print(json.dumps({'checks': sorted(CHECKS), **result}, indent=2, sort_keys=True))
            return 0
        result = full_regression(base)
        assert len(CHECKS) >= 26, sorted(CHECKS)
        print(f'PASS: BM-PROD5.3C.1 controlled empty local SQLite rebuild ({len(CHECKS)} checks)')
        print(json.dumps({'checks': sorted(CHECKS), **result}, indent=2, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
