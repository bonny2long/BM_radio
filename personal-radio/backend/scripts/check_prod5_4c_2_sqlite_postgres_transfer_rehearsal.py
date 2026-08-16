from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
REPO = PROJECT.parent
REAL_DB = BACKEND / "bm_radio.db"
BACKUP_DIR = BACKEND / ".local_backups"
LOCAL_POSTGRES = BACKEND / ".local_postgres"
TMP_ROOT = BACKEND / "tmp_tests" / "prod5_4c_2"
REPORT_PATH = TMP_ROOT / "transfer_rehearsal_report.json"
IMAGE_TAG = "postgres:16"
EXPECTED_SOURCE_SHA = "e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619"
PERSISTENT_CONTAINER = "bm-radio-postgres-dev"
PERSISTENT_VOLUME = "bm-radio-postgres-dev-data"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database_dialect import engine_options  # noqa: E402
from app.database_readiness import READY, inspect_database_readiness  # noqa: E402
from app.database_transfer import (  # noqa: E402
    TransferBlockedError,
    application_row_counts,
    canonical_row_digests,
    create_verified_sqlite_backup,
    database_inventory,
    inventory_counts,
    inventory_digests,
    sqlite_foreign_key_violations,
    transfer_database,
    verify_database_transfer,
)
from app.migration_contract import APP_TABLES, compare_schema, engine_for_url, read_only_sqlite_url_for_path  # noqa: E402
from app.sqlite_adoption import sha256_file, snapshot_sqlite_database  # noqa: E402


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(BACKEND),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )
    if check and result.returncode != 0:
        raise TransferBlockedError(f"command failed safely: {Path(command[0]).name}")
    return result


def docker(*args: str, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["docker", *args], timeout=timeout, check=check)


def sha256_path(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def safe_sqlite_state(path: Path) -> dict[str, Any]:
    snapshot = snapshot_sqlite_database(path, logical_path="bm_radio.db")
    engine = engine_for_url(read_only_sqlite_url_for_path(path))
    try:
        inventory = database_inventory(engine)
    finally:
        engine.dispose()
    return {
        "sha256": snapshot.sha256,
        "schema_fingerprint": snapshot.schema_fingerprint,
        "integrity": snapshot.integrity_check,
        "quick_check": snapshot.quick_check,
        "revision": snapshot.current_revision,
        "readiness": snapshot.readiness_status,
        "compatibility": snapshot.compatibility,
        "application_tables": len(snapshot.application_tables),
        "application_rows": sum(inventory_counts(inventory).values()),
        "per_table_row_counts": inventory_counts(inventory),
        "per_table_canonical_digests": inventory_digests(inventory),
    }


def docker_exists(kind: str, name: str) -> bool:
    command = "container" if kind == "container" else "volume"
    return docker(command, "inspect", name, timeout=30, check=False).returncode == 0


def protected_state() -> dict[str, Any]:
    return {
        "sqlite": safe_sqlite_state(REAL_DB),
        "backend_env_sha256": sha256_path(BACKEND / ".env"),
        "local_postgres_exists": LOCAL_POSTGRES.exists(),
        "persistent_container_exists": docker_exists("container", PERSISTENT_CONTAINER),
        "persistent_volume_exists": docker_exists("volume", PERSISTENT_VOLUME),
    }


def assert_source_contract(state: dict[str, Any]) -> None:
    source = state["sqlite"]
    required = (
        source["sha256"] == EXPECTED_SOURCE_SHA
        and source["integrity"] == "ok"
        and source["quick_check"] == "ok"
        and source["revision"] == "0001_current_schema_baseline"
        and source["readiness"] == READY
        and source["compatibility"] == "PASS"
        and source["application_tables"] == 21
        and source["application_rows"] == 1257
        and not state["local_postgres_exists"]
        and not state["persistent_container_exists"]
        and not state["persistent_volume_exists"]
    )
    if not required:
        raise TransferBlockedError("live source or persistent-resource entry contract does not match the accepted checkpoint")


def docker_preflight() -> dict[str, str]:
    if shutil.which("docker") is None:
        raise TransferBlockedError("Docker CLI is unavailable")
    context = docker("context", "show", timeout=30).stdout.strip()
    endpoint = docker("context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}", timeout=30).stdout.strip()
    if endpoint.startswith(("tcp://", "ssh://")) or not endpoint.startswith(("npipe://", "unix://")):
        raise TransferBlockedError("Docker context is not local to this workstation")
    version = docker("version", "--format", "{{.Server.Version}}|{{.Server.Os}}|{{.Server.Arch}}", timeout=30).stdout.strip()
    server_version, os_type, architecture = version.split("|", 2)
    if os_type != "linux":
        raise TransferBlockedError("Docker engine is not using Linux containers")
    return {
        "context": context,
        "endpoint_class": "local_named_pipe" if endpoint.startswith("npipe://") else "local_unix_socket",
        "engine_version": server_version,
        "server_os": os_type,
        "server_arch": architecture,
    }


def source_quiescence() -> dict[str, Any]:
    if os.name != "nt":
        result = run(["ps", "-eo", "pid=,comm=,args="], timeout=30)
        lines = result.stdout.splitlines()
        candidates = [{"ProcessId": None, "Name": line, "CommandLine": line} for line in lines]
    else:
        script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -match '^(python|pythonw|node|npm|uvicorn)(\\.exe)?$' } | "
            "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
        )
        result = run(["powershell", "-NoProfile", "-Command", script], timeout=30)
        payload = json.loads(result.stdout) if result.stdout.strip() else []
        candidates = payload if isinstance(payload, list) else [payload]
    blockers = []
    for process in candidates:
        pid = process.get("ProcessId")
        if pid == os.getpid():
            continue
        command = str(process.get("CommandLine") or "").lower().replace("\\", "/")
        name = str(process.get("Name") or "").lower()
        if "check_prod5_4c_2_sqlite_postgres_transfer_rehearsal.py" in command:
            continue
        repo_related = "personal-radio" in command or "bm_radio" in command or "bm-radio" in command
        writer_shape = any(token in command for token in ("uvicorn", "app.main", "npm run dev", "vite"))
        if repo_related and (writer_shape or name.startswith(("python", "node", "npm", "uvicorn"))):
            blockers.append({"pid": pid, "name": name})
    if blockers:
        raise TransferBlockedError("a BM Radio-related process may be writing the live SQLite source")
    return {"candidate_processes_inspected": len(candidates), "bm_radio_writer_detected": False}


def ensure_image() -> dict[str, str]:
    inspected = docker("image", "inspect", IMAGE_TAG, timeout=30, check=False)
    if inspected.returncode != 0:
        docker("pull", IMAGE_TAG, timeout=600)
    data = json.loads(docker("image", "inspect", IMAGE_TAG, timeout=30).stdout)[0]
    image_id = str(data.get("Id") or "")
    digests = [str(item) for item in data.get("RepoDigests") or [] if str(item).startswith("postgres@sha256:")]
    if not image_id.startswith("sha256:") or not digests:
        raise TransferBlockedError("official PostgreSQL image identity could not be established")
    return {"tag": IMAGE_TAG, "image_id": image_id, "digest": digests[0]}


def database_url(user: str, password: str, port: int, database: str) -> str:
    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host="127.0.0.1",
        port=port,
        database=database,
    ).render_as_string(hide_password=False)


def wait_for_postgres(url: str, timeout: int = 90) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        engine = create_engine(url, **engine_options(url))
        try:
            with engine.connect() as connection:
                return str(connection.execute(text("select version()")).scalar_one())
        except Exception:
            time.sleep(1)
        finally:
            engine.dispose()
    raise TransferBlockedError("disposable PostgreSQL did not become reachable")


def published_port(container_name: str) -> int:
    raw = docker("port", container_name, "5432/tcp", timeout=30).stdout.strip()
    if not raw.startswith("127.0.0.1:"):
        raise TransferBlockedError("disposable PostgreSQL is not bound exclusively to loopback")
    return int(raw.rsplit(":", 1)[1])


def port_closed(port: int | None) -> bool:
    if port is None:
        return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def create_databases(admin_url: str, names: list[str]) -> None:
    import psycopg
    from psycopg import sql

    psycopg_url = admin_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        for name in names:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def alembic(url: str, *arguments: str, timeout: int = 180) -> None:
    environment = os.environ.copy()
    environment["BM_RADIO_DB_URL"] = url
    result = run([sys.executable, "-m", "alembic", *arguments], env=environment, timeout=timeout, check=False)
    if result.returncode == 0:
        return
    safe = result.stdout.replace(url, "<redacted-database-url>")
    password = make_url(url).password
    if password:
        safe = safe.replace(password, "<redacted-password>")
    diagnostic = TMP_ROOT / "reports" / "alembic_failure.txt"
    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    diagnostic.write_text(safe.replace(str(Path.home()), "<home>").replace(str(REPO), "<repo>"), encoding="utf-8")
    raise TransferBlockedError("Alembic command failed; sanitized diagnostic recorded")


def target_schema(url: str) -> dict[str, Any]:
    engine = create_engine(url, **engine_options(url))
    try:
        readiness = inspect_database_readiness(engine)
        issues = compare_schema(engine)
        counts = application_row_counts(engine)
        return {
            "revision": readiness.current_revision,
            "head_revision": readiness.head_revision,
            "readiness": readiness.status,
            "compatibility": "PASS" if not issues else "FAIL",
            "application_tables": len(counts),
            "application_rows": sum(counts.values()),
        }
    finally:
        engine.dispose()


def child_environment(url: str, backup: Path, roots: dict[str, Path]) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "BM_RADIO_DB_URL": url,
            "BM_RADIO_TRANSFER_SOURCE_BACKUP": str(backup),
            "APP_ENV": "test",
            "BM_RADIO_MUSIC_ROOT": str(roots["music"]),
            "BM_RADIO_AUDIOBOOK_ROOT": str(roots["audiobooks"]),
            "BM_RADIO_BOOK_ROOT": str(roots["books"]),
            "BM_RADIO_CACHE_ROOT": str(roots["cache"]),
            "BM_RADIO_ARTWORK_CACHE_ROOT": str(roots["artwork"]),
            "BM_RADIO_API_HOST": "127.0.0.1",
            "BM_RADIO_API_DOCS_ENABLED": "false",
            "BM_RADIO_CORS_ORIGINS": '["http://127.0.0.1:5174"]',
            "PUBLIC_ACCESS": "false",
            "ALLOW_FILE_MUTATION": "false",
            "ALLOW_DELETE": "false",
            "ALLOW_TAG_WRITES": "false",
            "SCAN_INGEST_FOLDERS": "false",
        }
    )
    return environment


def startup_child() -> int:
    from fastapi.testclient import TestClient

    from app import db
    from app.database_transfer import application_row_counts, canonical_row_digests
    from app.main import app

    before_counts = application_row_counts(db.engine)
    before_rows = {table: canonical_row_digests(db.engine, table) for table in APP_TABLES}
    with TestClient(app) as client:
        endpoints = {
            "health": client.get("/api/health"),
            "library_summary": client.get("/api/library/summary"),
            "artists": client.get("/api/library/artists"),
            "albums": client.get("/api/library/albums"),
            "search": client.get("/api/search", params={"q": "transfer-canary-no-media-probe"}),
            "playlists": client.get("/api/playlists"),
            "stations": client.get("/api/stations"),
            "audiobooks": client.get("/api/audiobooks"),
        }
        assert all(response.status_code == 200 for response in endpoints.values())
        with db.engine.connect() as connection:
            recording_id = connection.execute(text("select min(id) from music_recordings")).scalar_one()
            audiobook_id = connection.execute(text("select min(id) from audiobooks")).scalar_one()
        data_dependent = {"recording_control": "not_applicable", "audiobook_progress": "not_applicable"}
        if recording_id is not None:
            assert client.get(f"/api/music/recordings/{recording_id}/control").status_code == 200
            data_dependent["recording_control"] = "PASS"
        if audiobook_id is not None:
            response = client.get(f"/api/audiobooks/{audiobook_id}/progress")
            assert response.status_code in {200, 404}
            data_dependent["audiobook_progress"] = "PASS"
    first_counts = application_row_counts(db.engine)
    with TestClient(app) as second_client:
        assert second_client.get("/api/health").status_code == 200
    second_counts = application_row_counts(db.engine)
    after_rows = {table: canonical_row_digests(db.engine, table) for table in APP_TABLES}
    imported_preserved = all(
        all(after_rows[table].get(key) == digest for key, digest in before_rows[table].items())
        for table in APP_TABLES
    )
    assert imported_preserved and first_counts == second_counts
    print(
        json.dumps(
            {
                "first_startup": "PASS",
                "second_startup": "PASS",
                "seed_idempotence": "PASS",
                "existing_imported_data_preserved": True,
                "row_delta_by_table": {table: first_counts[table] - before_counts[table] for table in APP_TABLES},
                "read_api_canary": {name: "PASS" for name in endpoints},
                "data_dependent_canary": data_dependent,
                "scanner_started": False,
                "media_streamed": False,
                "media_metadata_probed": False,
            },
            sort_keys=True,
        )
    )
    db.engine.dispose()
    return 0


def run_startup_child(url: str, backup: Path, roots: dict[str, Path]) -> dict[str, Any]:
    result = run(
        [sys.executable, str(Path(__file__).resolve()), "--startup-child"],
        env=child_environment(url, backup, roots),
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        safe = result.stdout.replace(url, "<redacted-database-url>")
        password = make_url(url).password
        if password:
            safe = safe.replace(password, "<redacted-password>")
        diagnostic = TMP_ROOT / "reports" / "startup_child_failure.txt"
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        diagnostic.write_text(safe.replace(str(Path.home()), "<home>").replace(str(REPO), "<repo>"), encoding="utf-8")
        raise TransferBlockedError("imported startup canary failed; sanitized diagnostic recorded")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


def credential_absent(root: Path, secret: str) -> bool:
    for path in root.rglob("*"):
        if path.is_file() and secret in path.read_text(encoding="utf-8", errors="ignore"):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.4C.2 populated SQLite transfer rehearsal")
    parser.add_argument("--startup-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.startup_child:
        return startup_child()

    if TMP_ROOT.resolve().parent != (BACKEND / "tmp_tests").resolve():
        raise TransferBlockedError("unsafe rehearsal temporary root")
    shutil.rmtree(TMP_ROOT, ignore_errors=True)
    (TMP_ROOT / "reports").mkdir(parents=True, exist_ok=True)
    roots = {name: TMP_ROOT / "synthetic_roots" / name for name in ("music", "audiobooks", "books", "cache", "artwork")}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)

    token = secrets.token_hex(6)
    password = secrets.token_urlsafe(40)
    user = f"bm_transfer_{token}"
    container = f"bm-prod5-4c2-{token}"
    databases = {kind: f"bm_radio_{kind}_{token}" for kind in ("transfer", "startup_canary")}
    env_file = TMP_ROOT / f"postgres-{token}.env"
    port: int | None = None
    container_started = False
    failure: Exception | None = None
    stage = "entry"
    report: dict[str, Any] = {"run_id": secrets.token_hex(8), "started_utc": utc_now(), "status": "FAIL"}
    live_before: dict[str, Any] | None = None
    backup: Path | None = None

    try:
        stage = "docker_preflight"
        docker_status = docker_preflight()
        stage = "source_quiescence"
        quiescence = source_quiescence()
        stage = "protected_source_before"
        live_before = protected_state()
        assert_source_contract(live_before)
        if sqlite_foreign_key_violations(REAL_DB):
            raise TransferBlockedError("live SQLite source contains foreign-key violations")
        stage = "verified_backup"
        backup, manifest_path, backup_manifest = create_verified_sqlite_backup(REAL_DB, BACKUP_DIR)
        stage = "postgres_image"
        image = ensure_image()

        env_file.write_text(f"POSTGRES_USER={user}\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=postgres\n", encoding="utf-8")
        try:
            os.chmod(env_file, 0o600)
        except OSError:
            pass
        stage = "container_start"
        docker(
            "run", "-d", "--name", container,
            "--env-file", str(env_file),
            "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=768m",
            "-p", "127.0.0.1::5432",
            IMAGE_TAG,
            timeout=180,
        )
        container_started = True
        port = published_port(container)
        admin_url = database_url(user, password, port, "postgres")
        server_version = wait_for_postgres(admin_url)
        create_databases(admin_url, list(databases.values()))
        urls = {name: database_url(user, password, port, database) for name, database in databases.items()}

        source_engine = engine_for_url(read_only_sqlite_url_for_path(backup))
        try:
            transfers: dict[str, Any] = {}
            verifications: dict[str, Any] = {}
            for name in ("transfer", "startup_canary"):
                stage = f"{name}_alembic_upgrade"
                alembic(urls[name], "upgrade", "head")
                schema_before = target_schema(urls[name])
                if schema_before["application_rows"] != 0:
                    raise TransferBlockedError("fresh PostgreSQL target is not empty")
                target_engine = create_engine(urls[name], **engine_options(urls[name]))
                try:
                    stage = f"{name}_row_transfer"
                    transfers[name] = transfer_database(source_engine, target_engine).as_dict()
                    stage = f"{name}_verification"
                    verifications[name] = verify_database_transfer(source_engine, target_engine)
                finally:
                    target_engine.dispose()
                alembic(urls[name], "check")
                verifications[name]["alembic_drift_check"] = "PASS"
        finally:
            source_engine.dispose()

        stage = "startup_and_api_canary"
        startup = run_startup_child(urls["startup_canary"], backup, roots)
        stage = "live_source_after"
        live_after = protected_state()
        exact_live_equality = live_before == live_after
        if not exact_live_equality:
            raise TransferBlockedError("live SQLite or protected local state changed during rehearsal")

        report.update(
            {
                "status": "PASS",
                "docker": docker_status,
                "source_quiescence": quiescence,
                "postgresql_image": image,
                "postgresql_server": server_version.split(",", 1)[0],
                "disposable_target": "postgresql+psycopg://<ephemeral>:***@127.0.0.1:<dynamic-port>/<ephemeral>",
                "loopback_binding": "127.0.0.1 dynamic port",
                "source": live_before["sqlite"],
                "source_foreign_key_check": "PASS",
                "backup": {
                    "logical_filename": backup.name,
                    "manifest_filename": manifest_path.name,
                    "verified": True,
                    "integrity": backup_manifest["integrity_check"],
                    "quick_check": backup_manifest["quick_check"],
                    "revision": backup_manifest["revision"],
                    "application_rows": backup_manifest["application_row_count"],
                    "counts_equal": backup_manifest["source_backup_counts_equal"],
                    "digests_equal": backup_manifest["source_backup_digests_equal"],
                },
                "transfer": transfers["transfer"],
                "transfer_verification": verifications["transfer"],
                "startup_import_verification": verifications["startup_canary"],
                "startup_canary": startup,
                "live_source_exact_equality": exact_live_equality,
                "persistent_container_created": False,
                "persistent_volume_created": False,
                "backend_env_modified": False,
                "active_database_switched": False,
                "media_accessed": False,
            }
        )
    except BaseException as exc:
        failure = exc if isinstance(exc, Exception) else RuntimeError(type(exc).__name__)
        report["failed_stage"] = stage
        report["failure_type"] = type(exc).__name__
    finally:
        env_file.unlink(missing_ok=True)
        if container_started:
            docker("rm", "-f", container, timeout=90, check=False)
        cleanup = {
            "container_removed": docker("ps", "-a", "--filter", f"name=^{container}$", "--format", "{{.Names}}", timeout=30, check=False).stdout.strip() == "",
            "volume_removed": True,
            "network_removed": True,
            "port_closed": port_closed(port),
            "credentials_absent": credential_absent(TMP_ROOT, password),
        }
        report["cleanup"] = cleanup
        try:
            live_after_cleanup = protected_state()
            report["live_source_after"] = live_after_cleanup["sqlite"]
            report["protected_state_exact_equality"] = live_before is not None and live_before == live_after_cleanup
        except Exception:
            report["protected_state_exact_equality"] = False
        report["ended_utc"] = utc_now()
        serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if password in serialized or str(Path.home()) in serialized or str(REPO) in serialized:
            failure = failure or TransferBlockedError("privacy-safe report validation failed")
            report = {"status": "FAIL", "failure_type": "PrivacySafetyError", "failed_stage": "report_redaction", "cleanup": cleanup, "ended_utc": utc_now()}
            serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
        REPORT_PATH.write_text(serialized, encoding="utf-8")

    if failure:
        raise TransferBlockedError(f"BM-PROD5.4C.2 rehearsal blocked at {report.get('failed_stage', stage)}") from None
    if not all(report["cleanup"].values()) or not report.get("protected_state_exact_equality"):
        raise TransferBlockedError("rehearsal cleanup or protected-state equality failed")
    print("BM-PROD5.4C.2 PRE-TRANSFER GATE: PASS")
    print("Live SQLite unchanged: YES")
    print("Verified backup: PASS")
    print("Disposable PostgreSQL transfer: PASS")
    print("Canonical row equality: PASS")
    print("Imported startup and read/API canary: PASS")
    print("Disposable resources removed: YES")
    print("Persistent PostgreSQL created: NO")
    print("Persistent volume created: NO")
    print("backend/.env modified: NO")
    print("Active DB switch: NO")
    print("Media accessed: NO")
    print(json.dumps({"report": "tmp_tests/prod5_4c_2/transfer_rehearsal_report.json", "status": "PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
