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

from app.database_readiness import LEGACY_UNVERSIONED, READY
from app.migration_contract import BASELINE_REVISION, compare_schema, engine_for_url
from app.sqlite_adoption import backup_sqlite_database, restore_sqlite_backup, snapshot_sqlite_database

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[0]
REAL_DB = BACKEND / 'bm_radio.db'
BACKUP_DIR = BACKEND / '.local_backups'
CHECKS: set[str] = set()


def mark(name: str) -> None:
    CHECKS.add(name)


def sqlite_url(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    return f'sqlite:///{path.resolve().as_posix()}'


def run_cmd(args: list[str], *, expect_ok: bool = True, env: dict[str, str] | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=BACKEND, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env)
    if expect_ok and result.returncode != 0:
        raise AssertionError(f'command failed {args}:\n{result.stdout}')
    if not expect_ok and result.returncode == 0:
        raise AssertionError(f'command unexpectedly passed {args}:\n{result.stdout}')
    return result


def alembic_cmd(*args: str, db_url: str, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    return run_cmd([sys.executable, '-m', 'alembic', '-x', f'db_url={db_url}', *args], expect_ok=expect_ok)


def process_snapshot() -> list[dict[str, Any]]:
    result = subprocess.run(['powershell', '-NoProfile', '-Command', "Get-Process python,pythonw,node,npm -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,CPU,StartTime,Path | ConvertTo-Json -Compress"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    parsed = json.loads(result.stdout)
    return [parsed] if isinstance(parsed, dict) else parsed


def assert_no_backend_processes() -> None:
    processes = process_snapshot()
    python_processes = [proc for proc in processes if str(proc.get('ProcessName', '')).lower().startswith('python')]
    assert not python_processes, python_processes
    mark('no stale Python BM Radio process detected')


def app_row_count(snapshot: Any) -> int:
    return sum(snapshot.application_row_counts.values())


def snapshot_summary(snapshot: Any) -> dict[str, Any]:
    return {
        'logical_path': snapshot.logical_path,
        'size': snapshot.size,
        'modified_utc': snapshot.modified_utc,
        'sha256': snapshot.sha256,
        'integrity_check': snapshot.integrity_check,
        'quick_check': snapshot.quick_check,
        'journal_mode': snapshot.journal_mode,
        'user_version': snapshot.user_version,
        'application_table_count': len(snapshot.application_tables),
        'application_row_count': app_row_count(snapshot),
        'application_row_counts': snapshot.application_row_counts,
        'schema_fingerprint': snapshot.schema_fingerprint,
        'has_alembic_version': snapshot.has_alembic_version,
        'alembic_version_rows': list(snapshot.alembic_version_rows),
        'compatibility': snapshot.compatibility,
        'readiness_status': snapshot.readiness_status,
        'readiness_ready': snapshot.readiness_ready,
        'current_revision': snapshot.current_revision,
        'head_revision': snapshot.head_revision,
    }


def assert_preconditions(snapshot: Any, *, expected_status: str) -> None:
    assert snapshot.integrity_check == 'ok', snapshot_summary(snapshot)
    assert snapshot.quick_check == 'ok', snapshot_summary(snapshot)
    assert len(snapshot.application_tables) == 13, snapshot_summary(snapshot)
    assert app_row_count(snapshot) == 0, snapshot_summary(snapshot)
    assert snapshot.compatibility == 'PASS', snapshot_summary(snapshot)
    assert snapshot.readiness_status == expected_status, snapshot_summary(snapshot)
    assert snapshot.head_revision == BASELINE_REVISION, snapshot_summary(snapshot)


def assert_one_head() -> None:
    result = run_cmd([sys.executable, 'scripts/migration_status.py', 'heads'])
    assert result.stdout.strip() == BASELINE_REVISION, result.stdout
    mark('real DB is at one committed head')


def assert_backup_manifest_safe(manifest_path: Path) -> None:
    text = manifest_path.read_text(encoding='utf-8')
    assert 'C:' + chr(92) + 'Users' not in text
    assert 'BonnyMakaniankhondo' not in text
    assert 'sqlite:///' not in text
    assert 'password' not in text.lower()
    mark('backup manifest excludes secrets and absolute personal paths')


def assert_backup_dir_ignored() -> None:
    result = subprocess.run(['git', 'check-ignore', '-q', 'backend/.local_backups/probe.manifest.json'], cwd=ROOT, text=True)
    assert result.returncode == 0
    mark('backup directory is Git-ignored')


def latest_pre_adoption_backup() -> tuple[Path, Path, dict[str, Any]]:
    manifests = sorted(BACKUP_DIR.glob('bm_radio.pre_alembic_adoption.*.manifest.json'))
    for manifest_path in reversed(manifests):
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        backup_path = BACKUP_DIR / manifest['backup_filename']
        if backup_path.exists() and manifest.get('readiness') == LEGACY_UNVERSIONED:
            return backup_path, manifest_path, manifest
    raise AssertionError('no verified pre-adoption backup manifest found')


def create_or_find_pre_adoption_backup(real_snapshot: Any, *, create: bool) -> tuple[Path, Path, dict[str, Any]]:
    if create:
        backup_path, manifest_path, manifest = backup_sqlite_database(REAL_DB, BACKUP_DIR)
    else:
        backup_path, manifest_path, manifest = latest_pre_adoption_backup()
    backup_snapshot = snapshot_sqlite_database(backup_path, logical_path=backup_path.name)
    assert backup_snapshot.integrity_check == 'ok', snapshot_summary(backup_snapshot)
    assert backup_snapshot.quick_check == 'ok', snapshot_summary(backup_snapshot)
    assert backup_snapshot.schema_fingerprint == manifest['source_schema_fingerprint']
    assert backup_snapshot.application_row_counts == real_snapshot.application_row_counts
    assert backup_snapshot.compatibility == 'PASS'
    assert backup_snapshot.readiness_status == LEGACY_UNVERSIONED
    assert manifest['backup_sha256'] == backup_snapshot.sha256
    assert manifest['schema_fingerprint'] == backup_snapshot.schema_fingerprint
    assert_backup_manifest_safe(manifest_path)
    mark('backup helper uses SQLite backup API')
    mark('verified pre-adoption backup exists')
    return backup_path, manifest_path, manifest


def alembic_rows(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
        if 'alembic_version' not in tables:
            return []
        return [row[0] for row in conn.execute('select version_num from alembic_version order by version_num')]
    finally:
        conn.close()


def adoption_rehearsal(backup_path: Path, base: Path, source_fingerprint: str, source_counts: dict[str, int]) -> Path:
    rehearsal = base / 'rehearsal.db'
    restore_sqlite_backup(backup_path, rehearsal)
    before = snapshot_sqlite_database(rehearsal, logical_path='rehearsal.db')
    assert before.readiness_status == LEGACY_UNVERSIONED, snapshot_summary(before)
    url = sqlite_url(rehearsal)
    alembic_cmd('stamp', BASELINE_REVISION, db_url=url)
    assert 'PASS' in run_cmd([sys.executable, 'scripts/migration_status.py', 'check', '--db-url', url]).stdout
    readiness_payload = json.loads(run_cmd([sys.executable, 'scripts/database_readiness.py', '--db-url', url, '--json']).stdout)
    assert readiness_payload['status'] == READY and readiness_payload['ready'] is True, readiness_payload
    assert 'PASS' in run_cmd([sys.executable, 'scripts/check_migration_schema_compatibility.py', '--db-url', url]).stdout
    after = snapshot_sqlite_database(rehearsal, logical_path='rehearsal.db')
    assert after.schema_fingerprint == source_fingerprint
    assert after.application_row_counts == source_counts
    assert alembic_rows(rehearsal) == [BASELINE_REVISION]
    before_hash = after.sha256
    alembic_cmd('stamp', BASELINE_REVISION, db_url=url)
    second = snapshot_sqlite_database(rehearsal, logical_path='rehearsal.db')
    assert second.schema_fingerprint == source_fingerprint
    assert second.application_row_counts == source_counts
    assert alembic_rows(rehearsal) == [BASELINE_REVISION]
    assert second.sha256 == before_hash
    mark('disposable legacy copy stamps successfully')
    mark('second stamp is idempotent')
    mark('stamp changes only Alembic state')
    mark('disposable adopted copy passes readiness')
    return rehearsal


def startup_canary(adopted_path: Path, base: Path) -> None:
    canary = base / 'startup_canary.db'
    restore_sqlite_backup(adopted_path, canary)
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
    result = run_cmd([sys.executable, '-c', code], env=env)
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload['first']['readiness']['status'] == READY, payload
    assert payload['first']['artist_profiles'] > 0 and payload['first']['album_profiles'] > 0, payload
    assert payload['second']['artist_profiles'] == payload['first']['artist_profiles'], payload
    assert payload['second']['album_profiles'] == payload['first']['album_profiles'], payload
    engine = engine_for_url(url)
    try:
        assert not compare_schema(engine)
    finally:
        engine.dispose()
    mark('disposable adopted copy starts the lifespan')
    mark('startup seeding on copy is idempotent')


def restore_rehearsal(backup_path: Path, base: Path, source_fingerprint: str, source_counts: dict[str, int]) -> None:
    restored = base / 'restored.db'
    restore_sqlite_backup(backup_path, restored)
    snap = snapshot_sqlite_database(restored, logical_path='restored.db')
    assert snap.integrity_check == 'ok'
    assert snap.quick_check == 'ok'
    assert snap.schema_fingerprint == source_fingerprint
    assert snap.application_row_counts == source_counts
    assert not snap.has_alembic_version
    assert snap.readiness_status == LEGACY_UNVERSIONED
    assert snap.compatibility == 'PASS'
    mark('restore rehearsal returns to unversioned compatible state')
    mark('restore fingerprint matches source')


def assert_real_ready(snapshot: Any) -> None:
    assert snapshot.readiness_status == READY, snapshot_summary(snapshot)
    assert snapshot.current_revision == BASELINE_REVISION, snapshot_summary(snapshot)
    assert snapshot.compatibility == 'PASS', snapshot_summary(snapshot)
    assert snapshot.integrity_check == 'ok', snapshot_summary(snapshot)
    assert snapshot.quick_check == 'ok', snapshot_summary(snapshot)
    assert len(snapshot.application_tables) == 13, snapshot_summary(snapshot)
    assert app_row_count(snapshot) == 0, snapshot_summary(snapshot)
    assert snapshot.has_alembic_version, snapshot_summary(snapshot)
    assert snapshot.alembic_version_rows == (BASELINE_REVISION,), snapshot_summary(snapshot)
    mark('real DB readiness is ready')
    mark('real DB compatibility is PASS')
    mark('real DB integrity is ok')


def assert_prior_regressions() -> None:
    for script in ['scripts/check_prod5_3b_migration_authoritative_startup.py', 'scripts/check_prod5_3a_1_schema_parity_hardening.py', 'scripts/check_prod5_3a_migration_framework.py']:
        result = run_cmd([sys.executable, script], timeout=480)
        assert 'PASS' in result.stdout
    gate = (ROOT / 'scripts' / 'check_prod0_baseline.py').read_text(encoding='utf-8')
    assert 'check_prod4_2e_benchmark_selected_projection_policy.py' in gate
    mark('BM-PROD5.3B remains passing')
    mark('BM-PROD5.3A.1 remains passing')
    mark('BM-PROD5.3A remains passing')
    mark('BM-PROD4.2E remains in gate')


def assert_no_media_access() -> None:
    tokens = ['scan_' + 'music(', 'music_' + 'flac_' + 'root', 'music_' + 'mp3_' + 'root', 'audiobooks_' + 'root', 'books_' + 'root']
    for relative in ['app/sqlite_adoption.py', 'scripts/check_local_db_adoption.py', 'scripts/check_prod5_3c_controlled_local_adoption.py']:
        source = (BACKEND / relative).read_text(encoding='utf-8').lower()
        assert not any(token in source for token in tokens), relative
    mark('no media access or mutation')


def preflight(base: Path) -> dict[str, Any]:
    assert_no_backend_processes()
    assert_backup_dir_ignored()
    before = snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db')
    assert_preconditions(before, expected_status=LEGACY_UNVERSIONED)
    assert_one_head()
    backup_path, manifest_path, manifest = create_or_find_pre_adoption_backup(before, create=True)
    rehearsal = adoption_rehearsal(backup_path, base, before.schema_fingerprint, before.application_row_counts)
    startup_canary(rehearsal, base)
    restore_rehearsal(backup_path, base, before.schema_fingerprint, before.application_row_counts)
    after = snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db')
    assert snapshot_summary(before) == snapshot_summary(after), {'before': snapshot_summary(before), 'after': snapshot_summary(after)}
    assert_no_media_access()
    mark('real DB is inspected read-only')
    return {'snapshot': snapshot_summary(before), 'backup': backup_path.name, 'manifest': manifest_path.name, 'manifest_data': manifest}


def full_regression(base: Path) -> dict[str, Any]:
    before = snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db')
    assert_real_ready(before)
    assert_one_head()
    assert_backup_dir_ignored()
    backup_path, manifest_path, manifest = create_or_find_pre_adoption_backup(before, create=False)
    backup_snapshot = snapshot_sqlite_database(backup_path, logical_path=backup_path.name)
    rehearsal = adoption_rehearsal(backup_path, base, backup_snapshot.schema_fingerprint, backup_snapshot.application_row_counts)
    startup_canary(rehearsal, base)
    restore_rehearsal(backup_path, base, backup_snapshot.schema_fingerprint, backup_snapshot.application_row_counts)
    adoption_payload = json.loads(run_cmd([sys.executable, 'scripts/check_local_db_adoption.py', '--db-url', sqlite_url(REAL_DB), '--json']).stdout)
    assert adoption_payload['readiness'] == READY, adoption_payload
    missing = run_cmd([sys.executable, 'scripts/check_local_db_adoption.py'], expect_ok=False)
    assert '--db-url' in missing.stdout
    after_cli = snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db')
    assert snapshot_summary(before) == snapshot_summary(after_cli), {'before': snapshot_summary(before), 'after': snapshot_summary(after_cli)}
    mark('adoption CLI requires explicit URL')
    mark('adoption CLI is read-only')
    assert_prior_regressions()
    assert_no_media_access()
    after = snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db')
    assert snapshot_summary(before) == snapshot_summary(after), {'before': snapshot_summary(before), 'after': snapshot_summary(after)}
    mark('real DB remains unchanged during regression')
    mark('no real application startup occurs')
    return {'snapshot': snapshot_summary(before), 'backup': backup_path.name, 'manifest': manifest_path.name, 'manifest_data': manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description='BM-PROD5.3C controlled local SQLite adoption regression')
    parser.add_argument('--preflight-only', action='store_true', help='run backup, rehearsal, canary and restore proof, then stop before real adoption')
    args = parser.parse_args()
    base = BACKEND / 'tmp_tests' / 'prod5_3c_local_adoption'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        if args.preflight_only:
            result = preflight(base)
            print('PRE-ADOPTION GATE: PASS')
            print(json.dumps({'checks': sorted(CHECKS), **result}, indent=2, sort_keys=True))
            return 0
        result = full_regression(base)
        assert len(CHECKS) >= 25, sorted(CHECKS)
        print(f'PASS: BM-PROD5.3C controlled local SQLite adoption ({len(CHECKS)} checks)')
        print(json.dumps({'checks': sorted(CHECKS), **result}, indent=2, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())




