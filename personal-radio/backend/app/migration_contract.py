from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.sql.sqltypes import Boolean, DateTime, Enum, Float, Integer, String, Text

from .database_dialect import engine_options, require_sqlite_path, require_supported_database_url
from . import models
from .perf import INDEX_STATEMENTS as PERFORMANCE_INDEX_STATEMENTS
from .schema_maintenance import (
    PLAYBACK_IDENTITY_INDEXES,
    RECORDING_FEEDBACK_INDEXES,
    SCAN_RECONCILIATION_INDEXES,
    ensure_manifest_ingestion_columns,
    ensure_playback_identity_columns,
    ensure_recording_feedback_columns,
    ensure_scan_reconciliation_columns,
)

BASELINE_REVISION = '0001_current_schema_baseline'
BASELINE_SLUG = 'current_schema_baseline'
APP_TABLES = tuple(models.Base.metadata.tables.keys())
BASELINE_MIGRATION_PATH = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / '0001_current_schema_baseline.py'
RUNTIME_INDEX_STATEMENTS = tuple(
    dict.fromkeys(
        list(SCAN_RECONCILIATION_INDEXES)
        + list(PLAYBACK_IDENTITY_INDEXES)
        + list(RECORDING_FEEDBACK_INDEXES)
        + list(PERFORMANCE_INDEX_STATEMENTS)
    )
)


@dataclass(frozen=True)
class SchemaIssue:
    category: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {'category': self.category, 'detail': self.detail}


@dataclass(frozen=True)
class SchemaDialectPolicy:
    name: str

    @property
    def is_postgresql(self) -> bool:
        return self.name == 'postgresql'


def dialect_policy_for_engine(engine: Engine) -> SchemaDialectPolicy:
    name = engine.dialect.name
    if name not in {'sqlite', 'postgresql'}:
        raise ValueError(f'unsupported schema comparison dialect: {name}')
    return SchemaDialectPolicy(name=name)


def sqlite_connect_args(url: str) -> dict[str, Any]:
    target = require_supported_database_url(url)
    return dict(engine_options(url).get('connect_args', {})) if target.is_sqlite else {}


def engine_for_url(url: str) -> Engine:
    return create_engine(url, **engine_options(url))


def read_only_sqlite_url_for_path(path: Path) -> str:
    path = require_sqlite_path(path)
    resolved = path.resolve().as_posix()
    return f'sqlite:///file:{resolved}?mode=ro&uri=true'


def create_legacy_current_schema(engine: Engine) -> None:
    if engine.dialect.name != 'sqlite':
        raise ValueError('legacy schema construction is SQLite-only')
    models.Base.metadata.create_all(bind=engine)
    ensure_manifest_ingestion_columns(engine)
    ensure_scan_reconciliation_columns(engine)
    ensure_playback_identity_columns(engine)
    ensure_recording_feedback_columns(engine)
    with engine.begin() as conn:
        for statement in PERFORMANCE_INDEX_STATEMENTS:
            conn.execute(text(statement))


def user_tables(engine: Engine) -> list[str]:
    return sorted(name for name in inspect(engine).get_table_names() if not name.startswith('sqlite_'))


def row_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {name: int(conn.execute(text(f'select count(*) from "{name}"')).scalar() or 0) for name in user_tables(engine)}


def _type_affinity(type_: Any) -> str:
    if isinstance(type_, Integer):
        return 'integer'
    if isinstance(type_, Boolean):
        return 'boolean'
    if isinstance(type_, Float):
        return 'float'
    if isinstance(type_, DateTime):
        return 'datetime'
    if isinstance(type_, Text):
        return 'text'
    if isinstance(type_, (String, Enum)):
        return 'string'
    name = type_.__class__.__name__.lower()
    if 'integer' in name:
        return 'integer'
    if 'bool' in name:
        return 'boolean'
    if 'float' in name or 'real' in name or 'numeric' in name:
        return 'float'
    if 'date' in name or 'time' in name:
        return 'datetime'
    if 'text' in name:
        return 'text'
    if 'char' in name or 'clob' in name or 'varchar' in name or 'string' in name:
        return 'string'
    return name


def _strip_outer_parentheses(value: str) -> str:
    value = value.strip()
    while value.startswith('(') and value.endswith(')'):
        depth = 0
        balanced = True
        for index, char in enumerate(value):
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    balanced = False
                    break
        if not balanced or depth != 0:
            break
        value = value[1:-1].strip()
    return value


def normalize_server_default(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    raw = _strip_outer_parentheses(raw)
    raw = re.sub(r'::(?:character varying|varchar|text|timestamp(?: with time zone)?|boolean|integer|bigint)$', '', raw, flags=re.IGNORECASE)
    lowered = raw.lower().replace(' ', '')
    if lowered in {'now()', 'current_timestamp', 'current_timestamp()'}:
        return 'current_timestamp'
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1]
    return raw


def _effective_nullable(column: dict[str, Any]) -> bool:
    if column.get('primary_key'):
        return False
    return bool(column.get('nullable', True))


def _column_contract(*, type_: Any, nullable: bool, primary_key: bool, server_default: Any) -> dict[str, Any]:
    default = normalize_server_default(server_default)
    return {
        'affinity': _type_affinity(type_),
        'nullable': bool(nullable),
        'effective_nullable': False if primary_key else bool(nullable),
        'primary_key': bool(primary_key),
        'has_server_default': server_default is not None,
        'server_default': default,
    }


def expected_columns() -> dict[str, dict[str, dict[str, Any]]]:
    expected: dict[str, dict[str, dict[str, Any]]] = {}
    for table_name, table in models.Base.metadata.tables.items():
        expected[table_name] = {}
        for column in table.columns:
            expected[table_name][column.name] = _column_contract(
                type_=column.type,
                nullable=bool(column.nullable),
                primary_key=bool(column.primary_key),
                server_default=column.server_default.arg if column.server_default is not None else None,
            )
    return expected


def expected_foreign_keys() -> dict[str, set[tuple[tuple[str, ...], str, tuple[str, ...]]]]:
    out: dict[str, set[tuple[tuple[str, ...], str, tuple[str, ...]]]] = {}
    for table_name, table in models.Base.metadata.tables.items():
        values: set[tuple[tuple[str, ...], str, tuple[str, ...]]] = set()
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                columns = tuple(column.name for column in constraint.columns)
                referred_table = constraint.elements[0].column.table.name
                referred_columns = tuple(element.column.name for element in constraint.elements)
                values.add((columns, referred_table, referred_columns))
        out[table_name] = values
    return out


def expected_unique_constraints() -> dict[str, set[tuple[str, ...]]]:
    out: dict[str, set[tuple[str, ...]]] = {}
    for table_name, table in models.Base.metadata.tables.items():
        values: set[tuple[str, ...]] = set()
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                values.add(tuple(column.name for column in constraint.columns))
        out[table_name] = values
    return out


def expected_check_constraints() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for table_name, table in models.Base.metadata.tables.items():
        values: set[str] = set()
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and constraint.name:
                values.add(constraint.name)
        out[table_name] = values
    return out


def _index_name_from_statement(statement: str) -> str | None:
    match = re.search(r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+([^\s]+)', statement, flags=re.IGNORECASE)
    return match.group(1) if match else None


def model_declared_index_names() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {name: set() for name in models.Base.metadata.tables}
    for table_name, table in models.Base.metadata.tables.items():
        out[table_name] = {index.name for index in table.indexes if index.name}
    return out


@lru_cache(maxsize=1)
def migration_authoritative_index_names() -> dict[str, set[str]]:
    tree = ast.parse(BASELINE_MIGRATION_PATH.read_text(encoding='utf-8'))
    out: dict[str, set[str]] = {name: set() for name in models.Base.metadata.tables}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != 'create_index':
            continue
        if len(node.args) < 2 or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[1], ast.Constant):
            continue
        index_name = node.args[0].value
        table_name = node.args[1].value
        if isinstance(index_name, str) and isinstance(table_name, str) and table_name in out:
            out[table_name].add(index_name)
    return out


def sqlite_legacy_index_names() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {name: set() for name in models.Base.metadata.tables}
    for statement in RUNTIME_INDEX_STATEMENTS:
        name = _index_name_from_statement(statement)
        table_match = re.search(r'\sON\s+([^\s(]+)', statement, flags=re.IGNORECASE)
        if name and table_match:
            table_name = table_match.group(1).strip('"')
            if table_name in out:
                out[table_name].add(name)
    return out


def expected_index_names(policy: SchemaDialectPolicy | None = None) -> dict[str, set[str]]:
    # Fresh databases are governed by the Alembic baseline for both accepted dialects.
    return {table: set(names) for table, names in migration_authoritative_index_names().items()}


def inspect_schema(engine: Engine) -> dict[str, Any]:
    inspector = inspect(engine)
    tables = [name for name in inspector.get_table_names() if name != 'alembic_version' and not name.startswith('sqlite_')]
    columns: dict[str, dict[str, dict[str, Any]]] = {}
    indexes: dict[str, set[str]] = {}
    foreign_keys: dict[str, set[tuple[tuple[str, ...], str, tuple[str, ...]]]] = {}
    unique_constraints: dict[str, set[tuple[str, ...]]] = {}
    check_constraints: dict[str, set[str]] = {}
    for table_name in tables:
        columns[table_name] = {}
        primary_key_columns = set(inspector.get_pk_constraint(table_name).get('constrained_columns') or ())
        for column in inspector.get_columns(table_name):
            primary_key = column['name'] in primary_key_columns or bool(column.get('primary_key', False))
            columns[table_name][column['name']] = _column_contract(
                type_=column['type'],
                nullable=bool(column.get('nullable', True)),
                primary_key=primary_key,
                server_default=column.get('default'),
            )
        indexes[table_name] = {row['name'] for row in inspector.get_indexes(table_name) if row.get('name')}
        foreign_keys[table_name] = {
            (tuple(row.get('constrained_columns') or ()), row.get('referred_table') or '', tuple(row.get('referred_columns') or ()))
            for row in inspector.get_foreign_keys(table_name)
        }
        unique_values = {tuple(row.get('column_names') or ()) for row in inspector.get_unique_constraints(table_name)}
        for row in inspector.get_indexes(table_name):
            if row.get('unique'):
                unique_values.add(tuple(row.get('column_names') or ()))
        unique_constraints[table_name] = unique_values
        try:
            check_constraints[table_name] = {row['name'] for row in inspector.get_check_constraints(table_name) if row.get('name')}
        except NotImplementedError:
            check_constraints[table_name] = set()
    return {
        'tables': set(tables),
        'columns': columns,
        'indexes': indexes,
        'foreign_keys': foreign_keys,
        'unique_constraints': unique_constraints,
        'check_constraints': check_constraints,
    }


def compare_schema(engine: Engine, dialect_policy: SchemaDialectPolicy | None = None) -> list[SchemaIssue]:
    policy = dialect_policy or dialect_policy_for_engine(engine)
    actual = inspect_schema(engine)
    expected_table_names = set(APP_TABLES)
    issues: list[SchemaIssue] = []
    for table in sorted(expected_table_names - actual['tables']):
        issues.append(SchemaIssue('missing_table', table))
    for table in sorted(actual['tables'] - expected_table_names):
        issues.append(SchemaIssue('unexpected_table', table))

    expected_cols = expected_columns()
    for table in sorted(expected_table_names & actual['tables']):
        actual_cols = actual['columns'].get(table, {})
        for column in sorted(set(expected_cols[table]) - set(actual_cols)):
            issues.append(SchemaIssue('missing_column', f'{table}.{column}'))
        for column in sorted(set(actual_cols) - set(expected_cols[table])):
            issues.append(SchemaIssue('unexpected_column', f'{table}.{column}'))
        for column in sorted(set(expected_cols[table]) & set(actual_cols)):
            expected = expected_cols[table][column]
            found = actual_cols[column]
            if expected['affinity'] != found['affinity']:
                issues.append(SchemaIssue('incompatible_type', f'{table}.{column}: expected {expected["affinity"]}, found {found["affinity"]}'))
            if expected['primary_key'] != found['primary_key']:
                issues.append(SchemaIssue('incompatible_primary_key', f'{table}.{column}'))
            if expected['effective_nullable'] != found['effective_nullable']:
                issues.append(SchemaIssue('incompatible_nullability', f'{table}.{column}: expected nullable={expected["effective_nullable"]}, found nullable={found["effective_nullable"]}'))
            generated_postgresql_pk = policy.is_postgresql and expected['primary_key'] and found['has_server_default']
            if expected['has_server_default'] != found['has_server_default'] and not generated_postgresql_pk:
                issues.append(SchemaIssue('incompatible_server_default', f'{table}.{column}: expected default={expected["server_default"]!r}, found default={found["server_default"]!r}'))
            elif expected['has_server_default'] and expected['server_default'] != found['server_default']:
                issues.append(SchemaIssue('incompatible_server_default', f'{table}.{column}: expected default={expected["server_default"]!r}, found default={found["server_default"]!r}'))

    expected_indexes = expected_index_names(policy)
    for table in sorted(expected_table_names & actual['tables']):
        missing = expected_indexes.get(table, set()) - actual['indexes'].get(table, set())
        for index_name in sorted(missing):
            issues.append(SchemaIssue('missing_index', f'{table}.{index_name}'))

    expected_fks = expected_foreign_keys()
    for table in sorted(expected_table_names & actual['tables']):
        missing = expected_fks.get(table, set()) - actual['foreign_keys'].get(table, set())
        for fk in sorted(missing):
            issues.append(SchemaIssue('missing_foreign_key', f'{table}.{fk}'))

    expected_uniques = expected_unique_constraints()
    for table in sorted(expected_table_names & actual['tables']):
        missing = expected_uniques.get(table, set()) - actual['unique_constraints'].get(table, set())
        for unique in sorted(missing):
            issues.append(SchemaIssue('missing_unique_constraint', f'{table}.{unique}'))

    expected_checks = expected_check_constraints()
    for table in sorted(expected_table_names & actual['tables']):
        missing = expected_checks.get(table, set()) - actual['check_constraints'].get(table, set())
        for check in sorted(missing):
            issues.append(SchemaIssue('missing_check_constraint', f'{table}.{check}'))
    return issues


def assert_schema_compatible(engine: Engine) -> None:
    issues = compare_schema(engine)
    if issues:
        detail = '; '.join(f'{issue.category}: {issue.detail}' for issue in issues[:20])
        raise AssertionError(detail)
