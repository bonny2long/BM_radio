from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from typing import Any

from sqlalchemy import create_engine, inspect

from .database_readiness import DATABASE_UNREACHABLE, inspect_database_readiness
from .local_postgres_adoption import (
    ADOPTION_VERIFICATION_PATH,
    BACKEND_ENV_BEFORE_PATH,
    BACKEND_ENV_PATH,
    CONTAINER_NAME,
    DATA_MOUNT,
    DATABASE_NAME,
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
    target_url_from_secret_file,
    utc_now,
)
from .migration_contract import APP_TABLES, engine_for_url
from .postgres_backup_restore import (
    BACKUP_DIR,
    BACKUP_VERIFICATION_PATH,
    EXPECTED_REVISION,
    EXPECTED_SOURCE_ROWS,
    FORBIDDEN_EVIDENCE_TOKENS,
    MEDIA_ROOT_KEYS,
    STARTING_COMMIT as PROD5_5A_STARTING_COMMIT,
    BackupRestoreBlockedError,
    _alembic_check,
    _constraint_and_type_canaries,
    _database_snapshot,
    _dynamic_port,
    _process_quiescence,
    _restore_url,
    _run,
    _safe_json,
    _sequence_state,
    _validate_archive_listing,
    _wait_for_restore,
    _write_safe_json,
    protected_snapshot,
    sha256_file,
)


STARTING_COMMIT = "789964e841ad06663e96e02f57cb53b259c93283"
RECOVERY_APPROVAL = "APPROVE-BM-PROD5.5B-COLD-RECOVERY"
ACCEPTED_BACKUP_FILENAME = "bm_radio.postgres.logical.20260816T221250Z.8268bb.dump"
ACCEPTED_BACKUP_SHA256 = "32cedd69db4927756b61795e793f0a919f4856cd54195cc953c635cda67cadfe"
ACCEPTED_MANIFEST_FILENAME = "bm_radio.postgres.logical.20260816T221250Z.8268bb.manifest.json"
ACCEPTED_MANIFEST_SHA256 = "3d33ecd199ca19abfbc8ab8799c07525d44723d22f50f0e965673fc47af66327"
ACCEPTED_BACKUP_VERIFICATION_SHA256 = "ee70daf7f74bcadc460c7f365c016f74ac72a875d8bb59de2345fb83daa46c56"
ACCEPTED_INVENTORY_SHA256 = "8cae3d6fd0a4780c1418541fd3b89cc66bfb270a5075f3ee71436efec2ac9da1"
ACCEPTED_SQLITE_SHA256 = "e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619"
ACCEPTED_SQLITE_SCHEMA_FINGERPRINT = "bd34f4cf845273954a42a4febd9d0340ae52d221f8f07b9b77eeb3cd04125678"
BACKUP_PATH = BACKUP_DIR / ACCEPTED_BACKUP_FILENAME
MANIFEST_PATH = BACKUP_DIR / ACCEPTED_MANIFEST_FILENAME
RECOVERY_VERIFICATION_PATH = BACKUP_VERIFICATION_PATH.parent / "recovery_rehearsal_verification.json"
RECOVERY_CONTAINER_PREFIX = "bm-prod5-5b-recovery-"
RECOVERY_VOLUME_PREFIX = "bm-prod5-5b-recovery-data-"
HELPER_CONTAINER_PREFIX = "bm-prod5-5b-helper-"
RECOVERY_ROLE_PREFIX = "bm_radio_app_recovery_"
RECOVERY_CREDENTIAL_PREFIX = "recovery_credentials_"


class RecoveryBlockedError(BackupRestoreBlockedError):
    """Fail-closed cold-recovery error with privacy-safe messages."""


def _docker(*arguments: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return _run(["docker", *arguments], timeout=timeout)


def _require_success(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        raise RecoveryBlockedError(f"{label} failed")
    return result.stdout.strip()


def _git_head() -> str:
    return _require_success(_run(["git", "rev-parse", "HEAD"], cwd=BACKEND_ENV_PATH.parents[1]), "Git HEAD inspection")


def _inventory_sha(snapshot: dict[str, Any]) -> str:
    payload = {
        "counts": snapshot["per_table_row_counts"],
        "digests": snapshot["per_table_canonical_digests"],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RecoveryBlockedError(f"{label} is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryBlockedError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise RecoveryBlockedError(f"{label} is invalid")
    return payload


def _privacy_check(payload: dict[str, Any], label: str) -> None:
    encoded = json.dumps(payload, sort_keys=True).lower()
    if any(token in encoded for token in FORBIDDEN_EVIDENCE_TOKENS):
        raise RecoveryBlockedError(f"{label} contains forbidden private data")


def volume_identity(name: str = VOLUME_NAME) -> dict[str, Any]:
    result = _docker("volume", "inspect", name)
    if result.returncode != 0:
        return {"exists": False, "name": name}
    try:
        raw = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise RecoveryBlockedError("Docker volume identity is invalid") from exc
    safe = {
        "exists": True,
        "name": str(raw.get("Name")),
        "driver": str(raw.get("Driver")),
        "scope": str(raw.get("Scope")),
        "created_at": str(raw.get("CreatedAt")),
        "labels": dict(raw.get("Labels") or {}),
        "options": dict(raw.get("Options") or {}),
    }
    safe["identity_sha256"] = hashlib.sha256(
        json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return safe


def active_container_identity() -> dict[str, Any]:
    result = _docker("container", "inspect", CONTAINER_NAME)
    if result.returncode != 0:
        return {"exists": False, "name": CONTAINER_NAME}
    try:
        raw = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise RecoveryBlockedError("active container identity is invalid") from exc
    mounts = [
        {
            "type": item.get("Type"),
            "name": item.get("Name"),
            "destination": item.get("Destination"),
        }
        for item in raw.get("Mounts", [])
    ]
    return {
        "exists": True,
        "name": str(raw.get("Name", "")).lstrip("/"),
        "container_id": str(raw.get("Id")),
        "image": str(raw.get("Config", {}).get("Image")),
        "created": str(raw.get("Created")),
        "mounts": mounts,
    }


def _remove_helper(container: str) -> None:
    if not container.startswith(HELPER_CONTAINER_PREFIX):
        raise RecoveryBlockedError("refusing to remove a non-helper container")
    if _docker("container", "inspect", container).returncode == 0:
        _require_success(_docker("container", "rm", "-f", container, timeout=120), "archive helper cleanup")


def independent_archive_inspection(backup_path: Path = BACKUP_PATH) -> dict[str, Any]:
    """Inspect with a task-scoped PostgreSQL 16 helper, never the active container."""
    helper = HELPER_CONTAINER_PREFIX + secrets.token_hex(5)
    container_path = f"/tmp/{backup_path.name}"
    try:
        started = _docker(
            "run",
            "--detach",
            "--name",
            helper,
            "--entrypoint",
            "tail",
            IMAGE_TAG,
            "-f",
            "/dev/null",
            timeout=300,
        )
        _require_success(started, "PostgreSQL 16 archive helper creation")
        _require_success(
            _docker("cp", str(backup_path), f"{helper}:{container_path}", timeout=300),
            "retained backup copy to independent helper",
        )
        version = _require_success(
            _docker("exec", helper, "pg_restore", "--version"),
            "independent pg_restore version inspection",
        )
        if "PostgreSQL) 16." not in version:
            raise RecoveryBlockedError("independent archive helper is not PostgreSQL 16")
        listing = _require_success(
            _docker("exec", helper, "pg_restore", "--list", container_path, timeout=300),
            "independent retained-archive inspection",
        )
        return {"tool": version, "independent_of_active_container": True, **_validate_archive_listing(listing)}
    finally:
        _remove_helper(helper)


def verify_retained_recovery_input(*, inspect_archive: bool) -> dict[str, Any]:
    hashes = {
        "backup_sha256": sha256_file(BACKUP_PATH) if BACKUP_PATH.is_file() else None,
        "manifest_sha256": sha256_file(MANIFEST_PATH) if MANIFEST_PATH.is_file() else None,
        "backup_verification_sha256": sha256_file(BACKUP_VERIFICATION_PATH)
        if BACKUP_VERIFICATION_PATH.is_file()
        else None,
    }
    expected = {
        "backup_sha256": ACCEPTED_BACKUP_SHA256,
        "manifest_sha256": ACCEPTED_MANIFEST_SHA256,
        "backup_verification_sha256": ACCEPTED_BACKUP_VERIFICATION_SHA256,
    }
    if hashes != expected:
        raise RecoveryBlockedError("retained 5.5A backup evidence hash mismatch")
    if BACKUP_PATH.read_bytes()[:5] != b"PGDMP":
        raise RecoveryBlockedError("retained backup is not PostgreSQL custom format")
    manifest = _load_json(MANIFEST_PATH, "retained backup manifest")
    verification = _load_json(BACKUP_VERIFICATION_PATH, "5.5A backup verification")
    _privacy_check(manifest, "retained backup manifest")
    _privacy_check(verification, "5.5A backup verification")
    if (
        manifest.get("logical_backup_filename") != ACCEPTED_BACKUP_FILENAME
        or manifest.get("backup_sha256") != ACCEPTED_BACKUP_SHA256
        or manifest.get("source_revision") != EXPECTED_REVISION
        or manifest.get("application_table_count") != len(APP_TABLES)
        or manifest.get("application_total_rows") != EXPECTED_SOURCE_ROWS
        or verification.get("backup_sha256") != ACCEPTED_BACKUP_SHA256
        or verification.get("manifest_sha256") != ACCEPTED_MANIFEST_SHA256
        or verification.get("restored_revision") != EXPECTED_REVISION
        or verification.get("restored_rows") != EXPECTED_SOURCE_ROWS
    ):
        raise RecoveryBlockedError("retained 5.5A backup metadata does not match accepted recovery input")
    archive = independent_archive_inspection() if inspect_archive else {"result": "not_run"}
    return {
        "backup_filename": ACCEPTED_BACKUP_FILENAME,
        **hashes,
        "manifest_revision": manifest["source_revision"],
        "manifest_tables": manifest["application_table_count"],
        "manifest_rows": manifest["application_total_rows"],
        "manifest_counts": manifest["per_table_row_counts"],
        "manifest_digests": manifest["per_table_canonical_digests"],
        "archive_inventory": archive,
    }


def pre_recovery_gate() -> dict[str, Any]:
    blockers: list[str] = []
    head = _git_head()
    if head != STARTING_COMMIT:
        blockers.append("Git HEAD is not the accepted BM-PROD5.5A implementation commit")
    docker = docker_context_status()
    if not (docker.get("available") and docker.get("local") and docker.get("linux")):
        blockers.append("a reachable local Docker Linux engine is required")
    persistent = container_status() if docker.get("available") and docker.get("local") else {}
    if not all(persistent.get(key) for key in ("exists", "running", "healthy", "loopback_binding", "named_volume")):
        blockers.append("active PostgreSQL container identity, health, binding, or volume is invalid")
    volume = volume_identity() if docker.get("available") and docker.get("local") else {"exists": False}
    if not volume.get("exists") or volume.get("name") != VOLUME_NAME:
        blockers.append("active PostgreSQL named volume identity is invalid")
    configuration = env_target_summary()
    state = read_state()
    if configuration.get("dialect") != "postgresql" or configuration.get("driver") != "psycopg":
        blockers.append("backend/.env is not adopted to PostgreSQL/Psycopg")
    if (
        state.get("phase") != "BM-PROD5.4C.3B"
        or state.get("application_adopted") is not True
        or state.get("active_database") != "postgresql"
    ):
        blockers.append("active adoption state is invalid")
    quiescence = _process_quiescence()
    if not quiescence.get("inspectable"):
        blockers.append("BM Radio backend writer inventory is unavailable")
    elif quiescence.get("writer_detected"):
        blockers.append("an active BM Radio backend writer is running")

    backup: dict[str, Any] = {}
    snapshot: dict[str, Any] = {}
    active_database: dict[str, Any] = {}
    try:
        backup = verify_retained_recovery_input(inspect_archive=True)
    except (RecoveryBlockedError, OSError) as exc:
        blockers.append(str(exc))
    if not blockers:
        snapshot = protected_snapshot()
        active = snapshot["active_postgresql"]
        sqlite = snapshot["sqlite_fallback"]
        active_database = database_verification()
        if (
            active_database.get("server_major") != POSTGRES_MAJOR
            or active["revision"] != EXPECTED_REVISION
            or active["readiness"] != "ready"
            or active["compatibility"] != "PASS"
            or active["application_table_count"] != len(APP_TABLES)
            or active["application_total_rows"] != EXPECTED_SOURCE_ROWS
            or _inventory_sha(active) != ACCEPTED_INVENTORY_SHA256
            or active["per_table_row_counts"] != backup["manifest_counts"]
            or active["per_table_canonical_digests"] != backup["manifest_digests"]
        ):
            blockers.append("active PostgreSQL does not match accepted 5.5A recovery evidence")
        if (
            sqlite.get("sha256") != ACCEPTED_SQLITE_SHA256
            or sqlite.get("schema_fingerprint") != ACCEPTED_SQLITE_SCHEMA_FINGERPRINT
            or sqlite["revision"] != EXPECTED_REVISION
            or sqlite["application_total_rows"] != EXPECTED_SOURCE_ROWS
            or _inventory_sha(sqlite) != ACCEPTED_INVENTORY_SHA256
        ):
            blockers.append("SQLite fallback does not match accepted 5.5A evidence")
        try:
            _alembic_check(target_url_from_secret_file())
        except BackupRestoreBlockedError as exc:
            blockers.append(str(exc))

    return {
        "gate": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "source_commit": head,
        "docker": {"context": docker.get("context"), "local": docker.get("local"), "linux": docker.get("linux")},
        "active_container": persistent,
        "active_container_identity": active_container_identity() if persistent.get("exists") else {"exists": False},
        "active_volume_identity": volume,
        "active_database": active_database,
        "active_configuration": {
            "dialect": configuration.get("dialect"),
            "driver": configuration.get("driver"),
            "backend_env_sha256": sha256_path(BACKEND_ENV_PATH),
        },
        "adoption_state": {
            "phase": state.get("phase"),
            "application_adopted": state.get("application_adopted"),
            "active_database": state.get("active_database"),
        },
        "quiescence": quiescence,
        "retained_backup": backup,
        "protected_snapshot": snapshot,
        "interruption_approved": False,
    }


def _port_closed(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex((HOST, port)) != 0


def stop_active_container() -> dict[str, Any]:
    """The only permitted active outage operation; never removes the container or volume."""
    _require_success(_docker("stop", CONTAINER_NAME, timeout=120), "active PostgreSQL stop")
    current = container_status()
    volume = volume_identity()
    if not current.get("exists") or current.get("running") or not volume.get("exists"):
        raise RecoveryBlockedError("active PostgreSQL stop did not preserve container and volume")
    if not _port_closed(HOST_PORT):
        raise RecoveryBlockedError("active PostgreSQL port remained open after stop")
    return {"container_stopped": True, "container_retained": True, "volume_retained": True, "port_55432_closed": True}


def start_active_container() -> None:
    if not container_status().get("exists"):
        raise RecoveryBlockedError("active PostgreSQL container is missing and cannot be restarted safely")
    if not container_status().get("running"):
        _require_success(_docker("start", CONTAINER_NAME, timeout=120), "active PostgreSQL restart")
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        current = container_status()
        if current.get("running") and current.get("healthy"):
            return
        time.sleep(1)
    raise RecoveryBlockedError("original active PostgreSQL did not return healthy")


def prove_active_unreachable() -> dict[str, Any]:
    if not _port_closed(HOST_PORT):
        raise RecoveryBlockedError("active PostgreSQL port is still reachable during outage")
    engine = create_engine(target_url_from_secret_file(), connect_args={"connect_timeout": 3})
    try:
        readiness = inspect_database_readiness(engine)
    finally:
        engine.dispose()
    if readiness.status != DATABASE_UNREACHABLE:
        raise RecoveryBlockedError("adopted active database was not proven unavailable")
    return {"readiness": DATABASE_UNREACHABLE, "port_55432_closed": True}


def _safe_recovery_names(run_id: str) -> dict[str, str]:
    names = {
        "container_a": f"{RECOVERY_CONTAINER_PREFIX}{run_id}-a",
        "container_b": f"{RECOVERY_CONTAINER_PREFIX}{run_id}-b",
        "volume": f"{RECOVERY_VOLUME_PREFIX}{run_id}",
        "database": DATABASE_NAME,
        "role": f"{RECOVERY_ROLE_PREFIX}{run_id}",
    }
    if (
        names["container_a"] == CONTAINER_NAME
        or names["container_b"] == CONTAINER_NAME
        or names["volume"] == VOLUME_NAME
        or not names["container_a"].startswith(RECOVERY_CONTAINER_PREFIX)
        or not names["container_b"].startswith(RECOVERY_CONTAINER_PREFIX)
        or not names["volume"].startswith(RECOVERY_VOLUME_PREFIX)
    ):
        raise RecoveryBlockedError("recovery resource identity overlaps active resources")
    return names


def _write_recovery_credentials(run_id: str, database: str, role: str, password: str) -> Path:
    path = BACKUP_VERIFICATION_PATH.parent / f"{RECOVERY_CREDENTIAL_PREFIX}{run_id}.env"
    path.write_text(
        f"POSTGRES_DB={database}\nPOSTGRES_USER={role}\nPOSTGRES_PASSWORD={password}\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _run_recovery_container(container: str, volume: str, credentials: Path) -> int:
    if not container.startswith(RECOVERY_CONTAINER_PREFIX) or not volume.startswith(RECOVERY_VOLUME_PREFIX):
        raise RecoveryBlockedError("recovery container/volume prefix guard failed")
    started = _docker(
        "run",
        "--detach",
        "--name",
        container,
        "--env-file",
        str(credentials),
        "--mount",
        f"type=volume,source={volume},target={DATA_MOUNT}",
        "--publish",
        "127.0.0.1::5432",
        IMAGE_TAG,
        timeout=300,
    )
    _require_success(started, "recovery PostgreSQL container creation")
    return _dynamic_port(container)


def create_recovery_target() -> dict[str, Any]:
    run_id = secrets.token_hex(5)
    names = _safe_recovery_names(run_id)
    password = secrets.token_urlsafe(32)
    credentials = _write_recovery_credentials(run_id, names["database"], names["role"], password)
    resource: dict[str, Any] = {
        **names,
        "password": password,
        "credential_path": credentials,
    }
    try:
        created = _docker("volume", "create", names["volume"])
        _require_success(created, "recovery named volume creation")
        port_a = _run_recovery_container(names["container_a"], names["volume"], credentials)
        resource["port_a"] = port_a
        if port_a == HOST_PORT:
            raise RecoveryBlockedError("recovery target reused active PostgreSQL host port")
        _wait_for_restore(names["container_a"], names["role"], names["database"])
        url_a = _restore_url(names["role"], password, names["database"], port_a)
        resource["url_a"] = url_a
        engine = engine_for_url(url_a)
        try:
            existing = set(inspect(engine).get_table_names()) & set(APP_TABLES)
        finally:
            engine.dispose()
        if existing:
            raise RecoveryBlockedError("new recovery named volume was not an empty database")
        resource.update({
            "postgresql_version": _require_success(
            _docker("exec", names["container_a"], "postgres", "--version"),
            "recovery PostgreSQL version inspection",
        ),
            "volume_identity": volume_identity(names["volume"]),
        })
        return resource
    except Exception:
        cleanup_recovery_resources(resource)
        raise


def restore_retained_backup(resource: dict[str, Any]) -> None:
    container = str(resource["container_a"])
    if not container.startswith(RECOVERY_CONTAINER_PREFIX) or container == CONTAINER_NAME:
        raise RecoveryBlockedError("restore container identity is unsafe")
    container_path = f"/tmp/{ACCEPTED_BACKUP_FILENAME}"
    _require_success(
        _docker("cp", str(BACKUP_PATH), f"{container}:{container_path}", timeout=300),
        "retained backup copy to recovery container",
    )
    restored = _docker(
        "exec",
        container,
        "pg_restore",
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
        f"--username={resource['role']}",
        f"--dbname={resource['database']}",
        container_path,
        timeout=900,
    )
    _require_success(restored, "cold recovery pg_restore")


def verify_recovered_database(database_url: str, retained: dict[str, Any]) -> dict[str, Any]:
    engine = engine_for_url(database_url)
    try:
        snapshot = _database_snapshot(engine)
        if (
            snapshot["revision"] != EXPECTED_REVISION
            or snapshot["readiness"] != "ready"
            or snapshot["compatibility"] != "PASS"
            or snapshot["application_table_count"] != len(APP_TABLES)
            or snapshot["application_total_rows"] != EXPECTED_SOURCE_ROWS
            or snapshot["per_table_row_counts"] != retained["manifest_counts"]
            or snapshot["per_table_canonical_digests"] != retained["manifest_digests"]
        ):
            raise RecoveryBlockedError("recovered database does not exactly match retained manifest")
        constraints = _constraint_and_type_canaries(engine)
        sequence_results, next_id_canary = _sequence_state(engine)
        after_canaries = _database_snapshot(engine)
    finally:
        engine.dispose()
    if (
        after_canaries["per_table_row_counts"] != retained["manifest_counts"]
        or after_canaries["per_table_canonical_digests"] != retained["manifest_digests"]
    ):
        raise RecoveryBlockedError("recovery validation canary left database residue")
    _alembic_check(database_url)
    return {
        "snapshot": snapshot,
        "count_equality": True,
        "canonical_digest_equality": True,
        "foreign_key_validation": snapshot["foreign_key_validation"],
        "constraints_and_types": constraints,
        "sequence_verification": "PASS",
        "sequence_count": len(sequence_results),
        "next_id_canary": next_id_canary,
        "alembic_check": "PASS",
    }


def recreate_from_recovery_volume(resource: dict[str, Any]) -> dict[str, Any]:
    container_a = str(resource["container_a"])
    volume = str(resource["volume"])
    if not container_a.startswith(RECOVERY_CONTAINER_PREFIX) or not volume.startswith(RECOVERY_VOLUME_PREFIX):
        raise RecoveryBlockedError("container-loss simulation prefix guard failed")
    _require_success(_docker("stop", container_a, timeout=120), "recovery container A stop")
    _require_success(_docker("container", "rm", container_a, timeout=120), "recovery container A removal")
    if _docker("volume", "inspect", volume).returncode != 0:
        raise RecoveryBlockedError("recovery named volume did not survive container A removal")
    port_b = _run_recovery_container(str(resource["container_b"]), volume, Path(resource["credential_path"]))
    if port_b == HOST_PORT or port_b == int(resource["port_a"]):
        raise RecoveryBlockedError("recovery container B did not receive a new safe dynamic port")
    _wait_for_restore(str(resource["container_b"]), str(resource["role"]), str(resource["database"]))
    url_b = _restore_url(str(resource["role"]), str(resource["password"]), str(resource["database"]), port_b)
    resource.update({"container_a_removed": True, "recovery_volume_retained": True, "port_b": port_b, "url_b": url_b})
    return resource


def cleanup_recovery_resources(resource: dict[str, Any] | None) -> dict[str, Any]:
    if resource is None:
        return {"container_a_removed": True, "container_b_removed": True, "volume_removed": True, "ports_closed": True, "credentials_removed": True}
    for key in ("container_a", "container_b"):
        name = str(resource.get(key) or "")
        if name:
            if not name.startswith(RECOVERY_CONTAINER_PREFIX) or name == CONTAINER_NAME:
                raise RecoveryBlockedError("refusing to remove a non-recovery container")
            if _docker("container", "inspect", name).returncode == 0:
                _require_success(_docker("container", "rm", "-f", name, timeout=120), "recovery container cleanup")
    volume = str(resource.get("volume") or "")
    if volume:
        if not volume.startswith(RECOVERY_VOLUME_PREFIX) or volume == VOLUME_NAME:
            raise RecoveryBlockedError("refusing to delete a non-recovery-prefixed volume")
        if _docker("volume", "inspect", volume).returncode == 0:
            _require_success(_docker("volume", "rm", volume, timeout=120), "recovery named volume cleanup")
    credential_path = resource.get("credential_path")
    if credential_path:
        Path(credential_path).unlink(missing_ok=True)
    ports = [int(resource[key]) for key in ("port_a", "port_b") if resource.get(key) is not None]
    return {
        "container_a_removed": not resource.get("container_a")
        or _docker("container", "inspect", str(resource["container_a"])).returncode != 0,
        "container_b_removed": not resource.get("container_b")
        or _docker("container", "inspect", str(resource["container_b"])).returncode != 0,
        "volume_removed": not volume or _docker("volume", "inspect", volume).returncode != 0,
        "ports_closed": all(_port_closed(port) for port in ports),
        "credentials_removed": not credential_path or not Path(credential_path).exists(),
        "helper_resources_removed": True,
    }


def protected_hashes() -> dict[str, str | None]:
    return {
        "backend_env_sha256": sha256_path(BACKEND_ENV_PATH),
        "state_sha256": sha256_path(STATE_PATH),
        "transfer_verification_sha256": sha256_path(TRANSFER_VERIFICATION_PATH),
        "adoption_verification_sha256": sha256_path(ADOPTION_VERIFICATION_PATH),
        "backup_verification_sha256": sha256_path(BACKUP_VERIFICATION_PATH),
        "backend_env_before_sha256": sha256_path(BACKEND_ENV_BEFORE_PATH),
        "sqlite_sha256": sha256_path(REAL_SQLITE_PATH),
    }


def write_recovery_verification(payload: dict[str, Any]) -> str:
    _privacy_check(payload, "recovery rehearsal verification")
    return _write_safe_json(RECOVERY_VERIFICATION_PATH, payload, label="recovery rehearsal verification")


def recovery_status() -> dict[str, Any]:
    active = container_status()
    active_volume = volume_identity()
    containers = _docker("container", "ls", "-a", "--filter", f"name={RECOVERY_CONTAINER_PREFIX}", "--format", "{{.Names}}")
    volumes = _docker("volume", "ls", "--filter", f"name={RECOVERY_VOLUME_PREFIX}", "--format", "{{.Name}}")
    helpers = _docker("container", "ls", "-a", "--filter", f"name={HELPER_CONTAINER_PREFIX}", "--format", "{{.Names}}")
    return {
        "active_container": active,
        "active_volume_identity": active_volume,
        "recovery_containers": sorted(item for item in containers.stdout.splitlines() if item),
        "recovery_volumes": sorted(item for item in volumes.stdout.splitlines() if item),
        "helper_containers": sorted(item for item in helpers.stdout.splitlines() if item),
    }
