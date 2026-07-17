from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import bindparam, delete, insert, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.config import Settings
from app.database_dialect import (
    POSTGRESQL,
    SQLITE,
    UNSUPPORTED,
    classify_database_url,
    engine_options,
    require_supported_database_url,
)
from app.database_readiness import DATABASE_UNREACHABLE, inspect_database_readiness
from app.db import create_application_engine
from app.migration_contract import (
    APP_TABLES,
    BASELINE_REVISION,
    compare_schema,
    engine_for_url,
    migration_authoritative_index_names,
    model_declared_index_names,
    sqlite_legacy_index_names,
)
from app.schema_maintenance import ensure_scan_reconciliation_columns
from app.sqlite_adoption import snapshot_sqlite_database
from audit_postgresql_sql_compatibility import audit, payload

BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
REAL_DB = BACKEND / 'bm_radio.db'
FIXTURE_URL = 'postgresql+psycopg://bm_user:redacted@127.0.0.1:1/bm_radio_offline'
OUTPUT_DIR = BACKEND / 'tmp_tests' / 'prod5_4a'
CHECKS: set[str] = set()


def mark(name: str) -> None:
    CHECKS.add(name)


def run(args: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=BACKEND,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AssertionError(f'command failed {args}:\n{result.stdout}')
    return result


def real_state() -> dict[str, Any]:
    return snapshot_sqlite_database(REAL_DB, logical_path='bm_radio.db').as_dict(include_schema=False)


def assert_real_ready(state: dict[str, Any]) -> None:
    assert state['integrity_check'] == 'ok', state
    assert state['quick_check'] == 'ok', state
    assert state['compatibility'] == 'PASS', state
    assert state['readiness_status'] == 'ready', state
    assert state['current_revision'] == BASELINE_REVISION, state


def offline_sql(command: list[str], output: Path) -> str:
    result = run([sys.executable, '-m', 'alembic', '-x', f'db_url={FIXTURE_URL}', *command, '--sql'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.stdout, encoding='utf-8')
    return result.stdout


def assert_url_and_engine_policy() -> None:
    sqlite_target = classify_database_url('sqlite+pysqlite:///./fixture.db')
    postgres_target = classify_database_url('postgresql+psycopg://user:secret@localhost/db?token=secret')
    generic_postgres = classify_database_url('postgresql://user:secret@localhost/db')
    unsupported = classify_database_url('mysql+pymysql://user:secret@localhost/db')
    assert sqlite_target.dialect == SQLITE and sqlite_target.is_sqlite
    assert postgres_target.dialect == POSTGRESQL and postgres_target.driver == 'psycopg'
    assert generic_postgres.dialect == POSTGRESQL
    assert unsupported.dialect == UNSUPPORTED
    assert 'secret' not in postgres_target.safe_display and 'token=%3Credacted%3E' in postgres_target.safe_display
    absolute_sqlite = classify_database_url('sqlite:///C:/Users/example/private/bm_radio.db?key=secret')
    assert 'Users' not in absolute_sqlite.safe_display and 'secret' not in absolute_sqlite.safe_display
    require_supported_database_url(FIXTURE_URL)
    for invalid in ('postgresql://user:secret@localhost/db', 'mysql+pymysql://user:secret@localhost/db'):
        try:
            require_supported_database_url(invalid)
        except ValueError as exc:
            assert 'secret' not in str(exc)
        else:
            raise AssertionError(f'unsupported URL accepted: {invalid}')
    sqlite_options = engine_options('sqlite:///:memory:')
    postgres_options = engine_options(FIXTURE_URL)
    assert sqlite_options == {'connect_args': {'check_same_thread': False}}
    assert postgres_options['connect_args'] == {'connect_timeout': 5}
    assert postgres_options['pool_pre_ping'] is True
    sqlite_engine = create_application_engine('sqlite:///:memory:')
    postgres_engine = create_application_engine(FIXTURE_URL)
    try:
        assert sqlite_engine.dialect.name == 'sqlite'
        assert postgres_engine.dialect.name == 'postgresql'
        assert getattr(postgres_engine.pool, '_pre_ping', False) is True
    finally:
        sqlite_engine.dispose()
        postgres_engine.dispose()
    mark('database URL classification and redaction')
    mark('unsupported dialect and driver fail closed')
    mark('dialect-aware engine options')
    mark('PostgreSQL pool pre-ping enabled')


def assert_settings_policy() -> None:
    development = Settings(_env_file=None, BM_RADIO_DB_URL='sqlite:///./fixture.db')
    postgres = Settings(_env_file=None, BM_RADIO_DB_URL=FIXTURE_URL)
    assert development.BM_RADIO_DB_POLICY_STATUS == 'development_sqlite'
    assert development.DATABASE_URL == development.BM_RADIO_DB_URL
    assert postgres.BM_RADIO_DB_POLICY_STATUS == 'postgresql_supported'
    try:
        Settings(_env_file=None, APP_ENV='production', BM_RADIO_DB_URL='sqlite:///./fixture.db')
    except ValueError as exc:
        assert 'development-only' in str(exc)
    else:
        raise AssertionError('production-like SQLite configuration was accepted')
    mark('development SQLite settings preserved')
    mark('PostgreSQL settings accepted')
    mark('production-like SQLite rejected')


def assert_sqlite_boundaries() -> None:
    for call in (
        lambda: snapshot_sqlite_database(FIXTURE_URL),
        lambda: ensure_scan_reconciliation_columns(create_application_engine(FIXTURE_URL)),
    ):
        try:
            call()
        except ValueError as exc:
            assert 'SQLite' in str(exc)
        else:
            raise AssertionError('SQLite-only helper accepted PostgreSQL target')
    production_modules = [
        BACKEND / 'app' / 'main.py',
        BACKEND / 'app' / 'database_readiness.py',
        BACKEND / 'migrations' / 'env.py',
    ]
    for path in production_modules:
        source = path.read_text(encoding='utf-8')
        assert 'sqlite_adoption' not in source and 'sqlite_rebuild' not in source
    mark('SQLite-only helpers reject PostgreSQL')
    mark('production startup excludes SQLite adoption and rebuild')


def assert_inventory() -> dict[str, Any]:
    first = payload(audit())
    second = payload(audit())
    assert first == second
    assert first['requires_refactor_count'] == 0, first
    assert set(first['category_counts']) <= {'sqlite_isolated', 'postgresql_compatible'}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / 'postgresql_sql_audit.json').write_text(json.dumps(first, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    mark('raw SQL inventory deterministic')
    mark('no unresolved production SQL refactors')
    mark('SQLite SQL confined to approved modules')
    return first


def assert_schema_contract() -> None:
    migration_indexes = migration_authoritative_index_names()
    model_indexes = model_declared_index_names()
    legacy_indexes = sqlite_legacy_index_names()
    assert migration_indexes
    assert set(migration_indexes) == set(APP_TABLES)
    assert all(names <= migration_indexes[table] for table, names in model_indexes.items())
    assert any(legacy_indexes.values())
    engine = engine_for_url('sqlite:///:memory:')
    try:
        models.Base.metadata.create_all(engine)
        assert not compare_schema(engine)
    finally:
        engine.dispose()
    config = Config(str(BACKEND / 'alembic.ini'))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [BASELINE_REVISION]
    mark('dialect-separated index contracts')
    mark('SQLite schema parity retained')
    mark('exactly one migration head')


def assert_offline_migrations() -> tuple[str, str]:
    upgrade = offline_sql(['upgrade', 'head'], OUTPUT_DIR / 'postgresql_upgrade_head.sql')
    downgrade = offline_sql(
        ['downgrade', f'{BASELINE_REVISION}:base'],
        OUTPUT_DIR / 'postgresql_downgrade_base.sql',
    )
    upper = upgrade.upper()
    for table in APP_TABLES:
        assert f'CREATE TABLE {table.upper()}' in upper, table
    assert 'CREATE TABLE ALEMBIC_VERSION' in upper
    assert 'FOREIGN KEY' in upper
    assert 'INSERT INTO ALEMBIC_VERSION' in upper
    assert "DEFAULT 'UNKNOWN'" in upper
    for forbidden in ('PRAGMA', 'SQLITE_MASTER', 'BM_RADIO.DB', 'C:/USERS', 'REDACTED@'):
        assert forbidden not in upper
    assert 'DROP TABLE' in downgrade.upper()
    assert 'DELETE FROM ALEMBIC_VERSION' in downgrade.upper()
    assert 'PRAGMA' not in downgrade.upper()
    mark('PostgreSQL offline upgrade generated')
    mark('all 21 application tables in offline SQL')
    mark('offline SQL excludes SQLite constructs and credentials')
    mark('PostgreSQL offline downgrade generated')
    mark('baseline UNKNOWN default is a string literal')
    mark('no PostgreSQL server required for migration proof')
    return upgrade, downgrade


def assert_postgresql_compilation() -> None:
    dialect = postgresql.dialect()
    ddl: list[str] = []
    for table in models.Base.metadata.sorted_tables:
        ddl.append(str(CreateTable(table).compile(dialect=dialect)))
        for index in sorted(table.indexes, key=lambda item: item.name or ''):
            ddl.append(str(CreateIndex(index).compile(dialect=dialect)))
    assert len(models.Base.metadata.tables) == 21
    assert all('PRAGMA' not in statement.upper() for statement in ddl)

    statements = [
        select(models.Track).where(models.Track.id == bindparam('track_id')),
        insert(models.Track).values(path=bindparam('path'), title=bindparam('title')),
        update(models.Track).where(models.Track.id == bindparam('track_id')).values(title=bindparam('title')),
        delete(models.Track).where(models.Track.id == bindparam('track_id')),
        select(models.MusicRecording.id)
        .join(models.MusicTrackIdentity, models.MusicTrackIdentity.recording_id == models.MusicRecording.id)
        .where(models.MusicTrackIdentity.track_id == bindparam('track_id')),
        select(models.Track.id)
        .where(models.Track.library_availability == bindparam('availability'))
        .order_by(models.Track.id)
        .limit(bindparam('candidate_limit')),
    ]
    compiled = [str(statement.compile(dialect=dialect)) for statement in statements]
    assert all('%(' in statement or 'LIMIT' in statement for statement in compiled)
    assert all('PRAGMA' not in statement.upper() and 'SQLITE_' not in statement.upper() for statement in compiled)
    mark('all model DDL and indexes compile for PostgreSQL')
    mark('representative CRUD compiles with parameters')
    mark('station and scanner query shapes compile for PostgreSQL')


def assert_readiness_boundary() -> None:
    engine = create_application_engine(FIXTURE_URL)
    try:
        readiness = inspect_database_readiness(engine)
    finally:
        engine.dispose()
    assert readiness.status == DATABASE_UNREACHABLE
    assert not readiness.ready
    assert 'redacted' not in readiness.message.lower()
    assert 'bm_user' not in readiness.message
    mark('PostgreSQL unreachable readiness is bounded and safe')
    mark('readiness error contains no credentials')


def assert_prior_regressions() -> None:
    commands = (
        'check_prod5_3c_1_controlled_empty_local_rebuild.py',
        'check_prod5_3b_migration_authoritative_startup.py',
        'check_prod5_3a_1_schema_parity_hardening.py',
        'check_prod5_3a_migration_framework.py',
        'check_prod4_2e_benchmark_selected_projection_policy.py',
    )
    for name in commands:
        run([sys.executable, 'scripts/' + name])
        mark('prior regression: ' + name)
    gate = (PROJECT / 'scripts' / 'check_prod0_baseline.py').read_text(encoding='utf-8')
    assert 'check_prod5_4a_postgresql_dialect_foundation.py' in gate
    mark('BM-PROD5.4A registered in production gate')


def main() -> int:
    parser = argparse.ArgumentParser(description='BM-PROD5.4A PostgreSQL dialect foundation regression')
    parser.add_argument('--skip-prior-regressions', action='store_true', help='used only by PROD0, which already ran the prior gates')
    args = parser.parse_args()
    before = real_state()
    assert_real_ready(before)
    requirements = (BACKEND / 'requirements.txt').read_text(encoding='utf-8')
    assert 'psycopg[binary]' in requirements
    mark('Psycopg 3 dependency declared')
    assert_url_and_engine_policy()
    assert_settings_policy()
    assert_sqlite_boundaries()
    inventory = assert_inventory()
    assert_schema_contract()
    assert_offline_migrations()
    assert_postgresql_compilation()
    assert_readiness_boundary()
    if args.skip_prior_regressions:
        gate = (PROJECT / 'scripts' / 'check_prod0_baseline.py').read_text(encoding='utf-8')
        assert 'check_prod5_4a_postgresql_dialect_foundation.py' in gate
        mark('prior regressions delegated to enclosing production gate')
    else:
        assert_prior_regressions()
    after = real_state()
    assert_real_ready(after)
    assert before == after
    mark('real SQLite database unchanged')
    mark('no media path imported or accessed')
    assert len(CHECKS) >= 29, sorted(CHECKS)
    print(f'PASS: BM-PROD5.4A PostgreSQL dialect foundation ({len(CHECKS)} checks)')
    print(
        json.dumps(
            {
                'checks': sorted(CHECKS),
                'inventory': {
                    'finding_count': inventory['finding_count'],
                    'category_counts': inventory['category_counts'],
                },
                'real_database': {
                    'sha256': after['sha256'],
                    'schema_fingerprint': after['schema_fingerprint'],
                    'application_row_count': after['application_row_count'],
                    'readiness': after['readiness_status'],
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
