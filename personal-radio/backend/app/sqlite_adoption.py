from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database_readiness import inspect_database_readiness
from .database_dialect import require_sqlite_path
from .migration_contract import APP_TABLES, SchemaIssue, compare_schema, engine_for_url, read_only_sqlite_url_for_path

BACKUP_DIR_NAME = '.local_backups'


@dataclass(frozen=True)
class SqliteSnapshot:
    logical_path: str
    size: int
    modified_utc: str
    sha256: str
    integrity_check: str
    quick_check: str
    journal_mode: str
    user_version: int
    application_tables: tuple[str, ...]
    application_row_counts: dict[str, int]
    table_sql: dict[str, str]
    index_sql: dict[str, str]
    foreign_keys: dict[str, tuple[dict[str, Any], ...]]
    table_info: dict[str, tuple[dict[str, Any], ...]]
    schema_fingerprint: str
    has_alembic_version: bool
    alembic_version_rows: tuple[str, ...]
    compatibility: str
    compatibility_issues: tuple[SchemaIssue, ...]
    readiness_status: str
    readiness_ready: bool
    current_revision: str | None
    head_revision: str

    def as_dict(self, *, include_schema: bool = True, issue_limit: int = 20) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'logical_path': self.logical_path,
            'size': self.size,
            'modified_utc': self.modified_utc,
            'sha256': self.sha256,
            'integrity_check': self.integrity_check,
            'quick_check': self.quick_check,
            'journal_mode': self.journal_mode,
            'user_version': self.user_version,
            'application_tables': list(self.application_tables),
            'application_row_counts': self.application_row_counts,
            'application_row_count': application_row_count(self),
            'schema_fingerprint': self.schema_fingerprint,
            'has_alembic_version': self.has_alembic_version,
            'alembic_version_rows': list(self.alembic_version_rows),
            'compatibility': self.compatibility,
            'compatibility_issue_count': len(self.compatibility_issues),
            'compatibility_issue_summary': compatibility_issue_summary(self.compatibility_issues),
            'compatibility_issues': [issue.as_dict() for issue in self.compatibility_issues[:issue_limit]],
            'readiness_status': self.readiness_status,
            'readiness_ready': self.readiness_ready,
            'current_revision': self.current_revision,
            'head_revision': self.head_revision,
        }
        if include_schema:
            payload.update(
                {
                    'table_sql': self.table_sql,
                    'index_sql': self.index_sql,
                    'foreign_keys': self.foreign_keys,
                    'table_info': self.table_info,
                }
            )
        return payload


def application_row_count(snapshot: SqliteSnapshot) -> int:
    return sum(snapshot.application_row_counts.values())


def compatibility_issue_summary(issues: tuple[SchemaIssue, ...] | list[SchemaIssue]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for issue in issues:
        summary[issue.category] = summary.get(issue.category, 0) + 1
    return dict(sorted(summary.items()))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _connect(path: Path, *, read_only: bool = True) -> sqlite3.Connection:
    path = require_sqlite_path(path)
    if read_only:
        return sqlite3.connect(f'file:{path.resolve().as_posix()}?mode=ro', uri=True)
    return sqlite3.connect(path)


def application_tables(conn: sqlite3.Connection) -> tuple[str, ...]:
    tables = [row[0] for row in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
    return tuple(table for table in tables if table in APP_TABLES)


def _table_info(conn: sqlite3.Connection, table: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            'cid': int(row[0]),
            'name': row[1],
            'type': row[2],
            'notnull': int(row[3]),
            'default': row[4],
            'pk': int(row[5]),
        }
        for row in conn.execute(f'pragma table_info("{table}")')
    )


def _foreign_keys(conn: sqlite3.Connection, table: str) -> tuple[dict[str, Any], ...]:
    rows = []
    for row in conn.execute(f'pragma foreign_key_list("{table}")'):
        rows.append(
            {
                'id': int(row[0]),
                'seq': int(row[1]),
                'table': row[2],
                'from': row[3],
                'to': row[4],
                'on_update': row[5],
                'on_delete': row[6],
                'match': row[7],
            }
        )
    return tuple(rows)


def schema_payload(path: Path) -> dict[str, Any]:
    path = require_sqlite_path(path)
    conn = _connect(path)
    try:
        app_tables = application_tables(conn)
        table_sql = {
            table: conn.execute("select sql from sqlite_master where type='table' and name=?", (table,)).fetchone()[0]
            for table in app_tables
        }
        if app_tables:
            placeholders = ','.join('?' for _ in app_tables)
            index_sql = {
                row[0]: row[1]
                for row in conn.execute(
                    f"select name, sql from sqlite_master where type='index' and name not like 'sqlite_%' and tbl_name in ({placeholders}) and sql is not null order by name",
                    app_tables,
                )
            }
        else:
            index_sql = {}
        return {
            'application_tables': app_tables,
            'table_sql': table_sql,
            'index_sql': index_sql,
            'foreign_keys': {table: _foreign_keys(conn, table) for table in app_tables},
            'table_info': {table: _table_info(conn, table) for table in app_tables},
        }
    finally:
        conn.close()


def schema_fingerprint(path: Path) -> str:
    return hashlib.sha256(_canonical_json(schema_payload(path)).encode('utf-8')).hexdigest()


def snapshot_sqlite_database(path: Path, *, logical_path: str = '<redacted>') -> SqliteSnapshot:
    path = require_sqlite_path(path)
    stat = path.stat()
    conn = _connect(path)
    try:
        app_tables = application_tables(conn)
        row_counts = {table: int(conn.execute(f'select count(*) from "{table}"').fetchone()[0] or 0) for table in app_tables}
        integrity = str(conn.execute('pragma integrity_check').fetchone()[0])
        quick = str(conn.execute('pragma quick_check').fetchone()[0])
        journal = str(conn.execute('pragma journal_mode').fetchone()[0])
        user_version = int(conn.execute('pragma user_version').fetchone()[0])
        table_sql = {
            table: conn.execute("select sql from sqlite_master where type='table' and name=?", (table,)).fetchone()[0]
            for table in app_tables
        }
        if app_tables:
            placeholders = ','.join('?' for _ in app_tables)
            index_sql = {
                row[0]: row[1]
                for row in conn.execute(
                    f"select name, sql from sqlite_master where type='index' and name not like 'sqlite_%' and tbl_name in ({placeholders}) and sql is not null order by name",
                    app_tables,
                )
            }
        else:
            index_sql = {}
        all_tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
        has_alembic = 'alembic_version' in all_tables
        alembic_rows = tuple(row[0] for row in conn.execute('select version_num from alembic_version order by version_num')) if has_alembic else ()
    finally:
        conn.close()

    engine = engine_for_url(read_only_sqlite_url_for_path(path))
    try:
        issues = tuple(compare_schema(engine))
        readiness = inspect_database_readiness(engine)
    finally:
        engine.dispose()

    payload = schema_payload(path)
    return SqliteSnapshot(
        logical_path=logical_path,
        size=stat.st_size,
        modified_utc=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        sha256=sha256_file(path),
        integrity_check=integrity,
        quick_check=quick,
        journal_mode=journal,
        user_version=user_version,
        application_tables=app_tables,
        application_row_counts=row_counts,
        table_sql=table_sql,
        index_sql=index_sql,
        foreign_keys=payload['foreign_keys'],
        table_info=payload['table_info'],
        schema_fingerprint=hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest(),
        has_alembic_version=has_alembic,
        alembic_version_rows=alembic_rows,
        compatibility='PASS' if not issues else 'FAIL',
        compatibility_issues=issues,
        readiness_status=readiness.status,
        readiness_ready=readiness.ready,
        current_revision=readiness.current_revision,
        head_revision=readiness.head_revision,
    )


def backup_sqlite_database(
    source: Path,
    backup_dir: Path,
    *,
    created_utc: datetime | None = None,
    label: str = 'pre_alembic_adoption',
) -> tuple[Path, Path, dict[str, Any]]:
    source = require_sqlite_path(source)
    created = created_utc or datetime.now(timezone.utc)
    stamp = created.strftime('%Y%m%dT%H%M%SZ')
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_label = ''.join(char if char.isalnum() or char in {'_', '-'} else '_' for char in label)
    backup_path = backup_dir / f'bm_radio.{safe_label}.{stamp}.db'
    manifest_path = backup_dir / f'bm_radio.{safe_label}.{stamp}.manifest.json'
    if backup_path.exists() or manifest_path.exists():
        raise FileExistsError(f'backup already exists for timestamp {stamp}')

    source_conn = _connect(source)
    dest_conn = sqlite3.connect(backup_path)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    source_snapshot = snapshot_sqlite_database(source, logical_path='bm_radio.db')
    backup_snapshot = snapshot_sqlite_database(backup_path, logical_path=backup_path.name)
    manifest = {
        'logical_source_path': 'personal-radio/backend/bm_radio.db',
        'backup_filename': backup_path.name,
        'backup_label': safe_label,
        'created_utc': created.isoformat(),
        'source_sha256': source_snapshot.sha256,
        'backup_sha256': backup_snapshot.sha256,
        'source_size': source_snapshot.size,
        'backup_size': backup_snapshot.size,
        'integrity_check': backup_snapshot.integrity_check,
        'quick_check': backup_snapshot.quick_check,
        'application_row_counts': backup_snapshot.application_row_counts,
        'application_row_count': application_row_count(backup_snapshot),
        'schema_fingerprint': backup_snapshot.schema_fingerprint,
        'source_schema_fingerprint': source_snapshot.schema_fingerprint,
        'compatibility': backup_snapshot.compatibility,
        'compatibility_issue_summary': compatibility_issue_summary(backup_snapshot.compatibility_issues),
        'compatibility_issue_count': len(backup_snapshot.compatibility_issues),
        'readiness': backup_snapshot.readiness_status,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return backup_path, manifest_path, manifest


def restore_sqlite_backup(source: Path, destination: Path) -> None:
    source = require_sqlite_path(source)
    destination = require_sqlite_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    source_conn = _connect(source)
    dest_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()
