from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import URL, make_url

from .database_dialect import classify_database_url, require_supported_database_url
from .database_readiness import DATABASE_UNREACHABLE, READY, UNINITIALIZED, inspect_database_readiness, migration_head
from .migration_contract import APP_TABLES, compare_schema, engine_for_url, row_counts
from .sqlite_adoption import application_row_count, sha256_file, snapshot_sqlite_database, sqlite_foreign_key_violations


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
REAL_SQLITE_PATH = BACKEND_ROOT / "bm_radio.db"
BACKEND_ENV_PATH = BACKEND_ROOT / ".env"
LOCAL_STATE_DIR = BACKEND_ROOT / ".local_postgres"
POSTGRES_ENV_PATH = LOCAL_STATE_DIR / "postgres.env"
STATE_PATH = LOCAL_STATE_DIR / "state.json"
BACKEND_ENV_BEFORE_PATH = LOCAL_STATE_DIR / "backend_env.before"
TRANSFER_VERIFICATION_PATH = LOCAL_STATE_DIR / "transfer_verification.json"
ADOPTION_VERIFICATION_PATH = LOCAL_STATE_DIR / "adoption_verification.json"
BACKUP_DIR = BACKEND_ROOT / ".local_backups"
ACCEPTED_REHEARSAL_REPORT = BACKEND_ROOT / "tmp_tests" / "prod5_4c_2" / "transfer_rehearsal_report.json"

CONTAINER_NAME = "bm-radio-postgres-dev"
VOLUME_NAME = "bm-radio-postgres-dev-data"
DATABASE_NAME = "bm_radio"
APPLICATION_ROLE = "bm_radio_app"
POSTGRES_MAJOR = 16
IMAGE_TAG = "postgres:16"
HOST = "127.0.0.1"
HOST_PORT = 55432
CONTAINER_PORT = 5432
DATA_MOUNT = "/var/lib/postgresql/data"

ADOPT_CONFIRMATION = "APPROVE-BM-PROD5.4C-LOCAL-POSTGRES"
DESTROY_CONFIRMATION = "DESTROY-BM-RADIO-LOCAL-POSTGRES-DATA"
PERSISTENT_TRANSFER_CONFIRMATION = "APPROVE-BM-PROD5.4C.3A-PERSISTENT-CREATION"
EXPECTED_SOURCE_SHA256 = "e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619"
EXPECTED_SOURCE_SCHEMA_FINGERPRINT = "bd34f4cf845273954a42a4febd9d0340ae52d221f8f07b9b77eeb3cd04125678"
EXPECTED_SOURCE_REVISION = "0001_current_schema_baseline"
EXPECTED_SOURCE_ROWS = 1257
EXPECTED_BACKEND_ENV_SHA256 = "a668b6dc50b63ab6e23e5ccb0b743ccd41c581eecdf0e94dfef94f826441db3e"
EXPECTED_PROD5_4C_3A_COMMIT = "65157583b3b0c8ab74c3c08b697e9da114f114d9"
_RESOURCE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]+$")


class AdoptionBlockedError(RuntimeError):
    """A fail-closed operator safety decision, safe to display."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 60) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return CommandResult(127, "", type(exc).__name__)
    return CommandResult(completed.returncode, completed.stdout.strip(), completed.stderr.strip())


def _docker(*args: str, timeout: int = 60) -> CommandResult:
    return _run(["docker", *args], timeout=timeout)


def validate_resource_names() -> None:
    for kind, value in (("container", CONTAINER_NAME), ("volume", VOLUME_NAME)):
        if not _RESOURCE_NAME.fullmatch(value):
            raise AdoptionBlockedError(f"unsafe persistent {kind} name")


def docker_context_status() -> dict[str, Any]:
    """Classify Docker without changing contexts, images, or resources."""
    if shutil.which("docker") is None:
        return {"cli": False, "available": False, "context": None, "endpoint_class": "unavailable", "local": False, "linux": False, "reason": "Docker CLI unavailable"}

    current = _docker("context", "show")
    if current.returncode != 0 or not current.stdout:
        return {"cli": True, "available": False, "context": None, "endpoint_class": "unavailable", "local": False, "linux": False, "reason": "local Docker engine unavailable"}

    context = current.stdout.splitlines()[0].strip()
    inspected = _docker("context", "inspect", context)
    if inspected.returncode != 0:
        return {"cli": True, "available": False, "context": context, "endpoint_class": "unknown", "local": False, "linux": False, "reason": "Docker context inspection failed"}
    try:
        payload = json.loads(inspected.stdout)[0]
        endpoint = str(payload["Endpoints"]["docker"]["Host"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return {"cli": True, "available": False, "context": context, "endpoint_class": "unknown", "local": False, "linux": False, "reason": "Docker context endpoint is not classifiable"}

    lowered = endpoint.lower()
    is_local = lowered.startswith(("npipe://", "unix://")) and not lowered.startswith(("tcp://", "ssh://"))
    endpoint_class = "local" if is_local else "remote-or-unsupported"
    if not is_local:
        return {"cli": True, "available": True, "context": context, "endpoint_class": endpoint_class, "local": False, "linux": False, "reason": "Docker context is not local"}

    info = _docker("info", "--format", "{{.OSType}}")
    if info.returncode != 0:
        return {"cli": True, "available": False, "context": context, "endpoint_class": endpoint_class, "local": True, "linux": False, "reason": "local Docker engine unavailable"}
    linux = info.stdout.strip().lower() == "linux"
    return {
        "cli": True,
        "available": True,
        "context": context,
        "endpoint_class": endpoint_class,
        "local": True,
        "linux": linux,
        "reason": None if linux else "Docker server is not using Linux containers",
    }


def docker_resource_exists(kind: str, name: str) -> bool:
    if kind not in {"container", "volume"}:
        raise ValueError("Docker resource kind must be container or volume")
    result = _docker("container" if kind == "container" else "volume", "inspect", name)
    return result.returncode == 0


def postgres_image_status() -> dict[str, Any]:
    result = _docker("image", "inspect", IMAGE_TAG)
    return {"tag": IMAGE_TAG, "official": True, "available_locally": result.returncode == 0, "identified": True}


def loopback_port_state(port: int = HOST_PORT) -> str:
    """Return free or occupied using loopback only; never binds a public interface."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        probe.bind((HOST, port))
    except OSError:
        return "occupied"
    finally:
        probe.close()
    return "free"


def is_git_ignored(path: Path) -> bool:
    result = _run(["git", "check-ignore", "-q", str(path)], cwd=PROJECT_ROOT)
    return result.returncode == 0


def psycopg_declared_and_installed() -> dict[str, bool]:
    requirements = (BACKEND_ROOT / "requirements.txt").read_text(encoding="utf-8", errors="replace").lower()
    declared = any(line.strip().startswith("psycopg") for line in requirements.splitlines())
    try:
        import psycopg  # noqa: F401
    except ImportError:
        installed = False
    else:
        installed = True
    return {"declared": declared, "installed": installed}


def build_database_url(password: str) -> str:
    return URL.create(
        "postgresql+psycopg",
        username=APPLICATION_ROLE,
        password=password,
        host=HOST,
        port=HOST_PORT,
        database=DATABASE_NAME,
    ).render_as_string(hide_password=False)


def safe_target_display(database_url: str) -> str:
    return require_supported_database_url(database_url).safe_display


def generate_secret() -> str:
    return secrets.token_urlsafe(48)


def _secret_env_text(secret: str) -> str:
    if not secret or "\n" in secret or "\r" in secret:
        raise ValueError("invalid generated secret")
    return f"POSTGRES_DB={DATABASE_NAME}\nPOSTGRES_USER={APPLICATION_ROLE}\nPOSTGRES_PASSWORD={secret}\n"


def write_secret_environment(secret: str, *, directory: Path = LOCAL_STATE_DIR, path: Path = POSTGRES_ENV_PATH) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise AdoptionBlockedError("local PostgreSQL credential file already exists")
    path.write_text(_secret_env_text(secret), encoding="utf-8")
    try:
        os.chmod(directory, 0o700)
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_secret_environment(path: Path = POSTGRES_ENV_PATH) -> dict[str, str]:
    if not path.is_file():
        raise AdoptionBlockedError("local PostgreSQL credential file is missing")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value
    expected = {"POSTGRES_DB": DATABASE_NAME, "POSTGRES_USER": APPLICATION_ROLE}
    if any(values.get(key) != value for key, value in expected.items()) or not values.get("POSTGRES_PASSWORD"):
        raise AdoptionBlockedError("local PostgreSQL credential file does not match the fixed target")
    return values


def target_url_from_secret_file(path: Path = POSTGRES_ENV_PATH) -> str:
    return build_database_url(read_secret_environment(path)["POSTGRES_PASSWORD"])


def sqlite_snapshot() -> dict[str, Any]:
    if not REAL_SQLITE_PATH.is_file():
        return {"exists": False}
    snapshot = snapshot_sqlite_database(REAL_SQLITE_PATH, logical_path="backend/bm_radio.db")
    return {
        "exists": True,
        "integrity": snapshot.integrity_check,
        "quick_check": snapshot.quick_check,
        "readiness": snapshot.readiness_status,
        "ready": snapshot.readiness_ready,
        "compatibility": snapshot.compatibility,
        "revision": snapshot.current_revision,
        "head_revision": snapshot.head_revision,
        "application_table_count": len(snapshot.application_tables),
        "application_row_count": application_row_count(snapshot),
        "schema_fingerprint": snapshot.schema_fingerprint,
        "sha256": snapshot.sha256,
    }


def _read_env_database_url(path: Path = BACKEND_ENV_PATH) -> str | None:
    if not path.is_file():
        return None
    matches: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped.startswith("BM_RADIO_DB_URL="):
            matches.append(stripped.split("=", 1)[1])
    if len(matches) > 1:
        raise AdoptionBlockedError("backend/.env contains duplicate BM_RADIO_DB_URL entries")
    return matches[0] if matches else None


def env_target_summary(path: Path = BACKEND_ENV_PATH) -> dict[str, Any]:
    value = _read_env_database_url(path)
    if value is None:
        return {"exists": path.is_file(), "configured": False, "dialect": None, "driver": None, "safe_display": None}
    target = classify_database_url(value)
    return {"exists": True, "configured": True, "dialect": target.dialect, "driver": target.driver, "safe_display": target.safe_display}


def replace_database_target(original: bytes, target_url: str) -> bytes:
    """Replace exactly one DB target line while preserving all unrelated bytes."""
    text_value = original.decode("utf-8")
    newline = "\r\n" if "\r\n" in text_value else "\n"
    lines = text_value.splitlines()
    matches = [index for index, line in enumerate(lines) if line.strip().startswith("BM_RADIO_DB_URL=") and not line.lstrip().startswith("#")]
    if len(matches) != 1:
        raise AdoptionBlockedError("backend/.env must contain exactly one active BM_RADIO_DB_URL line")
    index = matches[0]
    prefix = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    lines[index] = f"{prefix}BM_RADIO_DB_URL={target_url}"
    trailing = newline if text_value.endswith(("\n", "\r")) else ""
    return (newline.join(lines) + trailing).encode("utf-8")


def _redacted_state(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, sort_keys=True)
    lowered = encoded.lower()
    if "postgres_password" in lowered or "postgresql+psycopg://" in lowered:
        raise ValueError("state metadata contains a forbidden credential or raw database URL")
    return payload


def write_state(payload: dict[str, Any], *, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = _redacted_state(payload)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AdoptionBlockedError("local PostgreSQL state metadata is invalid")
    return _redacted_state(payload)


def container_status() -> dict[str, Any]:
    inspected = _docker("container", "inspect", CONTAINER_NAME)
    if inspected.returncode != 0:
        return {"exists": False, "name": CONTAINER_NAME, "running": False, "healthy": False, "loopback_binding": False, "named_volume": False}
    try:
        data = json.loads(inspected.stdout)[0]
        state = data.get("State", {})
        bindings = data.get("HostConfig", {}).get("PortBindings", {}).get(f"{CONTAINER_PORT}/tcp") or []
        mounts = data.get("Mounts", [])
    except (json.JSONDecodeError, IndexError, TypeError):
        raise AdoptionBlockedError("persistent container inspection returned invalid data") from None
    loopback = any(item.get("HostIp") == HOST and str(item.get("HostPort")) == str(HOST_PORT) for item in bindings)
    named_volume = any(item.get("Type") == "volume" and item.get("Name") == VOLUME_NAME and item.get("Destination") == DATA_MOUNT for item in mounts)
    health = state.get("Health", {}).get("Status")
    return {
        "exists": True,
        "name": CONTAINER_NAME,
        "running": bool(state.get("Running")),
        "healthy": health == "healthy",
        "health": health or "not-configured",
        "loopback_binding": loopback,
        "named_volume": named_volume,
    }


def database_verification() -> dict[str, Any]:
    status = container_status()
    if not status["exists"] or not status["running"]:
        raise AdoptionBlockedError("persistent PostgreSQL container is not running")
    if not status["loopback_binding"] or not status["named_volume"]:
        raise AdoptionBlockedError("persistent PostgreSQL resource binding does not match the approved target")
    url = target_url_from_secret_file()
    engine = engine_for_url(url)
    try:
        readiness = inspect_database_readiness(engine)
        if readiness.status == DATABASE_UNREACHABLE:
            return {
                "reachable": False,
                "safe_display": safe_target_display(url),
                "revision": None,
                "head_revision": readiness.head_revision,
                "readiness": readiness.status,
                "ready": False,
                "compatibility": "UNAVAILABLE",
                "application_table_count": 0,
                "application_row_count": 0,
                "server_major": None,
                "container": CONTAINER_NAME,
                "volume": VOLUME_NAME,
                "binding": f"{HOST}:{HOST_PORT}:{CONTAINER_PORT}",
            }
        issues = compare_schema(engine)
        tables = sorted(name for name in inspect(engine).get_table_names() if name in APP_TABLES)
        counts = row_counts(engine) if readiness.status != DATABASE_UNREACHABLE else {}
        with engine.connect() as connection:
            version_num = str(connection.execute(text("show server_version_num")).scalar() or "")
    finally:
        engine.dispose()
    return {
        "reachable": readiness.status != DATABASE_UNREACHABLE,
        "safe_display": safe_target_display(url),
        "revision": readiness.current_revision,
        "head_revision": readiness.head_revision,
        "readiness": readiness.status,
        "ready": readiness.ready,
        "compatibility": "PASS" if not issues else "FAIL",
        "application_table_count": len(tables),
        "application_row_count": sum(counts.get(name, 0) for name in APP_TABLES),
        "server_major": int(version_num) // 10000 if version_num.isdigit() else None,
        "container": CONTAINER_NAME,
        "volume": VOLUME_NAME,
        "binding": f"{HOST}:{HOST_PORT}:{CONTAINER_PORT}",
    }


def source_quiescence_status() -> dict[str, Any]:
    """Read-only process inventory; command lines are inspected but never reported."""
    if os.name == "nt":
        script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -match '^(python|pythonw|node|npm|uvicorn)(\\.exe)?$' } | "
            "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
        )
        result = _run(["powershell", "-NoProfile", "-Command", script], timeout=30)
        if result.returncode != 0:
            return {"inspectable": False, "writer_detected": None, "reason": "process inventory unavailable"}
        try:
            payload = json.loads(result.stdout) if result.stdout else []
        except json.JSONDecodeError:
            return {"inspectable": False, "writer_detected": None, "reason": "process inventory was not valid JSON"}
        candidates = payload if isinstance(payload, list) else [payload]
    else:
        result = _run(["ps", "-eo", "pid=,comm=,args="], timeout=30)
        if result.returncode != 0:
            return {"inspectable": False, "writer_detected": None, "reason": "process inventory unavailable"}
        candidates = [{"ProcessId": None, "Name": "process", "CommandLine": line} for line in result.stdout.splitlines()]

    writers: list[dict[str, Any]] = []
    for process in candidates:
        pid = process.get("ProcessId")
        if pid == os.getpid():
            continue
        command = str(process.get("CommandLine") or "").lower().replace("\\", "/")
        name = str(process.get("Name") or "").lower()
        if "manage_local_postgres_adoption.py" in command or "check_prod5_4c_3b_active_postgres_adoption.py" in command:
            continue
        if "vite" in command and "uvicorn" not in command and "app.main" not in command:
            continue
        repo_related = "personal-radio" in command or "bm_radio" in command or "bm-radio" in command
        writer_shape = any(token in command for token in ("uvicorn", "app.main", "npm run dev", "vite"))
        if repo_related and (writer_shape or name.startswith(("python", "node", "npm", "uvicorn"))):
            writers.append({"pid": pid, "name": name})
    return {
        "inspectable": True,
        "candidate_processes_inspected": len(candidates),
        "writer_detected": bool(writers),
        "writer_processes": writers,
    }


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise AdoptionBlockedError(f"{label} is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdoptionBlockedError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise AdoptionBlockedError(f"{label} is invalid")
    return payload


def _source_inventory() -> tuple[dict[str, Any], dict[str, int], dict[str, str]]:
    from .database_transfer import database_inventory, inventory_counts, inventory_digests
    from .migration_contract import read_only_sqlite_url_for_path

    snapshot = sqlite_snapshot()
    engine = engine_for_url(read_only_sqlite_url_for_path(REAL_SQLITE_PATH))
    try:
        inventory = database_inventory(engine)
    finally:
        engine.dispose()
    return snapshot, inventory_counts(inventory), inventory_digests(inventory)


def accepted_source_evidence() -> dict[str, Any]:
    rehearsal = _load_json_object(ACCEPTED_REHEARSAL_REPORT, label="accepted BM-PROD5.4C.2 rehearsal evidence")
    if rehearsal.get("status") != "PASS" or not rehearsal.get("protected_state_exact_equality"):
        raise AdoptionBlockedError("accepted BM-PROD5.4C.2 rehearsal evidence is not a protected PASS")
    accepted = rehearsal.get("source")
    if not isinstance(accepted, dict):
        raise AdoptionBlockedError("accepted BM-PROD5.4C.2 source evidence is missing")
    snapshot, counts, digests = _source_inventory()
    expected_identity = (
        snapshot.get("sha256") == EXPECTED_SOURCE_SHA256
        and snapshot.get("schema_fingerprint") == EXPECTED_SOURCE_SCHEMA_FINGERPRINT
        and snapshot.get("revision") == EXPECTED_SOURCE_REVISION
        and snapshot.get("readiness") == READY
        and snapshot.get("compatibility") == "PASS"
        and snapshot.get("application_table_count") == 21
        and snapshot.get("application_row_count") == EXPECTED_SOURCE_ROWS
        and snapshot.get("integrity") == "ok"
        and snapshot.get("quick_check") == "ok"
    )
    accepted_match = (
        accepted.get("sha256") == snapshot.get("sha256")
        and accepted.get("schema_fingerprint") == snapshot.get("schema_fingerprint")
        and accepted.get("revision") == snapshot.get("revision")
        and accepted.get("application_rows") == snapshot.get("application_row_count")
        and accepted.get("per_table_row_counts") == counts
        and accepted.get("per_table_canonical_digests") == digests
    )
    foreign_keys_valid = not sqlite_foreign_key_violations(REAL_SQLITE_PATH)
    if not expected_identity or not accepted_match or not foreign_keys_valid:
        raise AdoptionBlockedError("live SQLite no longer exactly matches the accepted BM-PROD5.4C.2 source")
    return {
        "snapshot": snapshot,
        "per_table_row_counts": counts,
        "per_table_canonical_digests": digests,
        "accepted_evidence_match": True,
        "foreign_key_check": "PASS",
    }


def persistent_transfer_preflight() -> dict[str, Any]:
    """Strictly non-mutating BM-PROD5.4C.3A pre-creation gate."""
    result = preflight()
    blockers = list(result["blockers"])
    try:
        source = accepted_source_evidence()
    except AdoptionBlockedError as exc:
        source = None
        blockers.append(str(exc))
    quiescence = source_quiescence_status()
    if not quiescence.get("inspectable"):
        blockers.append(str(quiescence.get("reason") or "source quiescence is not inspectable"))
    elif quiescence.get("writer_detected"):
        blockers.append("a BM Radio process may be writing the live SQLite source")
    if LOCAL_STATE_DIR.exists():
        blockers.append("backend/.local_postgres already exists")
    env_summary = env_target_summary()
    if env_summary.get("dialect") != "sqlite":
        blockers.append("backend/.env is not currently configured for SQLite")
    if not result["image"].get("available_locally"):
        blockers.append("official postgres:16 image is not available locally")
    result.update(
        {
            "gate": "PASS" if not blockers else "BLOCKED",
            "blockers": blockers,
            "source_evidence": source,
            "source_quiescence": quiescence,
            "backend_env_sha256": sha256_path(BACKEND_ENV_PATH),
            "backend_env_target": env_summary,
            "explicit_approval_received": False,
        }
    )
    return result


def preflight(*, allow_expected_resources: bool = False) -> dict[str, Any]:
    """Strictly read-only preflight. It never creates local directories or Docker resources."""
    validate_resource_names()
    docker = docker_context_status()
    resources_inspectable = bool(docker["available"] and docker["local"])
    container_exists = docker_resource_exists("container", CONTAINER_NAME) if resources_inspectable else None
    volume_exists = docker_resource_exists("volume", VOLUME_NAME) if resources_inspectable else None
    image = postgres_image_status() if docker["available"] and docker["local"] else {"tag": IMAGE_TAG, "official": True, "available_locally": False, "identified": True}
    port_state = loopback_port_state()
    sqlite = sqlite_snapshot()
    dependencies = psycopg_declared_and_installed()
    policy = require_supported_database_url(build_database_url("preflight-placeholder"))
    head = migration_head()
    blockers: list[str] = []
    if not docker["cli"]:
        blockers.append("Docker CLI unavailable")
    elif not docker["available"]:
        blockers.append(str(docker["reason"] or "local Docker engine unavailable"))
    elif not docker["local"]:
        blockers.append("Docker context is not local")
    elif not docker["linux"]:
        blockers.append("Docker server is not using Linux containers")
    if not allow_expected_resources:
        if port_state != "free":
            blockers.append(f"loopback port {HOST_PORT} is occupied")
        if container_exists is True:
            blockers.append(f"persistent container {CONTAINER_NAME} already exists")
        if volume_exists is True:
            blockers.append(f"persistent volume {VOLUME_NAME} already exists")
    if not is_git_ignored(LOCAL_STATE_DIR / "state.json"):
        blockers.append("backend/.local_postgres is not Git-ignored")
    if not is_git_ignored(BACKEND_ENV_PATH):
        blockers.append("backend/.env is not Git-ignored")
    if not all(dependencies.values()):
        blockers.append("psycopg dependency is not both declared and installed")
    if policy.dialect != "postgresql" or policy.driver != "psycopg":
        blockers.append("BM Radio PostgreSQL URL policy is unsupported")
    if not head:
        blockers.append("Alembic migration head is unavailable")
    return {
        "gate": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "docker": docker,
        "image": image,
        "port": {"host": HOST, "port": HOST_PORT, "state": port_state},
        "container_exists": container_exists,
        "volume_exists": volume_exists,
        "local_state_ignored": is_git_ignored(LOCAL_STATE_DIR / "state.json"),
        "backend_env_ignored": is_git_ignored(BACKEND_ENV_PATH),
        "migration_head": head,
        "psycopg": dependencies,
        "database_policy": {"dialect": policy.dialect, "driver": policy.driver, "supported": True},
        "sqlite": sqlite,
        "zero_data_eligible": not sqlite.get("exists") or sqlite.get("application_row_count", 0) == 0,
        "transfer_required": bool(sqlite.get("exists") and sqlite.get("application_row_count", 0) > 0),
    }


def status() -> dict[str, Any]:
    """Read-only status; target database inspection occurs only for an existing container."""
    docker = docker_context_status()
    persistent = container_status() if docker["available"] and docker["local"] else {"exists": None, "name": CONTAINER_NAME, "running": None, "healthy": None, "loopback_binding": None, "named_volume": None, "reason": "local Docker engine unavailable"}
    volume_exists = docker_resource_exists("volume", VOLUME_NAME) if docker["available"] and docker["local"] else None
    pg_summary: dict[str, Any] | None = None
    if persistent["exists"] and persistent["running"] and POSTGRES_ENV_PATH.is_file():
        try:
            pg_summary = database_verification()
        except AdoptionBlockedError as exc:
            pg_summary = {"reachable": False, "reason": str(exc)}
    return {
        "docker": docker,
        "container": persistent,
        "volume": {"exists": volume_exists, "name": VOLUME_NAME},
        "port": {"host": HOST, "port": HOST_PORT, "state": loopback_port_state()},
        "local_state_directory_exists": LOCAL_STATE_DIR.is_dir(),
        "application_env_target": env_target_summary(),
        "sqlite": sqlite_snapshot(),
        "postgresql": pg_summary,
    }


def _require_clean_create_preflight() -> dict[str, Any]:
    result = preflight()
    if result["gate"] != "PASS":
        raise AdoptionBlockedError("create preflight blocked: " + "; ".join(result["blockers"]))
    if result["transfer_required"]:
        raise AdoptionBlockedError("populated SQLite requires the BM-PROD5.4C.3A verified-transfer workflow and exact approval token")
    return result


def create_persistent_target() -> dict[str, Any]:
    _require_clean_create_preflight()
    secret = generate_secret()
    write_secret_environment(secret)
    volume_created = False
    try:
        volume = _docker("volume", "create", VOLUME_NAME)
        if volume.returncode != 0:
            raise AdoptionBlockedError("failed to create persistent Docker volume")
        volume_created = True
        started = _docker(
            "run", "-d", "--name", CONTAINER_NAME,
            "--env-file", str(POSTGRES_ENV_PATH),
            "-p", f"{HOST}:{HOST_PORT}:{CONTAINER_PORT}",
            "-v", f"{VOLUME_NAME}:{DATA_MOUNT}",
            "--health-cmd", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB",
            "--health-interval", "5s", "--health-timeout", "5s", "--health-retries", "20",
            IMAGE_TAG,
            timeout=120,
        )
        if started.returncode != 0:
            raise AdoptionBlockedError("failed to start persistent PostgreSQL container")
    except Exception:
        _docker("container", "rm", "-f", CONTAINER_NAME)
        if volume_created:
            _docker("volume", "rm", VOLUME_NAME)
        POSTGRES_ENV_PATH.unlink(missing_ok=True)
        raise
    write_state({"version": 1, "created_utc": utc_now(), "container": CONTAINER_NAME, "volume": VOLUME_NAME, "database": DATABASE_NAME, "role": APPLICATION_ROLE, "binding": f"{HOST}:{HOST_PORT}:{CONTAINER_PORT}", "phase": "created"})
    return {"created": True, "container": CONTAINER_NAME, "volume": VOLUME_NAME, "binding": f"{HOST}:{HOST_PORT}:{CONTAINER_PORT}"}


def _wait_for_healthy(timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = container_status()
        if current.get("healthy"):
            return
        if not current.get("running"):
            break
        time.sleep(2)
    raise AdoptionBlockedError("persistent PostgreSQL container did not become healthy")


def migrate_persistent_target() -> dict[str, Any]:
    _wait_for_healthy()
    before = database_verification()
    if before["readiness"] not in {UNINITIALIZED, READY}:
        raise AdoptionBlockedError("target database is neither uninitialized nor at the known BM Radio head")
    url = target_url_from_secret_file()
    environment = os.environ.copy()
    environment["BM_RADIO_DB_URL"] = url
    upgraded = _run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_ROOT, env=environment, timeout=180)
    if upgraded.returncode != 0:
        raise AdoptionBlockedError("Alembic upgrade head failed")
    verified = database_verification()
    required = verified["ready"] and verified["compatibility"] == "PASS" and verified["revision"] == verified["head_revision"]
    required = required and verified["application_table_count"] == 21 and len(APP_TABLES) == 21 and verified["application_row_count"] == 0
    if not required:
        raise AdoptionBlockedError("persistent PostgreSQL post-migration verification failed")
    state = read_state()
    state.update({"phase": "migrated", "migrated_utc": utc_now(), "last_verified_application_rows": 0})
    write_state(state)
    return verified


def _run_alembic(database_url: str, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["BM_RADIO_DB_URL"] = database_url
    result = _run([sys.executable, "-m", "alembic", *arguments], cwd=BACKEND_ROOT, env=environment, timeout=180)
    if result.returncode != 0:
        raise AdoptionBlockedError(f"Alembic {' '.join(arguments)} failed")


def _write_transfer_verification(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    lowered = encoded.lower()
    forbidden = ("postgres_password", "postgresql+psycopg://", "c:\\users\\", "bonnymakaniankhondo")
    if any(token in lowered for token in forbidden):
        raise AdoptionBlockedError("transfer verification contains forbidden private data")
    temporary = TRANSFER_VERIFICATION_PATH.with_suffix(".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(TRANSFER_VERIFICATION_PATH)
    digest = sha256_path(TRANSFER_VERIFICATION_PATH)
    if not digest:
        raise AdoptionBlockedError("transfer verification hash could not be calculated")
    return digest


def create_verified_persistent_transfer(confirmation: str) -> dict[str, Any]:
    """Create and populate the fixed persistent target after exact operator approval."""
    if confirmation != PERSISTENT_TRANSFER_CONFIRMATION:
        raise AdoptionBlockedError("exact BM-PROD5.4C.3A persistent-creation confirmation token is required")
    gate = persistent_transfer_preflight()
    if gate["gate"] != "PASS":
        raise AdoptionBlockedError("persistent transfer preflight blocked: " + "; ".join(gate["blockers"]))

    from .database_transfer import (
        TransferBlockedError,
        create_verified_sqlite_backup,
        transfer_database,
        verify_database_transfer,
    )
    from .migration_contract import read_only_sqlite_url_for_path

    env_before = BACKEND_ENV_PATH.read_bytes()
    env_before_sha = hashlib.sha256(env_before).hexdigest()
    source_before = gate["source_evidence"]
    backup, _manifest_path, backup_manifest = create_verified_sqlite_backup(
        REAL_SQLITE_PATH,
        BACKUP_DIR,
        label="pre_persistent_postgres",
    )
    if not (
        backup_manifest["source_backup_counts_equal"]
        and backup_manifest["source_backup_digests_equal"]
        and backup_manifest["foreign_key_check"] == "PASS"
        and backup_manifest["application_row_count"] == EXPECTED_SOURCE_ROWS
    ):
        raise AdoptionBlockedError("fresh persistent-transfer SQLite backup verification failed")

    secret_written = False
    volume_created = False
    container_created = False
    transfer_verified = False
    try:
        write_secret_environment(generate_secret())
        secret_written = True
        volume = _docker("volume", "create", VOLUME_NAME)
        if volume.returncode != 0 or volume.stdout.strip() != VOLUME_NAME:
            raise AdoptionBlockedError("failed to create the exact persistent Docker volume")
        volume_created = True
        started = _docker(
            "run", "-d", "--name", CONTAINER_NAME,
            "--env-file", str(POSTGRES_ENV_PATH),
            "-p", f"{HOST}:{HOST_PORT}:{CONTAINER_PORT}",
            "-v", f"{VOLUME_NAME}:{DATA_MOUNT}",
            "--health-cmd", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB",
            "--health-interval", "5s", "--health-timeout", "5s", "--health-retries", "20",
            IMAGE_TAG,
            timeout=120,
        )
        if started.returncode != 0:
            raise AdoptionBlockedError("failed to start the exact persistent PostgreSQL container")
        container_created = True
        _wait_for_healthy()
        initial = database_verification()
        if initial["server_major"] != POSTGRES_MAJOR or initial["application_table_count"] != 0:
            raise AdoptionBlockedError("persistent PostgreSQL target is not a fresh PostgreSQL 16 database")

        target_url = target_url_from_secret_file()
        _run_alembic(target_url, "upgrade", "head")
        migrated = database_verification()
        if not (
            migrated["ready"]
            and migrated["revision"] == EXPECTED_SOURCE_REVISION
            and migrated["compatibility"] == "PASS"
            and migrated["application_table_count"] == 21
            and migrated["application_row_count"] == 0
        ):
            raise AdoptionBlockedError("persistent target migration verification failed")

        source_engine = engine_for_url(read_only_sqlite_url_for_path(backup))
        target_engine = engine_for_url(target_url)
        try:
            transferred = transfer_database(source_engine, target_engine)
            verification = verify_database_transfer(source_engine, target_engine)
            with target_engine.connect() as connection:
                postgres_version = str(connection.execute(text("select version()" )).scalar_one())
        finally:
            source_engine.dispose()
            target_engine.dispose()
        _run_alembic(target_url, "check")
        final_database = database_verification()
        if not (
            transferred.total_rows == EXPECTED_SOURCE_ROWS
            and verification["source_total_rows"] == EXPECTED_SOURCE_ROWS
            and verification["target_total_rows"] == EXPECTED_SOURCE_ROWS
            and final_database["application_row_count"] == EXPECTED_SOURCE_ROWS
            and final_database["revision"] == EXPECTED_SOURCE_REVISION
            and final_database["compatibility"] == "PASS"
        ):
            raise AdoptionBlockedError("persistent transfer post-verification failed")
        transfer_verified = True
        write_state(
            {
                "version": 2,
                "phase": "BM-PROD5.4C.3A-transfer-verified-restart-pending",
                "container": CONTAINER_NAME,
                "volume": VOLUME_NAME,
                "database": DATABASE_NAME,
                "role": APPLICATION_ROLE,
                "binding": HOST,
                "port": HOST_PORT,
                "postgres_major": POSTGRES_MAJOR,
                "source_sha256": EXPECTED_SOURCE_SHA256,
                "source_schema_fingerprint": EXPECTED_SOURCE_SCHEMA_FINGERPRINT,
                "source_rows": EXPECTED_SOURCE_ROWS,
                "target_revision": EXPECTED_SOURCE_REVISION,
                "target_rows": EXPECTED_SOURCE_ROWS,
                "target_compatibility": "PASS",
                "restart_persistence": "PENDING",
                "application_adopted": False,
                "created_utc": utc_now(),
            }
        )

        stopped = _docker("stop", CONTAINER_NAME, timeout=120)
        if stopped.returncode != 0:
            raise AdoptionBlockedError("persistent PostgreSQL stop proof failed")
        restarted = _docker("start", CONTAINER_NAME, timeout=120)
        if restarted.returncode != 0:
            raise AdoptionBlockedError("persistent PostgreSQL restart proof failed")
        _wait_for_healthy()
        restart_database = database_verification()
        restart_source = engine_for_url(read_only_sqlite_url_for_path(backup))
        restart_target = engine_for_url(target_url)
        try:
            restart_verification = verify_database_transfer(restart_source, restart_target)
        finally:
            restart_source.dispose()
            restart_target.dispose()
        if not (
            restart_database["ready"]
            and restart_database["compatibility"] == "PASS"
            and restart_database["application_row_count"] == EXPECTED_SOURCE_ROWS
            and restart_verification["per_table_row_counts"] == verification["per_table_row_counts"]
            and restart_verification["per_table_canonical_digests"] == verification["per_table_canonical_digests"]
        ):
            raise AdoptionBlockedError("persistent PostgreSQL restart equality proof failed")

        source_after = accepted_source_evidence()
        if source_after != source_before or BACKEND_ENV_PATH.read_bytes() != env_before:
            raise AdoptionBlockedError("protected SQLite or backend/.env changed during persistent transfer")
        if BACKEND_ENV_BEFORE_PATH.exists():
            raise AdoptionBlockedError("backend_env.before must not exist before active adoption")

        artifact = {
            "version": 1,
            "created_utc": utc_now(),
            "source_logical_db": "backend/bm_radio.db",
            "source_sha256": EXPECTED_SOURCE_SHA256,
            "source_schema_fingerprint": EXPECTED_SOURCE_SCHEMA_FINGERPRINT,
            "source_revision": EXPECTED_SOURCE_REVISION,
            "source_total_rows": EXPECTED_SOURCE_ROWS,
            "source_per_table_counts": verification["per_table_row_counts"],
            "source_per_table_canonical_digests": verification["per_table_canonical_digests"],
            "backup_logical_filename": backup.name,
            "container": CONTAINER_NAME,
            "volume": VOLUME_NAME,
            "postgres_server_major": POSTGRES_MAJOR,
            "postgres_server_version": postgres_version,
            "target_revision": restart_database["revision"],
            "target_total_rows": restart_verification["target_total_rows"],
            "target_per_table_counts": restart_verification["per_table_row_counts"],
            "target_per_table_canonical_digests": restart_verification["per_table_canonical_digests"],
            "schema_compatibility": restart_database["compatibility"],
            "foreign_key_validation": restart_verification["foreign_key_validation"],
            "sequence_validation": {
                "repairs": transferred.sequence_repairs,
                "next_id_rollback_canary": transferred.sequence_canary,
            },
            "alembic_drift": "PASS",
            "restart_persistence": "PASS",
        }
        artifact_sha = _write_transfer_verification(artifact)
        state = read_state()
        state.update(
            {
                "phase": "BM-PROD5.4C.3A",
                "transfer_verification_sha256": artifact_sha,
                "restart_persistence": "PASS",
                "application_adopted": False,
            }
        )
        write_state(state)
        return {
            "persistent_transfer": "PASS",
            "container": CONTAINER_NAME,
            "volume": VOLUME_NAME,
            "binding": f"{HOST}:{HOST_PORT}:{CONTAINER_PORT}",
            "source_rows": EXPECTED_SOURCE_ROWS,
            "target_rows": EXPECTED_SOURCE_ROWS,
            "backup_logical_filename": backup.name,
            "transfer_verification_sha256": artifact_sha,
            "backend_env_sha256": env_before_sha,
            "application_adopted": False,
        }
    except TransferBlockedError as exc:
        if not transfer_verified:
            if container_created:
                _docker("container", "rm", "-f", CONTAINER_NAME)
            if volume_created:
                _docker("volume", "rm", VOLUME_NAME)
            if secret_written:
                POSTGRES_ENV_PATH.unlink(missing_ok=True)
        raise AdoptionBlockedError(str(exc)) from exc
    except Exception:
        if not transfer_verified:
            if container_created:
                _docker("container", "rm", "-f", CONTAINER_NAME)
            if volume_created:
                _docker("volume", "rm", VOLUME_NAME)
            if secret_written:
                POSTGRES_ENV_PATH.unlink(missing_ok=True)
        raise


def validate_transfer_evidence() -> dict[str, Any]:
    """Validate durable source and target evidence without changing either database."""
    state = read_state()
    artifact = _load_json_object(TRANSFER_VERIFICATION_PATH, label="persistent transfer verification")
    expected_hash = state.get("transfer_verification_sha256")
    if not expected_hash or sha256_path(TRANSFER_VERIFICATION_PATH) != expected_hash:
        raise AdoptionBlockedError("persistent transfer verification hash does not match state.json")
    if state.get("phase") != "BM-PROD5.4C.3A" or state.get("application_adopted") is not False:
        raise AdoptionBlockedError("persistent transfer state is not eligible for active adoption")
    identity = container_status()
    if not (identity["exists"] and identity["running"] and identity["loopback_binding"] and identity["named_volume"]):
        raise AdoptionBlockedError("persistent PostgreSQL resource identity does not match transfer evidence")
    source = accepted_source_evidence()
    source_matches = (
        artifact.get("source_sha256") == source["snapshot"]["sha256"]
        and artifact.get("source_schema_fingerprint") == source["snapshot"]["schema_fingerprint"]
        and artifact.get("source_revision") == source["snapshot"]["revision"]
        and artifact.get("source_total_rows") == source["snapshot"]["application_row_count"]
        and artifact.get("source_per_table_counts") == source["per_table_row_counts"]
        and artifact.get("source_per_table_canonical_digests") == source["per_table_canonical_digests"]
    )
    if not source_matches:
        raise AdoptionBlockedError("live SQLite does not match persistent transfer verification")

    from .database_transfer import verify_database_transfer
    from .migration_contract import read_only_sqlite_url_for_path

    source_engine = engine_for_url(read_only_sqlite_url_for_path(REAL_SQLITE_PATH))
    target_engine = engine_for_url(target_url_from_secret_file())
    try:
        verified = verify_database_transfer(source_engine, target_engine)
    finally:
        source_engine.dispose()
        target_engine.dispose()
    database = database_verification()
    target_matches = (
        artifact.get("container") == CONTAINER_NAME
        and artifact.get("volume") == VOLUME_NAME
        and artifact.get("postgres_server_major") == POSTGRES_MAJOR
        and artifact.get("target_revision") == database["revision"]
        and artifact.get("target_total_rows") == verified["target_total_rows"]
        and artifact.get("target_per_table_counts") == verified["per_table_row_counts"]
        and artifact.get("target_per_table_canonical_digests") == verified["per_table_canonical_digests"]
        and database["readiness"] == READY
        and database["compatibility"] == "PASS"
    )
    if not target_matches:
        raise AdoptionBlockedError("persistent PostgreSQL does not match transfer verification")
    return {"verified": True, "source_rows": verified["source_total_rows"], "target_rows": verified["target_total_rows"], "artifact_sha256": expected_hash}


def active_adoption_preflight() -> dict[str, Any]:
    """Strictly read-only BM-PROD5.4C.3B gate; never changes configuration or databases."""
    blockers: list[str] = []
    commit = _run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT)
    if commit.returncode != 0 or commit.stdout.strip() != EXPECTED_PROD5_4C_3A_COMMIT:
        blockers.append("repository HEAD is not the accepted BM-PROD5.4C.3A commit")
    docker = docker_context_status()
    if not (docker.get("available") and docker.get("local") and docker.get("linux")):
        blockers.append("a reachable local Docker Linux engine is required")
    current_container = container_status() if docker.get("available") and docker.get("local") else None
    if not current_container or not (
        current_container.get("exists")
        and current_container.get("running")
        and current_container.get("healthy")
        and current_container.get("loopback_binding")
        and current_container.get("named_volume")
    ):
        blockers.append("the exact persistent PostgreSQL container is not healthy and correctly bound")
    try:
        evidence = validate_transfer_evidence()
    except AdoptionBlockedError as exc:
        evidence = None
        blockers.append(str(exc))
    quiescence = source_quiescence_status()
    if not quiescence.get("inspectable"):
        blockers.append(str(quiescence.get("reason") or "writer quiescence is not inspectable"))
    elif quiescence.get("writer_detected"):
        blockers.append("a BM Radio backend writer may already be active")
    env_sha = sha256_path(BACKEND_ENV_PATH)
    env_target = env_target_summary()
    if env_sha != EXPECTED_BACKEND_ENV_SHA256:
        blockers.append("backend/.env does not match the accepted pre-adoption hash")
    if env_target.get("dialect") != "sqlite":
        blockers.append("backend/.env is not currently configured for SQLite")
    if "BM_RADIO_DB_URL" in os.environ:
        blockers.append("process environment overrides BM_RADIO_DB_URL; adopted .env would not be authoritative")
    if BACKEND_ENV_BEFORE_PATH.exists():
        blockers.append("backend_env.before already exists")
    state = read_state()
    if state.get("phase") != "BM-PROD5.4C.3A" or state.get("application_adopted") is not False:
        blockers.append("persistent state is not at the accepted pre-adoption phase")
    database = None
    if current_container and current_container.get("running"):
        try:
            database = database_verification()
        except AdoptionBlockedError as exc:
            blockers.append(str(exc))
    if database and not (
        database.get("server_major") == POSTGRES_MAJOR
        and database.get("revision") == EXPECTED_SOURCE_REVISION
        and database.get("readiness") == READY
        and database.get("compatibility") == "PASS"
        and database.get("application_row_count") == EXPECTED_SOURCE_ROWS
    ):
        blockers.append("persistent PostgreSQL readiness or identity does not match the accepted transfer")
    return {
        "gate": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "source_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "transfer_evidence": evidence,
        "docker": docker,
        "container": current_container,
        "postgresql": database,
        "source_quiescence": quiescence,
        "backend_env_sha256": env_sha,
        "backend_env_target": env_target,
        "backend_env_before_exists": BACKEND_ENV_BEFORE_PATH.exists(),
        "explicit_approval_received": False,
    }


def write_active_adoption_verification(payload: dict[str, Any]) -> str:
    """Write only privacy-safe 5.4C.3B evidence and return its SHA-256."""
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    safe_display = payload.get("database_target_safe_display")
    expected_display = f"postgresql+psycopg://{APPLICATION_ROLE}:***@{HOST}:{HOST_PORT}/{DATABASE_NAME}"
    if safe_display != expected_display:
        raise AdoptionBlockedError("adoption verification database target is not the exact redacted persistent target")
    lowered = encoded.replace(expected_display, "<redacted-persistent-target>").lower()
    forbidden = ("postgres_password", "postgresql+psycopg://", "c:\\users\\", "bonnymakaniankhondo", "raw_rows", "media_path")
    if any(token in lowered for token in forbidden):
        raise AdoptionBlockedError("adoption verification contains forbidden private data")
    temporary = ADOPTION_VERIFICATION_PATH.with_suffix(".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(ADOPTION_VERIFICATION_PATH)
    digest = sha256_path(ADOPTION_VERIFICATION_PATH)
    if not digest:
        raise AdoptionBlockedError("adoption verification hash could not be calculated")
    return digest


def finalize_active_adoption(payload: dict[str, Any]) -> dict[str, Any]:
    artifact_sha = write_active_adoption_verification(payload)
    state = read_state()
    transfer_sha = state.get("transfer_verification_sha256")
    if not transfer_sha or transfer_sha != payload.get("transfer_verification_sha256"):
        raise AdoptionBlockedError("transfer verification SHA cannot be preserved during adoption finalization")
    state.update(
        {
            "phase": "BM-PROD5.4C.3B",
            "application_adopted": True,
            "active_database": "postgresql",
            "application_startup_verified": True,
            "application_startup_twice": True,
            "write_routing_verified": True,
            "post_canary_target_rows": EXPECTED_SOURCE_ROWS,
            "adoption_verification_sha256": artifact_sha,
            "sqlite_fallback_preserved": True,
            "rollback_snapshot_verified": True,
            "verified_utc": utc_now(),
        }
    )
    write_state(state)
    return {"phase": state["phase"], "application_adopted": True, "adoption_verification_sha256": artifact_sha}


def adopt_persistent_target(confirmation: str) -> dict[str, Any]:
    if confirmation != ADOPT_CONFIRMATION:
        raise AdoptionBlockedError("exact adoption confirmation token is required")
    safety = preflight(allow_expected_resources=True)
    environment_only_blockers = [item for item in safety["blockers"] if "already exists" not in item and "occupied" not in item]
    if environment_only_blockers:
        raise AdoptionBlockedError("adoption preflight blocked: " + "; ".join(environment_only_blockers))
    sqlite = safety["sqlite"]
    populated_source = bool(sqlite.get("exists") and sqlite.get("application_row_count") != 0)
    if populated_source:
        validate_transfer_evidence()
    verified = database_verification()
    expected_rows = int(sqlite.get("application_row_count", 0)) if populated_source else 0
    if not (verified["ready"] and verified["compatibility"] == "PASS" and verified["revision"] == verified["head_revision"] and verified["application_row_count"] == expected_rows):
        raise AdoptionBlockedError("persistent PostgreSQL target is not eligible for adoption")
    if not BACKEND_ENV_PATH.is_file() or BACKEND_ENV_BEFORE_PATH.exists():
        raise AdoptionBlockedError("backend/.env snapshot cannot be created safely")
    before = BACKEND_ENV_PATH.read_bytes()
    target_url = target_url_from_secret_file()
    adopted = replace_database_target(before, target_url)
    previous_state = read_state()
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    BACKEND_ENV_BEFORE_PATH.write_bytes(before)
    before_hash = hashlib.sha256(before).hexdigest()
    adopted_hash = hashlib.sha256(adopted).hexdigest()
    try:
        BACKEND_ENV_PATH.write_bytes(adopted)
        from .config import Settings

        settings = Settings(BM_RADIO_DB_URL=target_url)
        target = require_supported_database_url(settings.BM_RADIO_DB_URL)
        if target.dialect != "postgresql" or target.driver != "psycopg" or settings.BM_RADIO_DB_POLICY_STATUS != "postgresql_supported":
            raise AdoptionBlockedError("Settings did not resolve the adopted PostgreSQL policy")
        state = dict(previous_state)
        state.update({"phase": "adopted", "adopted_utc": utc_now(), "backend_env_before_sha256": before_hash, "backend_env_adopted_sha256": adopted_hash, "last_verified_application_rows": expected_rows, "application_adopted": True})
        write_state(state)
    except Exception:
        BACKEND_ENV_PATH.write_bytes(before)
        BACKEND_ENV_BEFORE_PATH.unlink(missing_ok=True)
        if previous_state:
            try:
                write_state(previous_state)
            except Exception:
                pass
        raise
    return {"adopted": True, "dialect": "postgresql", "driver": "psycopg", "policy": "postgresql_supported", "safe_display": safe_target_display(target_url)}


def validate_rollback_files(
    state: dict[str, Any],
    *,
    current_env_path: Path = BACKEND_ENV_PATH,
    snapshot_path: Path = BACKEND_ENV_BEFORE_PATH,
) -> bytes:
    before_hash = state.get("backend_env_before_sha256")
    adopted_hash = state.get("backend_env_adopted_sha256")
    if not snapshot_path.is_file() or not before_hash or not adopted_hash:
        raise AdoptionBlockedError("valid backend/.env recovery state is missing")
    if sha256_path(snapshot_path) != before_hash:
        raise AdoptionBlockedError("stored backend/.env snapshot hash does not match")
    if sha256_path(current_env_path) != adopted_hash:
        raise AdoptionBlockedError("backend/.env changed independently after adoption")
    return snapshot_path.read_bytes()


def rollback_configuration() -> dict[str, Any]:
    state = read_state()
    restored = validate_rollback_files(state)
    BACKEND_ENV_PATH.write_bytes(restored)
    summary = env_target_summary()
    state.update({"phase": "config-rolled-back", "rollback_utc": utc_now()})
    write_state(state)
    return {"restored": True, "database_target": summary}


def prepare_failed_adoption_retry(confirmation: str) -> dict[str, Any]:
    """Reset only a hash-verified 5.4C.3B rollback created by this operator."""
    if confirmation != ADOPT_CONFIRMATION:
        raise AdoptionBlockedError("exact active-adoption confirmation token is required for retry recovery")
    state = read_state()
    if state.get("phase") not in {"BM-PROD5.4C.3B-failed-rolled-back", "BM-PROD5.4C.3A"}:
        raise AdoptionBlockedError("local state is not an eligible failed-adoption rollback")
    if state.get("application_adopted") is not False or env_target_summary().get("dialect") != "sqlite":
        raise AdoptionBlockedError("application configuration is not safely rolled back to SQLite")
    if sha256_path(BACKEND_ENV_PATH) != EXPECTED_BACKEND_ENV_SHA256:
        raise AdoptionBlockedError("rolled-back backend/.env does not match the accepted hash")
    if not BACKEND_ENV_BEFORE_PATH.is_file() or sha256_path(BACKEND_ENV_BEFORE_PATH) != EXPECTED_BACKEND_ENV_SHA256:
        raise AdoptionBlockedError("failed-attempt fallback snapshot is missing or mismatched")
    if sha256_path(TRANSFER_VERIFICATION_PATH) != state.get("transfer_verification_sha256"):
        raise AdoptionBlockedError("transfer evidence changed during the failed adoption")
    retry_state = dict(state)
    for key in (
        "active_database",
        "adopted_utc",
        "backend_env_adopted_sha256",
        "backend_env_before_sha256",
        "failed_utc",
        "last_verified_application_rows",
        "rollback_utc",
    ):
        retry_state.pop(key, None)
    retry_state.update({"phase": "BM-PROD5.4C.3A", "application_adopted": False})
    write_state(retry_state)
    BACKEND_ENV_BEFORE_PATH.unlink()
    return {"retry_ready": True, "phase": retry_state["phase"], "backend_env_sha256": EXPECTED_BACKEND_ENV_SHA256}


def _env_points_to_persistent_target() -> bool:
    value = _read_env_database_url()
    if not value:
        return False
    try:
        parsed = make_url(value)
    except Exception:
        return False
    return parsed.get_backend_name() == "postgresql" and parsed.host == HOST and parsed.port == HOST_PORT and parsed.database == DATABASE_NAME


def destroy_persistent_target(confirmation: str, *, announce: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    if confirmation != DESTROY_CONFIRMATION:
        raise AdoptionBlockedError("exact destructive confirmation token is required")
    docker = docker_context_status()
    if not (docker["available"] and docker["local"] and docker["linux"]):
        raise AdoptionBlockedError("a verified local Docker Linux engine is required for destroy")
    if _env_points_to_persistent_target():
        raise AdoptionBlockedError("backend/.env still points at the persistent PostgreSQL target")
    current = container_status()
    if current["exists"] and current["running"]:
        raise AdoptionBlockedError("persistent PostgreSQL container must be stopped before destroy")
    state = read_state()
    rows = state.get("last_verified_application_rows")
    if not isinstance(rows, int) or rows < 0:
        raise AdoptionBlockedError("a verified database row count is required before destroy")
    result = {"safe_target": f"postgresql+psycopg://{APPLICATION_ROLE}:***@{HOST}:{HOST_PORT}/{DATABASE_NAME}", "application_row_count": rows, "volume": VOLUME_NAME}
    announce(dict(result))
    if current["exists"] and _docker("container", "rm", CONTAINER_NAME).returncode != 0:
        raise AdoptionBlockedError("failed to remove stopped persistent PostgreSQL container")
    if docker_resource_exists("volume", VOLUME_NAME) and _docker("volume", "rm", VOLUME_NAME).returncode != 0:
        raise AdoptionBlockedError("failed to remove persistent PostgreSQL volume")
    state.update({"phase": "destroyed", "destroyed_utc": utc_now()})
    write_state(state)
    return result
