from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.migration_contract import (
    APP_TABLES,
    BASELINE_REVISION,
    assert_schema_compatible,
    compare_schema,
    create_legacy_current_schema,
    engine_for_url,
    expected_check_constraints,
    expected_foreign_keys,
    expected_index_names,
    expected_unique_constraints,
    row_counts,
)

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[0]
REAL_DB = BACKEND / 'bm_radio.db'
CHECKS: set[str] = set()


def mark(name: str) -> None:
    CHECKS.add(name)


def sqlite_url(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.resolve().as_posix()}"


def run_cmd(args: list[str], *, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=BACKEND, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    if expect_ok and result.returncode != 0:
        raise AssertionError(f"command failed {args}:\n{result.stdout}")
    if not expect_ok and result.returncode == 0:
        raise AssertionError(f"command unexpectedly passed {args}:\n{result.stdout}")
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


def current_revision(db_url: str) -> str:
    result = run_cmd([sys.executable, 'scripts/migration_status.py', 'current', '--db-url', db_url])
    return result.stdout.strip()


def assert_layout() -> None:
    for path in [
        'alembic.ini',
        'migrations/env.py',
        'migrations/script.py.mako',
        'migrations/README.md',
        'migrations/versions/0001_current_schema_baseline.py',
    ]:
        assert (BACKEND / path).exists(), path
    script = ScriptDirectory.from_config(Config(str(BACKEND / 'alembic.ini')))
    assert script.get_heads() == [BASELINE_REVISION], script.get_heads()
    assert len(list((BACKEND / 'migrations' / 'versions').glob('*.py'))) == 1
    text_ini = (BACKEND / 'alembic.ini').read_text(encoding='utf-8')
    assert 'bm_radio.db' not in text_ini.lower()
    assert 'sqlite:///./' not in text_ini.lower()
    env_text = (BACKEND / 'migrations' / 'env.py').read_text(encoding='utf-8')
    assert 'models.Base.metadata' in env_text
    assert 'BM_RADIO_DB_URL' in env_text and 'db_url' in env_text
    mark('alembic layout exists')
    mark('exactly one migration head')
    mark('no local default or secret URL in alembic.ini')
    mark('env uses application metadata')


def assert_url_safety() -> None:
    result = alembic_cmd('upgrade', 'head', expect_ok=False)
    assert 'requires an explicit database URL' in result.stdout
    mark('explicit database URL required')


def assert_fresh_upgrade(base: Path) -> str:
    db_url = sqlite_url(base / 'fresh.db')
    alembic_cmd('upgrade', 'head', db_url=db_url)
    engine = engine_for_url(db_url)
    try:
        assert current_revision(db_url) == BASELINE_REVISION
        assert_schema_compatible(engine)
        counts = row_counts(engine)
        assert counts.get('alembic_version') == 1, counts
        alembic_cmd('upgrade', 'head', db_url=db_url)
        assert current_revision(db_url) == BASELINE_REVISION
        insp = inspect(engine)
        assert set(APP_TABLES).issubset(set(insp.get_table_names()))
        for table, columns in models.Base.metadata.tables.items():
            actual_columns = {row['name'] for row in insp.get_columns(table)}
            assert {column.name for column in columns.columns}.issubset(actual_columns), table
        assert any(expected_foreign_keys().values())
        assert any(expected_unique_constraints().values())
        assert any(expected_check_constraints().values())
        for table, names in expected_index_names().items():
            actual = {row['name'] for row in insp.get_indexes(table)}
            missing = names - actual
            assert not missing, (table, missing)
    finally:
        engine.dispose()
    mark('fresh temporary SQLite upgrade to head')
    mark('second upgrade is idempotent')
    mark('alembic current reports head')
    mark('expected tables and columns exist')
    mark('critical foreign keys and constraints exist')
    mark('required indexes exist')
    return db_url


def assert_downgrade(base: Path) -> None:
    db_url = sqlite_url(base / 'downgrade.db')
    alembic_cmd('upgrade', 'head', db_url=db_url)
    alembic_cmd('downgrade', 'base', db_url=db_url)
    mark('disposable downgrade succeeds')


def insert_representative_rows(engine) -> dict[str, Any]:
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        track = models.Track(
            id=1,
            path='tmp/music/track.flac',
            relative_path='tmp/music/track.flac',
            title='Migration Track',
            artist='Migration Artist',
            album='Migration Album',
            album_artist='Migration Artist',
            genre='Soul',
            primary_genre='Soul',
            library_availability='available',
        )
        release = models.MusicRelease(id=1, identity_key='rel-1', album_artist='Migration Artist', title='Migration Album', normalized_album_artist='migration artist', normalized_title='migration album')
        edition = models.MusicEdition(id=1, identity_key='ed-1', release_id=1, source_scope='tmp/music/track.flac')
        recording = models.MusicRecording(id=1, identity_key='rec-1', artist='Migration Artist', title='Migration Track', normalized_artist='migration artist', normalized_title='migration track')
        identity = models.MusicTrackIdentity(id=1, track_id=1, edition_id=1, recording_id=1)
        audiobook = models.Audiobook(id=1, path='tmp/books/book.m4b', relative_path='tmp/books/book.m4b', title='Migration Book', author='Migration Author', library_availability='available')
        chapter = models.AudiobookChapter(id=1, audiobook_id=1, path='tmp/books/book.m4b', relative_path='tmp/books/book.m4b', title='Chapter 1', sort_order=1, library_availability='available')
        progress = models.AudiobookProgress(id=1, audiobook_id=1, chapter_id=1, position_seconds=12.5, progress_percent=25.0, status='in_progress')
        station = models.Station(id=1, name='Migration Station', type='artist', seed_value='Migration Artist')
        favorite = models.TrackFavorite(id=1, track_id=1, recording_id=1)
        thumb = models.TrackThumb(id=1, track_id=1, recording_id=1, station_id=1, value=models.ThumbValue.up)
        event = models.PlaybackEvent(id=1, track_id=1, recording_id=1, station_id=1, event_type='qualified_play')
        db.add_all([track, release, edition, recording, identity, audiobook, chapter, progress, station, favorite, thumb, event])
        db.commit()
        return {
            'track_path': track.path,
            'recording_key': recording.identity_key,
            'book_title': audiobook.title,
            'progress': progress.progress_percent,
            'thumb': thumb.value.value,
        }
    finally:
        db.close()


def representative_values(engine) -> dict[str, Any]:
    with engine.connect() as conn:
        return {
            'track_path': conn.execute(text('select path from tracks where id=1')).scalar_one(),
            'recording_key': conn.execute(text('select identity_key from music_recordings where id=1')).scalar_one(),
            'book_title': conn.execute(text('select title from audiobooks where id=1')).scalar_one(),
            'progress': float(conn.execute(text('select progress_percent from audiobook_progress where id=1')).scalar_one()),
            'thumb': conn.execute(text('select value from track_thumbs where id=1')).scalar_one(),
        }


def assert_compatibility_and_adoption(base: Path) -> None:
    legacy_url = sqlite_url(base / 'legacy.db')
    engine = engine_for_url(legacy_url)
    try:
        create_legacy_current_schema(engine)
        expected_values = insert_representative_rows(engine)
        before_counts = row_counts(engine)
    finally:
        engine.dispose()

    result = run_cmd([sys.executable, 'scripts/check_migration_schema_compatibility.py', '--db-path', str(base / 'legacy.db')])
    assert 'PASS' in result.stdout
    after_verify = engine_for_url(legacy_url)
    try:
        assert row_counts(after_verify) == before_counts
        assert representative_values(after_verify) == expected_values
    finally:
        after_verify.dispose()

    alembic_cmd('stamp', 'head', db_url=legacy_url)
    alembic_cmd('upgrade', 'head', db_url=legacy_url)
    alembic_cmd('upgrade', 'head', db_url=legacy_url)
    upgraded = engine_for_url(legacy_url)
    try:
        assert row_counts(upgraded) == {**before_counts, 'alembic_version': 1}
        assert representative_values(upgraded) == expected_values
        assert current_revision(legacy_url) == BASELINE_REVISION
        assert_schema_compatible(upgraded)
    finally:
        upgraded.dispose()
    mark('compatibility verifier is read-only')
    mark('compatible legacy schema passes')
    mark('legacy data survives stamp plus upgrade')


def assert_incompatible_fails(base: Path) -> None:
    path = base / 'bad.db'
    conn = sqlite3.connect(path)
    try:
        conn.execute('create table tracks (id integer primary key)')
        conn.commit()
    finally:
        conn.close()
    result = run_cmd([sys.executable, 'scripts/check_migration_schema_compatibility.py', '--db-path', str(path)], expect_ok=False)
    assert 'FAIL' in result.stdout
    mark('incompatible schema fails')


def assert_drift_check(db_url: str) -> None:
    result = run_cmd([sys.executable, 'scripts/migration_status.py', 'check', '--db-url', db_url])
    assert 'PASS' in result.stdout
    engine = engine_for_url(db_url)
    try:
        assert not compare_schema(engine)
    finally:
        engine.dispose()
    mark('model-to-migration drift check passes')


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
    mark('runtime import does not auto-run Alembic')
    mark('startup uses migration-authoritative readiness')


def assert_no_media_access() -> None:
    tokens = [
        'scan_' + 'music(',
        'music_' + 'flac_' + 'root',
        'music_' + 'mp3_' + 'root',
        'audiobooks_' + 'root',
        'books_' + 'root',
    ]
    for path in [BACKEND / 'scripts' / 'check_prod5_3a_migration_framework.py', BACKEND / 'scripts' / 'check_migration_schema_compatibility.py', BACKEND / 'scripts' / 'migration_status.py']:
        source = path.read_text(encoding='utf-8').lower()
        assert not any(token in source for token in tokens), path
    mark('no media access or mutation')


def assert_gate_entries() -> None:
    gate = (ROOT / 'scripts' / 'check_prod0_baseline.py').read_text(encoding='utf-8')
    assert 'check_prod5_3a_migration_framework.py' in gate
    assert 'check_prod4_2e_benchmark_selected_projection_policy.py' in gate
    mark('BM-PROD4.2E regression remains in gate')
    mark('full production gate includes migration regression')


def main() -> int:
    before = real_db_state()
    assert_real_db_expected(before)
    base = BACKEND / 'tmp_tests' / 'prod5_3a_migration_framework'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        assert_layout()
        assert_url_safety()
        fresh_url = assert_fresh_upgrade(base)
        assert_downgrade(base)
        assert_compatibility_and_adoption(base)
        assert_incompatible_fails(base)
        assert_drift_check(fresh_url)
        assert_startup_unchanged()
        assert_no_media_access()
        assert_gate_entries()
        after = real_db_state()
        assert before == after, {'before': before, 'after': after}
        mark('real bm_radio.db remains unchanged')
        assert len(CHECKS) >= 22, sorted(CHECKS)
        print(f'PASS: BM-PROD5.3A migration framework ({len(CHECKS)} checks)')
        print(json.dumps({'real_db_before': before, 'real_db_after': after, 'checks': sorted(CHECKS)}, indent=2, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
