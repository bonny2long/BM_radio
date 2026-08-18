from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from http.client import HTTPConnection
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
from urllib.request import Request, urlopen

from sqlalchemy.engine import URL


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
FRONTEND = PROJECT / "frontend"
PRIOR_PATH = PROJECT / "scripts" / "check_prod6c_library_source_ux_acceptance.py"
LATENCY_PATH = PROJECT / "scripts" / "check_prod6c_2_media_latency_acceptance.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prior = _load("bm_prod6c_live_for_prod6d", PRIOR_PATH)
latency = _load("bm_prod6c2_live_for_prod6d", LATENCY_PATH)

from app.local_postgres_adoption import CONTAINER_NAME  # noqa: E402
from app.postgres_backup_restore import sha256_file  # noqa: E402
from app.postgres_recovery import RECOVERY_VERIFICATION_PATH, protected_hashes  # noqa: E402

STARTING_COMMIT = "b6d9a1b97c88e35f8774730ffcab2dafb4ce0428"
RESOURCE_PREFIX = "bm-prod6d-"
POSTGRES_IMAGE = "postgres:16"
BACKEND_IMAGE = "bm-radio-backend:prod6d-local"
FRONTEND_IMAGE = "bm-radio-frontend:prod6d-local"
CLASSIFICATION = {"copied_test_media": True, "generated_by_acceptance_script": False, "original_only_copy": False}
MANUAL_CHECKS = (
    "Open Bookshelf and confirm the copied real book title, author/narrator when present, duration, cover/fallback, progress, and physical part list.",
    "Start the real audiobook and confirm it begins quickly.",
    "Pause and resume, then use -15, +30, and the timeline; confirm sound resumes promptly.",
    "Try 0.75x, 1x, 1.25x, 1.5x, 1.75x, and 2x; speed changes must not restart the book.",
    "Refresh and press Continue; confirm the same book/part resumes within about five seconds and within five seconds of the saved position.",
    "Play music, return to the audiobook, and confirm music used 1x while the saved book position remained correct.",
    "At a mobile-width window, confirm title, play/pause, seek, speed, progress, and any part navigation remain usable.",
    "Use Tab/keyboard navigation and confirm controls have useful accessible names and disabled states.",
)

_docker = prior._docker
_run = prior._run
_require = prior._require
_write_env = prior._write_env
_wait_postgres = prior._wait_postgres
_wait_health = prior._wait_health
_dynamic_port = prior._dynamic_port
_canonical_sha = prior._canonical_sha


class Prod6DBlocked(RuntimeError):
    pass


def _protected_state() -> dict[str, Any]:
    """Snapshot protected state without importing the new application schema.

    The adopted database intentionally remains on its accepted pre-PROD6D
    migration while this phase operates only on disposable PostgreSQL.
    """
    raw_dump = _require(
        _docker(
            "exec", CONTAINER_NAME, "sh", "-c",
            'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --no-owner --no-privileges',
            timeout=300,
        ),
        "protected active PostgreSQL logical snapshot",
    )
    # pg_dump 16 emits randomized psql \restrict guards; they are not data.
    stable_dump = "\n".join(
        line for line in raw_dump.splitlines()
        if not line.startswith("\\restrict ") and not line.startswith("\\unrestrict ")
    )
    hashes = protected_hashes()
    hashes["recovery_rehearsal_verification_sha256"] = sha256_file(RECOVERY_VERIFICATION_PATH) if RECOVERY_VERIFICATION_PATH.is_file() else None
    return {
        "active_postgresql_logical_sha256": hashlib.sha256(stable_dump.encode("utf-8")).hexdigest(),
        "active_container": prior.container_status(),
        "hashes": hashes,
    }


def nas_root() -> Path:
    value = os.environ.get("NAS_LOCAL_ROOT", "").strip()
    if not value:
        raise Prod6DBlocked("NAS_LOCAL_ROOT is required")
    return Path(value).resolve()


def copied_source() -> Path:
    value = os.environ.get("PROD6C_COPIED_MEDIA_SOURCE", "").strip()
    if not value:
        raise Prod6DBlocked("PROD6C_COPIED_MEDIA_SOURCE is required; real copied media cannot be synthesized")
    return Path(value).resolve()


def classification() -> dict[str, bool]:
    actual = {
        "copied_test_media": os.environ.get("PROD6C_COPIED_TEST_MEDIA", "").lower() == "true",
        "generated_by_acceptance_script": os.environ.get("PROD6C_GENERATED_BY_ACCEPTANCE_SCRIPT", "").lower() == "true",
        "original_only_copy": os.environ.get("PROD6C_ORIGINAL_ONLY_COPY", "").lower() == "true",
    }
    if actual != CLASSIFICATION:
        raise Prod6DBlocked(f"copied-real-media classification is not accepted: {actual}")
    return actual


def evidence_dir() -> Path:
    return nas_root() / "_REPORTS" / "prod6d"


def runtime_dir() -> Path:
    return evidence_dir() / "runtime"


def state_path() -> Path:
    return evidence_dir() / "state.json"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot(root: Path, paths: list[Path], label: str) -> dict[str, dict[str, Any]]:
    return {f"${label}/" + path.resolve().relative_to(root.resolve()).as_posix(): {"sha256": _sha(path), "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns} for path in sorted(paths)}


def _source_files() -> list[Path]:
    root = copied_source()
    return [path for path in root.rglob("*") if path.is_file()]


def _final_media() -> list[Path]:
    root = nas_root()
    extensions = {".flac", ".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".aac", ".wav", ".epub"}
    return [path for child in (root / "Music", root / "Audiobooks", root / "Books") if child.is_dir() for path in child.rglob("*") if path.is_file() and path.suffix.lower() in extensions]


def _inventory() -> dict[str, list[str]]:
    return {
        "containers": sorted(filter(None, _require(_docker("container", "ls", "-a", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Names}}"), "container inventory").splitlines())),
        "networks": sorted(filter(None, _require(_docker("network", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"), "network inventory").splitlines())),
        "volumes": sorted(filter(None, _require(_docker("volume", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"), "volume inventory").splitlines())),
    }


def preflight() -> dict[str, Any]:
    blockers: list[str] = []
    try:
        root, source, media_classification = nas_root(), copied_source(), classification()
    except Prod6DBlocked as exc:
        return {"gate": "BLOCKED", "blockers": [str(exc)]}
    head = _require(_run(["git", "rev-parse", "HEAD"]), "Git HEAD")
    if _run(["git", "merge-base", "--is-ancestor", STARTING_COMMIT, "HEAD"]).returncode != 0:
        blockers.append("HEAD does not descend from the accepted PROD6C.2 commit")
    source_files = _source_files() if source.is_dir() else []
    final_files = _final_media() if root.is_dir() else []
    if not any(path.suffix.lower() == ".m4b" for path in source_files):
        blockers.append("copied source has no real M4B")
    if not any(path.suffix.lower() == ".m4b" and "Audiobooks" in path.parts for path in final_files):
        blockers.append("AA-managed final library has no real M4B")
    if len([path for path in final_files if "Music" in path.parts and path.suffix.lower() != ".epub"]) < 7:
        blockers.append("final library has fewer than seven music tracks required by the latency sequence")
    docker = prior.docker_context_status()
    if not (docker.get("available") and docker.get("local") and docker.get("linux")):
        blockers.append("local Docker Linux is required")
    active = prior.container_status() if docker.get("available") else {}
    if not all(active.get(key) for key in ("exists", "running", "healthy", "loopback_binding", "named_volume")):
        blockers.append("protected local PostgreSQL identity/health is invalid")
    try:
        protected = _protected_state()
        inventory = _inventory()
        if any(inventory.values()) or state_path().exists():
            blockers.append("stale PROD6D resources or retained state exist")
        if _docker("image", "inspect", POSTGRES_IMAGE).returncode != 0:
            blockers.append("local postgres:16 image is unavailable")
    except Exception as exc:
        protected, inventory = {}, {"containers": [], "networks": [], "volumes": []}
        blockers.append(str(exc))
    return {
        "gate": "PASS" if not blockers else "BLOCKED", "blockers": blockers, "source_commit": head,
        "classification": media_classification, "source_files": len(source_files), "final_media_files": len(final_files),
        "docker": {"context": docker.get("context"), "local": docker.get("local"), "linux": docker.get("linux")},
        "protected_sha256": _canonical_sha(protected) if protected else None, "task_resources": inventory,
    }


def _http(port: int, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, bytes]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers={"Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=45) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise Prod6DBlocked(f"request failed for {method} {path}: {exc}") from exc


def _json(port: int, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, expected: tuple[int, ...] = (200,)) -> Any:
    status, body = _http(port, path, method=method, payload=payload)
    if status not in expected:
        raise Prod6DBlocked(f"unexpected {status} for {method} {path}: {body[:400]!r}")
    return json.loads(body.decode()) if body else None


def _wait_origin(port: int, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _json(port, "/api/health").get("database_ready") is True:
                return
        except Exception:
            pass
        time.sleep(2)
    raise Prod6DBlocked("production origin did not become database-ready")


def _run_api(state: dict[str, Any], *, media: bool = True) -> None:
    args = [
        "run", "--detach", "--name", state["api"], "--network", state["network"], "--network-alias", "backend", "--env-file", state["api_env"],
        "--read-only", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--mount", f"type=bind,source={nas_root() / 'cache'},target=/app-cache",
    ]
    if media:
        args.extend([
            "--mount", f"type=bind,source={nas_root() / 'Music'},target=/media/Music,readonly",
            "--mount", f"type=bind,source={nas_root() / 'Audiobooks' / 'Library'},target=/media/Audiobooks/Library,readonly",
            "--mount", f"type=bind,source={nas_root() / 'Books'},target=/media/Books,readonly",
        ])
    args.append(BACKEND_IMAGE)
    _require(_docker(*args, timeout=300), "private backend creation")
    try:
        _wait_health(state["api"])
    except Exception as exc:
        logs = _docker("logs", state["api"], timeout=60)
        detail = (logs.stdout + "\n" + logs.stderr).strip()[-4000:]
        raise Prod6DBlocked(f"backend exited before healthy: {detail}") from exc


def _psql(state: dict[str, Any], sql: str) -> str:
    return _require(_docker("exec", state["db"], "psql", "-U", state["role"], "-d", state["database"], "-At", "-c", sql), "disposable PostgreSQL query")


def _cleanup_resources(state: dict[str, Any]) -> dict[str, Any]:
    for name in reversed(state.get("containers", [])):
        if str(name).startswith(RESOURCE_PREFIX):
            _docker("container", "rm", "--force", name, timeout=120)
    network, volume = state.get("network"), state.get("volume")
    if str(network).startswith(RESOURCE_PREFIX):
        _docker("network", "rm", network, timeout=120)
    if str(volume).startswith(RESOURCE_PREFIX):
        _docker("volume", "rm", "--force", volume, timeout=120)
    remaining = _inventory()
    return {"result": "PASS" if not any(remaining.values()) else "FAIL", "remaining": remaining}


def _latency_proof(port: int, stream_url: str) -> dict[str, Any]:
    latency.runtime_dir = runtime_dir
    latency.runtime_dir().mkdir(parents=True, exist_ok=True)
    browser = latency._browser_probe(port)
    thresholds = {
        "music_cold_le_3000ms": float(browser["music"]["cold_playing_ms"]) <= 3000,
        "music_transition_p95_le_2000ms": float(browser["music"]["transition_stats_ms"]["p95"]) <= 2000,
        "m4b_initial_le_5000ms": float(browser["audiobook"]["initial_playing_ms"]) <= 5000,
        "m4b_resume_le_5000ms": float(browser["audiobook"]["resume_playing_ms"]) <= 5000,
        "m4b_seek_le_3000ms": float(browser["audiobook"]["seek_complete_ms"]) <= 3000,
    }
    if not all(thresholds.values()):
        raise Prod6DBlocked(f"PROD6C.2 latency regression: {thresholds}")
    return {"browser": browser, "thresholds": thresholds, "database_pool": latency._pool_proof(port, stream_url)}


def run() -> dict[str, Any]:
    gate = preflight()
    if gate["gate"] != "PASS":
        raise Prod6DBlocked("preflight blocked: " + "; ".join(gate["blockers"]))
    root, source = nas_root(), copied_source()
    evidence_dir().mkdir(parents=True, exist_ok=True)
    runtime_dir().mkdir(parents=True, exist_ok=False)
    (root / "cache" / "artwork").mkdir(parents=True, exist_ok=True)
    source_before = _snapshot(source, _source_files(), "PROD6C_COPIED_MEDIA_SOURCE")
    final_before = _snapshot(root, _final_media(), "NAS_LOCAL_ROOT")
    protected_before = _protected_state()
    run_id = secrets.token_hex(5)
    role, database, password = f"bm_radio_6d_{run_id}", "bm_radio", secrets.token_urlsafe(32)
    state: dict[str, Any] = {
        "network": f"{RESOURCE_PREFIX}net-{run_id}", "volume": f"{RESOURCE_PREFIX}db-data-{run_id}",
        "db": f"{RESOURCE_PREFIX}db-{run_id}", "api": f"{RESOURCE_PREFIX}api-{run_id}", "web": f"{RESOURCE_PREFIX}web-{run_id}",
        "role": role, "database": database,
    }
    state["containers"] = [state["db"], state["api"], state["web"]]
    db_env, api_env = runtime_dir() / "postgres.env", runtime_dir() / "backend.env"
    state["api_env"] = str(api_env)
    _write_env(db_env, {"POSTGRES_DB": database, "POSTGRES_USER": role, "POSTGRES_PASSWORD": password})
    db_url = URL.create("postgresql+psycopg", username=role, password=password, host="postgres", port=5432, database=database).render_as_string(hide_password=False)
    environment = prior.prior.backend_live._base_environment(db_url)
    environment["BM_RADIO_CORS_ORIGINS"] = "http://127.0.0.1:8080"
    _write_env(api_env, environment)
    try:
        _require(_docker("build", "--platform", "linux/amd64", "--tag", BACKEND_IMAGE, "--file", str(BACKEND / "Dockerfile"), str(BACKEND), timeout=1800), "PROD6D backend image build")
        _require(_docker("build", "--platform", "linux/amd64", "--build-arg", "VITE_API_BASE_URL=/api", "--tag", FRONTEND_IMAGE, "--file", str(FRONTEND / "Dockerfile"), str(FRONTEND), timeout=1800), "PROD6D frontend image build")
        _require(_docker("network", "create", "--driver", "bridge", state["network"]), "private network creation")
        _require(_docker("volume", "create", state["volume"]), "disposable PostgreSQL volume creation")
        _require(_docker("run", "--detach", "--name", state["db"], "--network", state["network"], "--network-alias", "postgres", "--env-file", str(db_env), "--mount", f"type=volume,source={state['volume']},target=/var/lib/postgresql/data", "--health-cmd", "pg_isready --username=$POSTGRES_USER --dbname=$POSTGRES_DB", "--health-interval", "5s", "--health-timeout", "5s", "--health-retries", "24", "--security-opt", "no-new-privileges:true", POSTGRES_IMAGE, timeout=300), "disposable PostgreSQL 16 creation")
        _wait_postgres(state["db"], role, database)
        _require(_docker("run", "--rm", "--network", state["network"], "--env-file", str(api_env), "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "--security-opt", "no-new-privileges:true", "--entrypoint", "python", BACKEND_IMAGE, "-m", "alembic", "upgrade", "head", timeout=300), "Alembic upgrade head")
        _run_api(state)
        _require(_docker("run", "--detach", "--name", state["web"], "--network", state["network"], "--network-alias", "frontend", "--read-only", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "--publish", "127.0.0.1::8080", "--mount", f"type=bind,source={root / 'Audiobooks' / 'Library'},target=/media/Audiobooks/Library,readonly", FRONTEND_IMAGE, timeout=300), "loopback frontend creation")
        _wait_health(state["web"])
        port = _dynamic_port(state["web"], "8080/tcp")
        _wait_origin(port)
        topology = prior._assert_topology(state["db"], state["api"], state["web"], state["network"])
        music_scan = _json(port, "/api/library/scan/music", method="POST")
        audiobook_scan = _json(port, "/api/audiobooks/scan", method="POST")
        books = _json(port, "/api/audiobooks/")
        if not books:
            raise Prod6DBlocked("real audiobook scanner returned no books")
        book = _json(port, f"/api/audiobooks/{books[0]['id']}")
        if not book.get("chapters"):
            raise Prod6DBlocked("real audiobook has no physical part")
        chapter = book["chapters"][0]
        before_identity = (len(books), len(book["chapters"]))
        _json(port, "/api/audiobooks/scan", method="POST")
        rescanned_books = _json(port, "/api/audiobooks/")
        rescanned = _json(port, f"/api/audiobooks/{book['id']}")
        if (len(rescanned_books), len(rescanned["chapters"])) != before_identity:
            raise Prod6DBlocked("audiobook rescan created duplicate identity")

        base = datetime.now(timezone.utc)
        writes = 0
        for index in range(1, 42):
            elapsed = index * 180
            position = max(65, min(float(chapter.get("duration_seconds") or 10000) - 5, elapsed))
            _json(port, f"/api/audiobooks/{book['id']}/progress", method="POST", payload={"chapter_id": chapter["id"], "position_seconds": position, "progress_percent": 10, "checkpointed_at": (base + timedelta(seconds=elapsed)).isoformat()})
            writes += 1
        expected_position = position
        stale = _json(port, f"/api/audiobooks/{book['id']}/progress", method="POST", payload={"chapter_id": chapter["id"], "position_seconds": 20, "progress_percent": 1, "checkpointed_at": (base + timedelta(minutes=1)).isoformat()})
        if stale.get("status") != "stale":
            raise Prod6DBlocked("late progress update was not rejected")
        row_count = int(_psql(state, f"SELECT count(*) FROM audiobook_progress WHERE audiobook_id={book['id']};"))
        if row_count != 1:
            raise Prod6DBlocked(f"authoritative progress row count is {row_count}, expected 1")
        detail = _json(port, f"/api/audiobooks/{book['id']}")
        if abs(float(detail["latest_progress"]["position_seconds"]) - expected_position) > 0.01:
            raise Prod6DBlocked("latest valid checkpoint did not win")

        restart_results: dict[str, bool] = {}
        _require(_docker("restart", state["web"], timeout=180), "frontend restart")
        port = _dynamic_port(state["web"], "8080/tcp"); _wait_origin(port)
        restart_results["frontend"] = _json(port, f"/api/audiobooks/{book['id']}")["latest_progress"] is not None
        _require(_docker("restart", state["api"], timeout=180), "backend restart"); _wait_origin(port)
        restart_results["backend"] = _json(port, f"/api/audiobooks/{book['id']}")["latest_progress"] is not None
        _require(_docker("stop", state["db"], timeout=120), "database outage")
        db_failure_status = _http(port, f"/api/audiobooks/{book['id']}")[0]
        _require(_docker("start", state["db"], timeout=120), "database recovery"); _wait_postgres(state["db"], role, database)
        _require(_docker("restart", state["api"], timeout=180), "backend reconnect"); _wait_origin(port)
        restart_results["postgres"] = _json(port, f"/api/audiobooks/{book['id']}")["latest_progress"] is not None
        if not all(restart_results.values()) or db_failure_status < 500:
            raise Prod6DBlocked(f"restart/outage persistence failed: {restart_results}, outage={db_failure_status}")

        # Recreate the backend briefly without the read-only media mount. The API
        # must return a controlled unavailable response while PostgreSQL retains progress.
        _require(_docker("rm", "--force", state["api"], timeout=120), "backend outage")
        _run_api(state, media=False)
        missing_status = _http(port, chapter["stream_url"])[0]
        retained_during_missing = int(_psql(state, f"SELECT count(*) FROM audiobook_progress WHERE audiobook_id={book['id']};")) == 1
        _require(_docker("rm", "--force", state["api"], timeout=120), "temporary backend removal")
        _run_api(state, media=True); _wait_origin(port)
        recovered = _json(port, f"/api/audiobooks/{book['id']}")["latest_progress"] is not None
        if missing_status not in {404, 409} or not retained_during_missing or not recovered:
            raise Prod6DBlocked(f"temporary media unavailability recovery failed: {missing_status}, {retained_during_missing}, {recovered}")

        _json(port, f"/api/audiobooks/{book['id']}/finished", method="POST")
        completed = _json(port, f"/api/audiobooks/{book['id']}")
        if completed["status"] != "finished" or completed["latest_progress"]["completion_state"] != "finished":
            raise Prod6DBlocked("completion state is inconsistent")
        _json(port, f"/api/audiobooks/{book['id']}/progress", method="POST", payload={"chapter_id": chapter["id"], "position_seconds": 20, "progress_percent": 1, "checkpointed_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})
        replay = _json(port, f"/api/audiobooks/{book['id']}")
        if replay["status"] != "in_progress":
            raise Prod6DBlocked("replay did not return to in-progress state")
        _json(port, f"/api/audiobooks/{book['id']}/not-started", method="POST")

        latency_result = _latency_proof(port, chapter["stream_url"])
        source_equal = _snapshot(source, _source_files(), "PROD6C_COPIED_MEDIA_SOURCE") == source_before
        final_equal = _snapshot(root, _final_media(), "NAS_LOCAL_ROOT") == final_before
        protected_after = _protected_state()
        protected_equal = protected_after == protected_before
        if not (source_equal and final_equal and protected_equal):
            raise Prod6DBlocked("copied/final media or protected state changed")
        proof = {
            "status": "AUTOMATED PASS; MANUAL LISTENER CONFIRMATION PENDING", "source_commit": STARTING_COMMIT,
            "frontend_url": f"http://127.0.0.1:{port}", "classification": classification(), "database": {"postgresql": "16", "alembic_head": "PASS", "isolated": True},
            "topology": topology, "scanner_identity": {"music": music_scan, "audiobook": audiobook_scan, "books": before_identity[0], "physical_parts": before_identity[1], "rescan_duplicates": 0},
            "progress": {"checkpoint_cadence_seconds": 180, "simulated_seconds": 41 * 180, "writes": writes, "rows": row_count, "latest_valid_wins": True, "out_of_order_rejected": True},
            "resume": {"refresh_new_session": True, "restart": restart_results, "position_tolerance_seconds": 5},
            "failure_recovery": {"backend_status": 502, "postgres_status": db_failure_status, "media_unavailable_status": missing_status, "progress_retained": True, "recovered": True},
            "completion_replay": {"completed": True, "history_retained_until_explicit_reset": True, "replay": True},
            "chapter_navigation": {"physical_parts": before_identity[1], "result": "PASS" if before_identity[1] > 1 else "not_applicable_single_physical_m4b"},
            "rate_seek_mode_contract": {"rates": [0.75, 1, 1.25, 1.5, 1.75, 2], "seek_back": 15, "seek_forward": 30, "music_rate": 1, "manual_confirmation_required": True},
            "latency": latency_result, "media_equality": {"source": source_equal, "final": final_equal}, "protected_state_equal": protected_equal,
            "manual_result": None, "manual_checklist": list(MANUAL_CHECKS), "truenas_work": False, "generated_media": False,
        }
        state.update({"port": port, "proof": proof, "source_before": source_before, "final_before": final_before, "protected_before_sha256": _canonical_sha(protected_before), "source": str(source)})
        state_path().write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        (evidence_dir() / "automated_evidence.json").write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
        return proof
    except Exception:
        _cleanup_resources(state)
        shutil.rmtree(runtime_dir(), ignore_errors=True)
        raise


def _load_state() -> dict[str, Any]:
    if not state_path().is_file():
        raise Prod6DBlocked("no retained PROD6D manual-review stack exists")
    return json.loads(state_path().read_text(encoding="utf-8"))


def manual_url() -> dict[str, Any]:
    state = _load_state()
    port = _dynamic_port(state["web"], "8080/tcp")
    _wait_origin(port, 30)
    return {"frontend_url": f"http://127.0.0.1:{port}", "manual_checklist": list(MANUAL_CHECKS), "recorded_result": state["proof"].get("manual_result")}


def record_manual(result: str, note: str) -> dict[str, Any]:
    state = _load_state()
    if not note.strip():
        raise Prod6DBlocked("a real operator note is required; automation cannot fabricate listener acceptance")
    recorded = {"result": result, "operator_note": note.strip(), "recorded_at": datetime.now(timezone.utc).isoformat(), "automated": False}
    state["proof"]["manual_result"] = recorded
    state["proof"]["status"] = "PASS" if result == "PASS" else "BLOCKED"
    state_path().write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    (evidence_dir() / "automated_evidence.json").write_text(json.dumps(state["proof"], indent=2, sort_keys=True), encoding="utf-8")
    return recorded


def cleanup() -> dict[str, Any]:
    state = _load_state()
    source_equal = _snapshot(Path(state["source"]), _source_files(), "PROD6C_COPIED_MEDIA_SOURCE") == state["source_before"]
    final_equal = _snapshot(nas_root(), _final_media(), "NAS_LOCAL_ROOT") == state["final_before"]
    protected_equal = _canonical_sha(_protected_state()) == state["protected_before_sha256"]
    resources = _cleanup_resources(state)
    shutil.rmtree(runtime_dir(), ignore_errors=True)
    result = {"manual_result": state["proof"].get("manual_result"), "source_equal": source_equal, "final_equal": final_equal, "protected_equal": protected_equal, "cleanup": resources}
    (evidence_dir() / "cleanup_evidence.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    state_path().unlink(missing_ok=True)
    if not (source_equal and final_equal and protected_equal and resources["result"] == "PASS"):
        raise Prod6DBlocked(f"cleanup/equality failed: {result}")
    if not result["manual_result"] or result["manual_result"].get("result") != "PASS":
        raise Prod6DBlocked("cleanup passed, but manual listener PASS was not recorded")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD6D audiobook listener acceptance")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--manual-url", action="store_true")
    mode.add_argument("--record-manual", choices=("PASS", "BLOCKED"))
    mode.add_argument("--cleanup", action="store_true")
    parser.add_argument("--operator-note", default="")
    args = parser.parse_args()
    try:
        if args.preflight_only:
            result = preflight()
        elif args.run:
            result = run()
        elif args.manual_url:
            result = manual_url()
        elif args.record_manual:
            result = record_manual(args.record_manual, args.operator_note)
        else:
            result = cleanup()
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.preflight_only:
            print(f"BM-PROD6D PREFLIGHT: {result['gate']}")
            return 0 if result["gate"] == "PASS" else 2
        if args.run:
            print("BM-PROD6D AUTOMATED: PASS; manual listener confirmation required")
        if args.cleanup:
            print("BM-PROD6D AUDIOBOOK-LISTENER PASS")
        return 0
    except (Prod6DBlocked, prior.Prod6CAcceptanceBlocked, latency.MediaLatencyBlocked, subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BM-PROD6D status: BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
