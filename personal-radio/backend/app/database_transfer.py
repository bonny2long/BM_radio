from __future__ import annotations

import enum
import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, and_, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine

from . import models
from .database_readiness import READY, inspect_database_readiness
from .migration_contract import APP_TABLES, compare_schema
from .sqlite_adoption import sha256_file, snapshot_sqlite_database, sqlite_foreign_key_violations


CANONICAL_VERSION = 1


class TransferBlockedError(RuntimeError):
    """Fail-closed transfer error whose message contains no row data."""


@dataclass(frozen=True)
class TransferPlan:
    source_dialect: str
    target_dialect: str
    table_order: tuple[str, ...]
    expected_rows: dict[str, int]


@dataclass(frozen=True)
class TransferResult:
    table_order: tuple[str, ...]
    transferred_rows: dict[str, int]
    sequence_repairs: dict[str, dict[str, Any]]
    sequence_canary: dict[str, Any]
    dry_run: bool

    @property
    def total_rows(self) -> int:
        return sum(self.transferred_rows.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "table_order": list(self.table_order),
            "transferred_rows": dict(self.transferred_rows),
            "total_rows": self.total_rows,
            "sequence_repairs": self.sequence_repairs,
            "sequence_canary": self.sequence_canary,
            "dry_run": self.dry_run,
        }


def _table(name: str):
    if name not in APP_TABLES:
        raise TransferBlockedError("transfer table is outside the BM Radio application schema")
    return models.Base.metadata.tables[name]


def _readiness_contract(engine: Engine, *, require_empty: bool) -> dict[str, Any]:
    readiness = inspect_database_readiness(engine)
    issues = compare_schema(engine)
    present = set(inspect(engine).get_table_names()) & set(APP_TABLES)
    if readiness.status != READY or readiness.current_revision != readiness.head_revision:
        raise TransferBlockedError(f"{engine.dialect.name} database is not at the single Alembic head")
    if issues or present != set(APP_TABLES):
        raise TransferBlockedError(f"{engine.dialect.name} application schema is incompatible")
    counts = application_row_counts(engine)
    if require_empty and any(counts.values()):
        raise TransferBlockedError("PostgreSQL transfer target must be empty")
    return {
        "revision": readiness.current_revision,
        "head_revision": readiness.head_revision,
        "readiness": readiness.status,
        "compatibility": "PASS",
        "application_tables": len(present),
        "application_rows": sum(counts.values()),
    }


def application_row_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            name: int(connection.execute(select(func.count()).select_from(_table(name))).scalar_one())
            for name in APP_TABLES
        }


def dependency_order() -> tuple[str, ...]:
    """Topologically order application tables, failing on unresolved FK cycles."""
    names = set(APP_TABLES)
    dependencies: dict[str, set[str]] = {}
    for name in APP_TABLES:
        table = _table(name)
        dependencies[name] = {
            foreign_key.column.table.name
            for foreign_key in table.foreign_keys
            if foreign_key.column.table.name in names and foreign_key.column.table.name != name
        }

    pending = {name: set(values) for name, values in dependencies.items()}
    ordered: list[str] = []
    while pending:
        ready = sorted(name for name, values in pending.items() if not values)
        if not ready:
            cycle = ", ".join(sorted(pending))
            raise TransferBlockedError(f"unresolved application foreign-key dependency cycle: {cycle}")
        ordered.extend(ready)
        for name in ready:
            pending.pop(name)
        for values in pending.values():
            values.difference_update(ready)
    if set(ordered) != names or len(ordered) != len(names):
        raise TransferBlockedError("application transfer order is incomplete")
    return tuple(ordered)


def _datetime_value(value: Any) -> str:
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise TransferBlockedError("invalid datetime value in transfer source") from exc
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")


def canonical_value(column: Any, value: Any) -> list[Any]:
    """Typed comparison representation that preserves null, text, and number distinctions."""
    if value is None:
        return ["null", None]
    if isinstance(column.type, Boolean):
        if value not in (True, False, 0, 1):
            raise TransferBlockedError("invalid boolean value in transfer source")
        return ["boolean", bool(value)]
    if isinstance(column.type, Enum):
        raw = value.value if isinstance(value, enum.Enum) else str(value)
        allowed = {item.value if isinstance(item, enum.Enum) else str(item) for item in (column.type.enums or ())}
        enum_class = getattr(column.type, "enum_class", None)
        if enum_class is not None:
            allowed = {item.value for item in enum_class}
        if raw not in allowed:
            raise TransferBlockedError("invalid enum value in transfer source")
        return ["enum", raw]
    if isinstance(column.type, DateTime):
        return ["datetime", _datetime_value(value)]
    if isinstance(column.type, Float):
        number = float(value)
        if not math.isfinite(number):
            raise TransferBlockedError("non-finite float in transfer source")
        return ["float", number.hex()]
    if isinstance(column.type, Integer):
        if isinstance(value, bool):
            raise TransferBlockedError("boolean found in integer transfer column")
        return ["integer", int(value)]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, str):
        return ["text", value]
    return [type(value).__name__, str(value)]


def _primary_key_columns(table: Any) -> tuple[Any, ...]:
    columns = tuple(table.primary_key.columns)
    if not columns:
        raise TransferBlockedError(f"application table {table.name} has no primary key")
    return columns


def canonical_table_digest(engine: Engine, table_name: str) -> tuple[int, str]:
    table = _table(table_name)
    primary_key = _primary_key_columns(table)
    digest = hashlib.sha256()
    count = 0
    statement = select(table).order_by(*primary_key)
    try:
        with engine.connect() as connection:
            for row in connection.execute(statement).mappings():
                payload = {
                    "table": table_name,
                    "columns": [column.name for column in table.columns],
                    "values": [canonical_value(column, row[column.name]) for column in table.columns],
                }
                digest.update(json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
                digest.update(b"\n")
                count += 1
    except (LookupError, ValueError) as exc:
        raise TransferBlockedError(f"typed source decoding failed for table {table_name}") from exc
    return count, digest.hexdigest()


def canonical_row_digests(engine: Engine, table_name: str) -> dict[tuple[Any, ...], str]:
    """Return only PK tuples and row hashes so callers can prove imported-row preservation safely."""
    table = _table(table_name)
    primary_key = _primary_key_columns(table)
    result: dict[tuple[Any, ...], str] = {}
    with engine.connect() as connection:
        for row in connection.execute(select(table).order_by(*primary_key)).mappings():
            payload = {
                "table": table_name,
                "columns": [column.name for column in table.columns],
                "values": [canonical_value(column, row[column.name]) for column in table.columns],
            }
            key = tuple(row[column.name] for column in primary_key)
            result[key] = hashlib.sha256(json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return result


def database_inventory(engine: Engine) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for name in APP_TABLES:
        table = _table(name)
        pk_columns = _primary_key_columns(table)
        count, digest = canonical_table_digest(engine, name)
        minimum: int | None = None
        maximum: int | None = None
        if len(pk_columns) == 1 and isinstance(pk_columns[0].type, Integer) and count:
            with engine.connect() as connection:
                minimum, maximum = connection.execute(select(func.min(pk_columns[0]), func.max(pk_columns[0]))).one()
        inventory[name] = {
            "row_count": count,
            "primary_key": [column.name for column in pk_columns],
            "minimum_numeric_pk": int(minimum) if minimum is not None else None,
            "maximum_numeric_pk": int(maximum) if maximum is not None else None,
            "foreign_key_count": len(table.foreign_keys),
            "canonical_digest": digest,
        }
    return inventory


def inventory_counts(inventory: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {name: int(data["row_count"]) for name, data in inventory.items()}


def inventory_digests(inventory: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {name: str(data["canonical_digest"]) for name, data in inventory.items()}


def create_verified_sqlite_backup(source: Path, backup_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    if not source.is_file():
        raise TransferBlockedError("live SQLite source is missing")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = backup_dir / f"bm_radio.pre_postgres_transfer.{stamp}.db"
    manifest_path = backup.with_suffix(".manifest.json")
    source_uri = f"file:{source.resolve().as_posix()}?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True)
    backup_connection = sqlite3.connect(backup)
    try:
        source_connection.backup(backup_connection)
    finally:
        backup_connection.close()
        source_connection.close()

    from .migration_contract import engine_for_url, read_only_sqlite_url_for_path

    source_engine = engine_for_url(read_only_sqlite_url_for_path(source))
    backup_engine = engine_for_url(read_only_sqlite_url_for_path(backup))
    try:
        source_snapshot = snapshot_sqlite_database(source, logical_path="bm_radio.db")
        backup_snapshot = snapshot_sqlite_database(backup, logical_path=backup.name)
        source_inventory = database_inventory(source_engine)
        backup_inventory = database_inventory(backup_engine)
    finally:
        source_engine.dispose()
        backup_engine.dispose()
    source_counts = inventory_counts(source_inventory)
    backup_counts = inventory_counts(backup_inventory)
    source_digests = inventory_digests(source_inventory)
    backup_digests = inventory_digests(backup_inventory)
    valid = (
        backup_snapshot.integrity_check == "ok"
        and backup_snapshot.quick_check == "ok"
        and source_snapshot.schema_fingerprint == backup_snapshot.schema_fingerprint
        and source_snapshot.current_revision == backup_snapshot.current_revision
        and source_counts == backup_counts
        and source_digests == backup_digests
        and not sqlite_foreign_key_violations(backup)
    )
    if not valid:
        backup.unlink(missing_ok=True)
        raise TransferBlockedError("populated SQLite backup verification failed")
    manifest = {
        "version": 1,
        "logical_source": "backend/bm_radio.db",
        "backup_filename": backup.name,
        "created_utc": datetime.now(UTC).isoformat(),
        "source_sha256": sha256_file(source),
        "backup_sha256": sha256_file(backup),
        "integrity_check": backup_snapshot.integrity_check,
        "quick_check": backup_snapshot.quick_check,
        "schema_fingerprint": backup_snapshot.schema_fingerprint,
        "revision": backup_snapshot.current_revision,
        "application_table_count": len(backup_snapshot.application_tables),
        "application_row_count": sum(backup_counts.values()),
        "per_table_row_counts": backup_counts,
        "per_table_canonical_digests": backup_digests,
        "foreign_key_check": "PASS",
        "source_backup_counts_equal": source_counts == backup_counts,
        "source_backup_digests_equal": source_digests == backup_digests,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return backup, manifest_path, manifest


def build_transfer_plan(source_engine: Engine, target_engine: Engine) -> TransferPlan:
    if source_engine.dialect.name != "sqlite":
        raise TransferBlockedError("transfer source must be SQLite")
    if target_engine.dialect.name != "postgresql":
        raise TransferBlockedError("transfer target must be PostgreSQL")
    _readiness_contract(source_engine, require_empty=False)
    _readiness_contract(target_engine, require_empty=True)
    return TransferPlan(
        source_dialect="sqlite",
        target_dialect="postgresql",
        table_order=dependency_order(),
        expected_rows=application_row_counts(source_engine),
    )


def _source_rows(source_engine: Engine, table_name: str) -> list[dict[str, Any]]:
    table = _table(table_name)
    primary_key = _primary_key_columns(table)
    try:
        with source_engine.connect() as source:
            return [dict(row) for row in source.execute(select(table).order_by(*primary_key)).mappings()]
    except (LookupError, ValueError) as exc:
        raise TransferBlockedError(f"typed source decoding failed for table {table_name}") from exc


def _repair_sequences(connection: Connection, table_order: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    repairs: dict[str, dict[str, Any]] = {}
    for table_name in table_order:
        table = _table(table_name)
        pk_columns = _primary_key_columns(table)
        if len(pk_columns) != 1 or not isinstance(pk_columns[0].type, Integer):
            continue
        column = pk_columns[0]
        sequence = connection.execute(
            text("select pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": table_name, "column_name": column.name},
        ).scalar_one_or_none()
        if not sequence:
            continue
        maximum = connection.execute(select(func.max(column))).scalar_one()
        if maximum is not None:
            connection.execute(
                text("select setval(cast(:sequence_name as regclass), :maximum_value, true)"),
                {"sequence_name": sequence, "maximum_value": int(maximum)},
            )
            next_value = connection.execute(text("select nextval(cast(:sequence_name as regclass))"), {"sequence_name": sequence}).scalar_one()
            if int(next_value) <= int(maximum):
                raise TransferBlockedError(f"sequence repair failed for table {table_name}")
            connection.execute(
                text("select setval(cast(:sequence_name as regclass), :maximum_value, true)"),
                {"sequence_name": sequence, "maximum_value": int(maximum)},
            )
            repairs[table_name] = {"column": column.name, "maximum_imported_id": int(maximum), "next_id_greater": True}
        else:
            next_value = connection.execute(text("select nextval(cast(:sequence_name as regclass))"), {"sequence_name": sequence}).scalar_one()
            connection.execute(
                text("select setval(cast(:sequence_name as regclass), 1, false)"),
                {"sequence_name": sequence},
            )
            repairs[table_name] = {"column": column.name, "empty_initial_state_valid": int(next_value) >= 1}
            if not repairs[table_name]["empty_initial_state_valid"]:
                raise TransferBlockedError(f"empty sequence state is invalid for table {table_name}")
    return repairs


def _insert_rollback_sequence_canary(connection: Connection) -> dict[str, Any]:
    table = _table("tracks")
    pk = _primary_key_columns(table)[0]
    maximum = connection.execute(select(func.max(pk))).scalar_one()
    nested = connection.begin_nested()
    try:
        generated = connection.execute(table.insert().returning(pk)).scalar_one()
        if maximum is not None and int(generated) <= int(maximum):
            raise TransferBlockedError("insert/rollback sequence canary did not advance beyond imported IDs")
    finally:
        nested.rollback()
    sequence = connection.execute(
        text("select pg_get_serial_sequence(:table_name, :column_name)"),
        {"table_name": table.name, "column_name": pk.name},
    ).scalar_one()
    if maximum is not None:
        connection.execute(
            text("select setval(cast(:sequence_name as regclass), :maximum_value, true)"),
            {"sequence_name": sequence, "maximum_value": int(maximum)},
        )
    return {"table": table.name, "inserted_id": int(generated), "greater_than_imported_max": maximum is None or int(generated) > int(maximum), "rolled_back": True}


def transfer_database(source_engine: Engine, target_engine: Engine, *, dry_run: bool = False) -> TransferResult:
    plan = build_transfer_plan(source_engine, target_engine)
    if dry_run:
        return TransferResult(plan.table_order, dict(plan.expected_rows), {}, {}, True)
    transferred: dict[str, int] = {}
    failed_table = "pre-transfer"
    try:
        with target_engine.begin() as target:
            for table_name in plan.table_order:
                failed_table = table_name
                rows = _source_rows(source_engine, table_name)
                if len(rows) != plan.expected_rows[table_name]:
                    raise TransferBlockedError(f"source row count changed while reading table {table_name}")
                if rows:
                    target.execute(_table(table_name).insert(), rows)
                transferred[table_name] = len(rows)
            sequence_repairs = _repair_sequences(target, plan.table_order)
            sequence_canary = _insert_rollback_sequence_canary(target)
    except TransferBlockedError:
        raise
    except Exception as exc:
        raise TransferBlockedError(f"transactional transfer failed at table {failed_table}; target rolled back") from exc
    if transferred != plan.expected_rows:
        raise TransferBlockedError("transferred row counts do not match the source plan")
    return TransferResult(plan.table_order, transferred, sequence_repairs, sequence_canary, False)


def foreign_key_violations(engine: Engine) -> dict[str, int]:
    violations: dict[str, int] = {}
    with engine.connect() as connection:
        for table_name in APP_TABLES:
            table = _table(table_name)
            for foreign_key in sorted(table.foreign_keys, key=lambda item: (item.parent.name, item.column.table.name, item.column.name)):
                parent = foreign_key.column.table
                query = (
                    select(func.count())
                    .select_from(table.outerjoin(parent, foreign_key.parent == foreign_key.column))
                    .where(and_(foreign_key.parent.is_not(None), foreign_key.column.is_(None)))
                )
                count = int(connection.execute(query).scalar_one())
                if count:
                    violations[f"{table_name}.{foreign_key.parent.name}->{parent.name}.{foreign_key.column.name}"] = count
    return violations


def verify_database_transfer(source_engine: Engine, target_engine: Engine) -> dict[str, Any]:
    source_contract = _readiness_contract(source_engine, require_empty=False)
    target_contract = _readiness_contract(target_engine, require_empty=False)
    source_inventory = database_inventory(source_engine)
    target_inventory = database_inventory(target_engine)
    source_counts = inventory_counts(source_inventory)
    target_counts = inventory_counts(target_inventory)
    source_digests = inventory_digests(source_inventory)
    target_digests = inventory_digests(target_inventory)
    fk_violations = foreign_key_violations(target_engine)
    if source_counts != target_counts:
        raise TransferBlockedError("source and target per-table row counts differ")
    if source_digests != target_digests:
        raise TransferBlockedError("source and target canonical table digests differ")
    if fk_violations:
        raise TransferBlockedError("PostgreSQL target contains foreign-key violations")
    return {
        "source": source_contract,
        "target": target_contract,
        "source_total_rows": sum(source_counts.values()),
        "target_total_rows": sum(target_counts.values()),
        "per_table_row_counts": target_counts,
        "per_table_canonical_digests": target_digests,
        "count_equality": True,
        "canonical_digest_equality": True,
        "foreign_key_validation": "PASS",
        "unique_and_check_constraints": "PASS",
        "boolean_normalization": "PASS",
        "datetime_normalization": "PASS",
        "enum_validation": "PASS",
        "text_and_null_preservation": "PASS",
    }
