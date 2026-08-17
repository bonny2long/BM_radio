from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.local_postgres_adoption import (  # noqa: E402
    CONTAINER_NAME,
    LOCAL_STATE_DIR,
    VOLUME_NAME,
    container_status,
    docker_context_status,
)
from app.postgres_backup_restore import _database_snapshot, _process_quiescence, sha256_file  # noqa: E402
from app.postgres_recovery import (  # noqa: E402
    BACKUP_PATH,
    EXPECTED_SOURCE_ROWS,
    RECOVERY_VERIFICATION_PATH,
    protected_hashes,
    protected_snapshot,
    verify_recovered_database,
    verify_retained_recovery_input,
)


STARTING_COMMIT = "bc444f3b06c8006189d63607c139f6e90672d7f9"
IMAGE_TAG = "bm-radio-backend:prod5.6a-bc444f3"
RESOURCE_PREFIX = "bm-prod5-6a-"
POSTGRES_IMAGE = "postgres:16"
DOCKERFILE = BACKEND / "Dockerfile"
RUNTIME_REQUIREMENTS = BACKEND / "requirements-runtime.txt"


class ContainerProofBlocked(RuntimeError):
    pass


def _run(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(BACKEND),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )


def _docker(*arguments: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return _run(["docker", *arguments], timeout=timeout)


def _require(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        raise ContainerProofBlocked(f"{label} failed")
    return result.stdout.strip()


def _git_head() -> str:
    return _require(_run(["git", "rev-parse", "HEAD"]), "Git HEAD inspection")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_state() -> dict[str, Any]:
    hashes = protected_hashes()
    hashes["recovery_rehearsal_verification_sha256"] = (
        sha256_file(RECOVERY_VERIFICATION_PATH) if RECOVERY_VERIFICATION_PATH.is_file() else None
    )
    return {"snapshot": protected_snapshot(), "hashes": hashes}


def _resource_inventory() -> dict[str, list[str]]:
    containers = _require(
        _docker("container", "ls", "-a", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Names}}"),
        "task container inventory",
    )
    networks = _require(
        _docker("network", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"),
        "task network inventory",
    )
    volumes = _require(
        _docker("volume", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"),
        "task volume inventory",
    )
    return {
        "containers": sorted(item for item in containers.splitlines() if item),
        "networks": sorted(item for item in networks.splitlines() if item),
        "volumes": sorted(item for item in volumes.splitlines() if item),
    }


def preflight() -> dict[str, Any]:
    blockers: list[str] = []
    head = _git_head()
    if head != STARTING_COMMIT:
        blockers.append("Git HEAD is not the accepted BM-PROD5.5B implementation commit")
    docker = docker_context_status()
    if not (docker.get("available") and docker.get("local") and docker.get("linux")):
        blockers.append("a reachable local Docker Linux engine is required")
    active = container_status() if docker.get("available") else {}
    if not all(active.get(key) for key in ("exists", "running", "healthy", "loopback_binding", "named_volume")):
        blockers.append("the protected active PostgreSQL identity or health is invalid")
    if CONTAINER_NAME.startswith(RESOURCE_PREFIX) or VOLUME_NAME.startswith(RESOURCE_PREFIX):
        blockers.append("task resource prefix overlaps a protected resource")
    quiescence = _process_quiescence()
    if not quiescence.get("inspectable") or quiescence.get("writer_detected"):
        blockers.append("BM Radio backend writer quiescence is not proven")
    retained: dict[str, Any] = {}
    protected: dict[str, Any] = {}
    resources: dict[str, list[str]] = {"containers": [], "networks": [], "volumes": []}
    try:
        retained = verify_retained_recovery_input(inspect_archive=False)
        protected = _protected_state()
        if protected["snapshot"]["active_postgresql"]["application_total_rows"] != EXPECTED_SOURCE_ROWS:
            blockers.append("active PostgreSQL no longer has the accepted row count")
        if protected["snapshot"]["sqlite_fallback"]["application_total_rows"] != EXPECTED_SOURCE_ROWS:
            blockers.append("SQLite fallback no longer has the accepted row count")
        resources = _resource_inventory()
        if any(resources.values()):
            blockers.append("stale BM-PROD5.6A Docker resources already exist")
        if _docker("image", "inspect", POSTGRES_IMAGE).returncode != 0:
            blockers.append("the required local PostgreSQL 16 image is unavailable")
    except Exception as exc:
        blockers.append(str(exc))
    return {
        "gate": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "source_commit": head,
        "docker": {"context": docker.get("context"), "local": docker.get("local"), "linux": docker.get("linux")},
        "active_postgresql": active,
        "quiescence": quiescence,
        "retained_backup": {
            key: retained.get(key)
            for key in ("backup_filename", "backup_sha256", "manifest_revision", "manifest_tables", "manifest_rows")
        },
        "protected": {
            "postgresql_rows": protected.get("snapshot", {}).get("active_postgresql", {}).get("application_total_rows"),
            "sqlite_rows": protected.get("snapshot", {}).get("sqlite_fallback", {}).get("application_total_rows"),
            "hashes_present": sorted(key for key, value in protected.get("hashes", {}).items() if value),
        },
        "task_resources": resources,
    }


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _base_environment(database_url: str) -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "BM_RADIO_DB_URL": database_url,
        "BM_RADIO_MUSIC_ROOT": "/media/Music",
        "BM_RADIO_AUDIOBOOK_ROOT": "/media/Audiobooks/Library",
        "BM_RADIO_BOOK_ROOT": "/media/Books",
        "BM_RADIO_CACHE_ROOT": "/app-cache",
        "BM_RADIO_ARTWORK_CACHE_ROOT": "/app-cache/artwork",
        "BM_RADIO_API_HOST": "0.0.0.0",
        "BM_RADIO_API_PORT": "8094",
        "BM_RADIO_CORS_ORIGINS": "http://127.0.0.1:5174",
        "BM_RADIO_API_DOCS_ENABLED": "false",
        "BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN": "false",
        "PUBLIC_ACCESS": "false",
        "ALLOW_FILE_MUTATION": "false",
        "ALLOW_DELETE": "false",
        "ALLOW_TAG_WRITES": "false",
        "SCAN_INGEST_FOLDERS": "false",
    }


def _inspect_image() -> dict[str, Any]:
    data = json.loads(_require(_docker("image", "inspect", IMAGE_TAG), "image metadata inspection"))[0]
    if data.get("Os") != "linux" or data.get("Architecture") != "amd64":
        raise ContainerProofBlocked("image is not Linux/amd64")
    config = data.get("Config", {})
    if config.get("User") != "10001:10001":
        raise ContainerProofBlocked("image runtime user is not 10001:10001")
    if "8094/tcp" not in (config.get("ExposedPorts") or {}):
        raise ContainerProofBlocked("image does not expose 8094")
    health = config.get("Healthcheck") or {}
    if "app.container_healthcheck" not in " ".join(health.get("Test") or []):
        raise ContainerProofBlocked("image healthcheck is not database-aware BM Radio health")

    scan_code = (
        "import json,os,pathlib; root=pathlib.Path('/app'); "
        "paths=[str(p) for p in root.rglob('*')]; "
        "bad_names={'.env','postgres.env','backend_env.before','state.json','transfer_verification.json',"
        "'adoption_verification.json','backup_verification.json','recovery_rehearsal_verification.json','bm_radio.db'}; "
        "bad_paths=[p for p in paths if pathlib.Path(p).name in bad_names or '.git' in pathlib.Path(p).parts "
        "or '.local_backups' in pathlib.Path(p).parts or '.local_postgres' in pathlib.Path(p).parts "
        "or pathlib.Path(p).suffix.lower() in {'.db','.sqlite','.sqlite3','.dump'}]; "
        "tokens=[b'c:\\\\users\\\\',b'bonnymakaniankhondo']; hits=[]; "
        "[(hits.append(str(p)) if any(t in p.read_bytes().lower() for t in tokens) else None) "
        "for p in root.rglob('*') if p.is_file()]; "
        "print(json.dumps({'path_count':len(paths),'bad_paths':bad_paths,'personal_path_hits':hits}))"
    )
    scan = json.loads(
        _require(_docker("run", "--rm", "--entrypoint", "python", IMAGE_TAG, "-c", scan_code), "image filesystem inspection")
    )
    if scan["bad_paths"] or scan["personal_path_hits"]:
        raise ContainerProofBlocked("image filesystem contains forbidden state or personal paths")
    history = _require(_docker("history", "--no-trunc", "--format", "{{.CreatedBy}}", IMAGE_TAG), "image history inspection")
    forbidden_history = (
        "bonnymakaniankhondo",
        "postgres.env",
        "backend_env.before",
        "recovery_rehearsal_verification.json",
        "postgresql+psycopg://bm_radio_app:",
    )
    if any(token in history.lower() for token in forbidden_history):
        raise ContainerProofBlocked("image history contains forbidden secret/local-state text")
    identity = _require(
        _docker(
            "run",
            "--rm",
            "--entrypoint",
            "python",
            IMAGE_TAG,
            "-c",
            "import json,os,platform,sys; print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'python':platform.python_version(),'platform':sys.platform}))",
        ),
        "image runtime identity inspection",
    )
    runtime = json.loads(identity)
    if runtime["uid"] != 10001 or runtime["gid"] != 10001:
        raise ContainerProofBlocked("image process identity is not 10001:10001")
    return {
        "tag": IMAGE_TAG,
        "base": "python:3.13-slim-bookworm",
        "python": runtime["python"],
        "os": data["Os"],
        "architecture": data["Architecture"],
        "image_id": data["Id"],
        "size_bytes": data["Size"],
        "runtime_uid_gid": f"{runtime['uid']}:{runtime['gid']}",
        "dockerfile_sha256": _sha(DOCKERFILE),
        "runtime_requirements_sha256": _sha(RUNTIME_REQUIREMENTS),
        "filesystem_inspection": {**scan, "result": "PASS"},
        "history_inspection": "PASS",
        "published_remotely": False,
    }


def _wait_postgres(container: str, role: str, database: str) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = _docker("exec", container, "pg_isready", "--username", role, "--dbname", database, timeout=10)
        if result.returncode == 0:
            return
        time.sleep(1)
    raise ContainerProofBlocked("disposable PostgreSQL did not become ready")


def _dynamic_port(container: str, container_port: str) -> int:
    output = _require(_docker("port", container, container_port), "dynamic port inspection")
    binding = next((line for line in output.splitlines() if line.startswith("127.0.0.1:")), "")
    if not binding:
        raise ContainerProofBlocked("Docker port was not published to loopback")
    return int(binding.rsplit(":", 1)[1])


def _restore(container: str, role: str, database: str) -> None:
    destination = f"/tmp/{BACKUP_PATH.name}"
    _require(_docker("cp", str(BACKUP_PATH), f"{container}:{destination}", timeout=300), "backup copy")
    _require(
        _docker(
            "exec",
            container,
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            f"--username={role}",
            f"--dbname={database}",
            destination,
            timeout=900,
        ),
        "disposable PostgreSQL restore",
    )


def _backend_run_arguments(
    name: str,
    network: str,
    environment_path: Path,
    roots: dict[str, Path],
    *,
    publish: bool,
) -> list[str]:
    arguments = [
        "run",
        "--detach",
        "--name",
        name,
        "--network",
        network,
        "--env-file",
        str(environment_path),
        "--read-only",
        "--security-opt",
        "no-new-privileges:true",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--mount",
        f"type=bind,source={roots['cache']},target=/app-cache",
        "--mount",
        f"type=bind,source={roots['music']},target=/media/Music,readonly",
        "--mount",
        f"type=bind,source={roots['audiobooks']},target=/media/Audiobooks/Library,readonly",
        "--mount",
        f"type=bind,source={roots['books']},target=/media/Books,readonly",
    ]
    if publish:
        arguments.extend(["--publish", "127.0.0.1::8094"])
    arguments.append(IMAGE_TAG)
    return arguments


def _inspect_container(name: str) -> dict[str, Any]:
    return json.loads(_require(_docker("container", "inspect", name), f"{name} inspection"))[0]


def _wait_healthy(name: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = _inspect_container(name)
        status = (data.get("State", {}).get("Health") or {}).get("Status")
        if status == "healthy":
            return
        if not data.get("State", {}).get("Running"):
            raise ContainerProofBlocked("backend container exited before becoming healthy")
        time.sleep(1)
    raise ContainerProofBlocked("backend container did not become healthy in time")


def _http_json(port: int, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else None
    except HTTPError as exc:
        return exc.code, None
    except (URLError, TimeoutError, OSError) as exc:
        raise ContainerProofBlocked(f"HTTP canary failed for {path}") from exc


def _snapshot_url(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url)
    try:
        return _database_snapshot(engine)
    finally:
        engine.dispose()


def _require_http(port: int, path: str) -> Any:
    status, payload = _http_json(port, path)
    if status != 200:
        raise ContainerProofBlocked(f"HTTP read canary failed for {path}")
    return payload


def _filesystem_proof(api: str) -> dict[str, Any]:
    write_code = "from pathlib import Path; p=Path({path!r}); p.write_text('probe'); p.unlink()"
    denied: dict[str, bool] = {}
    for label, path in {
        "music": "/media/Music/.bm-prod5-6a-write-probe",
        "audiobooks": "/media/Audiobooks/Library/.bm-prod5-6a-write-probe",
        "books": "/media/Books/.bm-prod5-6a-write-probe",
        "root": "/bm-prod5-6a-root-write-probe",
    }.items():
        denied[label] = _docker("exec", api, "python", "-c", write_code.format(path=path), timeout=20).returncode != 0
    writable: dict[str, bool] = {}
    for label, path in {
        "tmp": "/tmp/bm-prod5-6a-write-probe",
        "cache": "/app-cache/bm-prod5-6a-write-probe",
        "artwork_cache": "/app-cache/artwork/bm-prod5-6a-write-probe",
    }.items():
        writable[label] = _docker("exec", api, "python", "-c", write_code.format(path=path), timeout=20).returncode == 0
    if not all(denied.values()) or not all(writable.values()):
        raise ContainerProofBlocked("read-only root/media or writable tmp/cache proof failed")
    return {"writes_denied": denied, "writes_succeeded": writable}


def _assert_hardening(name: str, roots: dict[str, Path], network: str) -> dict[str, Any]:
    data = _inspect_container(name)
    config = data["Config"]
    host = data["HostConfig"]
    if config.get("User") != "10001:10001" or host.get("ReadonlyRootfs") is not True:
        raise ContainerProofBlocked("live backend is not non-root with a read-only root")
    if host.get("NetworkMode") != network:
        raise ContainerProofBlocked("live backend is not attached to the task bridge network")
    mounts = {item["Destination"]: item for item in data.get("Mounts", [])}
    expected_ro = ("/media/Music", "/media/Audiobooks/Library", "/media/Books")
    if any(path not in mounts or mounts[path].get("RW") is not False for path in expected_ro):
        raise ContainerProofBlocked("synthetic media is not mounted read-only")
    if "/app-cache" not in mounts or mounts["/app-cache"].get("RW") is not True:
        raise ContainerProofBlocked("cache mount is not writable")
    allowed_mounts = {*expected_ro, "/app-cache", "/tmp"}
    if any(destination not in allowed_mounts for destination in mounts):
        raise ContainerProofBlocked("source bind mount detected")
    sources = {str(item.get("Source", "")).lower() for item in data.get("Mounts", [])}
    if any(source.endswith(".env") or "personal-radio\\media" in source for source in sources):
        raise ContainerProofBlocked("real environment/source/media mount detected")
    uid_gid = json.loads(
        _require(
            _docker("exec", name, "python", "-c", "import json,os; print(json.dumps({'uid':os.getuid(),'gid':os.getgid()}))"),
            "live runtime identity",
        )
    )
    if uid_gid != {"uid": 10001, "gid": 10001}:
        raise ContainerProofBlocked("live runtime identity changed")
    return {
        "non_root": True,
        "uid_gid": "10001:10001",
        "read_only_root": True,
        "tmpfs_tmp": "/tmp" in (host.get("Tmpfs") or {}),
        "writable_cache": True,
        "read_only_media": True,
        "source_bind_mount": False,
        "real_env_mount": False,
        "network": network,
    }


def _negative_canary(name: str, network: str, environment_path: Path, roots: dict[str, Path]) -> dict[str, Any]:
    _require(_docker(*_backend_run_arguments(name, network, environment_path, roots, publish=False)), f"{name} creation")
    ever_healthy = False
    deadline = time.monotonic() + 25
    data: dict[str, Any] = {}
    while time.monotonic() < deadline:
        data = _inspect_container(name)
        ever_healthy = ever_healthy or (data.get("State", {}).get("Health") or {}).get("Status") == "healthy"
        if not data.get("State", {}).get("Running"):
            break
        time.sleep(1)
    state = data.get("State", {})
    passed = not ever_healthy and not state.get("Running") and int(state.get("ExitCode", 0)) != 0
    if not passed:
        raise ContainerProofBlocked(f"negative fail-closed canary {name} did not fail closed")
    return {"result": "PASS", "ever_healthy": False, "running": False, "nonzero_exit": True, "sqlite_fallback": False}


def _cleanup(containers: list[str], network: str | None, task_root: Path | None) -> dict[str, Any]:
    for name in reversed(containers):
        if name and name.startswith(RESOURCE_PREFIX) and name != CONTAINER_NAME:
            _docker("container", "rm", "--force", name, timeout=120)
    if network and network.startswith(RESOURCE_PREFIX):
        _docker("network", "rm", network, timeout=120)
    if task_root and task_root.parent.resolve() == LOCAL_STATE_DIR.resolve() and task_root.name.startswith("bm-prod5-6a-"):
        shutil.rmtree(task_root, ignore_errors=True)
    remaining = _resource_inventory()
    return {"result": "PASS" if not any(remaining.values()) else "FAIL", "remaining": remaining}


def build_and_run() -> dict[str, Any]:
    gate = preflight()
    if gate["gate"] != "PASS":
        raise ContainerProofBlocked("preflight blocked: " + "; ".join(gate["blockers"]))
    before = _protected_state()
    retained = verify_retained_recovery_input(inspect_archive=False)

    _require(
        _docker("build", "--platform", "linux/amd64", "--tag", IMAGE_TAG, "--file", str(DOCKERFILE), str(BACKEND), timeout=1800),
        "production backend image build",
    )
    image = _inspect_image()

    run_id = secrets.token_hex(5)
    network = f"{RESOURCE_PREFIX}{run_id}"
    db_name = f"{RESOURCE_PREFIX}db-{run_id}"
    api_name = f"{RESOURCE_PREFIX}api-{run_id}"
    negative_names = {
        "unreachable": f"{RESOURCE_PREFIX}unreachable-{run_id}",
        "sqlite": f"{RESOURCE_PREFIX}sqlite-{run_id}",
        "stale": f"{RESOURCE_PREFIX}stale-{run_id}",
    }
    containers = [db_name, api_name, *negative_names.values()]
    role = f"bm_radio_container_{run_id}"
    database = "bm_radio"
    stale_database = "bm_radio_stale"
    password = secrets.token_urlsafe(32)
    task_root = LOCAL_STATE_DIR / f"bm-prod5-6a-{run_id}"
    roots = {
        "music": task_root / "media" / "Music",
        "audiobooks": task_root / "media" / "Audiobooks" / "Library",
        "books": task_root / "media" / "Books",
        "cache": task_root / "cache",
    }
    cleanup: dict[str, Any] = {}
    proof: dict[str, Any] = {}
    task_root.mkdir(parents=True)
    for path in roots.values():
        path.mkdir(parents=True)
    (roots["cache"] / "artwork").mkdir()
    db_env = task_root / "postgres.env"
    _write_env(db_env, {"POSTGRES_DB": database, "POSTGRES_USER": role, "POSTGRES_PASSWORD": password})

    try:
        _require(_docker("network", "create", "--driver", "bridge", network), "task bridge network creation")
        _require(
            _docker(
                "run",
                "--detach",
                "--name",
                db_name,
                "--network",
                network,
                "--network-alias",
                "postgres",
                "--env-file",
                str(db_env),
                "--tmpfs",
                "/var/lib/postgresql/data:rw,noexec,nosuid,size=768m",
                "--publish",
                "127.0.0.1::5432",
                POSTGRES_IMAGE,
                timeout=300,
            ),
            "disposable PostgreSQL creation",
        )
        _wait_postgres(db_name, role, database)
        db_port = _dynamic_port(db_name, "5432/tcp")
        _restore(db_name, role, database)
        host_url = URL.create(
            "postgresql+psycopg", username=role, password=password, host="127.0.0.1", port=db_port, database=database
        ).render_as_string(hide_password=False)
        container_url = URL.create(
            "postgresql+psycopg", username=role, password=password, host="postgres", port=5432, database=database
        ).render_as_string(hide_password=False)
        restored = verify_recovered_database(host_url, retained)
        baseline = restored["snapshot"]
        _require(_docker("exec", db_name, "createdb", "--username", role, stale_database), "stale database creation")

        api_env = task_root / "backend.env"
        _write_env(api_env, _base_environment(container_url))
        before_start = _snapshot_url(host_url)
        _require(_docker(*_backend_run_arguments(api_name, network, api_env, roots, publish=True)), "backend container creation")
        _wait_healthy(api_name)
        api_port = _dynamic_port(api_name, "8094/tcp")
        hardening = _assert_hardening(api_name, roots, network)
        after_start = _snapshot_url(host_url)
        if before_start != after_start:
            raise ContainerProofBlocked("backend startup changed disposable PostgreSQL")

        health = _require_http(api_port, "/api/health")
        if health.get("database_ready") is not True or str(health.get("environment", "")).lower() != "production":
            raise ContainerProofBlocked("container health response is not production/database-ready")
        docs_status, _ = _http_json(api_port, "/docs")
        if docs_status != 404:
            raise ContainerProofBlocked("production API documentation is enabled")
        read_paths = {
            "health_readiness": "/api/health",
            "library_summary": "/api/library/summary",
            "artists": "/api/library/artists",
            "albums_releases": "/api/library/albums",
            "search": "/api/search?q=container-canary-no-match",
            "playlists": "/api/playlists",
            "stations": "/api/stations/",
            "audiobooks": "/api/audiobooks/",
        }
        read_canaries = {label: "PASS" if _require_http(api_port, path) is not None else "PASS" for label, path in read_paths.items()}
        engine = create_engine(host_url)
        try:
            with engine.connect() as connection:
                recording_id = connection.execute(text("select min(id) from music_recordings")).scalar_one_or_none()
        finally:
            engine.dispose()
        read_canaries["recording_controls"] = (
            "PASS" if recording_id is not None and _require_http(api_port, f"/api/music/recordings/{int(recording_id)}/control") is not None else "not_applicable"
        )

        canary_name = f"BM-PROD5.6A Container Canary {run_id}"
        status, created = _http_json(
            api_port,
            "/api/playlists",
            method="POST",
            payload={"name": canary_name, "description": "temporary disposable-container canary"},
        )
        if status != 200:
            raise ContainerProofBlocked("playlist create canary failed")
        playlist_id = int(created["id"])
        engine = create_engine(host_url)
        try:
            with engine.connect() as connection:
                present = connection.execute(
                    text("select count(*) from playlists where id=:playlist_id and name=:name"),
                    {"playlist_id": playlist_id, "name": canary_name},
                ).scalar_one()
        finally:
            engine.dispose()
        if int(present) != 1:
            raise ContainerProofBlocked("playlist write did not reach disposable PostgreSQL")
        status, deleted = _http_json(api_port, f"/api/playlists/{playlist_id}", method="DELETE")
        if status != 200 or not deleted.get("deleted"):
            raise ContainerProofBlocked("playlist delete canary failed")
        restored_after_write = verify_recovered_database(host_url, retained)

        filesystem = _filesystem_proof(api_name)
        before_restart = _inspect_container(api_name)
        _require(_docker("restart", api_name, timeout=120), "backend restart")
        _wait_healthy(api_name)
        after_restart = _inspect_container(api_name)
        restart_hardening = _assert_hardening(api_name, roots, network)
        restarted_database = verify_recovered_database(host_url, retained)
        if before_restart["HostConfig"]["ReadonlyRootfs"] != after_restart["HostConfig"]["ReadonlyRootfs"]:
            raise ContainerProofBlocked("read-only root changed across restart")

        unreachable_env = task_root / "unreachable.env"
        unreachable_url = URL.create(
            "postgresql+psycopg", username=role, password=password, host=f"{RESOURCE_PREFIX}missing", port=5432, database=database
        ).render_as_string(hide_password=False)
        _write_env(unreachable_env, _base_environment(unreachable_url))
        sqlite_env = task_root / "sqlite.env"
        _write_env(sqlite_env, _base_environment("sqlite:////tmp/bm-prod5-6a.sqlite"))
        stale_env = task_root / "stale.env"
        stale_url = URL.create(
            "postgresql+psycopg", username=role, password=password, host="postgres", port=5432, database=stale_database
        ).render_as_string(hide_password=False)
        _write_env(stale_env, _base_environment(stale_url))
        negatives = {
            "unreachable_postgresql": _negative_canary(negative_names["unreachable"], network, unreachable_env, roots),
            "production_sqlite": _negative_canary(negative_names["sqlite"], network, sqlite_env, roots),
            "stale_postgresql": _negative_canary(negative_names["stale"], network, stale_env, roots),
        }
        final_disposable = verify_recovered_database(host_url, retained)
        proof = {
            "status": "BACKEND-CONTAINER PASS",
            "source_commit": STARTING_COMMIT,
            "image": image,
            "disposable_postgresql": {
                "image": POSTGRES_IMAGE,
                "network": "user-defined bridge",
                "restore": "PASS",
                "revision": baseline["revision"],
                "tables": baseline["application_table_count"],
                "rows": baseline["application_total_rows"],
                "counts_equal": restored["count_equality"],
                "digests_equal": restored["canonical_digest_equality"],
                "active_target_used": False,
                "named_volume_created": False,
            },
            "backend": {
                "startup": "PASS",
                "health": "healthy",
                "dialect": "postgresql",
                "driver": "psycopg",
                "environment": health["environment"],
                "api_docs": "disabled",
                "startup_row_delta": 0,
                "port_publication": f"127.0.0.1:dynamic->{8094}",
                **hardening,
            },
            "read_canaries": read_canaries,
            "write_canary": {
                "create": "PASS",
                "delete": "PASS",
                "rows_restored": restored_after_write["snapshot"]["application_total_rows"] == EXPECTED_SOURCE_ROWS,
                "digests_restored": restored_after_write["canonical_digest_equality"],
            },
            "filesystem": filesystem,
            "restart": {
                "result": "PASS",
                "health": "healthy",
                "rows": restarted_database["snapshot"]["application_total_rows"],
                "digests_unchanged": restarted_database["canonical_digest_equality"],
                **restart_hardening,
            },
            "negative_canaries": negatives,
            "final_disposable_rows": final_disposable["snapshot"]["application_total_rows"],
            "final_disposable_digests_equal": final_disposable["canonical_digest_equality"],
        }
    finally:
        cleanup = _cleanup(containers, network, task_root)

    if cleanup.get("result") != "PASS":
        raise ContainerProofBlocked("disposable task cleanup was incomplete")
    after = _protected_state()
    if before != after:
        raise ContainerProofBlocked("protected active PostgreSQL, SQLite, environment, or durable evidence changed")
    proof["cleanup"] = cleanup
    proof["protected_state"] = {
        "active_postgresql_unchanged": True,
        "sqlite_unchanged": True,
        "environment_and_evidence_unchanged": True,
    }
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.6A production backend container proof")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--build-and-run", action="store_true")
    arguments = parser.parse_args()
    try:
        result = preflight() if arguments.preflight_only else build_and_run()
        print(json.dumps(result, indent=2, sort_keys=True))
        if arguments.preflight_only:
            print(f"BM-PROD5.6A PREFLIGHT: {result['gate']}")
            return 0 if result["gate"] == "PASS" else 2
        print("BM-PROD5.6A status: BACKEND-CONTAINER PASS")
        return 0
    except (ContainerProofBlocked, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        print(f"BM-PROD5.6A status: BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
