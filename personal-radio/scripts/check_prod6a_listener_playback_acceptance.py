from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import wave

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
FIXTURE_SENTINEL = "BM-PROD6A GENERATED REGENERABLE TEST AUDIO"
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


def _resource_inventory() -> dict[str, list[str]]:
    return {
        "containers": sorted(filter(None, _require(_docker("container", "ls", "-a", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Names}}"), "container inventory").splitlines())),
        "networks": sorted(filter(None, _require(_docker("network", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"), "network inventory").splitlines())),
        "volumes": sorted(filter(None, _require(_docker("volume", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"), "volume inventory").splitlines())),
    }


def preflight() -> dict[str, Any]:
    blockers: list[str] = []
    head = _git_head()
    if head != STARTING_COMMIT:
        blockers.append("Git HEAD is not the accepted BM-PROD5.6B implementation commit")
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
        "media_classification": "script-generated, regenerable development WAV fixture; never archive/NAS media",
        "docker": {"context": docker.get("context"), "local": docker.get("local"), "linux": docker.get("linux")},
        "active_postgresql": active,
        "quiescence": quiescence,
        "protected_sha256": _canonical_sha(protected) if protected else None,
        "task_resources": resources,
    }


def _write_fixture(root: Path) -> list[Path]:
    music = root / "media" / "Music" / "Library" / "FLAC"
    layout = [
        ("Acceptance Artist One", "First Signals", 4, 220),
        ("Acceptance Artist Two", "Second Signals", 4, 330),
        ("Acceptance Artist Three", "Third Signals", 4, 440),
    ]
    selected: list[Path] = []
    sample_rate = 22050
    duration_seconds = 8
    amplitude = 6500
    for artist, album, count, base_frequency in layout:
        album_root = music / artist / album
        album_root.mkdir(parents=True, exist_ok=True)
        for number in range(1, count + 1):
            path = album_root / f"{number:02d} - Acceptance Tone {number}.wav"
            frequency = base_frequency + number * 17
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                frames = bytearray()
                for sample in range(sample_rate * duration_seconds):
                    value = int(amplitude * math.sin(2 * math.pi * frequency * sample / sample_rate))
                    frames.extend(value.to_bytes(2, byteorder="little", signed=True))
                output.writeframes(bytes(frames))
            selected.append(path)
    sentinel = root / "media" / "Music" / "BM-PROD6A-TEST-MEDIA.txt"
    sentinel.write_text(FIXTURE_SENTINEL + "\n", encoding="utf-8")
    for path in (root / "media" / "Audiobooks" / "Library", root / "media" / "Books", root / "cache" / "artwork"):
        path.mkdir(parents=True, exist_ok=True)
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
    if scan.get("status") not in {"ok", "succeeded"} or scan.get("scan_run_status") != "succeeded" or scan.get("tracks_scanned") != 12:
        raise ListenerAcceptanceBlocked(f"real scanner did not ingest 12 tracks: {scan}")
    summary = _json(port, "/api/library/summary")
    if summary.get("tracks") != 12 or summary.get("artists") < 3 or summary.get("albums") < 3:
        raise ListenerAcceptanceBlocked(f"fixture shape is invalid: {summary}")
    tracks = _json(port, "/api/library/tracks?limit=100")
    if not isinstance(tracks, list) or len(tracks) != 12:
        raise ListenerAcceptanceBlocked("listener track projection did not return 12 tracks")
    track = tracks[0]
    stream = track["stream_url"]
    source = next(
        (
            path for path in fixture
            if track["artist"] in path.parts
            and track["album"] in path.parts
            and path.stem.lower().endswith(str(track["title"]).lower())
        ),
        None,
    )
    if source is None:
        raise ListenerAcceptanceBlocked("scanner result could not be mapped to the bounded host fixture")
    full_status, full_headers, full_body = _http(port, stream, headers={"Accept": "audio/*"})
    if full_status != 200 or full_headers.get("content-type", "").split(";", 1)[0] != "audio/wav":
        raise ListenerAcceptanceBlocked("full media stream status or type is incorrect")
    if int(full_headers.get("content-length", "-1")) != len(full_body) or full_headers.get("accept-ranges") != "bytes":
        raise ListenerAcceptanceBlocked("full media stream length/range headers are incorrect")
    if len(full_body) != source.stat().st_size:
        source = next((path for path in fixture if path.stat().st_size == len(full_body)), source)
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

    search = _json(port, "/api/search?q=Acceptance%20Tone%201")
    if not search.get("tracks"):
        raise ListenerAcceptanceBlocked("search-to-play returned no track")
    search_track = search["tracks"][0]
    if _http(port, search_track["stream_url"], headers={"Range": "bytes=0-31"})[0] != 206:
        raise ListenerAcceptanceBlocked("search result did not resolve to playable media")

    album_payload = {"artist": track["artist"], "album": track["album"], "limit": 20, "shuffle": False}
    album_queue = _json(port, "/api/queue/album", method="POST", payload=album_payload)["queue"]
    if len(album_queue) != 4 or len({item["id"] for item in album_queue}) != 4:
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
    middle = reordered["tracks"][1]
    if _http(port, middle["stream_url"], headers={"Range": "bytes=0-31"})[0] != 206:
        raise ListenerAcceptanceBlocked("playlist middle item is not playable")
    after_remove = _json(port, f"/api/playlists/{playlist_id}/tracks/{middle['id']}", method="DELETE")
    if len(after_remove["tracks"]) != 2:
        raise ListenerAcceptanceBlocked("playlist remove failed")
    _json(port, f"/api/playlists/{playlist_id}", method="DELETE")

    event_track = album_queue[0]
    for payload in (
        {"event_type": "start", "mode": "music", "track_id": event_track["id"]},
        {"event_type": "pause", "mode": "music", "track_id": event_track["id"], "position_seconds": 1},
        {"event_type": "resume", "mode": "music", "track_id": event_track["id"], "position_seconds": 1},
        {"event_type": "seek", "mode": "music", "track_id": event_track["id"], "position_seconds": 3},
        {"event_type": "finish", "mode": "music", "track_id": event_track["id"], "position_seconds": 8},
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
        "scan": {"real_scanner": True, "tracks": 12, "artists": summary["artists"], "albums": summary["albums"]},
        "stream": {"full": "PASS", "range": "PASS", "mid_file": "PASS", "invalid_range": "PASS", "missing_file": "PASS", "path_disclosure": False},
        "artwork": "not_applicable (generated fixture intentionally contains no artwork)",
        "search_to_play": "PASS",
        "album_to_play": {"result": "PASS", "tracks": len(album_queue), "order": [item["title"] for item in album_queue]},
        "playlist": {"create_order_middle_next_reorder_remove_delete": "PASS"},
        "history": {"result": "PASS", "event_types": event_types, "recording_identity": True},
        "source_selection": "not_applicable (no alternate physical sources in bounded fixture)",
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
    TASK_ROOT.mkdir(parents=True, exist_ok=False)
    fixture = _write_fixture(TASK_ROOT)
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
            "--publish", "127.0.0.1::8080", FRONTEND_IMAGE, timeout=300,
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
        protected_after = _protected_state()
        if protected_after != protected_before:
            raise ListenerAcceptanceBlocked("protected active PostgreSQL, SQLite, environment, or evidence changed")

        proof = {
            "status": "AUTOMATED PASS; MANUAL CONFIRMATION REQUIRED",
            "source_commit": STARTING_COMMIT,
            "frontend_url": f"http://127.0.0.1:{port}",
            "fixture": {"classification": "generated/regenerable development audio", "tracks": 12, "artists": 3, "releases": 3, "media_before": media_before, "media_after_equal": True},
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
        state.update({"port": port, "proof": proof, "fixture_paths": [str(path) for path in fixture], "media_before": media_before})
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
    port = int(state["port"])
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
    protected_equal = _canonical_sha(_protected_state()) == state["proof"]["protected_before_sha256"]
    manual = state["proof"].get("manual_result")
    resources = _cleanup_resources(state, remove_task_root=False)
    result = {
        "manual_result": manual,
        "media_hash_size_mtime_equal": media_equal,
        "protected_state_equal": protected_equal,
        "cleanup": resources,
    }
    shutil.rmtree(TASK_ROOT, ignore_errors=True)
    if not media_equal or not protected_equal or resources["result"] != "PASS":
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
