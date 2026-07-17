from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Callable

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database_readiness import (
    DATABASE_UNREACHABLE,
    LEGACY_UNVERSIONED,
    READY,
    REVISION_BEHIND,
    REVISION_UNKNOWN,
    SCHEMA_DRIFT,
    UNINITIALIZED,
    inspect_database_readiness,
)
from app.migration_contract import BASELINE_REVISION, compare_schema, create_legacy_current_schema, engine_for_url

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[0]
REAL_DB = BACKEND / 'bm_radio.db'
CHECKS: set[str] = set()


def mark(name: str) -> None:
    CHECKS.add(name)


def sqlite_url(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    return f'sqlite:///{path.resolve().as_posix()}'


def run_cmd(args: list[str], *, expect_ok: bool = True, env: dict[str, str] | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=BACKEND, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env)
    if expect_ok and result.returncode != 0:
        raise AssertionError(f'command failed {args}:\n{result.stdout}')
    if not expect_ok and result.returncode == 0:
        raise AssertionError(f'command unexpectedly passed {args}:\n{result.stdout}')
    return result


def alembic_cmd(*args: str, db_url: str, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    return run_cmd([sys.executable, '-m', 'alembic', '-x', f'db_url={db_url}', *args], expect_ok=expect_ok)


def real_db_state() -> dict[str, Any]:
    conn = sqlite3.connect(f'file:{REAL_DB.resolve().as_posix()}?mode=ro', uri=True)
    try:
        tables = [row[0] for row in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        counts = {table: int(conn.execute(f'select count(*) from "{table}"').fetchone()[0] or 0) for table in tables}
        return {'tables': tables, 'total_rows': sum(counts.values()), 'counts': counts, 'has_alembic_version': 'alembic_version' in tables}
    finally:
        conn.close()


def assert_real_db_expected(state: dict[str, Any]) -> None:
    assert len(state['tables']) == 13, state
    assert state['total_rows'] == 0, state
    assert state['has_alembic_version'] is False, state


def sqlite_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    conn = sqlite3.connect(path)
    try:
        tables = [row[0] for row in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        return {table: int(conn.execute(f'select count(*) from "{table}"').fetchone()[0] or 0) for table in tables}
    finally:
        conn.close()


def create_fresh_db(path: Path) -> str:
    if path.exists():
        path.unlink()
    url = sqlite_url(path)
    alembic_cmd('upgrade', 'head', db_url=url)
    return url


def create_legacy_db(path: Path) -> str:
    if path.exists():
        path.unlink()
    url = sqlite_url(path)
    engine = engine_for_url(url)
    try:
        create_legacy_current_schema(engine)
        with engine.begin() as conn:
            conn.execute(text("insert into tracks (id, path, relative_path, title, artist, library_availability) values (1, 'tmp/music/song.flac', 'tmp/music/song.flac', 'Legacy Song', 'Legacy Artist', 'available')"))
            conn.execute(text("insert into music_releases (id, identity_key, normalized_album_artist, normalized_title, release_type) values (1, 'rel', 'legacy artist', 'legacy album', 'unknown')"))
            conn.execute(text("insert into music_editions (id, identity_key, release_id, source_scope, source_format_family) values (1, 'ed', 1, 'legacy-scope', 'UNKNOWN')"))
            conn.execute(text("insert into music_recordings (id, identity_key, normalized_artist, normalized_title, recording_type, duration_bucket) values (1, 'rec', 'legacy artist', 'legacy song', 'unknown', '')"))
            conn.execute(text("insert into music_track_identities (id, track_id, edition_id, recording_id) values (1, 1, 1, 1)"))
    finally:
        engine.dispose()
    return url


def profile_counts(path: Path) -> dict[str, int]:
    counts = sqlite_counts(path)
    return {'artist_radio_profiles': counts.get('artist_radio_profiles', 0), 'album_radio_profiles': counts.get('album_radio_profiles', 0)}


def startup_probe(db_url: str, *, alembic_ini: Path | None = None, expect_ok: bool = True) -> dict[str, Any]:
    env = os.environ.copy()
    env['BM_RADIO_DB_URL'] = db_url
    if alembic_ini is not None:
        env['BM_TEST_ALEMBIC_INI'] = str(alembic_ini)
    code = r'''
import asyncio
import json
import os
import sys
from pathlib import Path

try:
    override = os.environ.get('BM_TEST_ALEMBIC_INI')
    if override:
        import app.database_readiness as readiness_module
        readiness_module.DEFAULT_ALEMBIC_INI = Path(override)
    import app.main as main
    from app import db

    async def run_startup():
        async with main.app.router.lifespan_context(main.app):
            counts = {}
            with db.engine.connect() as conn:
                tables = [row[0] for row in conn.exec_driver_sql("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
                for table in tables:
                    counts[table] = int(conn.exec_driver_sql(f'select count(*) from "{table}"').scalar() or 0)
            return {'ok': True, 'readiness': main.app.state.database_readiness.as_dict(), 'counts': counts}

    payload = asyncio.run(run_startup())
    print(json.dumps(payload, sort_keys=True))
    raise SystemExit(0)
except Exception as exc:
    readiness = getattr(exc, 'readiness', None)
    payload = {'ok': False, 'type': type(exc).__name__, 'message': str(exc)}
    if readiness is not None:
        payload['readiness'] = readiness.as_dict()
    print(json.dumps(payload, sort_keys=True))
    raise SystemExit(3)
'''
    result = run_cmd([sys.executable, '-c', code], expect_ok=expect_ok, env=env)
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload['ok'] is expect_ok, payload
    return payload


def import_probe(db_url: str, path: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env['BM_RADIO_DB_URL'] = db_url
    env['BM_IMPORT_PROBE_PATH'] = str(path)
    code = r'''
import json
import os
from pathlib import Path
import app.main
path = Path(os.environ['BM_IMPORT_PROBE_PATH'])
print(json.dumps({'exists': path.exists(), 'size': path.stat().st_size if path.exists() else 0}))
'''
    result = run_cmd([sys.executable, '-c', code], env=env)
    return json.loads(result.stdout.strip().splitlines()[-1])


def rewrite_sqlite_table(path: Path, table: str, transform: Callable[[str], str]) -> None:
    conn = sqlite3.connect(path)
    old_table = f'_{table}_old_for_prod5_3b'
    try:
        original = conn.execute("select sql from sqlite_master where type='table' and name=?", (table,)).fetchone()
        if not original:
            raise AssertionError(f'table not found: {table}')
        table_sql = original[0]
        index_sql = [row[0] for row in conn.execute("select sql from sqlite_master where type='index' and tbl_name=? and sql is not null order by name", (table,))]
        columns = [row[1] for row in conn.execute(f'pragma table_info("{table}")')]
        new_sql = transform(table_sql)
        if new_sql == table_sql:
            raise AssertionError(f'transform did not change {table}')
        quoted_columns = ', '.join(f'"{column}"' for column in columns)
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute(f'drop table if exists "{old_table}"')
        conn.execute(f'alter table "{table}" rename to "{old_table}"')
        conn.execute(new_sql)
        conn.execute(f'insert into "{table}" ({quoted_columns}) select {quoted_columns} from "{old_table}"')
        conn.execute(f'drop table "{old_table}"')
        for statement in index_sql:
            conn.execute(statement)
        conn.execute('PRAGMA foreign_keys=ON')
        conn.commit()
    finally:
        conn.close()


def replace_once(sql: str, pattern: str, replacement: str) -> str:
    updated, count = re.subn(pattern, replacement, sql, count=1)
    if count != 1:
        raise AssertionError(f'pattern not found: {pattern}\n{sql}')
    return updated


def create_behind_alembic_config(base: Path) -> Path:
    root = base / 'behind_history'
    versions = root / 'migrations' / 'versions'
    versions.mkdir(parents=True, exist_ok=True)
    (root / 'alembic.ini').write_text('[alembic]\nscript_location = migrations\n', encoding='utf-8')
    (root / 'migrations' / 'script.py.mako').write_text('', encoding='utf-8')
    (versions / '0001_old.py').write_text("revision = 'old_revision'\ndown_revision = None\n", encoding='utf-8')
    (versions / '0002_new.py').write_text("revision = 'new_revision'\ndown_revision = 'old_revision'\n", encoding='utf-8')
    return root / 'alembic.ini'


def set_revision(path: Path, revision: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute('update alembic_version set version_num=?', (revision,))
        conn.commit()
    finally:
        conn.close()


def assert_static_startup_policy() -> None:
    source = (BACKEND / 'app' / 'main.py').read_text(encoding='utf-8')
    forbidden = ['Base.metadata.create_all', 'ensure_manifest_ingestion_columns', 'ensure_scan_reconciliation_columns', 'ensure_playback_identity_columns', 'ensure_recording_feedback_columns', 'ensure_performance_indexes', 'alembic.command', 'subprocess', '.upgrade(', '.stamp(', '.downgrade(']
    assert not any(token in source for token in forbidden), source
    assert 'assert_database_ready' in source
    assert source.index('assert_database_ready') < source.index('seed_default_radio_profiles')
    mark('startup no longer calls create_all')
    mark('startup no longer calls schema-maintenance helpers')
    mark('startup no longer creates performance indexes')
    mark('startup never runs Alembic automatically')
    mark('profile seeding occurs only after readiness')


def assert_import_safety(base: Path) -> None:
    path = base / 'import_only.db'
    payload = import_probe(sqlite_url(path), path)
    assert payload == {'exists': False, 'size': 0}, payload
    mark('importing app.main is mutation-free')


def assert_layout() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / 'alembic.ini')))
    assert script.get_heads() == [BASELINE_REVISION], script.get_heads()
    mark('one migration head remains')


def assert_fresh_startup(base: Path) -> None:
    path = base / 'fresh.db'
    url = create_fresh_db(path)
    before = sqlite_counts(path)
    payload = startup_probe(url)
    assert payload['readiness']['status'] == READY, payload
    after_first = sqlite_counts(path)
    assert after_first['artist_radio_profiles'] > before.get('artist_radio_profiles', 0)
    assert after_first['album_radio_profiles'] > before.get('album_radio_profiles', 0)
    second = startup_probe(url)
    after_second = sqlite_counts(path)
    assert after_second == after_first, {'first': after_first, 'second': after_second, 'payload': second}
    engine = engine_for_url(url)
    try:
        assert not compare_schema(engine)
    finally:
        engine.dispose()
    mark('fresh migrated DB starts')
    mark('second startup is idempotent')
    mark('profile seeding is idempotent')
    mark('schema remains unchanged after startup')


def assert_empty_fails(base: Path) -> None:
    path = base / 'empty.db'
    payload = startup_probe(sqlite_url(path), expect_ok=False)
    assert payload['readiness']['status'] == UNINITIALIZED, payload
    assert sqlite_counts(path) == {}, sqlite_counts(path)
    mark('empty DB fails closed')
    mark('empty DB remains empty')


def assert_legacy_adoption(base: Path) -> None:
    path = base / 'legacy.db'
    url = create_legacy_db(path)
    before_counts = sqlite_counts(path)
    before_profiles = profile_counts(path)
    payload = startup_probe(url, expect_ok=False)
    assert payload['readiness']['status'] == LEGACY_UNVERSIONED, payload
    assert sqlite_counts(path) == before_counts
    assert profile_counts(path) == before_profiles
    alembic_cmd('stamp', 'head', db_url=url)
    adopted = startup_probe(url)
    assert adopted['readiness']['status'] == READY, adopted
    assert profile_counts(path)['artist_radio_profiles'] > before_profiles['artist_radio_profiles']
    mark('compatible unversioned DB fails closed')
    mark('legacy data remains unchanged before adoption')
    mark('explicit temporary stamp enables startup')


def assert_unknown_revision(base: Path) -> None:
    path = base / 'unknown.db'
    url = create_fresh_db(path)
    set_revision(path, 'unknown_revision')
    before = sqlite_counts(path)
    payload = startup_probe(url, expect_ok=False)
    assert payload['readiness']['status'] == REVISION_UNKNOWN, payload
    assert sqlite_counts(path) == before
    mark('unknown revision fails closed')


def assert_behind_revision(base: Path) -> None:
    path = base / 'behind.db'
    url = create_fresh_db(path)
    set_revision(path, 'old_revision')
    ini = create_behind_alembic_config(base)
    payload = startup_probe(url, alembic_ini=ini, expect_ok=False)
    assert payload['readiness']['status'] == REVISION_BEHIND, payload
    mark('behind revision fails closed')


def assert_drift_at_head(base: Path) -> None:
    path = base / 'drift.db'
    url = create_fresh_db(path)
    rewrite_sqlite_table(path, 'scan_runs', lambda sql: replace_once(sql, r"(\bstatus\b\s+VARCHAR\s+DEFAULT\s+)'running'(\s+NOT NULL)", r"\1'queued'\2"))
    before = sqlite_counts(path)
    payload = startup_probe(url, expect_ok=False)
    assert payload['readiness']['status'] == SCHEMA_DRIFT, payload
    assert profile_counts(path) == {'artist_radio_profiles': 0, 'album_radio_profiles': 0}
    assert sqlite_counts(path) == before
    mark('drift at head fails closed')
    mark('drift failure performs no profile writes')


def assert_unreachable(base: Path) -> None:
    target = base / 'missing-parent-secret-password' / 'db.sqlite'
    shutil.rmtree(target.parent, ignore_errors=True)
    url = f'sqlite:///{target.resolve().as_posix()}'
    engine = engine_for_url(url)
    try:
        readiness = inspect_database_readiness(engine)
    finally:
        engine.dispose()
    assert readiness.status == DATABASE_UNREACHABLE, readiness.as_dict()
    assert 'secret-password' not in readiness.message
    assert str(target) not in readiness.message
    mark('unreachable database fails safely')
    mark('errors exclude credentials and paths')


def assert_readiness_cli(base: Path) -> None:
    path = base / 'cli.db'
    url = create_fresh_db(path)
    before = sqlite_counts(path)
    missing = run_cmd([sys.executable, 'scripts/database_readiness.py'], expect_ok=False)
    assert '--db-url' in missing.stdout
    result = run_cmd([sys.executable, 'scripts/database_readiness.py', '--db-url', url, '--json'])
    payload = json.loads(result.stdout)
    assert payload['status'] == READY and payload['ready'] is True, payload
    assert sqlite_counts(path) == before
    status = run_cmd([sys.executable, 'scripts/migration_status.py', 'check', '--db-url', url])
    assert 'PASS' in status.stdout
    mark('readiness CLI requires explicit URL')
    mark('readiness CLI is read-only')
    mark('migration status and readiness agree')


def assert_prior_regressions() -> None:
    result_53a1 = run_cmd([sys.executable, 'scripts/check_prod5_3a_1_schema_parity_hardening.py'], timeout=240)
    assert 'PASS' in result_53a1.stdout
    result_53a = run_cmd([sys.executable, 'scripts/check_prod5_3a_migration_framework.py'], timeout=240)
    assert 'PASS' in result_53a.stdout
    gate = (ROOT / 'scripts' / 'check_prod0_baseline.py').read_text(encoding='utf-8')
    assert 'check_prod4_2e_benchmark_selected_projection_policy.py' in gate
    mark('BM-PROD5.3A.1 remains passing')
    mark('BM-PROD5.3A remains passing')
    mark('BM-PROD4.2E remains in gate')


def assert_no_media_access() -> None:
    tokens = ['scan_' + 'music(', 'music_' + 'flac_' + 'root', 'music_' + 'mp3_' + 'root', 'audiobooks_' + 'root', 'books_' + 'root']
    for relative in ['app/database_readiness.py', 'app/main.py', 'scripts/database_readiness.py', 'scripts/check_prod5_3b_migration_authoritative_startup.py']:
        source = (BACKEND / relative).read_text(encoding='utf-8').lower()
        assert not any(token in source for token in tokens), relative
    mark('no media access or mutation')


def main() -> int:
    before = real_db_state()
    assert_real_db_expected(before)
    base = BACKEND / 'tmp_tests' / 'prod5_3b_migration_authoritative_startup'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        assert_static_startup_policy()
        assert_import_safety(base)
        assert_layout()
        assert_fresh_startup(base)
        assert_empty_fails(base)
        assert_legacy_adoption(base)
        assert_unknown_revision(base)
        assert_behind_revision(base)
        assert_drift_at_head(base)
        assert_unreachable(base)
        assert_readiness_cli(base)
        assert_prior_regressions()
        assert_no_media_access()
        after = real_db_state()
        assert before == after, {'before': before, 'after': after}
        mark('real bm_radio.db remains unchanged')
        assert len(CHECKS) >= 28, sorted(CHECKS)
        print(f'PASS: BM-PROD5.3B migration-authoritative startup ({len(CHECKS)} checks)')
        print(json.dumps({'real_db_before': before, 'real_db_after': after, 'checks': sorted(CHECKS)}, indent=2, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
