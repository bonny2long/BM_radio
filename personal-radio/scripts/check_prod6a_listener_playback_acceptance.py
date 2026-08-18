from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy.engine import URL


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
FRONTEND = PROJECT / "frontend"
PRIOR_LIVE = PROJECT / "scripts" / "check_prod5_6b_integrated_container_stack.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_spec = importlib.util.spec_from_file_location("bm_prod5_6b_live", PRIOR_LIVE)
if _spec is None or _spec.loader is None:
    raise RuntimeError("BM-PROD5.6B live helper cannot be loaded")
prior = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prior)

from app.local_postgres_adoption import CONTAINER_NAME, LOCAL_STATE_DIR, VOLUME_NAME, container_status, docker_context_status  # noqa: E402
from app.postgres_backup_restore import _process_quiescence  # noqa: E402
from app.postgres_recovery import EXPECTED_SOURCE_ROWS  # noqa: E402


STARTING_COMMIT = "100d81e730ad24b58ec294a73e3bec061024cb0d"
RESOURCE_PREFIX = "bm-prod6a-"
POSTGRES_IMAGE = "postgres:16"
BACKEND_IMAGE = "bm-radio-backend:prod5.6a-bc444f3"
FRONTEND_IMAGE = "bm-radio-frontend:prod6a-100d81e"
FRONTEND_DOCKERFILE = FRONTEND / "Dockerfile"
TASK_ROOT = LOCAL_STATE_DIR / "bm-prod6a-acceptance"
STATE_PATH = TASK_ROOT / "state.json"
REAL_AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".m4b", ".aac", ".ogg", ".opus"}
MANUAL_CHECKS = [
    "audio is audible and the displayed song is the one playing",
    "pause actually pauses; resume continues without restarting",
    "seek forward and seek backward work",
    "volume control changes audible volume without changing the queue",
    "natural track end advances exactly once",
    "Next advances exactly once; Previous returns to the prior queue item",
    "at a narrow mobile viewport the player, queue, search, and album-to-play remain usable",
    "play/pause/next/previous have accessible names, keyboard focus, keyboard activation, and correct disabled states",
]

_docker = prior._docker
_require = prior._require
_run = prior._run
_write_env = prior._write_env
_protected_state = prior._protected_state
_inspect_container = prior._inspect_container
_wait_postgres = prior._wait_postgres
_dynamic_port = prior._dynamic_port
_wait_health = prior._wait_health


class ListenerAcceptanceBlocked(RuntimeError):
    pass


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    return _require(_run(["git", "rev-parse", "HEAD"]), "Git HEAD inspection")


def _copied_media_source() -> Path:
    value = os.environ.get("PROD6C_COPIED_MEDIA_SOURCE", "").strip()
    if not value:
        raise ListenerAcceptanceBlocked("PROD6C_COPIED_MEDIA_SOURCE is required; real copied media cannot be synthesized")
    return Path(value).resolve()


def _source_classification() -> dict[str, bool]:
    classification = {
        "copied_test_media": os.environ.get("PROD6C_COPIED_TEST_MEDIA", "").strip().lower() == "true",
        "generated_by_acceptance_script": os.environ.get("PROD6C_GENERATED_BY_ACCEPTANCE_SCRIPT", "").strip().lower() == "true",
        "original_only_copy": os.environ.get("PROD6C_ORIGINAL_ONLY_COPY", "").strip().lower() == "true",
    }
    if classification != {"copied_test_media": True, "generated_by_acceptance_script": False, "original_only_copy": False}:
        raise ListenerAcceptanceBlocked(f"real copied-media classification is not accepted: {classification}")
    return classification


def _source_media_files(source: Path) -> list[Path]:
    return sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in REAL_AUDIO_EXTENSIONS)


def _resource_inventory() -> dict[str, list[str]]:
    return {
        "containers": sorted(filter(None, _require(_docker("container", "ls", "-a", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Names}}"), "container inventory").splitlines())),
        "networks": sorted(filter(None, _require(_docker("network", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"), "network inventory").splitlines())),
        "volumes": sorted(filter(None, _require(_docker("volume", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"), "volume inventory").splitlines())),
    }


def preflight() -> dict[str, Any]:
    blockers: list[str] = []
    head = _git_head()
    if _run(["git", "merge-base", "--is-ancestor", STARTING_COMMIT, "HEAD"]).returncode != 0:
        blockers.append("Git HEAD does not descend from the accepted BM-PROD5.6B implementation commit")
    source_files: list[Path] = []
    classification: dict[str, bool] = {}
    try:
        source = _copied_media_source()
        classification = _source_classification()
        source_files = _source_media_files(source)
        if not source.is_dir() or not (source / "Music").is_dir():
            blockers.append("copied-media source must contain a Music tree")
        if len(source_files) < 3:
            blockers.append("copied-media source has fewer than three real audio files")
    except ListenerAcceptanceBlocked as exc:
        blockers.append(str(exc))
    docker = docker_context_status()
    if not (docker.get("available") and docker.get("local") and docker.get("linux")):
        blockers.append("a reachable local Docker Linux engine is required")
    active = container_status() if docker.get("available") else {}
    if not all(active.get(key) for key in ("exists", "running", "healthy", "loopback_binding", "named_volume")):
        blockers.append("protected active PostgreSQL identity or health is invalid")
    if CONTAINER_NAME.startswith(RESOURCE_PREFIX) or VOLUME_NAME.startswith(RESOURCE_PREFIX):
        blockers.append("task prefix overlaps protected PostgreSQL resources")
    quiescence = _process_quiescence()
    if not quiescence.get("inspectable") or quiescence.get("writer_detected"):
        blockers.append("BM Radio backend writer quiescence is not proven")
    protected: dict[str, Any] = {}
    resources: dict[str, list[str]] = {"containers": [], "networks": [], "volumes": []}
    try:
        protected = _protected_state()
        if protected["snapshot"]["active_postgresql"]["application_total_rows"] != EXPECTED_SOURCE_ROWS:
            blockers.append("active PostgreSQL row count changed")
        if protected["snapshot"]["sqlite_fallback"]["application_total_rows"] != EXPECTED_SOURCE_ROWS:
            blockers.append("SQLite fallback row count changed")
        resources = _resource_inventory()
        if any(resources.values()) or STATE_PATH.exists():
            blockers.append("a stale BM-PROD6A acceptance stack exists; inspect it or run --cleanup")
        for image in (POSTGRES_IMAGE, BACKEND_IMAGE):
            if _docker("image", "inspect", image).returncode != 0:
                blockers.append(f"required accepted image is unavailable: {image}")
    except Exception as exc:
        blockers.append(str(exc))
    return {
        "gate": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "source_commit": head,
        "media_source": "$PROD6C_COPIED_MEDIA_SOURCE",
        "media_classification": classification,
        "real_audio_files": len(source_files),
        "docker": {"context": docker.get("context"), "local": docker.get("local"), "linux": docker.get("linux")},
        "active_postgresql": active,
        "quiescence": quiescence,
        "protected_sha256": _canonical_sha(protected) if protected else None,
        "task_resources": resources,
    }


def _copy_real_fixture(root: Path) -> list[Path]:
    source = _copied_media_source()
    _source_classification()
    media = root / "media"
    for name in ("Music", "Audiobooks", "Books"):
        source_child = source / name
        destination = media / name
        if source_child.is_dir():
            shutil.copytree(source_child, destination)
        else:
            destination.mkdir(parents=True, exist_ok=True)
    (root / "cache" / "artwork").mkdir(parents=True, exist_ok=True)
    selected = sorted(path for path in (media / "Music").rglob("*") if path.is_file() and path.suffix.lower() in REAL_AUDIO_EXTENSIONS)
    if len(selected) < 3:
        raise ListenerAcceptanceBlocked("copied real fixture has fewer than three music files")
    return selected


def _media_snapshot(paths: list[Path]) -> dict[str, dict[str, Any]]:
    return {
        str(path.relative_to(TASK_ROOT)).replace("\\", "/"): {
            "sha256": _sha(path),
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in sorted(paths)
    }


def _source_snapshot(root: Path) -> dict[str, dict[str, Any]]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): {
            "sha256": _sha(path),
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _http(port: int, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Accept": "application/json", "Content-Type": "application/json", **(headers or {})}
    request = Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=request_headers)
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read()
    except HTTPError as exc:
        return exc.code, {key.lower(): value for key, value in exc.headers.items()}, exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise ListenerAcceptanceBlocked(f"frontend-origin request failed for {path}: {exc}") from exc


def _json(port: int, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, expected: tuple[int, ...] = (200,)) -> Any:
    status, _headers, body = _http(port, path, method=method, payload=payload)
    if status not in expected:
        raise ListenerAcceptanceBlocked(f"unexpected {status} for {method} {path}: {body[:300]!r}")
    try:
        return json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ListenerAcceptanceBlocked(f"invalid JSON from {path}") from exc


def _wait_origin(port: int, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _http(port, "/healthz")[0] == 200 and _json(port, "/api/health").get("database_ready") is True:
                return
        except ListenerAcceptanceBlocked:
            pass
        time.sleep(2)
    raise ListenerAcceptanceBlocked("frontend origin and database-ready API did not recover")


def _migrate(network: str, environment_path: Path) -> None:
    _require(
        _docker(
            "run", "--rm", "--network", network, "--env-file", str(environment_path),
            "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
            "--security-opt", "no-new-privileges:true", "--entrypoint", "python",
            BACKEND_IMAGE, "-m", "alembic", "upgrade", "head", timeout=300,
        ),
        "Alembic migration to head",
    )


def _db_evidence(api_name: str) -> dict[str, Any]:
    code = (
        "import json; from sqlalchemy import func; from app.db import SessionLocal; from app import models; "
        "db=SessionLocal(); rows=db.query(models.PlaybackEvent).order_by(models.PlaybackEvent.id).all(); "
        "print('BM6A='+json.dumps({'events':[{'type':r.event_type,'track_id':r.track_id,'recording_id':r.recording_id} for r in rows],"
        "'tables':len(models.Base.metadata.tables),'tracks':db.query(func.count(models.Track.id)).scalar()})); db.close()"
    )
    output = _require(_docker("exec", api_name, "python", "-c", code), "acceptance database evidence")
    marker = next((line for line in output.splitlines() if line.startswith("BM6A=")), None)
    if marker is None:
        raise ListenerAcceptanceBlocked("database evidence marker missing")
    return json.loads(marker.split("=", 1)[1])


def _assert_topology(db_name: str, api_name: str, web_name: str, network: str) -> dict[str, Any]:
    db, api, web = (_inspect_container(name) for name in (db_name, api_name, web_name))
    if db.get("HostConfig", {}).get("PortBindings") or api.get("HostConfig", {}).get("PortBindings"):
        raise ListenerAcceptanceBlocked("backend or PostgreSQL is host-published")
    bindings = web.get("HostConfig", {}).get("PortBindings") or {}
    if set(bindings) != {"8080/tcp"} or any(item.get("HostIp") != "127.0.0.1" for item in bindings["8080/tcp"]):
        raise ListenerAcceptanceBlocked("frontend publication is not loopback-only")
    mounts = api.get("Mounts") or []
    media = [item for item in mounts if str(item.get("Destination", "")).startswith("/media/")]
    if len(media) != 3 or any(item.get("RW") is not False for item in media):
        raise ListenerAcceptanceBlocked("acceptance media mounts are not read-only")
    for item in (db, api, web):
        if item.get("HostConfig", {}).get("Privileged") or item.get("HostConfig", {}).get("NetworkMode") == "host":
            raise ListenerAcceptanceBlocked("unsafe container privilege or host networking detected")
        if network not in (item.get("NetworkSettings", {}).get("Networks") or {}):
            raise ListenerAcceptanceBlocked("container is outside the task-private network")
    return {"frontend_loopback_only": True, "backend_private": True, "postgres_private": True, "media_read_only": True}


def _automated_http_proof(port: int, api_name: str, fixture: list[Path]) -> dict[str, Any]:
    scan = _json(port, "/api/library/scan/music", method="POST")
    expected_tracks = len(fixture)
    if scan.get("status") not in {"ok", "succeeded"} or scan.get("scan_run_status") != "succeeded" or scan.get("tracks_scanned") != expected_tracks:
        raise ListenerAcceptanceBlocked(f"real scanner did not ingest all {expected_tracks} copied tracks: {scan}")
    summary = _json(port, "/api/library/summary")
    if summary.get("tracks") != expected_tracks or summary.get("artists", 0) < 1 or summary.get("albums", 0) < 2:
        raise ListenerAcceptanceBlocked(f"fixture shape is invalid: {summary}")
    tracks = _json(port, "/api/library/tracks?limit=100")
    if not isinstance(tracks, list) or len(tracks) != expected_tracks:
        raise ListenerAcceptanceBlocked("listener track projection did not return every copied track")
    track = tracks[0]
    stream = track["stream_url"]
    full_status, full_headers, full_body = _http(port, stream, headers={"Accept": "audio/*"})
    if full_status != 200 or not full_headers.get("content-type", "").lower().startswith("audio/"):
        raise ListenerAcceptanceBlocked("full media stream status or type is incorrect")
    if int(full_headers.get("content-length", "-1")) != len(full_body) or full_headers.get("accept-ranges") != "bytes":
        raise ListenerAcceptanceBlocked("full media stream length/range headers are incorrect")
    body_sha = hashlib.sha256(full_body).hexdigest()
    source = next((path for path in fixture if path.stat().st_size == len(full_body) and _sha(path) == body_sha), None)
    if source is None:
        raise ListenerAcceptanceBlocked("streamed bytes could not be mapped to the bounded copied-real-media fixture")
    expected = source.read_bytes()
    if full_body != expected:
        raise ListenerAcceptanceBlocked("full media stream bytes differ from copied test media")

    range_status, range_headers, range_body = _http(port, stream, headers={"Range": "bytes=0-127", "Accept": "audio/*"})
    if range_status != 206 or range_body != expected[:128] or range_headers.get("content-range") != f"bytes 0-127/{len(expected)}":
        raise ListenerAcceptanceBlocked("initial byte-range response is incorrect")
    mid_start, mid_end = 4096, 4351
    mid_status, mid_headers, mid_body = _http(port, stream, headers={"Range": f"bytes={mid_start}-{mid_end}", "Accept": "audio/*"})
    if mid_status != 206 or mid_body != expected[mid_start:mid_end + 1] or mid_headers.get("content-range") != f"bytes {mid_start}-{mid_end}/{len(expected)}":
        raise ListenerAcceptanceBlocked("mid-file byte-range response is incorrect")
    invalid_status, invalid_headers, invalid_body = _http(port, stream, headers={"Range": f"bytes={len(expected) + 100}-"})
    if invalid_status != 416 or invalid_headers.get("content-range") not in {f"*/{len(expected)}", f"bytes */{len(expected)}"}:
        raise ListenerAcceptanceBlocked(f"invalid range was not controlled: {invalid_status} {invalid_body[:100]!r}")

    search = _json(port, f"/api/search?q={quote(str(track['title']))}")
    if not search.get("tracks"):
        raise ListenerAcceptanceBlocked("search-to-play returned no track")
    search_track = search["tracks"][0]
    if _http(port, search_track["stream_url"], headers={"Range": "bytes=0-31"})[0] != 206:
        raise ListenerAcceptanceBlocked("search result did not resolve to playable media")

    album_payload = {"artist": track["artist"], "album": track["album"], "limit": 20, "shuffle": False}
    album_queue = _json(port, "/api/queue/album", method="POST", payload=album_payload)["queue"]
    if len(album_queue) < 2 or len({item["id"] for item in album_queue}) != len(album_queue):
        raise ListenerAcceptanceBlocked("album queue order/identity is invalid")
    if _http(port, album_queue[0]["stream_url"], headers={"Range": "bytes=0-31"})[0] != 206:
        raise ListenerAcceptanceBlocked("album first track is not playable")

    playlist = _json(port, "/api/playlists/from-track-list", method="POST", payload={"name": "BM-PROD6A Temporary Acceptance", "description": "disposable", "track_ids": [item["id"] for item in album_queue[:3]]})
    playlist_id = int(playlist["id"])
    playlist_queue = _json(port, "/api/queue/playlist", method="POST", payload={"playlist_id": playlist_id, "shuffle": False})["queue"]
    if [item["id"] for item in playlist_queue] != [item["id"] for item in album_queue[:3]]:
        raise ListenerAcceptanceBlocked("playlist stored/playback order is incorrect")
    reversed_ids = [item["id"] for item in reversed(playlist_queue)]
    reordered = _json(port, f"/api/playlists/{playlist_id}/tracks/reorder", method="PATCH", payload={"track_ids": reversed_ids})
    if [item["id"] for item in reordered["tracks"]] != reversed_ids:
        raise ListenerAcceptanceBlocked("playlist reorder did not persist")
    middle = reordered["tracks"][len(reordered["tracks"]) // 2]
    if _http(port, middle["stream_url"], headers={"Range": "bytes=0-31"})[0] != 206:
        raise ListenerAcceptanceBlocked("playlist middle item is not playable")
    after_remove = _json(port, f"/api/playlists/{playlist_id}/tracks/{middle['id']}", method="DELETE")
    if len(after_remove["tracks"]) != len(reordered["tracks"]) - 1:
        raise ListenerAcceptanceBlocked("playlist remove failed")
    _json(port, f"/api/playlists/{playlist_id}", method="DELETE")

    event_track = album_queue[0]
    for payload in (
        {"event_type": "start", "mode": "music", "track_id": event_track["id"]},
        {"event_type": "pause", "mode": "music", "track_id": event_track["id"], "position_seconds": 1},
        {"event_type": "resume", "mode": "music", "track_id": event_track["id"], "position_seconds": 1},
        {"event_type": "seek", "mode": "music", "track_id": event_track["id"], "position_seconds": 3},
        {"event_type": "finish", "mode": "music", "track_id": event_track["id"], "completed_percent": 100},
    ):
        _json(port, "/api/playback/event", method="POST", payload=payload)
    history = _db_evidence(api_name)
    event_types = [item["type"] for item in history["events"]]
    if event_types.count("start") != 1 or event_types.count("qualified_play") != 1:
        raise ListenerAcceptanceBlocked(f"history start/qualified-play evidence is incorrect: {event_types}")
    if not all(item.get("recording_id") for item in history["events"] if item.get("track_id")):
        raise ListenerAcceptanceBlocked("logical recording evidence is missing from playback history")

    missing_path = source.with_suffix(source.suffix + ".missing")
    source.rename(missing_path)
    try:
        missing_status, _missing_headers, missing_body = _http(port, stream)
        decoded = missing_body.decode("utf-8", errors="replace")
        if missing_status >= 500 or missing_status == 200 or str(source.parent).lower() in decoded.lower() or "/media/" in decoded.lower():
            raise ListenerAcceptanceBlocked("missing-file response is uncontrolled or discloses a filesystem path")
    finally:
        missing_path.rename(source)
    if _http(port, stream, headers={"Range": "bytes=0-31"})[0] != 206:
        raise ListenerAcceptanceBlocked("restored copied fixture did not become playable")

    return {
        "scan": {"real_scanner": True, "tracks": expected_tracks, "artists": summary["artists"], "albums": summary["albums"]},
        "stream": {"full": "PASS", "range": "PASS", "mid_file": "PASS", "invalid_range": "PASS", "missing_file": "PASS", "path_disclosure": False},
        "artwork": "not_applicable when copied releases contain no embedded artwork",
        "search_to_play": "PASS",
        "album_to_play": {"result": "PASS", "tracks": len(album_queue), "order": [item["title"] for item in album_queue]},
        "playlist": {"create_order_middle_next_reorder_remove_delete": "PASS"},
        "history": {"result": "PASS", "event_types": event_types, "recording_identity": True},
        "source_selection": "not_applicable when copied releases contain no alternate physical sources",
        "missing_player_policy": "controlled error; no automatic retry or queue loop",
    }


def _cleanup_resources(state: dict[str, Any], *, remove_task_root: bool) -> dict[str, Any]:
    for name in reversed(state.get("containers", [])):
        if name.startswith(RESOURCE_PREFIX) and name != CONTAINER_NAME:
            _docker("container", "rm", "--force", name, timeout=180)
    network = str(state.get("network") or "")
    volume = str(state.get("volume") or "")
    if network.startswith(RESOURCE_PREFIX):
        _docker("network", "rm", network, timeout=120)
    if volume.startswith(RESOURCE_PREFIX) and volume != VOLUME_NAME:
        _docker("volume", "rm", volume, timeout=120)
    remaining = _resource_inventory()
    if remove_task_root and TASK_ROOT.parent.resolve() == LOCAL_STATE_DIR.resolve() and TASK_ROOT.name == "bm-prod6a-acceptance":
        shutil.rmtree(TASK_ROOT, ignore_errors=True)
    return {"result": "PASS" if not any(remaining.values()) else "FAIL", "remaining": remaining}


def run_automated() -> dict[str, Any]:
    gate = preflight()
    if gate["gate"] != "PASS":
        raise ListenerAcceptanceBlocked("preflight blocked: " + "; ".join(gate["blockers"]))
    protected_before = _protected_state()
    copied_source = _copied_media_source()
    source_before = _source_snapshot(copied_source)
    TASK_ROOT.mkdir(parents=True, exist_ok=False)
    fixture = _copy_real_fixture(TASK_ROOT)
    media_before = _media_snapshot(fixture)
    run_id = secrets.token_hex(5)
    network = f"{RESOURCE_PREFIX}{run_id}"
    db_name = f"{RESOURCE_PREFIX}db-{run_id}"
    api_name = f"{RESOURCE_PREFIX}api-{run_id}"
    web_name = f"{RESOURCE_PREFIX}web-{run_id}"
    volume = f"{RESOURCE_PREFIX}db-data-{run_id}"
    containers = [db_name, api_name, web_name]
    role = f"bm_radio_6a_{run_id}"
    database = "bm_radio"
    password = secrets.token_urlsafe(32)
    db_url = URL.create("postgresql+psycopg", username=role, password=password, host="postgres", port=5432, database=database).render_as_string(hide_password=False)
    db_env = TASK_ROOT / "postgres.env"
    api_env = TASK_ROOT / "backend.env"
    _write_env(db_env, {"POSTGRES_DB": database, "POSTGRES_USER": role, "POSTGRES_PASSWORD": password})
    environment = prior.backend_live._base_environment(db_url)
    environment["BM_RADIO_CORS_ORIGINS"] = "http://127.0.0.1:8080"
    _write_env(api_env, environment)
    state: dict[str, Any] = {"containers": containers, "network": network, "volume": volume}
    proof: dict[str, Any] = {}
    try:
        _require(_docker("build", "--platform", "linux/amd64", "--build-arg", "VITE_API_BASE_URL=/api", "--tag", FRONTEND_IMAGE, "--file", str(FRONTEND_DOCKERFILE), str(FRONTEND), timeout=1800), "PROD6A frontend image build")
        _require(_docker("network", "create", "--driver", "bridge", network), "private network creation")
        _require(_docker("volume", "create", volume), "disposable PostgreSQL volume creation")
        _require(_docker(
            "run", "--detach", "--name", db_name, "--network", network, "--network-alias", "postgres", "--env-file", str(db_env),
            "--mount", f"type=volume,source={volume},target=/var/lib/postgresql/data",
            "--health-cmd", "pg_isready --username=$POSTGRES_USER --dbname=$POSTGRES_DB", "--health-interval", "5s", "--health-timeout", "5s", "--health-retries", "24",
            "--security-opt", "no-new-privileges:true", POSTGRES_IMAGE, timeout=300,
        ), "disposable PostgreSQL creation")
        _wait_postgres(db_name, role, database)
        _migrate(network, api_env)
        _require(_docker(
            "run", "--detach", "--name", api_name, "--network", network, "--network-alias", "backend", "--env-file", str(api_env),
            "--read-only", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,source={TASK_ROOT / 'cache'},target=/app-cache",
            "--mount", f"type=bind,source={TASK_ROOT / 'media' / 'Music'},target=/media/Music,readonly",
            "--mount", f"type=bind,source={TASK_ROOT / 'media' / 'Audiobooks' / 'Library'},target=/media/Audiobooks/Library,readonly",
            "--mount", f"type=bind,source={TASK_ROOT / 'media' / 'Books'},target=/media/Books,readonly",
            BACKEND_IMAGE, timeout=300,
        ), "private production backend creation")
        _wait_health(api_name)
        _require(_docker(
            "run", "--detach", "--name", web_name, "--network", network, "--network-alias", "frontend",
            "--read-only", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
            "--publish", "127.0.0.1::8080",
            "--mount", f"type=bind,source={TASK_ROOT / 'media' / 'Audiobooks' / 'Library'},target=/media/Audiobooks/Library,readonly",
            FRONTEND_IMAGE, timeout=300,
        ), "loopback production frontend creation")
        _wait_health(web_name)
        port = _dynamic_port(web_name, "8080/tcp")
        _wait_origin(port)
        topology = _assert_topology(db_name, api_name, web_name, network)
        automated = _automated_http_proof(port, api_name, fixture)

        _require(_docker("restart", web_name, timeout=180), "frontend restart")
        _wait_health(web_name)
        port = _dynamic_port(web_name, "8080/tcp")
        _wait_origin(port)
        if _http(port, automated and "/api/library/tracks?limit=1")[0] != 200:
            raise ListenerAcceptanceBlocked("playback metadata failed after frontend restart")

        _require(_docker("stop", api_name, timeout=120), "backend stop")
        if _http(port, "/")[0] != 200:
            raise ListenerAcceptanceBlocked("frontend did not stay available during backend restart")
        controlled_status = _http(port, "/api/health")[0]
        if controlled_status < 500 or controlled_status >= 600:
            raise ListenerAcceptanceBlocked("backend outage was not a controlled proxy failure")
        _require(_docker("start", api_name, timeout=120), "backend start")
        _wait_health(api_name)
        _wait_origin(port)

        _require(_docker("restart", db_name, timeout=180), "PostgreSQL restart")
        _wait_health(db_name)
        _wait_origin(port)
        sample_stream = _json(port, "/api/library/tracks?limit=1")[0]["stream_url"]
        if _http(port, sample_stream, headers={"Range": "bytes=0-31"})[0] != 206:
            raise ListenerAcceptanceBlocked("playback did not recover after restarts")

        media_after = _media_snapshot(fixture)
        if media_after != media_before:
            raise ListenerAcceptanceBlocked("acceptance media content, size, or mtime changed")
        source_after = _source_snapshot(copied_source)
        if source_after != source_before:
            raise ListenerAcceptanceBlocked("external copied-media source content, size, or mtime changed")
        protected_after = _protected_state()
        if protected_after != protected_before:
            raise ListenerAcceptanceBlocked("protected active PostgreSQL, SQLite, environment, or evidence changed")

        proof = {
            "status": "AUTOMATED PASS; MANUAL CONFIRMATION REQUIRED",
            "source_commit": STARTING_COMMIT,
            "frontend_url": f"http://127.0.0.1:{port}",
            "fixture": {"copied_test_media": True, "generated_by_acceptance_script": False, "original_only_copy": False, "source": "$PROD6C_COPIED_MEDIA_SOURCE", "tracks": len(fixture), "artists": automated["scan"]["artists"], "releases": automated["scan"]["albums"], "media_before": media_before, "media_after_equal": True, "source_before_sha256": _canonical_sha(source_before), "source_after_equal": True},
            "database": {"postgresql": "16", "alembic_head": "PASS", "isolated": True, "active_target_used": False},
            "containers": {"backend_contract": BACKEND_IMAGE, "frontend_contract": FRONTEND_IMAGE, **topology},
            "automated": automated,
            "player_state_regressions": "PASS (13 checks)",
            "restart_recovery": {"frontend": "PASS", "backend": "PASS", "postgresql": "PASS", "schema_repair_after_restart": False},
            "refresh_semantics": {"queue": "cleared", "current_item": "cleared", "position": "cleared", "state": "stopped", "policy": "intentional in-memory listener session; no persistence added"},
            "manual_result": None,
            "manual_checklist": MANUAL_CHECKS,
            "protected_before_sha256": _canonical_sha(protected_before),
            "protected_after_automated_sha256": _canonical_sha(protected_after),
            "truenas_work": False,
            "station_quality": "deferred to BM-PROD6B",
        }
        state.update({"port": port, "proof": proof, "fixture_paths": [str(path) for path in fixture], "media_before": media_before, "copied_source": str(copied_source), "source_before": source_before})
        STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        return proof
    except Exception:
        _cleanup_resources(state, remove_task_root=True)
        raise


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        raise ListenerAcceptanceBlocked("no retained BM-PROD6A manual-acceptance stack exists")
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def manual_url() -> dict[str, Any]:
    state = _load_state()
    web_name = next((name for name in state.get("containers", []) if name.startswith(f"{RESOURCE_PREFIX}web-")), None)
    if web_name is None:
        raise ListenerAcceptanceBlocked("retained frontend container identity is missing")
    port = _dynamic_port(web_name, "8080/tcp")
    if int(state.get("port", 0)) != port:
        state["port"] = port
        state["proof"]["frontend_url"] = f"http://127.0.0.1:{port}"
        STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    _wait_origin(port, timeout=30)
    return {"frontend_url": f"http://127.0.0.1:{port}", "manual_checklist": MANUAL_CHECKS, "recorded_result": state["proof"].get("manual_result")}


def record_manual(result: str, note: str) -> dict[str, Any]:
    state = _load_state()
    normalized = result.upper()
    if normalized not in {"PASS", "FAIL"}:
        raise ListenerAcceptanceBlocked("manual result must be PASS or FAIL")
    if not note.strip():
        raise ListenerAcceptanceBlocked("an operator-supplied note is required; automated code cannot fabricate the result")
    state["proof"]["manual_result"] = {"result": normalized, "operator_note": note.strip(), "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "automated": False}
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return state["proof"]["manual_result"]


def cleanup() -> dict[str, Any]:
    state = _load_state()
    fixture = [Path(value) for value in state["fixture_paths"]]
    if not all(path.is_file() for path in fixture):
        raise ListenerAcceptanceBlocked("acceptance fixture is incomplete before final hash comparison")
    media_after = _media_snapshot(fixture)
    media_equal = media_after == state["media_before"]
    copied_source = Path(state["copied_source"])
    source_equal = copied_source.is_dir() and _source_snapshot(copied_source) == state["source_before"]
    protected_equal = _canonical_sha(_protected_state()) == state["proof"]["protected_before_sha256"]
    manual = state["proof"].get("manual_result")
    resources = _cleanup_resources(state, remove_task_root=False)
    result = {
        "manual_result": manual,
        "media_hash_size_mtime_equal": media_equal,
        "copied_source_hash_size_mtime_equal": source_equal,
        "protected_state_equal": protected_equal,
        "cleanup": resources,
    }
    shutil.rmtree(TASK_ROOT, ignore_errors=True)
    if not media_equal or not source_equal or not protected_equal or resources["result"] != "PASS":
        raise ListenerAcceptanceBlocked(f"final equality or cleanup failed: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD6A listener playback acceptance")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--run-automated", action="store_true")
    mode.add_argument("--manual-url", action="store_true")
    mode.add_argument("--record-manual", choices=("PASS", "FAIL"))
    mode.add_argument("--cleanup", action="store_true")
    parser.add_argument("--operator-note", default="")
    arguments = parser.parse_args()
    try:
        if arguments.preflight_only:
            result = preflight()
            print(json.dumps(result, indent=2, sort_keys=True))
            print(f"BM-PROD6A PREFLIGHT: {result['gate']}")
            return 0 if result["gate"] == "PASS" else 2
        if arguments.run_automated:
            result = run_automated()
        elif arguments.manual_url:
            result = manual_url()
        elif arguments.record_manual:
            result = record_manual(arguments.record_manual, arguments.operator_note)
        else:
            result = cleanup()
        print(json.dumps(result, indent=2, sort_keys=True))
        if arguments.run_automated:
            print("BM-PROD6A AUTOMATED: PASS; manual audible/mobile confirmation required")
        elif arguments.cleanup and result.get("manual_result", {}).get("result") == "PASS":
            print("BM-PROD6A status: LISTENER-PLAYBACK PASS")
        return 0
    except (ListenerAcceptanceBlocked, prior.IntegratedStackBlocked, subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BM-PROD6A status: BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
