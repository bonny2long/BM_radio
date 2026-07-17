from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Callable

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.migration_contract import (
    BASELINE_REVISION,
    compare_schema,
    create_legacy_current_schema,
    engine_for_url,
    row_counts,
    sqlite_connect_args,
)

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[0]
REAL_DB = BACKEND / 'bm_radio.db'
CHECKS: set[str] = set()


def mark(name: str) -> None:
    CHECKS.add(name)


def sqlite_url(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    return f'sqlite:///{path.resolve().as_posix()}'


def run_cmd(args: list[str], *, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=BACKEND, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    if expect_ok and result.returncode != 0:
        raise AssertionError(f'command failed {args}:\n{result.stdout}')
    if not expect_ok and result.returncode == 0:
        raise AssertionError(f'command unexpectedly passed {args}:\n{result.stdout}')
    return result


def alembic_cmd(*args: str, db_url: str | None = None, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, '-m', 'alembic']
    if db_url is not None:
        command.extend(['-x', f'db_url={db_url}'])
    command.extend(args)
    return run_cmd(command, expect_ok=expect_ok)


def real_db_state() -> dict[str, Any]:
    conn = sqlite3.connect(f'file:{REAL_DB.resolve().as_posix()}?mode=ro', uri=True)
    try:
        tables = [row[0] for row in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        counts = {table: int(conn.execute(f'select count(*) from "{table}"').fetchone()[0] or 0) for table in tables}
        return {'tables': tables, 'total_rows': sum(counts.values()), 'counts': counts, 'has_alembic_version': 'alembic_version' in tables}
    finally:
        conn.close()


def assert_real_db_expected(state: dict[str, Any]) -> None:
    assert isinstance(state.get('tables'), list), state
    assert isinstance(state.get('counts'), dict), state
    assert 'total_rows' in state, state


def create_legacy_db(path: Path) -> str:
    if path.exists():
        path.unlink()
    url = sqlite_url(path)
    engine = engine_for_url(url)
    try:
        create_legacy_current_schema(engine)
    finally:
        engine.dispose()
    return url


def create_fresh_db(path: Path) -> str:
    if path.exists():
        path.unlink()
    url = sqlite_url(path)
    alembic_cmd('upgrade', 'head', db_url=url)
    return url


def assert_compatible(url: str, label: str) -> None:
    engine = engine_for_url(url)
    try:
        issues = compare_schema(engine)
    finally:
        engine.dispose()
    assert not issues, (label, [issue.as_dict() for issue in issues[:20]])


def issue_categories(url: str) -> set[str]:
    engine = engine_for_url(url)
    try:
        return {issue.category for issue in compare_schema(engine)}
    finally:
        engine.dispose()


def rewrite_sqlite_table(path: Path, table: str, transform: Callable[[str], str]) -> None:
    conn = sqlite3.connect(path)
    old_table = f'_{table}_old_for_schema_parity'
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


def run_cli_expect_failure(path: Path, expected_category: str) -> None:
    before = sqlite_counts(path)
    result = run_cmd([sys.executable, 'scripts/check_migration_schema_compatibility.py', '--db-path', str(path), '--json'], expect_ok=False)
    assert expected_category in result.stdout, result.stdout
    assert sqlite_counts(path) == before
    mark('compatibility verifier remains read-only')


def run_cli_expect_pass(path: Path) -> None:
    before = sqlite_counts(path)
    result = run_cmd([sys.executable, 'scripts/check_migration_schema_compatibility.py', '--db-path', str(path), '--json'])
    assert 'PASS' in result.stdout, result.stdout
    assert sqlite_counts(path) == before
    mark('compatibility verifier remains read-only')


def sqlite_counts(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        tables = [row[0] for row in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        return {table: int(conn.execute(f'select count(*) from "{table}"').fetchone()[0] or 0) for table in tables}
    finally:
        conn.close()


def assert_nullability_mismatch_detected(base: Path) -> None:
    path = base / 'nullable_false_to_true.db'
    create_legacy_db(path)
    rewrite_sqlite_table(
        path,
        'scan_runs',
        lambda sql: replace_once(sql, r'(\bmedia_kind\b\s+VARCHAR)\s+NOT NULL', r'\1'),
    )
    url = sqlite_url(path)
    categories = issue_categories(url)
    assert 'incompatible_nullability' in categories, categories
    run_cli_expect_failure(path, 'incompatible_nullability')
    mark('nullable mismatch fixture fails')
    mark('compatibility verifier exposes incompatible_nullability')


def assert_not_null_mismatch_detected(base: Path) -> None:
    path = base / 'nullable_true_to_false.db'
    create_legacy_db(path)
    rewrite_sqlite_table(
        path,
        'tracks',
        lambda sql: replace_once(sql, r'(\btitle\b\s+VARCHAR)(,)', r'\1 NOT NULL\2'),
    )
    categories = issue_categories(sqlite_url(path))
    assert 'incompatible_nullability' in categories, categories
    mark('NOT-NULL mismatch fixture fails')


def assert_missing_default_detected(base: Path) -> None:
    path = base / 'missing_default.db'
    create_legacy_db(path)
    rewrite_sqlite_table(
        path,
        'scan_runs',
        lambda sql: replace_once(sql, r"(\bstatus\b\s+VARCHAR)\s+DEFAULT\s+'running'(\s+NOT NULL)", r'\1\2'),
    )
    categories = issue_categories(sqlite_url(path))
    assert 'incompatible_server_default' in categories, categories
    run_cli_expect_failure(path, 'incompatible_server_default')
    mark('missing required server default fixture fails')


def assert_changed_default_detected(base: Path) -> None:
    path = base / 'changed_default.db'
    create_legacy_db(path)
    rewrite_sqlite_table(
        path,
        'scan_runs',
        lambda sql: replace_once(sql, r"(\bstatus\b\s+VARCHAR\s+DEFAULT\s+)'running'(\s+NOT NULL)", r"\1'queued'\2"),
    )
    categories = issue_categories(sqlite_url(path))
    assert 'incompatible_server_default' in categories, categories
    mark('changed server default fixture fails')


def assert_equivalent_default_passes(base: Path) -> None:
    path = base / 'equivalent_default.db'
    create_legacy_db(path)
    rewrite_sqlite_table(
        path,
        'scan_runs',
        lambda sql: replace_once(sql, r"(\bstatus\b\s+VARCHAR\s+DEFAULT\s+)'running'(\s+NOT NULL)", r"\1('running')\2"),
    )
    assert_compatible(sqlite_url(path), 'equivalent default formatting')
    run_cli_expect_pass(path)
    mark('equivalent SQLite default formatting passes')


def assert_primary_key_noise_normalized(base: Path) -> None:
    url = create_fresh_db(base / 'pk_noise.db')
    engine = engine_for_url(url)
    try:
        column = next(row for row in inspect(engine).get_columns('tracks') if row['name'] == 'id')
        assert column.get('primary_key'), column
        issues = compare_schema(engine)
        assert not [issue for issue in issues if issue.category == 'incompatible_nullability' and issue.detail.startswith('tracks.id:')], [issue.as_dict() for issue in issues]
    finally:
        engine.dispose()
    mark('SQLite primary-key nullability noise is normalized')


def assert_fresh_and_legacy_compatible(base: Path) -> None:
    fresh_url = create_fresh_db(base / 'fresh.db')
    legacy_url = create_legacy_db(base / 'legacy.db')
    assert_compatible(fresh_url, 'fresh')
    assert_compatible(legacy_url, 'legacy')
    result = run_cmd([sys.executable, 'scripts/migration_status.py', 'check', '--db-url', fresh_url])
    assert 'PASS' in result.stdout, result.stdout
    mark('fresh migration schema remains compatible')
    mark('legacy current schema remains compatible')
    mark('model-to-migration drift check passes')


def assert_drift_cases(base: Path) -> None:
    nullable_path = base / 'drift_nullable.db'
    default_path = base / 'drift_default.db'
    create_fresh_db(nullable_path)
    rewrite_sqlite_table(
        nullable_path,
        'scan_runs',
        lambda sql: replace_once(sql, r'(\bmedia_kind\b\s+VARCHAR)\s+NOT NULL', r'\1'),
    )
    assert 'incompatible_nullability' in issue_categories(sqlite_url(nullable_path))
    create_fresh_db(default_path)
    rewrite_sqlite_table(
        default_path,
        'scan_runs',
        lambda sql: replace_once(sql, r"(\bstatus\b\s+VARCHAR\s+DEFAULT\s+)'running'(\s+NOT NULL)", r"\1'queued'\2"),
    )
    assert 'incompatible_server_default' in issue_categories(sqlite_url(default_path))
    mark('model/migration nullability drift is detected')
    mark('model/migration default drift is detected')


def assert_layout_and_safety() -> None:
    script = ScriptDirectory.from_config(Config(str(BACKEND / 'alembic.ini')))
    assert script.get_heads() == [BASELINE_REVISION], script.get_heads()
    env_text = (BACKEND / 'migrations' / 'env.py').read_text(encoding='utf-8')
    assert 'compare_server_default=True' in env_text
    result = alembic_cmd('upgrade', 'head', expect_ok=False)
    assert 'requires an explicit database URL' in result.stdout
    gate = (ROOT / 'scripts' / 'check_prod0_baseline.py').read_text(encoding='utf-8')
    assert 'check_prod5_3a_migration_framework.py' in gate
    assert 'check_prod5_3a_1_schema_parity_hardening.py' in gate
    assert 'check_prod4_2e_benchmark_selected_projection_policy.py' in gate
    mark('exactly one migration head remains')
    mark('explicit URL safety remains')
    mark('Alembic server-default drift comparison is enabled')
    mark('BM-PROD4.2E regression remains in gate')


def assert_no_media_access() -> None:
    tokens = [
        'scan_' + 'music(',
        'music_' + 'flac_' + 'root',
        'music_' + 'mp3_' + 'root',
        'audiobooks_' + 'root',
        'books_' + 'root',
    ]
    for relative in [
        'app/migration_contract.py',
        'scripts/check_prod5_3a_migration_framework.py',
        'scripts/check_prod5_3a_1_schema_parity_hardening.py',
        'scripts/check_migration_schema_compatibility.py',
        'scripts/migration_status.py',
    ]:
        source = (BACKEND / relative).read_text(encoding='utf-8').lower()
        assert not any(token in source for token in tokens), relative
    mark('no media access or mutation')


def assert_startup_unchanged() -> None:
    source = (BACKEND / 'app' / 'main.py').read_text(encoding='utf-8')
    forbidden = [
        'Base.metadata.create_all',
        'ensure_manifest_ingestion_columns',
        'ensure_scan_reconciliation_columns',
        'ensure_playback_identity_columns',
        'ensure_recording_feedback_columns',
        'ensure_performance_indexes',
        'alembic.command',
    ]
    assert not any(token in source for token in forbidden), source
    assert 'assert_database_ready(db.engine)' in source
    assert source.index('assert_database_ready') < source.index('seed_default_radio_profiles')
    mark('startup behavior remains migration-authoritative')


def main() -> int:
    before = real_db_state()
    assert_real_db_expected(before)
    base = BACKEND / 'tmp_tests' / 'prod5_3a_1_schema_parity_hardening'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        assert_layout_and_safety()
        assert_fresh_and_legacy_compatible(base)
        assert_nullability_mismatch_detected(base)
        assert_not_null_mismatch_detected(base)
        assert_missing_default_detected(base)
        assert_changed_default_detected(base)
        assert_equivalent_default_passes(base)
        assert_primary_key_noise_normalized(base)
        assert_drift_cases(base)
        assert_startup_unchanged()
        assert_no_media_access()
        after = real_db_state()
        assert before == after, {'before': before, 'after': after}
        mark('real bm_radio.db remains unchanged')
        assert len(CHECKS) >= 20, sorted(CHECKS)
        print(f'PASS: BM-PROD5.3A.1 schema parity hardening ({len(CHECKS)} checks)')
        print(json.dumps({'real_db_before': before, 'real_db_after': after, 'checks': sorted(CHECKS)}, indent=2, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
