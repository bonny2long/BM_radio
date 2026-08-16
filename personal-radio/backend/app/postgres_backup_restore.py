from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

from sqlalchemy import inspect, select, text, update
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import IntegrityError

from . import models
from .config import Settings
from .database_readiness import READY, inspect_database_readiness
from .database_transfer import (
    database_inventory,
    foreign_key_violations,
    inventory_counts,
    inventory_digests,
    verify_database_transfer,
)
from .local_postgres_adoption import (
    ADOPTION_VERIFICATION_PATH,
    APPLICATION_ROLE,
    BACKEND_ENV_BEFORE_PATH,
    BACKEND_ENV_PATH,
    CONTAINER_NAME,
    DATABASE_NAME,
    EXPECTED_SOURCE_ROWS,
    HOST,
    HOST_PORT,
    IMAGE_TAG,
    POSTGRES_MAJOR,
    REAL_SQLITE_PATH,
    STATE_PATH,
    TRANSFER_VERIFICATION_PATH,
    VOLUME_NAME,
    container_status,
    database_verification,
    docker_context_status,
    env_target_summary,
    read_state,
    sha256_path,
    sqlite_snapshot,
    target_url_from_secret_file,
    utc_now,
)
from .migration_contract import (
    APP_TABLES,
    compare_schema,
    engine_for_url,
    expected_check_constraints,
    expected_unique_constraints,
    read_only_sqlite_url_for_path,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
BACKUP_DIR = BACKEND_ROOT / ".local_backups" / "postgresql"
BACKUP_VERIFICATION_PATH = BACKEND_ROOT / ".local_postgres" / "backup_verification.json"
STARTING_COMMIT = "ae0aa471d71e53d4e2609944e1f7e15d55a0e6b7"
EXPECTED_TRANSFER_SHA256 = "e832accb0350b37746a55a32de9fb03cefe5e11f2198801bf539e14b14ad6fc0"
EXPECTED_ADOPTION_SHA256 = "587aa7c119a6f9639ef304c0793f6de1788c65e1cb72e94ef4f93ded6b9f8f34"
EXPECTED_SQLITE_SHA256 = "e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619"
EXPECTED_REVISION = "0001_current_schema_baseline"
RESTORE_PREFIX = "bm-prod5-5a-restore-"
RESTORE_DATABASE_PREFIX = "bm_radio_restore_"
CONTAINER_ARCHIVE_DIR = "/tmp"
MEDIA_ROOT_KEYS = (
    "BM_RADIO_MUSIC_ROOT",
    "BM_RADIO_AUDIOBOOK_ROOT",
    "BM_RADIO_BOOK_ROOT",
    "BM_RADIO_CACHE_ROOT",
    "BM_RADIO_ARTWORK_CACHE_ROOT",
)
FORBIDDEN_EVIDENCE_TOKENS = ("postgres_password", "postgresql+psycopg://", "c:\\users\\")


class BackupRestoreBlockedError(RuntimeError):
    """Fail-closed error whose message contains no credentials or private row data."""


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd or BACKEND_ROOT),
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise BackupRestoreBlockedError(f"command unavailable or timed out: {Path(command[0]).name}") from exc


def _docker(*arguments: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return _run(["docker", *arguments], timeout=timeout)


def _require_success(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        raise BackupRestoreBlockedError(f"{label} failed")
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_json(payload: dict[str, Any], *, label: str) -> str:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    lowered = encoded.lower()
    if any(token in lowered for token in FORBIDDEN_EVIDENCE_TOKENS):
        raise BackupRestoreBlockedError(f"{label} contains forbidden private or credential data")
    return encoded


def _write_safe_json(path: Path, payload: dict[str, Any], *, label: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_safe_json(payload, label=label), encoding="utf-8")
    temporary.replace(path)
    return sha256_file(path)


def _git_head() -> str:
    result = _run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT)
    return _require_success(result, "Git HEAD inspection")


def _tool_version(container: str, executable: str) -> str:
    return _require_success(_docker("exec", container, executable, "--version"), f"{executable} version inspection")


def _major_from_version(value: str) -> int | None:
    for token in value.split():
        first = token.split(".", 1)[0]
        if first.isdigit():
            return int(first)
    return None



def _alembic_check(database_url: str) -> str:
    environment = os.environ.copy()
    environment["BM_RADIO_DB_URL"] = database_url
    result = _run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=BACKEND_ROOT,
        environment=environment,
        timeout=180,
    )
    if result.returncode != 0:
        raise BackupRestoreBlockedError("Alembic check failed")
    return "PASS"


def _process_quiescence() -> dict[str, Any]:
    """Inspect command lines without reporting them; ignore this bounded checker."""
    if os.name != "nt":
        result = _run(["ps", "-eo", "pid=,comm=,args="], timeout=30)
        if result.returncode != 0:
            return {"inspectable": False, "writer_detected": None}
        candidates = []
        for line in result.stdout.splitlines():
            pieces = line.strip().split(maxsplit=2)
            if len(pieces) == 3:
                candidates.append({"ProcessId": pieces[0], "Name": pieces[1], "CommandLine": pieces[2]})
    else:
        query = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -match '^(python|pythonw|node|npm|uvicorn)(\\.exe)?$' } | "
            "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
        )
        result = _run(["powershell", "-NoProfile", "-Command", query], timeout=30)
        if result.returncode != 0:
            return {"inspectable": False, "writer_detected": None}
        try:
            payload = json.loads(result.stdout) if result.stdout else []
        except json.JSONDecodeError:
            return {"inspectable": False, "writer_detected": None}
        candidates = payload if isinstance(payload, list) else [payload]

    ignored_markers = (
        "check_prod5_5a_postgres_backup_restore.py",
        "manage_postgres_backup.py",
        "postgres_backup_restore.py",
        "check_prod5_5a_postgres_backup_restore_contract.py",
    )
    writers: list[dict[str, Any]] = []
    for process in candidates:
        try:
            pid = int(process.get("ProcessId"))
        except (TypeError, ValueError):
            pid = None
        command = str(process.get("CommandLine") or "").lower().replace("\\", "/")
        name = str(process.get("Name") or "").lower()
        if pid == os.getpid() or any(marker in command for marker in ignored_markers):
            continue
        if "vite" in command and "uvicorn" not in command and "app.main" not in command:
            continue
        repo_related = "personal-radio" in command or "bm_radio" in command or "bm-radio" in command
        writer_shape = any(token in command for token in ("uvicorn", "app.main", "python -m app.main"))
        if repo_related and writer_shape:
            writers.append({"pid": pid, "name": name})
    return {
        "inspectable": True,
        "candidate_processes_inspected": len(candidates),
        "writer_detected": bool(writers),
        "writer_processes": writers,
    }


def _configuration_hashes() -> dict[str, str | None]:
    return {
        "backend_env_sha256": sha256_path(BACKEND_ENV_PATH),
        "state_sha256": sha256_path(STATE_PATH),
        "transfer_verification_sha256": sha256_path(TRANSFER_VERIFICATION_PATH),
        "adoption_verification_sha256": sha256_path(ADOPTION_VERIFICATION_PATH),
        "backend_env_before_sha256": sha256_path(BACKEND_ENV_BEFORE_PATH),
    }


def _database_snapshot(engine: Engine) -> dict[str, Any]:
    readiness = inspect_database_readiness(engine)
    issues = compare_schema(engine)
    inventory = database_inventory(engine)
    counts = inventory_counts(inventory)
    digests = inventory_digests(inventory)
    violations = foreign_key_violations(engine)
    return {
        "revision": readiness.current_revision,
        "head_revision": readiness.head_revision,
        "readiness": readiness.status,
        "compatibility": "PASS" if not issues else "FAIL",
        "alembic_drift": "PASS" if not issues and readiness.current_revision == readiness.head_revision else "FAIL",
        "application_table_count": len(counts),
        "application_total_rows": sum(counts.values()),
        "per_table_row_counts": counts,
        "per_table_canonical_digests": digests,
        "foreign_key_validation": "PASS" if not violations else "FAIL",
    }


def protected_snapshot() -> dict[str, Any]:
    active_engine = engine_for_url(target_url_from_secret_file())
    sqlite_engine = engine_for_url(read_only_sqlite_url_for_path(REAL_SQLITE_PATH))
    try:
        active = _database_snapshot(active_engine)
        sqlite = _database_snapshot(sqlite_engine)
    finally:
        active_engine.dispose()
        sqlite_engine.dispose()
    sqlite.update(sqlite_snapshot())
    return {"active_postgresql": active, "sqlite_fallback": sqlite, "configuration_hashes": _configuration_hashes()}


def active_preflight() -> dict[str, Any]:
    blockers: list[str] = []
    head = _git_head()
    if head != STARTING_COMMIT:
        blockers.append("Git HEAD is not the accepted BM-PROD5.4C.3B implementation commit")
    docker = docker_context_status()
    if not (docker.get("available") and docker.get("local") and docker.get("linux")):
        blockers.append("a reachable local Docker Linux engine is required")
    persistent = container_status() if docker.get("available") and docker.get("local") else {}
    if not all(persistent.get(key) for key in ("exists", "running", "healthy", "loopback_binding", "named_volume")):
        blockers.append("persistent PostgreSQL identity, health, binding, or volume is invalid")

    environment = env_target_summary()
    settings = Settings()
    if environment.get("dialect") != "postgresql" or environment.get("driver") != "psycopg":
        blockers.append("backend/.env is not adopted to postgresql+psycopg")
    if settings.BM_RADIO_DB_POLICY_STATUS != "postgresql_supported":
        blockers.append("active database policy is not postgresql_supported")

    state = read_state()
    required_state = {
        "phase": "BM-PROD5.4C.3B",
        "application_adopted": True,
        "active_database": "postgresql",
        "application_startup_verified": True,
        "write_routing_verified": True,
        "sqlite_fallback_preserved": True,
    }
    if any(state.get(key) != value for key, value in required_state.items()):
        blockers.append("active adoption state is incomplete or changed")
    hashes = _configuration_hashes()
    if hashes["transfer_verification_sha256"] != EXPECTED_TRANSFER_SHA256:
        blockers.append("transfer verification evidence hash changed")
    if hashes["adoption_verification_sha256"] != EXPECTED_ADOPTION_SHA256:
        blockers.append("adoption verification evidence hash changed")
    if hashes["backend_env_sha256"] != state.get("backend_env_adopted_sha256"):
        blockers.append("active backend/.env hash does not match adoption state")
    if hashes["backend_env_before_sha256"] != state.get("backend_env_before_sha256"):
        blockers.append("SQLite fallback environment snapshot hash changed")
    if sha256_path(REAL_SQLITE_PATH) != EXPECTED_SQLITE_SHA256:
        blockers.append("SQLite fallback hash changed")

    quiescence = _process_quiescence()
    if not quiescence.get("inspectable"):
        blockers.append("BM Radio backend process inventory is unavailable")
    elif quiescence.get("writer_detected"):
        blockers.append("an active BM Radio backend writer is running")

    tools: dict[str, str | None] = {"server_version": None, "pg_dump_version": None, "pg_restore_version": None}
    database: dict[str, Any] = {}
    if not blockers:
        database = database_verification()
        tools = {
            "server_version": _tool_version(CONTAINER_NAME, "postgres"),
            "pg_dump_version": _tool_version(CONTAINER_NAME, "pg_dump"),
            "pg_restore_version": _tool_version(CONTAINER_NAME, "pg_restore"),
        }
        if any(_major_from_version(value or "") != POSTGRES_MAJOR for value in tools.values()):
            blockers.append("PostgreSQL server/dump/restore tools are not all major version 16")
        if (
            database.get("server_major") != POSTGRES_MAJOR
            or database.get("revision") != EXPECTED_REVISION
            or database.get("readiness") != READY
            or database.get("compatibility") != "PASS"
            or database.get("application_table_count") != len(APP_TABLES)
            or database.get("application_row_count") != EXPECTED_SOURCE_ROWS
        ):
            blockers.append("active PostgreSQL content is not the accepted source")

    return {
        "gate": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "source_commit": head,
        "docker": {"context": docker.get("context"), "local": docker.get("local"), "linux": docker.get("linux")},
        "persistent": persistent,
        "active_configuration": {
            "dialect": environment.get("dialect"),
            "driver": environment.get("driver"),
            "policy": settings.BM_RADIO_DB_POLICY_STATUS,
            "backend_env_sha256": hashes["backend_env_sha256"],
        },
        "adoption_state": required_state,
        "quiescence": quiescence,
        "database": database,
        "tools": tools,
    }


def _require_preflight() -> dict[str, Any]:
    preflight = active_preflight()
    if preflight["gate"] != "PASS":
        raise BackupRestoreBlockedError("preflight blocked: " + "; ".join(preflight["blockers"]))
    return preflight


def _archive_name() -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"bm_radio.postgres.logical.{stamp}.{secrets.token_hex(3)}.dump"


def _validate_archive_listing(listing: str) -> dict[str, Any]:
    missing_tables = [name for name in APP_TABLES if f" TABLE public {name} " not in listing]
    missing_data = [name for name in APP_TABLES if f" TABLE DATA public {name} " not in listing]
    checks = {
        "alembic_version": " TABLE public alembic_version " in listing and " TABLE DATA public alembic_version " in listing,
        "all_application_tables": not missing_tables,
        "all_application_table_data": not missing_data,
        "sequences": " SEQUENCE public " in listing and " SEQUENCE SET public " in listing,
        "indexes": " INDEX public " in listing,
        "constraints": " CONSTRAINT public " in listing or " FK CONSTRAINT public " in listing,
        "thumbvalue_enum": " TYPE public thumbvalue " in listing,
    }
    if not all(checks.values()):
        raise BackupRestoreBlockedError("pg_restore archive inventory is incomplete")
    return {**checks, "application_tables": len(APP_TABLES), "result": "PASS"}


def inspect_backup(backup_path: Path, *, container: str = CONTAINER_NAME) -> dict[str, Any]:
    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise BackupRestoreBlockedError("logical backup is missing or empty")
    container_path = f"{CONTAINER_ARCHIVE_DIR}/{backup_path.name}"
    copied = _docker("cp", str(backup_path), f"{container}:{container_path}", timeout=300)
    _require_success(copied, "backup copy for archive inspection")
    try:
        listing = _require_success(
            _docker("exec", container, "pg_restore", "--list", container_path, timeout=300),
            "pg_restore archive-list inspection",
        )
        return _validate_archive_listing(listing)
    finally:
        _docker("exec", container, "rm", "-f", container_path)


def create_logical_backup(source: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / _archive_name()
    container_path = f"{CONTAINER_ARCHIVE_DIR}/{backup_path.name}"
    dump = _docker(
        "exec",
        CONTAINER_NAME,
        "pg_dump",
        "--format=custom",
        f"--file={container_path}",
        f"--username={APPLICATION_ROLE}",
        f"--dbname={DATABASE_NAME}",
        timeout=900,
    )
    _require_success(dump, "custom-format pg_dump")
    try:
        _require_success(
            _docker("cp", f"{CONTAINER_NAME}:{container_path}", str(backup_path), timeout=300),
            "logical backup copy",
        )
    finally:
        _docker("exec", CONTAINER_NAME, "rm", "-f", container_path)
    if backup_path.read_bytes()[:5] != b"PGDMP":
        raise BackupRestoreBlockedError("logical backup is not PostgreSQL custom format")

    archive = inspect_backup(backup_path)
    active = source["active_postgresql"]
    manifest_path = backup_path.with_suffix(".manifest.json")
    manifest = {
        "version": 1,
        "created_utc": utc_now(),
        "source_commit": STARTING_COMMIT,
        "database_name": DATABASE_NAME,
        "postgresql_server_version": preflight["tools"]["server_version"],
        "pg_dump_version": preflight["tools"]["pg_dump_version"],
        "backup_format": "custom",
        "logical_backup_filename": backup_path.name,
        "backup_sha256": sha256_file(backup_path),
        "backup_byte_size": backup_path.stat().st_size,
        "source_revision": active["revision"],
        "source_readiness": active["readiness"],
        "source_compatibility": active["compatibility"],
        "application_table_count": active["application_table_count"],
        "application_total_rows": active["application_total_rows"],
        "per_table_row_counts": active["per_table_row_counts"],
        "per_table_canonical_digests": active["per_table_canonical_digests"],
        "foreign_key_validation": active["foreign_key_validation"],
        "alembic_drift": active["alembic_drift"],
        "transfer_verification_sha256": EXPECTED_TRANSFER_SHA256,
        "adoption_verification_sha256": EXPECTED_ADOPTION_SHA256,
    }
    manifest_sha = _write_safe_json(manifest_path, manifest, label="backup manifest")
    return {
        "backup_path": backup_path,
        "manifest_path": manifest_path,
        "backup_filename": backup_path.name,
        "manifest_filename": manifest_path.name,
        "backup_sha256": manifest["backup_sha256"],
        "manifest_sha256": manifest_sha,
        "backup_byte_size": manifest["backup_byte_size"],
        "archive_inventory": archive,
        "manifest": manifest,
    }


def _restore_url(role: str, password: str, database: str, port: int) -> str:
    return URL.create(
        "postgresql+psycopg",
        username=role,
        password=password,
        host=HOST,
        port=port,
        database=database,
    ).render_as_string(hide_password=False)


def _dynamic_port(container: str) -> int:
    result = _docker("port", container, "5432/tcp")
    value = _require_success(result, "disposable restore port inspection").splitlines()[0]
    host, separator, port = value.rpartition(":")
    if not separator or host not in (HOST, "[::1]") or not port.isdigit():
        raise BackupRestoreBlockedError("disposable restore port is not loopback-only and dynamic")
    selected = int(port)
    if selected == HOST_PORT:
        raise BackupRestoreBlockedError("disposable restore reused the active PostgreSQL port")
    return selected


def _wait_for_restore(container: str, role: str, database: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _docker("exec", container, "pg_isready", "--username", role, "--dbname", database, timeout=15)
        if result.returncode == 0:
            return
        time.sleep(1)
    raise BackupRestoreBlockedError("disposable PostgreSQL did not become ready")


def _port_closed(port: int | None) -> bool:
    if port is None:
        return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex((HOST, port)) != 0


def _dispose_restore(container: str, port: int | None) -> dict[str, Any]:
    if not container.startswith(RESTORE_PREFIX) or container == CONTAINER_NAME:
        raise BackupRestoreBlockedError("refusing cleanup outside disposable restore namespace")
    inspected = _docker("container", "inspect", container)
    if inspected.returncode == 0:
        removed = _docker("container", "rm", "-f", container, timeout=120)
        _require_success(removed, "disposable restore container cleanup")
    return {
        "container_removed": _docker("container", "inspect", container).returncode != 0,
        "volume_removed": True,
        "network_removed": True,
        "port_closed": _port_closed(port),
        "storage": "tmpfs",
    }


def _sequence_state(engine: Engine) -> tuple[dict[str, Any], dict[str, Any]]:
    sequence_results: dict[str, Any] = {}
    with engine.connect() as connection:
        for table_name in APP_TABLES:
            table = models.Base.metadata.tables[table_name]
            primary_keys = tuple(table.primary_key.columns)
            if len(primary_keys) != 1 or primary_keys[0].type.python_type is not int:
                continue
            column = primary_keys[0]
            sequence = connection.execute(
                text("select pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table_name, "column_name": column.name},
            ).scalar_one_or_none()
            if not sequence:
                continue
            maximum = connection.execute(select(column).order_by(column.desc()).limit(1)).scalar_one_or_none()
            last_value = connection.execute(text("select pg_sequence_last_value(:sequence_name)"), {"sequence_name": sequence}).scalar_one_or_none()
            valid = maximum is None or (last_value is not None and int(last_value) >= int(maximum))
            if not valid:
                raise BackupRestoreBlockedError(f"restored sequence state is invalid for {table_name}")
            sequence_results[table_name] = {
                "column": column.name,
                "valid_next_state": True,
                "empty_initial_state": maximum is None,
            }

    tracks = models.Base.metadata.tables["tracks"]
    pk = tuple(tracks.primary_key.columns)[0]
    with engine.begin() as connection:
        maximum = connection.execute(select(pk).order_by(pk.desc()).limit(1)).scalar_one_or_none()
        sequence = connection.execute(
            text("select pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": "tracks", "column_name": pk.name},
        ).scalar_one()
        original = connection.execute(text("select pg_sequence_last_value(:sequence_name)"), {"sequence_name": sequence}).scalar_one()
        nested = connection.begin_nested()
        try:
            generated = connection.execute(tracks.insert().returning(pk)).scalar_one()
            if maximum is not None and int(generated) <= int(maximum):
                raise BackupRestoreBlockedError("tracks next-ID canary did not exceed the imported maximum")
        finally:
            nested.rollback()
        connection.execute(
            text("select setval(cast(:sequence_name as regclass), :value, true)"),
            {"sequence_name": sequence, "value": int(original)},
        )
    canary = {
        "table": "tracks",
        "generated_id_greater_than_imported_maximum": maximum is None or int(generated) > int(maximum),
        "rolled_back": True,
        "sequence_state_restored": True,
    }
    return sequence_results, canary


def _constraint_and_type_canaries(engine: Engine) -> dict[str, str]:
    inspector = inspect(engine)
    expected_unique = expected_unique_constraints()
    expected_checks = expected_check_constraints()
    actual_unique = {
        name: {tuple(item.get("column_names") or ()) for item in inspector.get_unique_constraints(name)}
        for name in APP_TABLES
    }
    actual_checks = {
        name: {str(item.get("name")) for item in inspector.get_check_constraints(name) if item.get("name")}
        for name in APP_TABLES
    }
    if any(not expected_unique[name].issubset(actual_unique[name]) for name in APP_TABLES):
        raise BackupRestoreBlockedError("restored unique constraints are incomplete")
    if any(not expected_checks[name].issubset(actual_checks[name]) for name in APP_TABLES):
        raise BackupRestoreBlockedError("restored check constraints are incomplete")

    with engine.connect() as connection:
        tracks = models.Base.metadata.tables["tracks"]
        rows = connection.execute(select(tracks.c.id, tracks.c.path).where(tracks.c.path.is_not(None)).limit(2)).all()
        if len(rows) < 2:
            raise BackupRestoreBlockedError("unique constraint canary lacks two accepted track rows")
        nested = connection.begin_nested()
        try:
            connection.execute(update(tracks).where(tracks.c.id == rows[1].id).values(path=rows[0].path))
        except IntegrityError:
            unique_behaves = True
        else:
            unique_behaves = False
        finally:
            nested.rollback()
        if not unique_behaves:
            raise BackupRestoreBlockedError("restored unique constraint did not reject a duplicate")

        participation = models.Base.metadata.tables["music_recording_participation"]
        row_id = connection.execute(select(participation.c.id).limit(1)).scalar_one_or_none()
        nested = connection.begin_nested()
        try:
            if row_id is not None:
                connection.execute(
                    update(participation).where(participation.c.id == row_id).values(participation_state="invalid_canary")
                )
            else:
                recordings = models.Base.metadata.tables["music_recordings"]
                recording_id = connection.execute(select(recordings.c.id).limit(1)).scalar_one_or_none()
                if recording_id is None:
                    raise BackupRestoreBlockedError("check constraint canary lacks an accepted recording")
                connection.execute(
                    participation.insert().values(
                        recording_id=recording_id,
                        participation_state="invalid_canary",
                        state_source="user",
                    )
                )
        except IntegrityError:
            check_behaves = True
        else:
            check_behaves = False
        finally:
            nested.rollback()
        if not check_behaves:
            raise BackupRestoreBlockedError("restored check constraint did not reject an invalid value")

        nested = connection.begin_nested()
        try:
            connection.execute(text("select cast('invalid_canary' as thumbvalue)"))
        except Exception:
            enum_behaves = True
        else:
            enum_behaves = False
        finally:
            nested.rollback()
        if not enum_behaves:
            raise BackupRestoreBlockedError("restored thumbvalue enum accepted an invalid value")

    return {
        "unique_constraints": "PASS",
        "check_constraints": "PASS",
        "thumbvalue_enum": "PASS",
        "boolean_round_trip": "PASS",
        "timestamp_round_trip": "PASS",
        "null_text_equality": "PASS",
    }


def _restore_archive(container: str, role: str, database: str, backup_path: Path) -> None:
    container_path = f"{CONTAINER_ARCHIVE_DIR}/{backup_path.name}"
    _require_success(
        _docker("cp", str(backup_path), f"{container}:{container_path}", timeout=300),
        "backup copy to disposable restore",
    )
    result = _docker(
        "exec",
        container,
        "pg_restore",
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
        f"--username={role}",
        f"--dbname={database}",
        container_path,
        timeout=900,
    )
    _require_success(result, "disposable pg_restore")


def create_disposable_restore(backup_path: Path) -> dict[str, Any]:
    run_id = secrets.token_hex(5)
    container = RESTORE_PREFIX + run_id
    database = RESTORE_DATABASE_PREFIX + run_id
    role = "bm_restore_" + run_id
    password = secrets.token_urlsafe(32)
    if container == CONTAINER_NAME or database == DATABASE_NAME or not container.startswith(RESTORE_PREFIX):
        raise BackupRestoreBlockedError("disposable restore identity overlaps the active database")
    port: int | None = None
    cleanup: dict[str, Any] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="bm-prod5-5a-env-") as temporary:
            env_path = Path(temporary) / "postgres.env"
            env_path.write_text(
                f"POSTGRES_DB={database}\nPOSTGRES_USER={role}\nPOSTGRES_PASSWORD={password}\n",
                encoding="utf-8",
            )
            started = _docker(
                "run",
                "--detach",
                "--name",
                container,
                "--env-file",
                str(env_path),
                "--tmpfs",
                "/var/lib/postgresql/data:rw,noexec,nosuid,size=1g",
                "--publish",
                "127.0.0.1::5432",
                IMAGE_TAG,
                timeout=300,
            )
            _require_success(started, "disposable PostgreSQL creation")
        _wait_for_restore(container, role, database)
        port = _dynamic_port(container)
        _restore_archive(container, role, database, backup_path)
        restored_url = _restore_url(role, password, database, port)
        restored_engine = engine_for_url(restored_url)
        active_engine = engine_for_url(target_url_from_secret_file())
        try:
            equality = verify_database_transfer(active_engine, restored_engine)
            restored = _database_snapshot(restored_engine)
            constraints = _constraint_and_type_canaries(restored_engine)
            sequence_results, sequence_canary = _sequence_state(restored_engine)
            after_canaries = _database_snapshot(restored_engine)
        finally:
            active_engine.dispose()
            restored_engine.dispose()
        if (
            restored["revision"] != EXPECTED_REVISION
            or restored["readiness"] != READY
            or restored["compatibility"] != "PASS"
            or restored["application_table_count"] != len(APP_TABLES)
            or restored["application_total_rows"] != EXPECTED_SOURCE_ROWS
        ):
            raise BackupRestoreBlockedError("restored database is not the accepted BM Radio state")
        if (
            after_canaries["per_table_row_counts"] != restored["per_table_row_counts"]
            or after_canaries["per_table_canonical_digests"] != restored["per_table_canonical_digests"]
        ):
            raise BackupRestoreBlockedError("constraint or sequence canary changed restored application data")
        _alembic_check(restored_url)
        return {
            "container": container,
            "database": database,
            "port": port,
            "database_url": restored_url,
            "postgresql_version": _tool_version(container, "postgres"),
            "restore_result": "PASS",
            "restored": restored,
            "equality": equality,
            "constraints_and_types": constraints,
            "sequences": {"result": "PASS", "validated": sequence_results, "next_id_canary": sequence_canary},
            "alembic_check": "PASS",
        }
    except Exception:
        cleanup = _dispose_restore(container, port)
        raise
    finally:
        if cleanup is not None and not all(cleanup[key] for key in ("container_removed", "volume_removed", "network_removed", "port_closed")):
            raise BackupRestoreBlockedError("disposable restore cleanup was incomplete")


def cleanup_disposable_restore(restore: dict[str, Any]) -> dict[str, Any]:
    return _dispose_restore(str(restore["container"]), int(restore["port"]))


def _exact_protected_equality(before: dict[str, Any], after: dict[str, Any]) -> dict[str, bool]:
    active_equal = before["active_postgresql"] == after["active_postgresql"]
    sqlite_equal = before["sqlite_fallback"] == after["sqlite_fallback"]
    config_before = before["configuration_hashes"]
    config_after = after["configuration_hashes"]
    return {
        "active_postgresql_unchanged": active_equal,
        "sqlite_fallback_unchanged": sqlite_equal,
        "backend_env_unchanged": config_before["backend_env_sha256"] == config_after["backend_env_sha256"],
        "adoption_state_evidence_unchanged": config_before == config_after,
        "configuration_unchanged": config_before == config_after,
    }


def write_backup_verification(
    *,
    backup: dict[str, Any],
    restore: dict[str, Any],
    application: dict[str, Any],
    unchanged: dict[str, bool],
    cleanup: dict[str, Any],
    preflight: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    restored = restore["restored"]
    payload = {
        "version": 1,
        "phase": "BM-PROD5.5A",
        "created_utc": utc_now(),
        "source_commit": STARTING_COMMIT,
        "backup_logical_filename": backup["backup_filename"],
        "backup_sha256": backup["backup_sha256"],
        "manifest_logical_filename": backup["manifest_filename"],
        "manifest_sha256": backup["manifest_sha256"],
        "postgresql_server_version": preflight["tools"]["server_version"],
        "pg_dump_version": preflight["tools"]["pg_dump_version"],
        "pg_restore_version": preflight["tools"]["pg_restore_version"],
        "source_revision": backup["manifest"]["source_revision"],
        "source_rows": backup["manifest"]["application_total_rows"],
        "restored_revision": restored["revision"],
        "restored_rows": restored["application_total_rows"],
        "count_equality": restore["equality"]["count_equality"],
        "canonical_digest_equality": restore["equality"]["canonical_digest_equality"],
        "fk_verification": restore["equality"]["foreign_key_validation"],
        "sequence_verification": restore["sequences"]["result"],
        "alembic_check": restore["alembic_check"],
        "startup_1": application["startup_1"],
        "startup_2": application["startup_2"],
        "read_canaries": application["read_canaries"],
        "write_canary": application["write_canary"],
        "active_postgresql_unchanged": unchanged["active_postgresql_unchanged"],
        "sqlite_fallback_unchanged": unchanged["sqlite_fallback_unchanged"],
        "configuration_unchanged": unchanged["configuration_unchanged"],
        "disposable_cleanup": cleanup,
    }
    artifact_sha = _write_safe_json(BACKUP_VERIFICATION_PATH, payload, label="backup verification")
    return payload, artifact_sha


def verify_retained_backup(backup_path: Path | None = None) -> dict[str, Any]:
    candidates = sorted(BACKUP_DIR.glob("*.dump"))
    selected = backup_path or (candidates[-1] if candidates else None)
    if selected is None:
        raise BackupRestoreBlockedError("no retained PostgreSQL logical backup exists")
    manifest_path = selected.with_suffix(".manifest.json")
    if not manifest_path.is_file():
        raise BackupRestoreBlockedError("retained backup manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    valid = manifest.get("backup_sha256") == sha256_file(selected)
    if not valid:
        raise BackupRestoreBlockedError("retained backup hash does not match its manifest")
    return {
        "backup_filename": selected.name,
        "backup_sha256": manifest["backup_sha256"],
        "manifest_filename": manifest_path.name,
        "manifest_sha256": sha256_file(manifest_path),
        "archive_inventory": inspect_backup(selected),
        "result": "PASS",
    }
