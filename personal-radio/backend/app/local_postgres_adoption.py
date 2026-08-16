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
from .sqlite_adoption import application_row_count, sha256_file, snapshot_sqlite_database


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
REAL_SQLITE_PATH = BACKEND_ROOT / "bm_radio.db"
BACKEND_ENV_PATH = BACKEND_ROOT / ".env"
LOCAL_STATE_DIR = BACKEND_ROOT / ".local_postgres"
POSTGRES_ENV_PATH = LOCAL_STATE_DIR / "postgres.env"
STATE_PATH = LOCAL_STATE_DIR / "state.json"
BACKEND_ENV_BEFORE_PATH = LOCAL_STATE_DIR / "backend_env.before"

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
    if sqlite.get("exists") and sqlite.get("application_row_count", 0) > 0:
        blockers.append("SQLite contains application rows; a separately reviewed data-transfer plan is required")
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


def adopt_persistent_target(confirmation: str) -> dict[str, Any]:
    if confirmation != ADOPT_CONFIRMATION:
        raise AdoptionBlockedError("exact adoption confirmation token is required")
    safety = preflight(allow_expected_resources=True)
    environment_only_blockers = [item for item in safety["blockers"] if "already exists" not in item and "occupied" not in item]
    if environment_only_blockers:
        raise AdoptionBlockedError("adoption preflight blocked: " + "; ".join(environment_only_blockers))
    sqlite = safety["sqlite"]
    if sqlite.get("exists") and sqlite.get("application_row_count") != 0:
        raise AdoptionBlockedError("populated SQLite requires verified transfer evidence from a future approved adoption phase")
    verified = database_verification()
    if not (verified["ready"] and verified["compatibility"] == "PASS" and verified["revision"] == verified["head_revision"] and verified["application_row_count"] == 0):
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
        state.update({"phase": "adopted", "adopted_utc": utc_now(), "backend_env_before_sha256": before_hash, "backend_env_adopted_sha256": adopted_hash, "last_verified_application_rows": 0})
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


def rollback_configuration() -> dict[str, Any]:
    state = read_state()
    before_hash = state.get("backend_env_before_sha256")
    adopted_hash = state.get("backend_env_adopted_sha256")
    if not BACKEND_ENV_BEFORE_PATH.is_file() or not before_hash or not adopted_hash:
        raise AdoptionBlockedError("valid backend/.env recovery state is missing")
    if sha256_path(BACKEND_ENV_BEFORE_PATH) != before_hash:
        raise AdoptionBlockedError("stored backend/.env snapshot hash does not match")
    if sha256_path(BACKEND_ENV_PATH) != adopted_hash:
        raise AdoptionBlockedError("backend/.env changed independently after adoption")
    restored = BACKEND_ENV_BEFORE_PATH.read_bytes()
    BACKEND_ENV_PATH.write_bytes(restored)
    summary = env_target_summary()
    state.update({"phase": "config-rolled-back", "rollback_utc": utc_now()})
    write_state(state)
    return {"restored": True, "database_target": summary}


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
