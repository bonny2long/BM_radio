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

from app.local_postgres_adoption import CONTAINER_NAME, VOLUME_NAME, container_status, docker_context_status  # noqa: E402
from app.postgres_backup_restore import _process_quiescence  # noqa: E402
from app.postgres_recovery import EXPECTED_SOURCE_ROWS  # noqa: E402


STARTING_COMMIT = "5e3b2be2e5163c37297881dd9d1fcd33d55bd129"
RESOURCE_PREFIX = "bm-prod6c-"
POSTGRES_IMAGE = "postgres:16"
BACKEND_IMAGE = "bm-radio-backend:prod6c-local"
FRONTEND_IMAGE = "bm-radio-frontend:prod6c-local"
EXPECTED_CHILDREN = (
    "_INGEST", "_QUARANTINE", "_REPORTS", "_STAGING", "Audiobooks", "Backups",
    "Books", "Documents", "Movies", "Music", "Photos", "Projects", "TV",
)
MANUAL_CHECKS = (
    "library organization looks correct",
    "artist and album names are correct and track order is coherent",
    "search results make sense and do not show a FLAC/MP3 duplicate song",
    "playlist create/add/reorder/play/remove/delete UX is usable",
    "favorite and thumb controls update and remain correct after refresh",
    "preferred-source details are understandable without cluttering Now Playing",
    "copied tracks are audible and the displayed item is the one playing",
)

_docker = prior._docker
_require = prior._require
_run = prior._run
_write_env = prior._write_env
_protected_state = prior._protected_state
_inspect_container = prior._inspect_container
_wait_postgres = prior._wait_postgres
_dynamic_port = prior._dynamic_port
_wait_health = prior._wait_health


class Prod6CAcceptanceBlocked(RuntimeError):
    pass


def nas_root() -> Path:
    value = os.environ.get("NAS_LOCAL_ROOT", "").strip()
    if not value:
        raise Prod6CAcceptanceBlocked("NAS_LOCAL_ROOT must name the task-scoped local NAS root")
    return Path(value).resolve()


def evidence_dir(root: Path) -> Path:
    return root / "_REPORTS" / "prod6c"


def state_path(root: Path) -> Path:
    return evidence_dir(root) / "bm_radio_state.json"


def runtime_dir(root: Path) -> Path:
    return evidence_dir(root) / "runtime"


def _canonical_sha(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return "$NAS_LOCAL_ROOT/" + path.resolve().relative_to(root.resolve()).as_posix()


def _media_files(root: Path) -> list[Path]:
    extensions = {".flac", ".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".aac", ".wav", ".epub"}
    paths: list[Path] = []
    for child in (root / "Music", root / "Audiobooks", root / "Books"):
        if child.is_dir():
            paths.extend(path for path in child.rglob("*") if path.is_file() and path.suffix.lower() in extensions)
    return sorted(paths)


def _snapshot(root: Path, paths: list[Path]) -> dict[str, dict[str, Any]]:
    return {
        _relative(root, path): {"sha256": _sha(path), "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
        for path in sorted(paths)
    }


def _source_snapshot(root: Path) -> dict[str, dict[str, Any]]:
    source = root / "_TEST_FIXTURES" / "prod6c_source"
    return _snapshot(root, [path for path in source.rglob("*") if path.is_file()]) if source.is_dir() else {}


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
    try:
        root = nas_root()
    except Prod6CAcceptanceBlocked as exc:
        return {"gate": "BLOCKED", "blockers": [str(exc)]}
    head = _git_head()
    if head != STARTING_COMMIT:
        blockers.append("Git HEAD is not the accepted BM-PROD6B implementation commit")
    if not root.is_dir():
        blockers.append("NAS_LOCAL_ROOT does not exist")
    missing = [name for name in EXPECTED_CHILDREN if not (root / name).is_dir()]
    if missing:
        blockers.append("local NAS root is missing required children: " + ", ".join(missing))
    source = _source_snapshot(root)
    if not source:
        blockers.append("immutable copied fixture source is absent")
    docker = docker_context_status()
    if not (docker.get("available") and docker.get("local") and docker.get("linux")):
        blockers.append("a reachable local Docker Linux engine is required")
    active = container_status() if docker.get("available") else {}
    if not all(active.get(key) for key in ("exists", "running", "healthy", "loopback_binding", "named_volume")):
        blockers.append("protected active PostgreSQL identity or health is invalid")
    if CONTAINER_NAME.startswith(RESOURCE_PREFIX) or VOLUME_NAME.startswith(RESOURCE_PREFIX):
        blockers.append("task Docker prefix overlaps protected PostgreSQL resources")
    quiescence = _process_quiescence()
    if not quiescence.get("inspectable") or quiescence.get("writer_detected"):
        blockers.append("BM Radio backend writer quiescence is not proven")
    resources: dict[str, list[str]] = {"containers": [], "networks": [], "volumes": []}
    protected: dict[str, Any] = {}
    try:
        protected = _protected_state()
        if protected["snapshot"]["active_postgresql"]["application_total_rows"] != EXPECTED_SOURCE_ROWS:
            blockers.append("active PostgreSQL row count changed")
        if protected["snapshot"]["sqlite_fallback"]["application_total_rows"] != EXPECTED_SOURCE_ROWS:
            blockers.append("SQLite fallback row count changed")
        resources = _resource_inventory()
        if any(resources.values()) or state_path(root).exists():
            blockers.append("stale BM-PROD6C acceptance resources exist; inspect or clean them")
        if _docker("image", "inspect", POSTGRES_IMAGE).returncode != 0:
            blockers.append("local postgres:16 image is unavailable")
    except Exception as exc:
        blockers.append(str(exc))
    return {
        "gate": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "source_commit": head,
        "nas_root": "$NAS_LOCAL_ROOT",
        "fixture_source_files": len(source),
        "docker": {"context": docker.get("context"), "local": docker.get("local"), "linux": docker.get("linux")},
        "active_postgresql": active,
        "quiescence": quiescence,
        "protected_sha256": _canonical_sha(protected) if protected else None,
        "task_resources": resources,
    }


def _http(port: int, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read()
    except HTTPError as exc:
        return exc.code, {key.lower(): value for key, value in exc.headers.items()}, exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise Prod6CAcceptanceBlocked(f"frontend-origin request failed for {path}: {exc}") from exc


def _json(port: int, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, expected: tuple[int, ...] = (200,)) -> Any:
    status, _headers, body = _http(port, path, method=method, payload=payload)
    if status not in expected:
        raise Prod6CAcceptanceBlocked(f"unexpected {status} for {method} {path}: {body[:400]!r}")
    try:
        return json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Prod6CAcceptanceBlocked(f"invalid JSON from {path}") from exc


def _wait_origin(port: int, timeout: int = 150) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _http(port, "/healthz")[0] == 200 and _json(port, "/api/health").get("database_ready") is True:
                return
        except Prod6CAcceptanceBlocked:
            pass
        time.sleep(2)
    raise Prod6CAcceptanceBlocked("production frontend and database-ready API did not become healthy")


def _migrate(network: str, environment_path: Path) -> None:
    _require(_docker(
        "run", "--rm", "--network", network, "--env-file", str(environment_path),
        "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "--security-opt", "no-new-privileges:true",
        "--entrypoint", "python", BACKEND_IMAGE, "-m", "alembic", "upgrade", "head", timeout=300,
    ), "Alembic upgrade head")


def _assert_topology(db_name: str, api_name: str, web_name: str, network: str) -> dict[str, bool]:
    db, api, web = (_inspect_container(name) for name in (db_name, api_name, web_name))
    if db.get("HostConfig", {}).get("PortBindings") or api.get("HostConfig", {}).get("PortBindings"):
        raise Prod6CAcceptanceBlocked("PostgreSQL or backend is host-published")
    bindings = web.get("HostConfig", {}).get("PortBindings") or {}
    if set(bindings) != {"8080/tcp"} or any(item.get("HostIp") != "127.0.0.1" for item in bindings["8080/tcp"]):
        raise Prod6CAcceptanceBlocked("frontend is not loopback-only")
    mounts = [item for item in api.get("Mounts", []) if str(item.get("Destination", "")).startswith("/media/")]
    if len(mounts) != 3 or any(item.get("RW") is not False for item in mounts):
        raise Prod6CAcceptanceBlocked("Music/Audiobooks/Books are not three read-only mounts")
    if any("Movies" in str(item.get("Source")) or "TV" in str(item.get("Source")) for item in mounts):
        raise Prod6CAcceptanceBlocked("Movies or TV was connected to BM Radio")
    for item in (db, api, web):
        if item.get("HostConfig", {}).get("Privileged") or network not in (item.get("NetworkSettings", {}).get("Networks") or {}):
            raise Prod6CAcceptanceBlocked("unsafe container privilege or network topology")
    return {"frontend_loopback_only": True, "backend_private": True, "postgres_private": True, "final_media_read_only": True, "movies_tv_excluded": True}


def _score(debug: dict[str, Any], recording_id: int) -> float | None:
    for row in list(debug.get("selected", [])) + list(debug.get("top_rejected", [])):
        if int(row.get("recording_id") or 0) == recording_id:
            return float(row.get("score", 0))
    return None


def _automated_http_proof(port: int, final_files: list[Path]) -> dict[str, Any]:
    music_scan = _json(port, "/api/library/scan/music", method="POST")
    if music_scan.get("status") not in {"ok", "succeeded"} or music_scan.get("scan_run_status") != "succeeded":
        raise Prod6CAcceptanceBlocked(f"real music scanner failed: {music_scan}")
    audiobook_scan = _json(port, "/api/audiobooks/scan", method="POST")
    if audiobook_scan.get("status") not in {"ok", "succeeded"} and audiobook_scan.get("scan_run_status") != "succeeded":
        raise Prod6CAcceptanceBlocked(f"real audiobook scanner failed: {audiobook_scan}")
    summary = _json(port, "/api/library/summary")
    tracks = _json(port, "/api/library/tracks?limit=200")
    if not tracks or summary.get("tracks") != len(tracks):
        raise Prod6CAcceptanceBlocked(f"listener library/count mismatch: {summary}")
    if any(not item.get("recording_id") or not item.get("effective_track_id") for item in tracks):
        raise Prod6CAcceptanceBlocked("listener rows lack recording/effective-source identity")
    recording_ids = [int(item["recording_id"]) for item in tracks]
    if len(recording_ids) != len(set(recording_ids)):
        raise Prod6CAcceptanceBlocked("listener library exposes a physical-source duplicate song")
    if any("movies" in str(item).casefold() or "\\tv\\" in str(item).casefold() for item in tracks):
        raise Prod6CAcceptanceBlocked("movie/TV path leaked into BM Radio")

    artists = _json(port, "/api/library/artists")
    albums = _json(port, "/api/library/albums")
    if len({item["name"].casefold() for item in artists}) != len(artists):
        raise Prod6CAcceptanceBlocked("duplicate logical artist rows exist")
    album_keys = {(item["artist"].casefold(), item["title"].casefold()) for item in albums}
    if len(album_keys) != len(albums):
        raise Prod6CAcceptanceBlocked("duplicate logical album rows exist")

    target = tracks[0]
    search = _json(port, f"/api/search?q={quote(target['title'])}")
    search_ids = [int(item["recording_id"]) for item in search.get("tracks", [])]
    if int(target["recording_id"]) not in search_ids or len(search_ids) != len(set(search_ids)):
        raise Prod6CAcceptanceBlocked("song search missing target or exposing source duplicates")
    artist_search = _json(port, f"/api/search?q={quote(target['artist'])}")
    album_search = _json(port, f"/api/search?q={quote(target['album'])}")
    if not artist_search.get("artists") or not album_search.get("albums"):
        raise Prod6CAcceptanceBlocked("artist or album search failed")
    if _http(port, search["tracks"][0]["stream_url"], headers={"Range": "bytes=0-31"})[0] != 206:
        raise Prod6CAcceptanceBlocked("search-to-play byte range failed")

    album_tracks = _json(port, f"/api/library/album-tracks?artist={quote(target['artist'])}&album={quote(target['album'])}")
    album_recordings = [int(item["recording_id"]) for item in album_tracks]
    if not album_tracks or len(album_recordings) != len(set(album_recordings)):
        raise Prod6CAcceptanceBlocked("album tracks are empty or contain physical-source duplicates")
    album_queue = _json(port, "/api/queue/album", method="POST", payload={"artist": target["artist"], "album": target["album"], "limit": 200, "shuffle": False})["queue"]
    if [item["recording_id"] for item in album_queue] != album_recordings:
        raise Prod6CAcceptanceBlocked("album queue lost logical order/identity")

    audiobooks = _json(port, "/api/audiobooks/")
    if not audiobooks:
        raise Prod6CAcceptanceBlocked("AA-cleaned audiobook did not materialize")
    audiobook = _json(port, f"/api/audiobooks/{audiobooks[0]['id']}")
    if not audiobook.get("chapters") or _http(port, audiobook["chapters"][0]["stream_url"], headers={"Range": "bytes=0-31"})[0] != 206:
        raise Prod6CAcceptanceBlocked("audiobook playback entry point failed")

    controls = {int(item["recording_id"]): _json(port, f"/api/music/recordings/{item['recording_id']}/control") for item in tracks}
    variant = next((item for item in tracks if len(controls[int(item["recording_id"])]["candidates"]) > 1), None)
    source_result: dict[str, Any]
    feedback_target = variant or target
    control = controls[int(feedback_target["recording_id"])]
    initial_effective = int(control["effective_source"]["track_id"])
    if variant is not None:
        candidates = control["candidates"]
        lossless = [item for item in candidates if (item.get("technical") or {}).get("is_lossless") is True]
        lossy = [item for item in candidates if (item.get("technical") or {}).get("is_lossless") is False]
        if len(lossless) == 1 and lossy and initial_effective != int(lossless[0]["track_id"]):
            raise Prod6CAcceptanceBlocked("unique lossless source was not automatically preferred")
        alternate = next(item for item in candidates if int(item["track_id"]) != initial_effective)
        overridden = _json(port, f"/api/music/recordings/{variant['recording_id']}/preferred-track", method="PUT", payload={"track_id": alternate["track_id"]})
        if int(overridden["effective_source"]["track_id"]) != int(alternate["track_id"]):
            raise Prod6CAcceptanceBlocked("manual preferred-source override did not take effect")
        restored = _json(port, f"/api/music/recordings/{variant['recording_id']}/preferred-track", method="DELETE")
        if int(restored["effective_source"]["track_id"]) != initial_effective:
            raise Prod6CAcceptanceBlocked("unset override did not resume automatic selection")
        source_result = {"variant": "PASS", "logical_recordings": 1, "physical_occurrences": len(candidates), "automatic_track_id": initial_effective, "override_unset": "PASS", "lossless_vs_lossy": "PASS" if lossless and lossy else "not_applicable"}
    else:
        if len(control["candidates"]) != 1 or initial_effective != int(control["candidates"][0]["track_id"]):
            raise Prod6CAcceptanceBlocked("single-source fallback is invalid")
        source_result = {"variant": "not_applicable", "single_source_fallback": "PASS", "prior_synthetic_policy_regressions_retained": True}

    recording_id = int(feedback_target["recording_id"])
    initial_track_id = int(feedback_target["id"])
    favorite = _json(port, f"/api/playback/tracks/{initial_track_id}/favorite", method="POST", payload={"favorite": True})
    up = _json(port, f"/api/playback/tracks/{initial_track_id}/feedback", method="POST", payload={"value": "thumbs_up"})
    if not favorite.get("favorite") or up.get("value") != "up" or int(up.get("recording_id") or 0) != recording_id:
        raise Prod6CAcceptanceBlocked("favorite/thumbs-up did not persist at recording level")
    refreshed_favorite = _json(port, f"/api/playback/tracks/{initial_track_id}/favorite")
    refreshed_up = _json(port, f"/api/playback/tracks/{initial_track_id}/feedback")
    if not refreshed_favorite.get("favorite") or refreshed_up.get("value") != "up":
        raise Prod6CAcceptanceBlocked("feedback refresh persistence failed")

    cross_source = "not_applicable"
    if variant is not None:
        alternate = next(item for item in control["candidates"] if int(item["track_id"]) != initial_track_id)
        _json(port, f"/api/music/recordings/{recording_id}/preferred-track", method="PUT", payload={"track_id": alternate["track_id"]})
        if not _json(port, f"/api/playback/tracks/{alternate['track_id']}/favorite").get("favorite") or _json(port, f"/api/playback/tracks/{alternate['track_id']}/feedback").get("value") != "up":
            raise Prod6CAcceptanceBlocked("recording-level feedback was lost across source switch")
        before_queue = [item["recording_id"] for item in album_queue]
        after_queue = [item["recording_id"] for item in _json(port, "/api/queue/album", method="POST", payload={"artist": target["artist"], "album": target["album"], "limit": 200, "shuffle": False})["queue"]]
        if before_queue != after_queue:
            raise Prod6CAcceptanceBlocked("source override corrupted logical album queue identity")
        cross_source = "PASS"

    debug_payload = {"type": "artist", "seed_value": feedback_target["artist"], "limit": 100, "shuffle": False}
    up_score = _score(_json(port, "/api/queue/station/debug", method="POST", payload=debug_payload), recording_id)
    _json(port, f"/api/playback/tracks/{initial_track_id}/feedback", method="POST", payload={"value": "neutral"})
    _json(port, f"/api/playback/tracks/{initial_track_id}/favorite", method="POST", payload={"favorite": False})
    base_score = _score(_json(port, "/api/queue/station/debug", method="POST", payload=debug_payload), recording_id)
    if up_score is None or base_score is None or up_score <= base_score:
        raise Prod6CAcceptanceBlocked("thumbs-up/favorite scoring bridge was not observed")
    _json(port, f"/api/playback/tracks/{initial_track_id}/favorite", method="POST", payload={"favorite": True})
    favorites_before = _json(port, "/api/queue/station", method="POST", payload={"type": "favorites", "limit": 100, "shuffle": False})["queue"]
    if recording_id not in {int(item["recording_id"]) for item in favorites_before}:
        raise Prod6CAcceptanceBlocked("favorite recording is absent from Favorites station")
    _json(port, f"/api/playback/tracks/{initial_track_id}/feedback", method="POST", payload={"value": "thumbs_down"})
    favorites_after = _json(port, "/api/queue/station", method="POST", payload={"type": "favorites", "limit": 100, "shuffle": False})["queue"]
    if recording_id in {int(item["recording_id"]) for item in favorites_after}:
        raise Prod6CAcceptanceBlocked("later thumbs-down did not exclude Favorites eligibility")
    _json(port, f"/api/playback/tracks/{initial_track_id}/feedback", method="POST", payload={"value": "neutral"})
    _json(port, f"/api/playback/tracks/{initial_track_id}/favorite", method="POST", payload={"favorite": False})
    if _json(port, f"/api/playback/tracks/{initial_track_id}/favorite").get("favorite"):
        raise Prod6CAcceptanceBlocked("unfavorite failed")

    playlist_tracks = tracks[: min(4, len(tracks))]
    if len(playlist_tracks) < 3:
        raise Prod6CAcceptanceBlocked("fixture must expose at least three listener songs for playlist proof")
    playlist = _json(port, "/api/playlists/from-track-list", method="POST", payload={"name": "BM-PROD6C Acceptance", "description": "disposable", "track_ids": [item["id"] for item in playlist_tracks]})
    playlist_id = int(playlist["id"])
    renamed = _json(port, f"/api/playlists/{playlist_id}", method="PATCH", payload={"name": "BM-PROD6C Acceptance Renamed"})
    if renamed.get("name") != "BM-PROD6C Acceptance Renamed":
        raise Prod6CAcceptanceBlocked("playlist rename failed")
    queue = _json(port, "/api/queue/playlist", method="POST", payload={"playlist_id": playlist_id, "shuffle": False})["queue"]
    expected_ids = [item["recording_id"] for item in playlist_tracks]
    if [item["recording_id"] for item in queue] != expected_ids:
        raise Prod6CAcceptanceBlocked("playlist logical order is invalid")
    for item in (queue[0], queue[len(queue) // 2]):
        if _http(port, item["stream_url"], headers={"Range": "bytes=0-31"})[0] != 206:
            raise Prod6CAcceptanceBlocked("playlist first/middle playback failed")
    reversed_ids = [item["id"] for item in reversed(queue)]
    reordered = _json(port, f"/api/playlists/{playlist_id}/tracks/reorder", method="PATCH", payload={"track_ids": reversed_ids})
    if [item["id"] for item in reordered["tracks"]] != reversed_ids:
        raise Prod6CAcceptanceBlocked("playlist reorder failed")
    removed_id = int(reordered["tracks"][1]["id"])
    removed = _json(port, f"/api/playlists/{playlist_id}/tracks/{removed_id}", method="DELETE")
    if len(removed["tracks"]) != len(reordered["tracks"]) - 1:
        raise Prod6CAcceptanceBlocked("playlist remove failed")
    _json(port, f"/api/playlists/{playlist_id}", method="DELETE")

    rescan_music = _json(port, "/api/library/scan/music", method="POST")
    rescan_audiobook = _json(port, "/api/audiobooks/scan", method="POST")
    tracks_after = _json(port, "/api/library/tracks?limit=200")
    controls_after = {int(item["recording_id"]): _json(port, f"/api/music/recordings/{item['recording_id']}/control") for item in tracks_after}
    physical_before = sum(len(item["candidates"]) for item in controls.values())
    physical_after = sum(len(item["candidates"]) for item in controls_after.values())
    if len(tracks_after) != len(tracks) or physical_after != physical_before or len(_json(port, "/api/audiobooks/")) != len(audiobooks):
        raise Prod6CAcceptanceBlocked("BM Radio rescan changed logical/physical/audiobook counts")

    artwork = "not_applicable"
    cover = next((item.get("cover_url") for item in tracks if item.get("cover_url")), None)
    if cover and _http(port, cover)[0] == 200:
        artwork = "PASS"

    return {
        "real_scanners": {"music": music_scan, "audiobook": audiobook_scan},
        "library": {"tracks": len(tracks), "artists": len(artists), "albums": len(albums), "audiobooks": len(audiobooks), "final_media_files": len(final_files)},
        "identity": {"logical_recordings": len(tracks), "physical_occurrences": physical_before, "listener_duplicates": 0, "artist_duplicates": 0, "album_duplicates": 0},
        "search_album_audiobook": "PASS",
        "preferred_source": source_result,
        "feedback": {"favorite_unfavorite": "PASS", "thumbs_up_down": "PASS", "refresh_persistence": "PASS", "recording_level_across_source": cross_source, "down_excluded_favorites": "PASS", "up_favorite_score_delta": up_score - base_score},
        "playlist": {"create_rename_add_reorder_play_first_middle_remove_delete": "PASS", "duplicate_policy": "duplicate logical entries are intentionally allowed"},
        "queue_source_continuity": {"album": "PASS", "search": "PASS", "playlist": "PASS", "source_override": cross_source},
        "artwork": artwork,
        "rerun": {"music": rescan_music.get("scan_run_status"), "audiobook": rescan_audiobook.get("scan_run_status"), "logical_equal": True, "physical_equal": True},
    }


def _cleanup_resources(state: dict[str, Any]) -> dict[str, Any]:
    for name in reversed(state.get("containers", [])):
        if str(name).startswith(RESOURCE_PREFIX) and name != CONTAINER_NAME:
            _docker("container", "rm", "--force", name, timeout=180)
    network = str(state.get("network") or "")
    volume = str(state.get("volume") or "")
    if network.startswith(RESOURCE_PREFIX):
        _docker("network", "rm", network, timeout=120)
    if volume.startswith(RESOURCE_PREFIX) and volume != VOLUME_NAME:
        _docker("volume", "rm", volume, timeout=120)
    remaining = _resource_inventory()
    return {"result": "PASS" if not any(remaining.values()) else "FAIL", "remaining": remaining}


def run_automated() -> dict[str, Any]:
    root = nas_root()
    gate = preflight()
    if gate["gate"] != "PASS":
        raise Prod6CAcceptanceBlocked("preflight blocked: " + "; ".join(gate["blockers"]))
    final_files = _media_files(root)
    if not any(path.suffix.lower() in {".flac", ".mp3", ".wav", ".m4a", ".ogg", ".opus", ".aac"} and "Music" in path.parts for path in final_files):
        raise Prod6CAcceptanceBlocked("AA-cleaned final Music fixture is absent")
    if not any(path.suffix.lower() in {".mp3", ".m4a", ".m4b", ".flac", ".ogg", ".opus", ".aac"} and "Audiobooks" in path.parts for path in final_files):
        raise Prod6CAcceptanceBlocked("AA-cleaned final Audiobook fixture is absent")
    if not any(path.suffix.lower() == ".epub" and "Books" in path.parts for path in final_files):
        raise Prod6CAcceptanceBlocked("AA-cleaned final EPUB fixture is absent")
    source_before = _source_snapshot(root)
    final_before = _snapshot(root, final_files)
    protected_before = _protected_state()
    run_id = secrets.token_hex(5)
    network = f"{RESOURCE_PREFIX}{run_id}"
    db_name = f"{RESOURCE_PREFIX}db-{run_id}"
    api_name = f"{RESOURCE_PREFIX}api-{run_id}"
    web_name = f"{RESOURCE_PREFIX}web-{run_id}"
    volume = f"{RESOURCE_PREFIX}db-data-{run_id}"
    role = f"bm_radio_6c_{run_id}"
    password = secrets.token_urlsafe(32)
    database = "bm_radio"
    db_url = URL.create("postgresql+psycopg", username=role, password=password, host="postgres", port=5432, database=database).render_as_string(hide_password=False)
    runtime = runtime_dir(root)
    runtime.mkdir(parents=True, exist_ok=False)
    (root / "cache" / "artwork").mkdir(parents=True, exist_ok=True)
    db_env = runtime / "postgres.env"
    api_env = runtime / "backend.env"
    _write_env(db_env, {"POSTGRES_DB": database, "POSTGRES_USER": role, "POSTGRES_PASSWORD": password})
    environment = prior.backend_live._base_environment(db_url)
    environment["BM_RADIO_CORS_ORIGINS"] = "http://127.0.0.1:8080"
    _write_env(api_env, environment)
    state: dict[str, Any] = {"containers": [db_name, api_name, web_name], "network": network, "volume": volume}
    try:
        _require(_docker("build", "--platform", "linux/amd64", "--tag", BACKEND_IMAGE, "--file", str(BACKEND / "Dockerfile"), str(BACKEND), timeout=1800), "PROD6C backend image build")
        _require(_docker("build", "--platform", "linux/amd64", "--build-arg", "VITE_API_BASE_URL=/api", "--tag", FRONTEND_IMAGE, "--file", str(FRONTEND / "Dockerfile"), str(FRONTEND), timeout=1800), "PROD6C frontend image build")
        _require(_docker("network", "create", "--driver", "bridge", network), "private network creation")
        _require(_docker("volume", "create", volume), "disposable PostgreSQL volume creation")
        _require(_docker(
            "run", "--detach", "--name", db_name, "--network", network, "--network-alias", "postgres", "--env-file", str(db_env),
            "--mount", f"type=volume,source={volume},target=/var/lib/postgresql/data",
            "--health-cmd", "pg_isready --username=$POSTGRES_USER --dbname=$POSTGRES_DB", "--health-interval", "5s", "--health-timeout", "5s", "--health-retries", "24",
            "--security-opt", "no-new-privileges:true", POSTGRES_IMAGE, timeout=300,
        ), "disposable PostgreSQL 16 creation")
        _wait_postgres(db_name, role, database)
        _migrate(network, api_env)
        _require(_docker(
            "run", "--detach", "--name", api_name, "--network", network, "--network-alias", "backend", "--env-file", str(api_env),
            "--read-only", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,source={root / 'cache'},target=/app-cache",
            "--mount", f"type=bind,source={root / 'Music'},target=/media/Music,readonly",
            "--mount", f"type=bind,source={root / 'Audiobooks' / 'Library'},target=/media/Audiobooks/Library,readonly",
            "--mount", f"type=bind,source={root / 'Books'},target=/media/Books,readonly",
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
        automated = _automated_http_proof(port, final_files)
        if _snapshot(root, final_files) != final_before:
            raise Prod6CAcceptanceBlocked("BM Radio modified read-only final media")
        if _source_snapshot(root) != source_before:
            raise Prod6CAcceptanceBlocked("immutable source fixture hashes changed")
        protected_after = _protected_state()
        if protected_after != protected_before:
            raise Prod6CAcceptanceBlocked("active PostgreSQL/SQLite/.env/durable evidence changed")
        proof = {
            "status": "AUTOMATED PASS; HUMAN LIBRARY REVIEW REQUIRED",
            "source_commit": STARTING_COMMIT,
            "frontend_url": f"http://127.0.0.1:{port}",
            "nas_root": "$NAS_LOCAL_ROOT",
            "database": {"postgresql": "16", "alembic_head": "PASS", "isolated": True, "active_target_used": False},
            "topology": topology,
            "fixture": {"source_files": len(source_before), "final_files": len(final_files), "source_hashes_equal": True, "final_media_unchanged_by_bm_radio": True},
            "automated": automated,
            "protected_before_sha256": _canonical_sha(protected_before),
            "protected_after_sha256": _canonical_sha(protected_after),
            "human_result": None,
            "human_checklist": list(MANUAL_CHECKS),
            "truenas_work": False,
            "cleaner_deletion": False,
        }
        state.update({"port": port, "proof": proof, "source_before": source_before, "final_before": final_before})
        state_path(root).write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        (evidence_dir(root) / "bm_radio_automated_evidence.json").write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
        return proof
    except Exception:
        _cleanup_resources(state)
        shutil.rmtree(runtime, ignore_errors=True)
        raise


def _load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        raise Prod6CAcceptanceBlocked("no retained BM-PROD6C manual-review stack exists")
    return json.loads(path.read_text(encoding="utf-8"))


def manual_url() -> dict[str, Any]:
    root = nas_root()
    state = _load_state(root)
    web = next((name for name in state["containers"] if name.startswith(f"{RESOURCE_PREFIX}web-")), None)
    if not web:
        raise Prod6CAcceptanceBlocked("retained frontend container identity is missing")
    port = _dynamic_port(web, "8080/tcp")
    _wait_origin(port, timeout=30)
    return {"frontend_url": f"http://127.0.0.1:{port}", "human_checklist": list(MANUAL_CHECKS), "recorded_result": state["proof"].get("human_result")}


def record_manual(result: str, note: str) -> dict[str, Any]:
    root = nas_root()
    state = _load_state(root)
    if not note.strip():
        raise Prod6CAcceptanceBlocked("a real operator note is required; automation cannot fabricate human review")
    recorded = {"result": result.upper(), "operator_note": note.strip(), "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "automated": False}
    state["proof"]["human_result"] = recorded
    state_path(root).write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    (evidence_dir(root) / "bm_radio_automated_evidence.json").write_text(json.dumps(state["proof"], indent=2, sort_keys=True), encoding="utf-8")
    return recorded


def cleanup() -> dict[str, Any]:
    root = nas_root()
    state = _load_state(root)
    human = state["proof"].get("human_result")
    source_equal = _source_snapshot(root) == state["source_before"]
    final_equal = _snapshot(root, _media_files(root)) == state["final_before"]
    protected_equal = _canonical_sha(_protected_state()) == state["proof"]["protected_before_sha256"]
    resources = _cleanup_resources(state)
    shutil.rmtree(runtime_dir(root), ignore_errors=True)
    result = {"human_result": human, "source_hashes_equal": source_equal, "final_media_equal": final_equal, "protected_state_equal": protected_equal, "cleanup": resources}
    (evidence_dir(root) / "cleanup_evidence.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    state_path(root).unlink(missing_ok=True)
    if not source_equal or not final_equal or not protected_equal or resources["result"] != "PASS":
        raise Prod6CAcceptanceBlocked(f"final equality or cleanup failed: {result}")
    if not human or human.get("result") != "PASS":
        raise Prod6CAcceptanceBlocked("cleanup passed, but human library review has not recorded PASS")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD6C local NAS library/source UX acceptance")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--bm-radio-automated", action="store_true")
    mode.add_argument("--manual-url", action="store_true")
    mode.add_argument("--record-manual", choices=("PASS", "FAIL"))
    mode.add_argument("--cleanup", action="store_true")
    parser.add_argument("--operator-note", default="")
    args = parser.parse_args()
    try:
        if args.preflight_only:
            result = preflight()
            print(json.dumps(result, indent=2, sort_keys=True))
            print(f"BM-PROD6C PREFLIGHT: {result['gate']}")
            return 0 if result["gate"] == "PASS" else 2
        if args.bm_radio_automated:
            result = run_automated()
        elif args.manual_url:
            result = manual_url()
        elif args.record_manual:
            result = record_manual(args.record_manual, args.operator_note)
        else:
            result = cleanup()
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.bm_radio_automated:
            print("BM-PROD6C AUTOMATED: PASS; human library review required")
        elif args.cleanup:
            print("BM-PROD6C status: LOCAL-LIBRARY-UX PASS")
        return 0
    except (Prod6CAcceptanceBlocked, prior.IntegratedStackBlocked, subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BM-PROD6C status: BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
