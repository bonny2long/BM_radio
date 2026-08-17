from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.engine import URL


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
FRONTEND = PROJECT / "frontend"
BACKEND_LIVE_PATH = BACKEND / "scripts" / "check_prod5_6a_backend_container.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_spec = importlib.util.spec_from_file_location("bm_prod5_6a_live", BACKEND_LIVE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("BM-PROD5.6A live helper cannot be loaded")
backend_live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backend_live)

from app.local_postgres_adoption import (  # noqa: E402
    CONTAINER_NAME,
    LOCAL_STATE_DIR,
    VOLUME_NAME,
    container_status,
    docker_context_status,
)
from app.postgres_backup_restore import _process_quiescence  # noqa: E402
from app.postgres_recovery import (  # noqa: E402
    BACKUP_PATH,
    EXPECTED_SOURCE_ROWS,
    verify_retained_recovery_input,
)


STARTING_COMMIT = "18775bea08d19ea84bd87364c1bbacf206c7b746"
RESOURCE_PREFIX = "bm-prod5-6b-"
BACKEND_IMAGE = "bm-radio-backend:prod5.6a-bc444f3"
FRONTEND_IMAGE = "bm-radio-frontend:prod5.6b-18775be"
POSTGRES_IMAGE = "postgres:16"
NODE_BASE = "node:22.14.0-alpine3.21"
NGINX_BASE = "nginxinc/nginx-unprivileged:1.27.4-alpine"
FRONTEND_DOCKERFILE = FRONTEND / "Dockerfile"

_docker = backend_live._docker
_require = backend_live._require
_run = backend_live._run
_write_env = backend_live._write_env
_protected_state = backend_live._protected_state
_inspect_container = backend_live._inspect_container
_wait_postgres = backend_live._wait_postgres
_dynamic_port = backend_live._dynamic_port
_restore = backend_live._restore


class IntegratedStackBlocked(RuntimeError):
    pass


VERIFY_CODE = r'''
import enum, hashlib, json, math, os
from datetime import UTC, datetime
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.sql.sqltypes import Boolean, DateTime, Enum, Float, Integer
from app.database_readiness import inspect_database_readiness
from app.migration_contract import APP_TABLES
from app.models import Base

def datetime_value(value):
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")

def canonical_value(column, value):
    if value is None:
        return ["null", None]
    if isinstance(column.type, Boolean):
        return ["boolean", bool(value)]
    if isinstance(column.type, Enum):
        raw = value.value if isinstance(value, enum.Enum) else str(value)
        return ["enum", raw]
    if isinstance(column.type, DateTime):
        return ["datetime", datetime_value(value)]
    if isinstance(column.type, Float):
        number = float(value)
        if not math.isfinite(number):
            raise RuntimeError("non-finite float")
        return ["float", number.hex()]
    if isinstance(column.type, Integer):
        return ["integer", int(value)]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, str):
        return ["text", value]
    return [type(value).__name__, str(value)]

engine = create_engine(os.environ["BM_VERIFY_DB_URL"], connect_args={"connect_timeout": 5}, pool_pre_ping=True)
try:
    readiness = inspect_database_readiness(engine)
    counts, digests = {}, {}
    for name in APP_TABLES:
        table = Base.metadata.tables[name]
        primary_key = tuple(table.primary_key.columns)
        digest = hashlib.sha256()
        count = 0
        with engine.connect() as connection:
            rows = connection.execute(select(table).order_by(*primary_key)).mappings()
            for row in rows:
                payload = {
                    "table": name,
                    "columns": [column.name for column in table.columns],
                    "values": [canonical_value(column, row[column.name]) for column in table.columns],
                }
                digest.update(json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
                digest.update(b"\n")
                count += 1
        counts[name] = count
        digests[name] = digest.hexdigest()
    with engine.connect() as connection:
        recording_id = connection.execute(text("select min(id) from music_recordings")).scalar_one_or_none()
        server_version = str(connection.execute(text("show server_version")).scalar_one())
    print("BM_PROD5_6B_VERIFY=" + json.dumps({
        "revision": readiness.current_revision,
        "head_revision": readiness.head_revision,
        "readiness": readiness.status,
        "ready": readiness.ready,
        "table_count": len(counts),
        "rows": sum(counts.values()),
        "counts": counts,
        "digests": digests,
        "recording_id": recording_id,
        "server_version": server_version,
    }, sort_keys=True))
finally:
    engine.dispose()
'''


def _git_head() -> str:
    return _require(_run(["git", "rev-parse", "HEAD"]), "Git HEAD inspection")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resource_inventory() -> dict[str, list[str]]:
    containers = _require(
        _docker("container", "ls", "-a", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Names}}"),
        "5.6B container inventory",
    )
    networks = _require(
        _docker("network", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"),
        "5.6B network inventory",
    )
    volumes = _require(
        _docker("volume", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"),
        "5.6B volume inventory",
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
        blockers.append("Git HEAD is not the accepted BM-PROD5.6A implementation commit")
    docker = docker_context_status()
    if not (docker.get("available") and docker.get("local") and docker.get("linux")):
        blockers.append("a reachable local Docker Linux engine is required")
    active = container_status() if docker.get("available") else {}
    if not all(active.get(key) for key in ("exists", "running", "healthy", "loopback_binding", "named_volume")):
        blockers.append("protected active PostgreSQL identity or health is invalid")
    if CONTAINER_NAME.startswith(RESOURCE_PREFIX) or VOLUME_NAME.startswith(RESOURCE_PREFIX):
        blockers.append("task resource prefix overlaps protected PostgreSQL")
    quiescence = _process_quiescence()
    if not quiescence.get("inspectable") or quiescence.get("writer_detected"):
        blockers.append("BM Radio backend writer quiescence is not proven")
    retained: dict[str, Any] = {}
    protected: dict[str, Any] = {}
    resources: dict[str, list[str]] = {"containers": [], "networks": [], "volumes": []}
    try:
        retained = verify_retained_recovery_input(inspect_archive=False)
        protected = _protected_state()
        snapshot = protected["snapshot"]
        if snapshot["active_postgresql"]["application_total_rows"] != EXPECTED_SOURCE_ROWS:
            blockers.append("active PostgreSQL no longer matches accepted row count")
        if snapshot["sqlite_fallback"]["application_total_rows"] != EXPECTED_SOURCE_ROWS:
            blockers.append("SQLite fallback no longer matches accepted row count")
        resources = _resource_inventory()
        if any(resources.values()):
            blockers.append("stale BM-PROD5.6B Docker resources already exist")
        if _docker("image", "inspect", BACKEND_IMAGE).returncode != 0:
            blockers.append("accepted production backend image is unavailable")
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


def _image_metadata() -> dict[str, Any]:
    data = json.loads(_require(_docker("image", "inspect", FRONTEND_IMAGE), "frontend image inspection"))[0]
    config = data.get("Config", {})
    if data.get("Os") != "linux" or data.get("Architecture") != "amd64":
        raise IntegratedStackBlocked("frontend image is not Linux/amd64")
    if config.get("User") != "101:101":
        raise IntegratedStackBlocked("frontend image user is not 101:101")
    if "8080/tcp" not in (config.get("ExposedPorts") or {}):
        raise IntegratedStackBlocked("frontend image does not expose 8080")
    command = " ".join(config.get("Cmd") or [])
    if "nginx" not in command or "vite" in command.lower():
        raise IntegratedStackBlocked("frontend runtime is not the production Nginx server")

    listing = _require(
        _docker(
            "run",
            "--rm",
            "--entrypoint",
            "sh",
            FRONTEND_IMAGE,
            "-c",
            "find /usr/share/nginx/html -mindepth 1 -print | sort",
        ),
        "frontend filesystem listing",
    )
    lowered_paths = listing.lower()
    forbidden_paths = ("node_modules", "/.env", "/.git", ".sqlite", ".db", ".dump", "local_backups", "local_postgres")
    if any(token in lowered_paths for token in forbidden_paths):
        raise IntegratedStackBlocked("frontend image contains forbidden build or local-state paths")
    content_scan = _docker(
        "run",
        "--rm",
        "--entrypoint",
        "sh",
        FRONTEND_IMAGE,
        "-c",
        "if grep -r -I -E '127\\.0\\.0\\.1:8094|bonnymakaniankhondo|postgresql\\+psycopg|postgres_password' /usr/share/nginx/html /etc/nginx/nginx.conf; then exit 3; else exit 0; fi",
    )
    if content_scan.returncode != 0:
        raise IntegratedStackBlocked("frontend image contains localhost, personal-path, or secret text")
    history = _require(_docker("history", "--no-trunc", "--format", "{{.CreatedBy}}", FRONTEND_IMAGE), "frontend history")
    if any(token in history.lower() for token in ("bonnymakaniankhondo", "postgres_password", "postgresql+psycopg://")):
        raise IntegratedStackBlocked("frontend image history contains forbidden text")

    bases: dict[str, Any] = {}
    for label, tag in (("node", NODE_BASE), ("nginx", NGINX_BASE)):
        local = _docker("image", "inspect", tag)
        if local.returncode == 0:
            inspected = json.loads(local.stdout)[0]
            bases[label] = {"tag": tag, "id": inspected["Id"], "repo_digests": inspected.get("RepoDigests") or []}
            continue
        remote = _require(_docker("buildx", "imagetools", "inspect", tag), f"{label} base digest inspection")
        digest_match = re.search(r"^Digest:\s+(sha256:[0-9a-f]{64})$", remote, flags=re.MULTILINE)
        if digest_match is None:
            raise IntegratedStackBlocked(f"{label} base digest could not be resolved")
        bases[label] = {"tag": tag, "id": None, "repo_digests": [f"{tag.split(':', 1)[0]}@{digest_match.group(1)}"]}
    return {
        "tag": FRONTEND_IMAGE,
        "id": data["Id"],
        "size_bytes": data["Size"],
        "os": data["Os"],
        "architecture": data["Architecture"],
        "user": config["User"],
        "dockerfile_sha256": _sha(FRONTEND_DOCKERFILE),
        "bases": bases,
        "static_path_count": len(listing.splitlines()),
        "filesystem_inspection": "PASS",
        "history_inspection": "PASS",
        "production_api_base": "/api",
        "published_remotely": False,
    }


def _wait_health(name: str, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = _inspect_container(name)
        health = (data.get("State", {}).get("Health") or {}).get("Status")
        if health == "healthy":
            return
        if not data.get("State", {}).get("Running"):
            raise IntegratedStackBlocked(f"{name} exited before becoming healthy")
        time.sleep(1)
    raise IntegratedStackBlocked(f"{name} did not become healthy")


def _verify_database(network: str, environment_path: Path, retained: dict[str, Any]) -> dict[str, Any]:
    result = _docker(
        "run",
        "--rm",
        "--network",
        network,
        "--env-file",
        str(environment_path),
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=32m",
        "--security-opt",
        "no-new-privileges:true",
        "--entrypoint",
        "python",
        BACKEND_IMAGE,
        "-c",
        VERIFY_CODE,
        timeout=300,
    )
    output = _require(result, "private-network canonical database verification")
    marker = next((line for line in reversed(output.splitlines()) if line.startswith("BM_PROD5_6B_VERIFY=")), None)
    if marker is None:
        raise IntegratedStackBlocked("database verifier returned no result")
    payload = json.loads(marker.split("=", 1)[1])
    if (
        payload.get("ready") is not True
        or payload.get("readiness") != "ready"
        or payload.get("revision") != payload.get("head_revision")
        or payload.get("table_count") != 21
        or payload.get("rows") != EXPECTED_SOURCE_ROWS
        or payload.get("counts") != retained.get("manifest_counts")
        or payload.get("digests") != retained.get("manifest_digests")
    ):
        raise IntegratedStackBlocked("disposable PostgreSQL does not exactly match the accepted backup")
    return payload


def _http(
    port: int,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read()
    except HTTPError as exc:
        return exc.code, {key.lower(): value for key, value in exc.headers.items()}, exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise IntegratedStackBlocked(f"frontend-origin request failed for {path}") from exc


def _json_response(port: int, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    status, _headers, body = _http(port, path, method=method, payload=payload)
    try:
        value = json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegratedStackBlocked(f"frontend-origin JSON response invalid for {path}") from exc
    return status, value


def _require_json(port: int, path: str) -> Any:
    status, payload = _json_response(port, path)
    if status != 200:
        raise IntegratedStackBlocked(f"frontend-origin read canary failed for {path}")
    return payload


def _wait_frontend_origin(port: int, *, require_api: bool, phase: str, timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            healthz = _http(port, "/healthz")[0] == 200
            api_ready = True
            if require_api:
                status, payload = _json_response(port, "/api/health")
                api_ready = status == 200 and isinstance(payload, dict) and payload.get("database_ready") is True
            if healthz and api_ready:
                return
        except IntegratedStackBlocked:
            pass
        time.sleep(1)
    raise IntegratedStackBlocked(f"frontend origin did not become ready during {phase}")


def _assert_stack_hardening(db_name: str, api_name: str, web_name: str, network: str) -> dict[str, Any]:
    db = _inspect_container(db_name)
    api = _inspect_container(api_name)
    web = _inspect_container(web_name)
    for name, data in ((db_name, db), (api_name, api), (web_name, web)):
        host = data["HostConfig"]
        if host.get("Privileged") or host.get("NetworkMode") == "host":
            raise IntegratedStackBlocked(f"{name} uses privileged or host-network mode")
        if any(item.get("Destination") == "/var/run/docker.sock" for item in data.get("Mounts", [])):
            raise IntegratedStackBlocked(f"{name} mounts the Docker socket")
        if host.get("NetworkMode") != network:
            raise IntegratedStackBlocked(f"{name} is outside the private task network")
    if (db["HostConfig"].get("PortBindings") or {}) or (api["HostConfig"].get("PortBindings") or {}):
        raise IntegratedStackBlocked("backend or PostgreSQL is host-published")
    web_bindings = web["HostConfig"].get("PortBindings") or {}
    bindings = web_bindings.get("8080/tcp") or []
    if len(bindings) != 1 or bindings[0].get("HostIp") != "127.0.0.1":
        raise IntegratedStackBlocked("frontend is not the only loopback-published service")
    if api["Config"].get("User") != "10001:10001" or api["HostConfig"].get("ReadonlyRootfs") is not True:
        raise IntegratedStackBlocked("backend is not non-root/read-only")
    if web["Config"].get("User") != "101:101" or web["HostConfig"].get("ReadonlyRootfs") is not True:
        raise IntegratedStackBlocked("frontend is not non-root/read-only")
    api_mounts = {item["Destination"]: item for item in api.get("Mounts", [])}
    for path in ("/media/Music", "/media/Audiobooks/Library", "/media/Books"):
        if path not in api_mounts or api_mounts[path].get("RW") is not False:
            raise IntegratedStackBlocked("synthetic media is not read-only")
    return {
        "frontend_only_publication": True,
        "frontend_loopback_only": True,
        "backend_host_publication": False,
        "postgres_host_publication": False,
        "frontend_non_root_read_only": True,
        "backend_non_root_read_only": True,
        "synthetic_media_read_only": True,
        "privileged": False,
        "host_network": False,
        "docker_socket_mount": False,
    }


def _integrated_http_proof(port: int, recording_id: int | None, run_id: str) -> dict[str, Any]:
    root_status, root_headers, root_body = _http(port, "/")
    if root_status != 200 or b"<html" not in root_body.lower():
        raise IntegratedStackBlocked("frontend root did not serve built index")
    if "must-revalidate" not in root_headers.get("cache-control", ""):
        raise IntegratedStackBlocked("frontend index is not no-cache/must-revalidate")
    for header in ("x-content-type-options", "referrer-policy", "x-frame-options", "content-security-policy"):
        if header not in root_headers:
            raise IntegratedStackBlocked(f"frontend security header missing: {header}")
    html = root_body.decode("utf-8")
    assets = sorted(set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)))
    if not assets or not any(path.endswith(".js") for path in assets) or not any(path.endswith(".css") for path in assets):
        raise IntegratedStackBlocked("built JS/CSS assets were not found in index")
    asset_results: dict[str, str] = {}
    for path in assets:
        status, headers, body = _http(port, path)
        if status != 200 or not body or "immutable" not in headers.get("cache-control", ""):
            raise IntegratedStackBlocked(f"hashed asset policy failed for {path}")
        asset_results[path] = "PASS"
    spa_status, _spa_headers, spa_body = _http(port, "/library/deep-link-container-proof")
    if spa_status != 200 or hashlib.sha256(spa_body).digest() != hashlib.sha256(root_body).digest():
        raise IntegratedStackBlocked("unknown SPA route did not return frontend index")
    healthz_status, _headers, healthz_body = _http(port, "/healthz")
    if healthz_status != 200 or healthz_body.strip() != b"ok":
        raise IntegratedStackBlocked("frontend-local health endpoint failed")
    health = _require_json(port, "/api/health")
    if health.get("database_ready") is not True or str(health.get("environment", "")).lower() != "production":
        raise IntegratedStackBlocked("proxied backend health is not production/database-ready")
    docs_status, _docs = _json_response(port, "/api/docs")
    if docs_status != 404:
        raise IntegratedStackBlocked("backend API docs are enabled")

    paths = {
        "library_summary": "/api/library/summary",
        "artists": "/api/library/artists",
        "albums_releases": "/api/library/albums",
        "search": "/api/search?q=integrated-container-no-match",
        "playlists": "/api/playlists",
        "stations": "/api/stations/",
        "audiobooks": "/api/audiobooks/",
    }
    read_canaries = {label: "PASS" if _require_json(port, path) is not None else "PASS" for label, path in paths.items()}
    if recording_id is not None:
        _require_json(port, f"/api/music/recordings/{recording_id}/control")
        read_canaries["recording_controls"] = "PASS"
    else:
        read_canaries["recording_controls"] = "not_applicable"

    tracks = _require_json(port, "/api/library/tracks?limit=1&offset=0")
    if not tracks:
        raise IntegratedStackBlocked("accepted fixture has no representative track URL")
    track = tracks[0]
    media_paths = [track.get("cover_url"), track.get("stream_url")]
    albums = _require_json(port, "/api/library/albums")
    if albums:
        media_paths.append(albums[0].get("cover_url"))
    books = _require_json(port, "/api/audiobooks/")
    if books:
        media_paths.append(books[0].get("cover_url"))
    audited: dict[str, int] = {}
    for path in [str(item) for item in media_paths if item]:
        if not path.startswith("/api/media/") or path.startswith("http://") or path.startswith("https://"):
            raise IntegratedStackBlocked("API media URL is not same-origin /api/media")
        status, headers, body = _http(port, path)
        if status not in {404, 409} or b"<html" in body.lower() or "application/json" not in headers.get("content-type", ""):
            raise IntegratedStackBlocked("missing synthetic media did not return a controlled backend response")
        audited[path] = status

    canary_name = f"BM-PROD5.6B Integrated Canary {run_id}"
    status, created = _json_response(
        port,
        "/api/playlists",
        method="POST",
        payload={"name": canary_name, "description": "temporary proxied integrated-stack canary"},
    )
    if status != 200:
        raise IntegratedStackBlocked("proxied playlist create failed")
    playlist_id = int(created["id"])
    detail = _require_json(port, f"/api/playlists/{playlist_id}")
    if detail.get("name") != canary_name:
        raise IntegratedStackBlocked("proxied playlist verification failed")
    status, deleted = _json_response(port, f"/api/playlists/{playlist_id}", method="DELETE")
    if status != 200 or not deleted.get("deleted"):
        raise IntegratedStackBlocked("proxied playlist delete failed")

    secret_results: dict[str, int] = {}
    for path in ("/.env", "/.git/config", "/backend/.env"):
        status, _headers, body = _http(port, path)
        if status != 404 or b"vite" in body.lower() or b"postgres" in body.lower():
            raise IntegratedStackBlocked("frontend exposed or SPA-fell-back for a secret path")
        secret_results[path] = status
    traversal_results: dict[str, int] = {}
    for path in ("/%2e%2e/%2e%2e/etc/passwd", "/..%2f..%2fetc%2fpasswd"):
        status, _headers, body = _http(port, path)
        if status not in {400, 404} or b"root:x:" in body:
            raise IntegratedStackBlocked("malformed traversal request was not safely rejected")
        traversal_results[path] = status

    return {
        "root": "PASS",
        "assets": asset_results,
        "spa_fallback": "PASS",
        "healthz": "PASS",
        "api_health": "PASS",
        "security_headers": "PASS",
        "index_cache": "no-cache, must-revalidate",
        "asset_cache": "long immutable",
        "read_canaries": read_canaries,
        "media_routes": audited,
        "write_canary": {"create": "PASS", "verify": "PASS", "delete": "PASS"},
        "api_docs": "disabled",
        "secret_paths": secret_results,
        "traversal": traversal_results,
        "scanner_invoked": False,
        "real_media_accessed": False,
    }


def _cleanup(containers: list[str], network: str | None, volume: str | None, task_root: Path | None) -> dict[str, Any]:
    for name in reversed(containers):
        if name and name.startswith(RESOURCE_PREFIX) and name != CONTAINER_NAME:
            _docker("container", "rm", "--force", name, timeout=120)
    if network and network.startswith(RESOURCE_PREFIX):
        _docker("network", "rm", network, timeout=120)
    if volume and volume.startswith(RESOURCE_PREFIX) and volume != VOLUME_NAME:
        _docker("volume", "rm", volume, timeout=120)
    if task_root and task_root.parent.resolve() == LOCAL_STATE_DIR.resolve() and task_root.name.startswith(RESOURCE_PREFIX):
        shutil.rmtree(task_root, ignore_errors=True)
    remaining = _resource_inventory()
    return {"result": "PASS" if not any(remaining.values()) else "FAIL", "remaining": remaining}


def build_and_run() -> dict[str, Any]:
    gate = preflight()
    if gate["gate"] != "PASS":
        raise IntegratedStackBlocked("preflight blocked: " + "; ".join(gate["blockers"]))
    before = _protected_state()
    retained = verify_retained_recovery_input(inspect_archive=False)
    _require(
        _docker(
            "build",
            "--pull",
            "--platform",
            "linux/amd64",
            "--build-arg",
            "VITE_API_BASE_URL=/api",
            "--tag",
            FRONTEND_IMAGE,
            "--file",
            str(FRONTEND_DOCKERFILE),
            str(FRONTEND),
            timeout=1800,
        ),
        "production frontend image build",
    )
    image = _image_metadata()

    run_id = secrets.token_hex(5)
    network = f"{RESOURCE_PREFIX}{run_id}"
    db_name = f"{RESOURCE_PREFIX}db-{run_id}"
    api_name = f"{RESOURCE_PREFIX}api-{run_id}"
    web_name = f"{RESOURCE_PREFIX}web-{run_id}"
    volume = f"{RESOURCE_PREFIX}db-data-{run_id}"
    containers = [db_name, api_name, web_name]
    task_root = LOCAL_STATE_DIR / f"{RESOURCE_PREFIX}{run_id}"
    role = f"bm_radio_stack_{run_id}"
    database = "bm_radio"
    password = secrets.token_urlsafe(32)
    roots = {
        "music": task_root / "media" / "Music",
        "audiobooks": task_root / "media" / "Audiobooks" / "Library",
        "books": task_root / "media" / "Books",
        "cache": task_root / "cache",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    (roots["cache"] / "artwork").mkdir()
    db_env = task_root / "postgres.env"
    _write_env(db_env, {"POSTGRES_DB": database, "POSTGRES_USER": role, "POSTGRES_PASSWORD": password})
    db_url = URL.create(
        "postgresql+psycopg", username=role, password=password, host="postgres", port=5432, database=database
    ).render_as_string(hide_password=False)
    api_env = task_root / "backend.env"
    _write_env(api_env, backend_live._base_environment(db_url))
    verify_env = task_root / "verify.env"
    _write_env(verify_env, {"BM_VERIFY_DB_URL": db_url})

    cleanup: dict[str, Any] = {}
    proof: dict[str, Any] = {}
    try:
        _require(_docker("network", "create", "--driver", "bridge", network), "private bridge creation")
        _require(_docker("volume", "create", volume), "disposable PostgreSQL volume creation")
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
                "--mount",
                f"type=volume,source={volume},target=/var/lib/postgresql/data",
                "--health-cmd",
                "pg_isready --username=$POSTGRES_USER --dbname=$POSTGRES_DB",
                "--health-interval",
                "5s",
                "--health-timeout",
                "5s",
                "--health-retries",
                "24",
                "--security-opt",
                "no-new-privileges:true",
                POSTGRES_IMAGE,
                timeout=300,
            ),
            "private disposable PostgreSQL creation",
        )
        _wait_postgres(db_name, role, database)
        _restore(db_name, role, database)
        baseline = _verify_database(network, verify_env, retained)

        _require(
            _docker(
                "run",
                "--detach",
                "--name",
                api_name,
                "--network",
                network,
                "--network-alias",
                "backend",
                "--env-file",
                str(api_env),
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
                BACKEND_IMAGE,
                timeout=300,
            ),
            "private backend creation",
        )
        _wait_health(api_name)
        after_api_start = _verify_database(network, verify_env, retained)

        _require(
            _docker(
                "run",
                "--detach",
                "--name",
                web_name,
                "--network",
                network,
                "--network-alias",
                "frontend",
                "--read-only",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=32m",
                "--publish",
                "127.0.0.1::8080",
                FRONTEND_IMAGE,
                timeout=300,
            ),
            "frontend creation",
        )
        _wait_health(web_name)
        web_port = _dynamic_port(web_name, "8080/tcp")
        _wait_frontend_origin(web_port, require_api=True, phase="initial startup")
        hardening = _assert_stack_hardening(db_name, api_name, web_name, network)
        integrated = _integrated_http_proof(web_port, baseline.get("recording_id"), run_id)
        after_write = _verify_database(network, verify_env, retained)

        _require(_docker("restart", web_name, timeout=120), "frontend restart")
        _wait_health(web_name)
        web_port = _dynamic_port(web_name, "8080/tcp")
        _wait_frontend_origin(web_port, require_api=True, phase="frontend restart")
        frontend_restart = "PASS"

        _require(_docker("restart", api_name, timeout=120), "backend restart")
        if _http(web_port, "/")[0] != 200:
            raise IntegratedStackBlocked("frontend static service failed during backend restart")
        _wait_health(api_name)
        if _require_json(web_port, "/api/health").get("database_ready") is not True:
            raise IntegratedStackBlocked("proxied API did not recover after backend restart")
        backend_restart = "PASS"

        _require(_docker("restart", db_name, timeout=180), "PostgreSQL restart")
        _wait_health(db_name)
        deadline = time.monotonic() + 120
        postgres_recovered = False
        while time.monotonic() < deadline:
            try:
                if _require_json(web_port, "/api/library/summary") is not None:
                    postgres_recovered = True
                    break
            except IntegratedStackBlocked:
                pass
            time.sleep(2)
        if not postgres_recovered:
            raise IntegratedStackBlocked("backend did not recover after PostgreSQL restart")
        after_postgres_restart = _verify_database(network, verify_env, retained)

        _require(_docker("stop", web_name, timeout=120), "ordered frontend stop")
        _require(_docker("stop", api_name, timeout=120), "ordered backend stop")
        _require(_docker("stop", db_name, timeout=120), "ordered PostgreSQL stop")
        _require(_docker("start", db_name, timeout=120), "ordered PostgreSQL start")
        _wait_health(db_name)
        _require(_docker("start", api_name, timeout=120), "ordered backend start")
        _wait_health(api_name)
        _require(_docker("start", web_name, timeout=120), "ordered frontend start")
        _wait_health(web_name)
        web_port = _dynamic_port(web_name, "8080/tcp")
        _wait_frontend_origin(web_port, require_api=True, phase="ordered full-stack restart")
        final_database = _verify_database(network, verify_env, retained)
        final_hardening = _assert_stack_hardening(db_name, api_name, web_name, network)

        proof = {
            "status": "INTEGRATED-STACK PASS",
            "source_commit": STARTING_COMMIT,
            "frontend_image": image,
            "topology": {
                "frontend": "loopback-only dynamic host port -> 8080",
                "backend": "private network only -> 8094",
                "postgresql": "private network only -> 5432",
                "network": "user-defined bridge",
                "frontend_only_user_facing": True,
            },
            "hardening": {**hardening, "post_restart": final_hardening},
            "database": {
                "image": POSTGRES_IMAGE,
                "version": baseline["server_version"],
                "restore": "PASS",
                "revision": baseline["revision"],
                "tables": baseline["table_count"],
                "rows": baseline["rows"],
                "counts_equal": baseline["counts"] == retained["manifest_counts"],
                "digests_equal": baseline["digests"] == retained["manifest_digests"],
                "backend_start_zero_delta": after_api_start["digests"] == baseline["digests"],
                "write_cleanup_exact": after_write["digests"] == baseline["digests"],
                "postgres_restart_exact": after_postgres_restart["digests"] == baseline["digests"],
                "final_exact": final_database["digests"] == baseline["digests"],
            },
            "integrated_http": integrated,
            "restarts": {
                "frontend": frontend_restart,
                "backend": backend_restart,
                "postgresql": "PASS",
                "ordered_full_stack": "PASS",
            },
            "images_published": False,
            "truenas_deployed": False,
        }
    finally:
        cleanup = _cleanup(containers, network, volume, task_root)

    if cleanup.get("result") != "PASS":
        raise IntegratedStackBlocked("BM-PROD5.6B resource cleanup was incomplete")
    after = _protected_state()
    if before != after:
        raise IntegratedStackBlocked("protected PostgreSQL, SQLite, environment, or evidence changed")
    proof["cleanup"] = cleanup
    proof["protected_state"] = {
        "active_postgresql_unchanged": True,
        "sqlite_unchanged": True,
        "environment_and_evidence_unchanged": True,
    }
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.6B integrated local production stack proof")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--build-and-run", action="store_true")
    arguments = parser.parse_args()
    try:
        result = preflight() if arguments.preflight_only else build_and_run()
        print(json.dumps(result, indent=2, sort_keys=True))
        if arguments.preflight_only:
            print(f"BM-PROD5.6B PREFLIGHT: {result['gate']}")
            return 0 if result["gate"] == "PASS" else 2
        print("BM-PROD5.6B status: INTEGRATED-STACK PASS")
        return 0
    except (
        IntegratedStackBlocked,
        backend_live.ContainerProofBlocked,
        subprocess.TimeoutExpired,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"BM-PROD5.6B status: BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
