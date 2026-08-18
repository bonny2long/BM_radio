from __future__ import annotations

import argparse
import base64
import hashlib
from http.client import HTTPConnection
import importlib.util
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from sqlalchemy.engine import URL


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
FRONTEND = PROJECT / "frontend"
PRIOR_PATH = PROJECT / "scripts" / "check_prod6c_library_source_ux_acceptance.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_spec = importlib.util.spec_from_file_location("bm_prod6c_live", PRIOR_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("BM-PROD6C live helper cannot be loaded")
prior = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prior)

from app.local_postgres_adoption import CONTAINER_NAME, VOLUME_NAME, container_status, docker_context_status  # noqa: E402
from app.postgres_backup_restore import _process_quiescence  # noqa: E402


STARTING_COMMIT = "9f0899b11de24f3fbc45b0a5f2b2bfd9745b4013"
RESOURCE_PREFIX = "bm-prod6c2-"
POSTGRES_IMAGE = "postgres:16"
BACKEND_IMAGE = "bm-radio-backend:prod6c2-local"
FRONTEND_IMAGE = "bm-radio-frontend:prod6c2-local"
RANGE_SIZE = 256 * 1024
MUSIC_START_COUNT = 10
CLASSIFICATION = {
    "copied_test_media": True,
    "generated_by_acceptance_script": False,
    "original_only_copy": False,
}

_docker = prior._docker
_require = prior._require
_run = prior._run
_write_env = prior._write_env
_protected_state = prior._protected_state
_wait_postgres = prior._wait_postgres
_wait_health = prior._wait_health
_dynamic_port = prior._dynamic_port


class MediaLatencyBlocked(RuntimeError):
    pass


class ChromeDevToolsError(MediaLatencyBlocked):
    def __init__(self, code: int | None, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Chrome DevTools error: code={code} message={message}")


def nas_root() -> Path:
    value = os.environ.get("NAS_LOCAL_ROOT", "").strip()
    if not value:
        raise MediaLatencyBlocked("NAS_LOCAL_ROOT is required")
    return Path(value).resolve()


def copied_source() -> Path:
    value = os.environ.get("PROD6C_COPIED_MEDIA_SOURCE", "").strip()
    if not value:
        raise MediaLatencyBlocked("PROD6C_COPIED_MEDIA_SOURCE is required; media must not be synthesized")
    return Path(value).resolve()


def source_classification() -> dict[str, bool]:
    actual = {
        "copied_test_media": os.environ.get("PROD6C_COPIED_TEST_MEDIA", "").strip().lower() == "true",
        "generated_by_acceptance_script": os.environ.get("PROD6C_GENERATED_BY_ACCEPTANCE_SCRIPT", "").strip().lower() == "true",
        "original_only_copy": os.environ.get("PROD6C_ORIGINAL_ONLY_COPY", "").strip().lower() == "true",
    }
    if actual != CLASSIFICATION:
        raise MediaLatencyBlocked(f"copied-real-media classification is not accepted: {actual}")
    return actual


def evidence_dir() -> Path:
    return nas_root() / "_REPORTS" / "prod6c2"


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
    return {
        f"${label}/" + path.resolve().relative_to(root.resolve()).as_posix(): {
            "sha256": _sha(path),
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in sorted(paths)
    }


def _source_files() -> list[Path]:
    root = copied_source()
    return [path for path in root.rglob("*") if path.is_file()]


def _final_media() -> list[Path]:
    root = nas_root()
    extensions = {".flac", ".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".aac", ".wav", ".epub"}
    return [
        path
        for child in (root / "Music", root / "Audiobooks", root / "Books")
        if child.is_dir()
        for path in child.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions
    ]


def _resource_inventory() -> dict[str, list[str]]:
    return {
        "containers": sorted(filter(None, _require(_docker("container", "ls", "-a", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Names}}"), "container inventory").splitlines())),
        "networks": sorted(filter(None, _require(_docker("network", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"), "network inventory").splitlines())),
        "volumes": sorted(filter(None, _require(_docker("volume", "ls", "--filter", f"name={RESOURCE_PREFIX}", "--format", "{{.Name}}"), "volume inventory").splitlines())),
    }


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def preflight() -> dict[str, Any]:
    blockers: list[str] = []
    try:
        root = nas_root()
        source = copied_source()
        classification = source_classification()
    except MediaLatencyBlocked as exc:
        return {"gate": "BLOCKED", "blockers": [str(exc)]}
    head = _require(_run(["git", "rev-parse", "HEAD"]), "Git HEAD")
    if _run(["git", "merge-base", "--is-ancestor", STARTING_COMMIT, "HEAD"]).returncode != 0:
        blockers.append("HEAD does not descend from the required PROD6C.2 starting commit")
    source_files = _source_files() if source.is_dir() else []
    final_files = _final_media() if root.is_dir() else []
    source_audio = [p for p in source_files if p.suffix.lower() in {".flac", ".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".aac", ".wav"}]
    if not source.is_dir() or not source_audio:
        blockers.append("real copied-media source is absent")
    if not any(p.suffix.lower() == ".m4b" for p in source_audio):
        blockers.append("copied source has no M4B")
    if len([p for p in source_audio if "Music" in p.parts]) < 3:
        blockers.append("copied source has fewer than three music files")
    if not any(p.suffix.lower() == ".m4b" and "Audiobooks" in p.parts for p in final_files):
        blockers.append("AA-managed final library has no M4B")
    if len([p for p in final_files if "Music" in p.parts and p.suffix.lower() != ".epub"]) < 3:
        blockers.append("AA-managed final library has fewer than three music files")
    docker = docker_context_status()
    if not (docker.get("available") and docker.get("local") and docker.get("linux")):
        blockers.append("local Docker Linux engine is required")
    active = container_status() if docker.get("available") else {}
    if not all(active.get(key) for key in ("exists", "running", "healthy", "loopback_binding", "named_volume")):
        blockers.append("protected local PostgreSQL identity/health is invalid")
    if CONTAINER_NAME.startswith(RESOURCE_PREFIX) or VOLUME_NAME.startswith(RESOURCE_PREFIX):
        blockers.append("task resource prefix overlaps protected PostgreSQL")
    quiescence = _process_quiescence()
    if not quiescence.get("inspectable") or quiescence.get("writer_detected"):
        blockers.append("protected BM Radio writer quiescence is not proven")
    protected = _protected_state()
    resources = _resource_inventory()
    if any(resources.values()) and not state_path().is_file():
        blockers.append("unowned stale PROD6C.2 resources exist")
    if _docker("image", "inspect", POSTGRES_IMAGE).returncode != 0:
        blockers.append("local postgres:16 image is unavailable")
    return {
        "gate": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "source_commit": head,
        "classification": classification,
        "copied_source_files": len(source_files),
        "final_media_files": len(final_files),
        "docker": {"context": docker.get("context"), "local": docker.get("local"), "linux": docker.get("linux")},
        "protected_sha256": _canonical_sha(protected),
        "task_resources": resources,
    }


def _http_json(port: int, path: str, *, method: str = "GET") -> Any:
    connection = HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        connection.request(method, path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise MediaLatencyBlocked(f"{method} {path} returned {response.status}: {body[:300]!r}")
        return json.loads(body.decode()) if body else None
    finally:
        connection.close()


def _post_json(port: int, path: str) -> Any:
    connection = HTTPConnection("127.0.0.1", port, timeout=300)
    try:
        connection.request("POST", path, body=b"{}", headers={"Accept": "application/json", "Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise MediaLatencyBlocked(f"POST {path} returned {response.status}: {body[:300]!r}")
        return json.loads(body.decode()) if body else None
    finally:
        connection.close()


def _wait_origin(port: int, timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _http_json(port, "/api/health").get("database_ready") is True:
                return
        except (OSError, MediaLatencyBlocked, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise MediaLatencyBlocked("production stack did not become healthy")


def _remove_resources(state: dict[str, Any]) -> None:
    for name in reversed(state.get("containers", [])):
        if str(name).startswith(RESOURCE_PREFIX):
            _docker("container", "rm", "--force", str(name), timeout=180)
    network = str(state.get("network") or "")
    volume = str(state.get("volume") or "")
    if network.startswith(RESOURCE_PREFIX):
        _docker("network", "rm", network, timeout=120)
    if volume.startswith(RESOURCE_PREFIX):
        _docker("volume", "rm", volume, timeout=120)


def _load_state() -> dict[str, Any]:
    if not state_path().is_file():
        raise MediaLatencyBlocked("no retained PROD6C.2 stack exists")
    return json.loads(state_path().read_text(encoding="utf-8"))


def _teardown_retained_stack() -> None:
    if not state_path().is_file():
        return
    state = _load_state()
    _assert_equality(state)
    _remove_resources(state)
    shutil.rmtree(runtime_dir(), ignore_errors=True)
    state_path().unlink(missing_ok=True)


def _start_stack(phase: str) -> dict[str, Any]:
    gate = preflight()
    if gate["gate"] != "PASS":
        raise MediaLatencyBlocked("preflight blocked: " + "; ".join(gate["blockers"]))
    root = nas_root()
    source = copied_source()
    source_before = _snapshot(source, _source_files(), "PROD6C_COPIED_MEDIA_SOURCE")
    final_before = _snapshot(root, _final_media(), "NAS_LOCAL_ROOT")
    protected_before = _protected_state()
    run_id = secrets.token_hex(5)
    network = f"{RESOURCE_PREFIX}{run_id}"
    db_name = f"{RESOURCE_PREFIX}db-{run_id}"
    api_name = f"{RESOURCE_PREFIX}api-{run_id}"
    web_name = f"{RESOURCE_PREFIX}web-{run_id}"
    volume = f"{RESOURCE_PREFIX}db-data-{run_id}"
    role = f"bm_radio_6c2_{run_id}"
    password = secrets.token_urlsafe(32)
    database = "bm_radio"
    db_url = URL.create("postgresql+psycopg", username=role, password=password, host="postgres", port=5432, database=database).render_as_string(hide_password=False)
    runtime_dir().mkdir(parents=True, exist_ok=False)
    (root / "cache" / "artwork").mkdir(parents=True, exist_ok=True)
    db_env = runtime_dir() / "postgres.env"
    api_env = runtime_dir() / "backend.env"
    _write_env(db_env, {"POSTGRES_DB": database, "POSTGRES_USER": role, "POSTGRES_PASSWORD": password})
    environment = prior.prior.backend_live._base_environment(db_url)
    environment["BM_RADIO_CORS_ORIGINS"] = "http://127.0.0.1:8080"
    _write_env(api_env, environment)
    state: dict[str, Any] = {
        "phase": phase,
        "containers": [db_name, api_name, web_name],
        "network": network,
        "volume": volume,
        "source_before": source_before,
        "final_before": final_before,
        "protected_before_sha256": _canonical_sha(protected_before),
    }
    try:
        _require(_docker("build", "--platform", "linux/amd64", "--tag", BACKEND_IMAGE, "--file", str(BACKEND / "Dockerfile"), str(BACKEND), timeout=1800), "PROD6C.2 backend image build")
        _require(_docker("build", "--platform", "linux/amd64", "--build-arg", "VITE_API_BASE_URL=/api", "--tag", FRONTEND_IMAGE, "--file", str(FRONTEND / "Dockerfile"), str(FRONTEND), timeout=1800), "PROD6C.2 frontend image build")
        _require(_docker("network", "create", "--driver", "bridge", network), "private network creation")
        _require(_docker("volume", "create", volume), "disposable PostgreSQL volume creation")
        _require(_docker(
            "run", "--detach", "--name", db_name, "--network", network, "--network-alias", "postgres", "--env-file", str(db_env),
            "--mount", f"type=volume,source={volume},target=/var/lib/postgresql/data",
            "--health-cmd", "pg_isready --username=$POSTGRES_USER --dbname=$POSTGRES_DB", "--health-interval", "5s", "--health-timeout", "5s", "--health-retries", "24",
            "--security-opt", "no-new-privileges:true", POSTGRES_IMAGE, timeout=300,
        ), "disposable PostgreSQL creation")
        _wait_postgres(db_name, role, database)
        prior._migrate(network, api_env)
        _require(_docker(
            "run", "--detach", "--name", api_name, "--network", network, "--network-alias", "backend", "--env-file", str(api_env),
            "--read-only", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--publish", "127.0.0.1::8094",
            "--mount", f"type=bind,source={root / 'cache'},target=/app-cache",
            "--mount", f"type=bind,source={root / 'Music'},target=/media/Music,readonly",
            "--mount", f"type=bind,source={root / 'Audiobooks' / 'Library'},target=/media/Audiobooks/Library,readonly",
            "--mount", f"type=bind,source={root / 'Books'},target=/media/Books,readonly",
            BACKEND_IMAGE, timeout=300,
        ), "private loopback-only backend creation")
        _wait_health(api_name)
        _require(_docker(
            "run", "--detach", "--name", web_name, "--network", network, "--network-alias", "frontend",
            "--read-only", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "--publish", "127.0.0.1::8080", FRONTEND_IMAGE, timeout=300,
        ), "loopback frontend creation")
        _wait_health(web_name)
        api_port = _dynamic_port(api_name, "8094/tcp")
        web_port = _dynamic_port(web_name, "8080/tcp")
        _wait_origin(web_port)
        music_scan = _post_json(web_port, "/api/library/scan/music")
        audiobook_scan = _post_json(web_port, "/api/audiobooks/scan")
        tracks = _http_json(web_port, "/api/library/tracks?limit=200")
        books = _http_json(web_port, "/api/audiobooks/")
        if len(tracks) < 3 or not books:
            raise MediaLatencyBlocked("real copied media did not scan into the disposable database")
        book = _http_json(web_port, f"/api/audiobooks/{books[0]['id']}")
        if not book.get("chapters"):
            raise MediaLatencyBlocked("real copied M4B has no chapter stream")
        state.update({
            "api_port": api_port,
            "web_port": web_port,
            "tracks": tracks,
            "audiobook": book,
            "scan": {"music": music_scan, "audiobook": audiobook_scan},
        })
        state_path().write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        return state
    except Exception:
        _remove_resources(state)
        shutil.rmtree(runtime_dir(), ignore_errors=True)
        raise


def _timed_range(port: int, path: str, start: int, end: int) -> dict[str, Any]:
    connection = HTTPConnection("127.0.0.1", port, timeout=60)
    started = time.perf_counter()
    try:
        connection.request("GET", path, headers={"Range": f"bytes={start}-{end}", "Accept": "audio/*"})
        response = connection.getresponse()
        headers_at = time.perf_counter()
        first = response.read(1)
        first_at = time.perf_counter()
        rest = response.read()
        ended_at = time.perf_counter()
        headers = {key.lower(): value for key, value in response.getheaders()}
        if response.status != 206 or len(first) + len(rest) != end - start + 1:
            raise MediaLatencyBlocked(f"range {start}-{end} returned status={response.status} bytes={len(first) + len(rest)}")
        return {
            "status": response.status,
            "content_range": headers.get("content-range"),
            "content_length": headers.get("content-length"),
            "accept_ranges": headers.get("accept-ranges"),
            "content_type": headers.get("content-type"),
            "content_disposition": headers.get("content-disposition"),
            "response_header_ms": round((headers_at - started) * 1000, 3),
            "first_byte_ms": round((first_at - started) * 1000, 3),
            "total_range_ms": round((ended_at - started) * 1000, 3),
            "bytes": len(first) + len(rest),
        }
    finally:
        connection.close()


def _total_size(port: int, path: str) -> int:
    probe = _timed_range(port, path, 0, 0)
    content_range = str(probe["content_range"] or "")
    if "/" not in content_range:
        raise MediaLatencyBlocked("M4B range response omitted total size")
    return int(content_range.rsplit("/", 1)[1])


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 3),
        "median": round((ordered[(len(ordered) - 1) // 2] + ordered[len(ordered) // 2]) / 2, 3),
        "p95": round(ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)], 3),
        "max": round(ordered[-1], 3),
    }


def _mp4_layout(path: Path) -> dict[str, Any]:
    atoms: list[dict[str, Any]] = []
    size = path.stat().st_size
    with path.open("rb") as stream:
        offset = 0
        while offset + 8 <= size:
            stream.seek(offset)
            header = stream.read(16)
            atom_size = struct.unpack(">I", header[:4])[0]
            atom_type = header[4:8].decode("latin-1")
            header_size = 8
            if atom_size == 1:
                atom_size = struct.unpack(">Q", header[8:16])[0]
                header_size = 16
            elif atom_size == 0:
                atom_size = size - offset
            if atom_size < header_size or offset + atom_size > size:
                atoms.append({"type": atom_type, "offset": offset, "size": atom_size, "valid": False})
                break
            if atom_type in {"ftyp", "moov", "mdat"}:
                atoms.append({"type": atom_type, "offset": offset, "size": atom_size, "valid": True})
            offset += atom_size
    positions = {atom["type"]: atom["offset"] for atom in atoms if atom.get("valid")}
    return {
        "file": "$NAS_LOCAL_ROOT/Audiobooks/<copied-real-media>.m4b",
        "size": size,
        "atoms": atoms,
        "order": [name for name, _offset in sorted(positions.items(), key=lambda item: item[1])],
        "moov_before_mdat": positions.get("moov", size + 1) < positions.get("mdat", -1),
    }


def _pool_proof(port: int, path: str, count: int = 18) -> dict[str, Any]:
    held: list[tuple[HTTPConnection, Any]] = []
    try:
        for _ in range(count):
            connection = HTTPConnection("127.0.0.1", port, timeout=30)
            connection.request("GET", path, headers={"Range": "bytes=0-", "Accept": "audio/*"})
            response = connection.getresponse()
            if response.status != 206:
                raise MediaLatencyBlocked(f"held stream returned {response.status}")
            held.append((connection, response))
        summary = _http_json(port, "/api/library/summary")
        if int(summary.get("tracks", 0)) < 1:
            raise MediaLatencyBlocked("library API failed during held-stream proof")
        return {"result": "PASS", "concurrent_unconsumed_range_streams": count, "database_pool_exhausted": False}
    finally:
        for connection, response in held:
            response.close()
            connection.close()


class _CDP:
    def __init__(self, websocket_url: str):
        parsed = urlparse(websocket_url)
        self.sock = socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        request = (
            f"GET {target} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port}\r\n"
            f"Origin: http://127.0.0.1:{parsed.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise MediaLatencyBlocked(f"Chrome DevTools websocket upgrade failed: {response[:1000].decode('latin-1', errors='replace')}")
        self.next_id = 0

    def close(self) -> None:
        self.sock.close()

    def _send(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        mask = os.urandom(4)
        length = len(data)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))
        header.extend(mask)
        header.extend(bytes(byte ^ mask[index % 4] for index, byte in enumerate(data)))
        self.sock.sendall(header)

    def _recv_exact(self, count: int) -> bytes:
        result = b""
        while len(result) < count:
            chunk = self.sock.recv(count - len(result))
            if not chunk:
                raise MediaLatencyBlocked("Chrome DevTools websocket closed")
            result += chunk
        return result

    def _recv(self) -> dict[str, Any]:
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        if second & 0x80:
            mask = self._recv_exact(4)
        else:
            mask = None
        data = self._recv_exact(length)
        if mask:
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        if opcode == 0x9:
            return self._recv()
        return json.loads(data.decode())

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.next_id += 1
        call_id = self.next_id
        self._send({"id": call_id, "method": method, "params": params})
        while True:
            message = self._recv()
            if message.get("id") == call_id:
                if "error" in message:
                    error = message["error"]
                    raise ChromeDevToolsError(error.get("code"), str(error.get("message", "unknown DevTools error")))
                return message.get("result", {})


def _is_pre_measurement_context_race(error: ChromeDevToolsError) -> bool:
    return error.code == -32000 and "execution context was destroyed" in error.message.casefold()


def _evaluate_value(cdp: _CDP, expression: str) -> Any:
    response = cdp.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    if response.get("exceptionDetails"):
        raise MediaLatencyBlocked(f"Chrome readiness JavaScript failed: {response['exceptionDetails']}")
    remote = response.get("result", {})
    if "value" not in remote:
        raise MediaLatencyBlocked(f"Chrome readiness probe returned no value: {remote}")
    return remote["value"]


def _wait_for_browser_ready(cdp: _CDP, expected_url: str, timeout: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    readiness_expression = "({href: location.href, readyState: document.readyState, control: Boolean(window.__BM_RADIO_LATENCY_CONTROL__)})"
    last_probe: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            probe = _evaluate_value(cdp, readiness_expression)
        except ChromeDevToolsError as exc:
            if not _is_pre_measurement_context_race(exc):
                raise
            time.sleep(0.1)
            continue
        if isinstance(probe, dict):
            last_probe = probe
            if probe.get("href") == expected_url and probe.get("readyState") in {"interactive", "complete"} and probe.get("control") is True:
                return probe
        time.sleep(0.1)
    raise MediaLatencyBlocked(f"Chrome acceptance page was not ready within {timeout:.0f}s: {last_probe}")


def _chrome_path() -> Path:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise MediaLatencyBlocked("Chrome or Edge is required for browser-event timing")


def _browser_probe(web_port: int) -> dict[str, Any]:
    profile = Path(tempfile.mkdtemp(prefix="chrome-", dir=runtime_dir()))
    chrome = subprocess.Popen([
        str(_chrome_path()), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        "--autoplay-policy=no-user-gesture-required", "--remote-allow-origins=*", "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cdp: _CDP | None = None
    try:
        active_port = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not active_port.is_file():
            if chrome.poll() is not None:
                raise MediaLatencyBlocked("headless browser exited before DevTools was ready")
            time.sleep(0.1)
        lines = active_port.read_text(encoding="utf-8").splitlines()
        debug_port = int(lines[0])
        target_url = f"http://127.0.0.1:{web_port}/?bm_latency_acceptance=1"
        targets = json.loads(urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=10).read().decode())
        target = next((item for item in targets if item.get("type") == "page" and item.get("url") == "about:blank"), None)
        if not target:
            raise MediaLatencyBlocked("stable about:blank Chrome target is unavailable")
        cdp = _CDP(target["webSocketDebuggerUrl"])
        cdp.call("Page.enable", {})
        cdp.call("Runtime.enable", {})
        navigation = cdp.call("Page.navigate", {"url": target_url})
        if navigation.get("errorText"):
            raise MediaLatencyBlocked(f"Chrome navigation failed: {navigation['errorText']}")
        readiness = _wait_for_browser_ready(cdp, target_url)
        expression = r"""
(async () => {
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const deadline = performance.now() + 30000;
  while (!window.__BM_RADIO_LATENCY_CONTROL__ && performance.now() < deadline) await sleep(100);
  if (!window.__BM_RADIO_LATENCY_CONTROL__) throw new Error('latency acceptance control unavailable');
  const store = window.__BM_RADIO_LATENCY__ ?? (window.__BM_RADIO_LATENCY__ = {loads: []});
  const control = () => window.__BM_RADIO_LATENCY_CONTROL__;
  const waitFor = async (predicate, timeout = 15000) => {
    const until = performance.now() + timeout;
    while (performance.now() < until) {
      if (predicate()) return;
      await sleep(25);
    }
    throw new Error('browser media event timeout');
  };
  const playForLoad = async (loadIndex, timeout = 15000) => {
    await waitFor(() => store.loads[loadIndex]?.events.some(event => event.event === 'playing'), timeout);
    return store.loads[loadIndex];
  };
  const tracks = await (await fetch('/api/library/tracks?limit=200')).json();
  const music = tracks.map(track => ({
    mode: 'music', id: track.id, title: track.title, subtitle: `${track.artist} - ${track.album}`,
    streamUrl: track.stream_url, artist: track.artist, album: track.album, durationSeconds: track.duration_seconds,
  }));
  const musicActions = [];
  let index = store.loads.length;
  control().playQueue(music, 0, {kind: 'album', artist: music[0].artist, album: music[0].album, canContinue: false});
  await playForLoad(index);
  musicActions.push({action: 'cold', loadIndex: index});
  const actions = ['next','next','next','next','next','next','previous','previous','previous','previous'];
  for (const action of actions) {
    index = store.loads.length;
    control()[action]();
    await playForLoad(index);
    musicActions.push({action, loadIndex: index});
  }
  const books = await (await fetch('/api/audiobooks/')).json();
  const book = await (await fetch(`/api/audiobooks/${books[0].id}`)).json();
  const chapter = book.chapters[0];
  const audiobook = {
    mode: 'audiobook', id: chapter.id, title: book.title, subtitle: chapter.title, tertiary: book.author,
    streamUrl: chapter.stream_url, durationSeconds: chapter.duration_seconds, audiobookId: book.id, chapterId: chapter.id,
    startPositionSeconds: 0,
  };
  index = store.loads.length;
  control().playQueue([audiobook], 0, {kind: 'manual', canContinue: false});
  await playForLoad(index, 240000);
  const audiobookLoad = index;
  control().togglePlayPause();
  await waitFor(() => !control().snapshot().isPlaying, 5000);
  await sleep(250);
  const playingBeforeResume = store.loads[audiobookLoad].events.filter(event => event.event === 'playing').length;
  const resumeStarted = performance.now();
  control().togglePlayPause();
  await waitFor(() => store.loads[audiobookLoad].events.filter(event => event.event === 'playing').length > playingBeforeResume, 10000);
  const resumeMs = performance.now() - resumeStarted;
  const seekedBefore = store.loads[audiobookLoad].events.filter(event => event.event === 'seeked').length;
  const seekStarted = performance.now();
  const duration = control().snapshot().duration;
  control().seek(Math.max(1, Math.min(60, duration / 4)));
  await waitFor(() => store.loads[audiobookLoad].events.filter(event => event.event === 'seeked').length > seekedBefore, 10000);
  const seekMs = performance.now() - seekStarted;
  return {loads: store.loads, musicActions, audiobookLoad, resumeMs, seekMs};
})()
"""
        cdp.sock.settimeout(360)
        result = cdp.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True, "timeout": 300000})
        if result.get("exceptionDetails"):
            raise MediaLatencyBlocked(f"browser timing JavaScript failed: {result['exceptionDetails']}")
        remote = result.get("result", {})
        if remote.get("subtype") == "error" or "value" not in remote:
            raise MediaLatencyBlocked(f"browser timing failed: {remote.get('description', remote)}")
        value = remote["value"]
        for load in value["loads"]:
            load.pop("startedAt", None)
        music_ms = []
        for action in value["musicActions"]:
            load = value["loads"][action["loadIndex"]]
            playing = next(event for event in load["events"] if event["event"] == "playing")
            action["playingMs"] = playing["elapsedMs"]
            music_ms.append(float(playing["elapsedMs"]))
        book_load = value["loads"][value["audiobookLoad"]]
        book_playing = next(event for event in book_load["events"] if event["event"] == "playing")
        return {
            "readiness": readiness,
            "music": {
                "actions": value["musicActions"],
                "cold_playing_ms": music_ms[0],
                "transition_stats_ms": _percentiles(music_ms[1:]),
            },
            "audiobook": {
                "initial_playing_ms": book_playing["elapsedMs"],
                "resume_playing_ms": round(float(value["resumeMs"]), 3),
                "seek_complete_ms": round(float(value["seekMs"]), 3),
                "events": book_load["events"],
            },
            "all_loads": value["loads"],
        }
    finally:
        if cdp:
            cdp.close()
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.kill()
        shutil.rmtree(profile, ignore_errors=True)


def _assert_equality(state: dict[str, Any]) -> dict[str, bool]:
    source = copied_source()
    root = nas_root()
    result = {
        "copied_media_hash_size_mtime_equal": _snapshot(source, _source_files(), "PROD6C_COPIED_MEDIA_SOURCE") == state["source_before"],
        "final_media_hash_size_mtime_equal": _snapshot(root, _final_media(), "NAS_LOCAL_ROOT") == state["final_before"],
        "protected_state_equal": _canonical_sha(_protected_state()) == state["protected_before_sha256"],
    }
    if not all(result.values()):
        raise MediaLatencyBlocked(f"protected/copied media equality failed: {result}")
    return result


def probe_http() -> dict[str, Any]:
    evidence_dir().mkdir(parents=True, exist_ok=True)
    phase = "baseline" if not (evidence_dir() / "baseline.json").is_file() else "post_fix"
    _teardown_retained_stack()
    state = _start_stack(phase)
    web_port = int(state["web_port"])
    api_port = int(state["api_port"])
    tracks = state["tracks"]
    chapter = state["audiobook"]["chapters"][0]
    music: dict[str, list[dict[str, Any]]] = {"backend_direct": [], "frontend_origin": []}
    for index in range(MUSIC_START_COUNT):
        path = tracks[index % len(tracks)]["stream_url"]
        for name, port in (("backend_direct", api_port), ("frontend_origin", web_port)):
            music[name].append(_timed_range(port, path, 0, RANGE_SIZE - 1))
    total = _total_size(web_port, chapter["stream_url"])
    ranges = {
        "first": (0, min(RANGE_SIZE, total) - 1),
        "middle": (max(0, total // 2 - RANGE_SIZE // 2), min(total - 1, total // 2 + RANGE_SIZE // 2 - 1)),
        "final": (max(0, total - RANGE_SIZE), total - 1),
    }
    audiobook: dict[str, dict[str, dict[str, Any]]] = {"backend_direct": {}, "frontend_origin": {}}
    for range_name, (start, end) in ranges.items():
        audiobook["backend_direct"][range_name] = _timed_range(api_port, chapter["stream_url"], start, end)
        audiobook["frontend_origin"][range_name] = _timed_range(web_port, chapter["stream_url"], start, end)
    m4b = next(path for path in _final_media() if path.suffix.lower() == ".m4b")
    partial = {
        "status": "PARTIAL; BROWSER MEASUREMENT PENDING; NOT A PASS",
        "partial": True,
        "phase": phase,
        "classification": source_classification(),
        "music_http": music,
        "music_http_first_byte_stats_ms": {
            name: _percentiles([float(row["first_byte_ms"]) for row in rows]) for name, rows in music.items()
        },
        "audiobook_http": audiobook,
        "m4b_layout": _mp4_layout(m4b),
        "frontend_url": f"http://127.0.0.1:{web_port}/?bm_latency_acceptance=1",
        "backend_direct_loopback_port": api_port,
    }
    partial_path = evidence_dir() / f"{phase}.partial.json"
    partial_path.write_text(json.dumps(partial, indent=2, sort_keys=True), encoding="utf-8")
    result = {
        **{key: value for key, value in partial.items() if key not in {"status", "partial"}},
        "browser": _browser_probe(web_port),
        "database_pool": _pool_proof(web_port, chapter["stream_url"]),
        "equality": _assert_equality(state),
    }
    (evidence_dir() / f"{phase}.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def manual_url() -> dict[str, Any]:
    state = _load_state()
    web_port = _dynamic_port(next(name for name in state["containers"] if str(name).startswith(f"{RESOURCE_PREFIX}web-")), "8080/tcp")
    _wait_origin(web_port, timeout=30)
    result = {
        "frontend_url": f"http://127.0.0.1:{web_port}/?bm_latency_acceptance=1",
        "checks": [
            "music cold start is prompt",
            "Next, Previous, and natural transition are prompt",
            "audiobook first audible sound is prompt",
            "audiobook pause/resume and seek are prompt",
        ],
        "recorded_result": json.loads((evidence_dir() / "human.json").read_text(encoding="utf-8")) if (evidence_dir() / "human.json").is_file() else None,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def record_manual(result: str, note: str) -> dict[str, Any]:
    if not note.strip():
        raise MediaLatencyBlocked("a real operator note is required; automation cannot fabricate PASS")
    recorded = {
        "result": result.upper(),
        "operator_note": note.strip(),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "automated": False,
    }
    evidence_dir().mkdir(parents=True, exist_ok=True)
    (evidence_dir() / "human.json").write_text(json.dumps(recorded, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(recorded, indent=2, sort_keys=True))
    return recorded


def report() -> dict[str, Any]:
    baseline_path = evidence_dir() / "baseline.json"
    latest_path = evidence_dir() / "post_fix.json" if (evidence_dir() / "post_fix.json").is_file() else baseline_path
    if not baseline_path.is_file() or not latest_path.is_file():
        raise MediaLatencyBlocked("baseline/latest latency evidence is incomplete")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    human = json.loads((evidence_dir() / "human.json").read_text(encoding="utf-8")) if (evidence_dir() / "human.json").is_file() else None
    browser = latest["browser"]
    thresholds = {
        "music_cold_le_3000ms": float(browser["music"]["cold_playing_ms"]) <= 3000,
        "music_transitions_p95_le_2000ms": float(browser["music"]["transition_stats_ms"]["p95"]) <= 2000,
        "audiobook_initial_le_5000ms": float(browser["audiobook"]["initial_playing_ms"]) <= 5000,
        "audiobook_resume_le_5000ms": float(browser["audiobook"]["resume_playing_ms"]) <= 5000,
        "audiobook_seek_le_3000ms": float(browser["audiobook"]["seek_complete_ms"]) <= 3000,
    }
    result = {
        "status": "PASS" if all(thresholds.values()) and human and human.get("result") == "PASS" else "HUMAN REVIEW REQUIRED" if all(thresholds.values()) else "FAIL",
        "baseline": baseline,
        "latest": latest,
        "thresholds": thresholds,
        "human_result": human,
    }
    (evidence_dir() / "report.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not all(thresholds.values()):
        raise MediaLatencyBlocked(f"latency thresholds failed: {thresholds}")
    if not human or human.get("result") != "PASS":
        raise MediaLatencyBlocked("automated thresholds pass, but human prompt-playback PASS is not recorded")
    return result


def cleanup() -> dict[str, Any]:
    state = _load_state()
    equality = _assert_equality(state)
    _remove_resources(state)
    shutil.rmtree(runtime_dir(), ignore_errors=True)
    state_path().unlink(missing_ok=True)
    remaining = _resource_inventory()
    result = {"equality": equality, "remaining_resources": remaining, "result": "PASS" if not any(remaining.values()) else "FAIL"}
    (evidence_dir() / "cleanup.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["result"] != "PASS":
        raise MediaLatencyBlocked(f"cleanup left task resources: {remaining}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD6C.2 real-media playback latency acceptance")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--probe-http", action="store_true")
    mode.add_argument("--manual-url", action="store_true")
    mode.add_argument("--record-manual", choices=("PASS", "FAIL"))
    mode.add_argument("--report", action="store_true")
    mode.add_argument("--cleanup", action="store_true")
    parser.add_argument("--operator-note", default="")
    args = parser.parse_args()
    try:
        if args.preflight_only:
            result = preflight()
            print(json.dumps(result, indent=2, sort_keys=True))
            print(f"BM-PROD6C.2 PREFLIGHT: {result['gate']}")
            return 0 if result["gate"] == "PASS" else 2
        if args.probe_http:
            probe_http()
        elif args.manual_url:
            manual_url()
        elif args.record_manual:
            record_manual(args.record_manual, args.operator_note)
        elif args.report:
            report()
        else:
            cleanup()
        return 0
    except (MediaLatencyBlocked, prior.Prod6CAcceptanceBlocked, subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BM-PROD6C.2 status: BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
