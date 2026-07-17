from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from .migration_contract import APP_TABLES, SchemaIssue, compare_schema

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALEMBIC_INI = BACKEND_ROOT / 'alembic.ini'

READY = 'ready'
UNINITIALIZED = 'uninitialized'
LEGACY_UNVERSIONED = 'legacy_unversioned'
REVISION_BEHIND = 'revision_behind'
REVISION_UNKNOWN = 'revision_unknown'
SCHEMA_DRIFT = 'schema_drift'
DATABASE_UNREACHABLE = 'database_unreachable'


@dataclass(frozen=True)
class DatabaseReadiness:
    status: str
    ready: bool
    current_revision: str | None
    head_revision: str
    schema_issue_count: int
    schema_issues: tuple[SchemaIssue, ...]
    message: str

    def as_dict(self, *, issue_limit: int = 10) -> dict[str, Any]:
        return {
            'status': self.status,
            'ready': self.ready,
            'current_revision': self.current_revision,
            'head_revision': self.head_revision,
            'schema_issue_count': self.schema_issue_count,
            'schema_issues': [issue.as_dict() for issue in self.schema_issues[:issue_limit]],
            'message': self.message,
        }


class DatabaseNotReadyError(RuntimeError):
    def __init__(self, readiness: DatabaseReadiness):
        self.readiness = readiness
        super().__init__(readiness.message)


def _config(path: Path | None = None) -> Config:
    resolved = path or DEFAULT_ALEMBIC_INI
    config = Config(str(resolved))
    config.set_main_option('script_location', str(resolved.resolve().parent / 'migrations'))
    return config


def migration_head(path: Path | None = None) -> str:
    script = ScriptDirectory.from_config(_config(path))
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError('BM Radio migration history must have exactly one head')
    return heads[0]


def _known_revisions(path: Path | None = None) -> set[str]:
    script = ScriptDirectory.from_config(_config(path))
    return {revision.revision for revision in script.walk_revisions()}


def _safe_unreachable(head: str) -> DatabaseReadiness:
    return DatabaseReadiness(
        status=DATABASE_UNREACHABLE,
        ready=False,
        current_revision=None,
        head_revision=head,
        schema_issue_count=0,
        schema_issues=(),
        message='BM Radio database is unreachable. Verify the configured database target before starting the API.',
    )


def inspect_database_readiness(engine: Engine, *, alembic_ini_path: Path | None = None) -> DatabaseReadiness:
    resolved_ini = alembic_ini_path or DEFAULT_ALEMBIC_INI
    head = migration_head(resolved_ini)
    known_revisions = _known_revisions(resolved_ini)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
            tables = set(inspect(connection).get_table_names())
            app_tables_present = bool(tables & set(APP_TABLES))
            issues = tuple(compare_schema(engine))
    except Exception:
        return _safe_unreachable(head)

    if current is None:
        if not app_tables_present:
            return DatabaseReadiness(
                status=UNINITIALIZED,
                ready=False,
                current_revision=None,
                head_revision=head,
                schema_issue_count=len(issues),
                schema_issues=issues,
                message='BM Radio database is not initialized. Run the explicit Alembic upgrade command before starting the API.',
            )
        if not issues:
            message = 'BM Radio database has a compatible legacy schema but no Alembic revision. Run compatibility verification and the explicit adoption/stamp procedure.'
        else:
            message = 'BM Radio database is unversioned and does not match the required schema. Run the read-only compatibility check before any adoption attempt.'
        return DatabaseReadiness(
            status=LEGACY_UNVERSIONED,
            ready=False,
            current_revision=None,
            head_revision=head,
            schema_issue_count=len(issues),
            schema_issues=issues,
            message=message,
        )

    if current not in known_revisions:
        return DatabaseReadiness(
            status=REVISION_UNKNOWN,
            ready=False,
            current_revision=current,
            head_revision=head,
            schema_issue_count=len(issues),
            schema_issues=issues,
            message='BM Radio database revision is not present in the committed migration history. Stop and review the database before starting the API.',
        )

    if current != head:
        return DatabaseReadiness(
            status=REVISION_BEHIND,
            ready=False,
            current_revision=current,
            head_revision=head,
            schema_issue_count=len(issues),
            schema_issues=issues,
            message=f'BM Radio database revision {current} is behind required head {head}. Run an explicit migration upgrade.',
        )

    if issues:
        return DatabaseReadiness(
            status=SCHEMA_DRIFT,
            ready=False,
            current_revision=current,
            head_revision=head,
            schema_issue_count=len(issues),
            schema_issues=issues,
            message='BM Radio database is at migration head but its schema is incompatible. Run the read-only compatibility check and repair through a reviewed migration.',
        )

    return DatabaseReadiness(
        status=READY,
        ready=True,
        current_revision=current,
        head_revision=head,
        schema_issue_count=0,
        schema_issues=(),
        message='BM Radio database is ready.',
    )


def assert_database_ready(engine: Engine, *, alembic_ini_path: Path | None = None) -> DatabaseReadiness:
    readiness = inspect_database_readiness(engine, alembic_ini_path=alembic_ini_path)
    if not readiness.ready:
        raise DatabaseNotReadyError(readiness)
    return readiness
