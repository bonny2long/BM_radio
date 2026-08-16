from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any, Iterator


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database_transfer import verify_database_transfer  # noqa: E402
from app.local_postgres_adoption import (  # noqa: E402
    ADOPT_CONFIRMATION,
    BACKEND_ENV_BEFORE_PATH,
    BACKEND_ENV_PATH,
    EXPECTED_SOURCE_ROWS,
    AdoptionBlockedError,
    active_adoption_preflight,
    adopt_persistent_target,
    database_verification,
    env_target_summary,
    finalize_active_adoption,
    read_state,
    rollback_configuration,
    sha256_path,
    target_url_from_secret_file,
    utc_now,
    validate_rollback_files,
    write_state,
)
from app.migration_contract import engine_for_url, read_only_sqlite_url_for_path  # noqa: E402


REAL_SQLITE = BACKEND / "bm_radio.db"
MEDIA_ROOT_KEYS = (
    "BM_RADIO_MUSIC_ROOT",
    "BM_RADIO_AUDIOBOOK_ROOT",
    "BM_RADIO_BOOK_ROOT",
    "BM_RADIO_CACHE_ROOT",
    "BM_RADIO_ARTWORK_CACHE_ROOT",
)


def _json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _without_database_target(value: bytes) -> bytes:
    lines = value.decode("utf-8").splitlines(keepends=True)
    return b"".join(line.encode("utf-8") for line in lines if not line.lstrip().startswith("BM_RADIO_DB_URL="))


def _database_equality() -> dict[str, Any]:
    source = engine_for_url(read_only_sqlite_url_for_path(REAL_SQLITE))
    target = engine_for_url(target_url_from_secret_file())
    try:
        verified = verify_database_transfer(source, target)
    finally:
        source.dispose()
        target.dispose()
    database = database_verification()
    return {
        "database": database,
        "source_total_rows": verified["source_total_rows"],
        "target_total_rows": verified["target_total_rows"],
        "per_table_row_counts": verified["per_table_row_counts"],
        "per_table_canonical_digests": verified["per_table_canonical_digests"],
        "foreign_key_validation": verified["foreign_key_validation"],
    }


def _zero_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    counts_before = before["per_table_row_counts"]
    counts_after = after["per_table_row_counts"]
    return {name: int(counts_after[name]) - int(counts_before[name]) for name in sorted(counts_before)}


def _require_unchanged(before: dict[str, Any], after: dict[str, Any], *, label: str) -> None:
    valid = (
        after["source_total_rows"] == EXPECTED_SOURCE_ROWS
        and after["target_total_rows"] == EXPECTED_SOURCE_ROWS
        and after["per_table_row_counts"] == before["per_table_row_counts"]
        and after["per_table_canonical_digests"] == before["per_table_canonical_digests"]
        and after["database"]["readiness"] == "ready"
        and after["database"]["compatibility"] == "PASS"
    )
    if not valid:
        raise AdoptionBlockedError(f"{label} changed accepted PostgreSQL data or readiness")


@contextmanager
def _temporary_canary_roots() -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in MEDIA_ROOT_KEYS}
    with tempfile.TemporaryDirectory(prefix="bm-prod5-4c3b-") as temporary:
        root = Path(temporary)
        for index, name in enumerate(MEDIA_ROOT_KEYS):
            directory = root / f"root-{index}"
            directory.mkdir()
            os.environ[name] = str(directory)
        try:
            yield
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _response_pass(client: Any, path: str) -> str:
    response = client.get(path)
    if response.status_code != 200:
        raise AdoptionBlockedError(f"read canary failed for {path}")
    return "PASS"


def _recording_control_canary(client: Any) -> str:
    target = engine_for_url(target_url_from_secret_file())
    try:
        from sqlalchemy import text

        with target.connect() as connection:
            recording_id = connection.execute(text("select min(id) from music_recordings")).scalar()
    finally:
        target.dispose()
    if recording_id is None:
        return "not_applicable"
    return _response_pass(client, f"/api/music/recordings/{int(recording_id)}/control")


def _playlist_presence(name: str) -> tuple[bool, bool]:
    from sqlalchemy import text

    target = engine_for_url(target_url_from_secret_file())
    try:
        with target.connect() as connection:
            in_postgresql = bool(connection.execute(text("select count(*) from playlists where name = :name"), {"name": name}).scalar_one())
    finally:
        target.dispose()
    uri = f"file:{REAL_SQLITE.resolve().as_posix()}?mode=ro"
    sqlite = sqlite3.connect(uri, uri=True)
    try:
        in_sqlite = bool(sqlite.execute("select count(*) from playlists where name = ?", (name,)).fetchone()[0])
    finally:
        sqlite.close()
    return in_postgresql, in_sqlite


def _alembic_check() -> None:
    environment = os.environ.copy()
    environment["BM_RADIO_DB_URL"] = target_url_from_secret_file()
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=str(BACKEND),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        shell=False,
    )
    if result.returncode != 0:
        raise AdoptionBlockedError("Alembic drift check failed after active adoption")


def _run_application_canary() -> dict[str, Any]:
    """Run only in a fresh child interpreter after .env adoption."""
    from fastapi.testclient import TestClient
    from app import db
    from app.config import settings
    from app.main import app

    if (
        settings.BM_RADIO_DB_POLICY_STATUS != "postgresql_supported"
        or db.engine.dialect.name != "postgresql"
        or db.engine.url.drivername != "postgresql+psycopg"
    ):
        raise AdoptionBlockedError("fresh canary process did not load PostgreSQL from adopted .env")
    before = _database_equality()
    startup_results: list[dict[str, Any]] = []
    with TestClient(app) as first_client:
        health = first_client.get("/api/health")
        if health.status_code != 200 or not health.json().get("database_ready"):
            raise AdoptionBlockedError("application startup #1 readiness canary failed")
    after_startup_1 = _database_equality()
    _require_unchanged(before, after_startup_1, label="application startup #1")
    startup_results.append({"result": "PASS", "row_delta": _zero_delta(before, after_startup_1), "rows": EXPECTED_SOURCE_ROWS})

    canary_name = f"BM-PROD5.4C.3B PostgreSQL Write Canary {secrets.token_hex(8)}"
    canary_id: int | None = None
    canary_deleted = False
    with TestClient(app) as second_client:
        try:
            health = second_client.get("/api/health")
            if health.status_code != 200 or not health.json().get("database_ready"):
                raise AdoptionBlockedError("application startup #2 readiness canary failed")
            read_canaries = {
                "health": "PASS",
                "library": _response_pass(second_client, "/api/library/summary"),
                "artists": _response_pass(second_client, "/api/library/artists"),
                "releases": _response_pass(second_client, "/api/library/albums"),
                "search": _response_pass(second_client, "/api/search?q=canary-no-match"),
                "playlists": _response_pass(second_client, "/api/playlists"),
                "stations": _response_pass(second_client, "/api/stations/"),
                "recording_controls": _recording_control_canary(second_client),
                "audiobooks": _response_pass(second_client, "/api/audiobooks/"),
            }
            created = second_client.post("/api/playlists", json={"name": canary_name, "description": "temporary database routing canary"})
            if created.status_code != 200:
                raise AdoptionBlockedError("playlist write-routing canary creation failed")
            canary_id = int(created.json()["id"])
            in_postgresql, in_sqlite = _playlist_presence(canary_name)
            if not in_postgresql or in_sqlite:
                raise AdoptionBlockedError("playlist write did not route exclusively to PostgreSQL")
            deleted = second_client.delete(f"/api/playlists/{canary_id}")
            if deleted.status_code != 200 or not deleted.json().get("deleted"):
                raise AdoptionBlockedError("playlist write-routing canary deletion failed")
            canary_deleted = True
            in_postgresql_after, in_sqlite_after = _playlist_presence(canary_name)
            if in_postgresql_after or in_sqlite_after:
                raise AdoptionBlockedError("playlist write-routing canary cleanup was incomplete")
        finally:
            if canary_id is not None and not canary_deleted:
                cleanup = second_client.delete(f"/api/playlists/{canary_id}")
                canary_deleted = cleanup.status_code == 200 and bool(cleanup.json().get("deleted"))
    after_startup_2 = _database_equality()
    _require_unchanged(before, after_startup_2, label="application startup #2 and write canary")
    startup_results.append({"result": "PASS", "row_delta": _zero_delta(before, after_startup_2), "rows": EXPECTED_SOURCE_ROWS})
    return {
        "application_startup_1": startup_results[0],
        "application_startup_2": startup_results[1],
        "startup_row_delta": startup_results,
        "read_canaries": read_canaries,
        "write_canary": {
            "type": "temporary_playlist",
            "create": "PASS",
            "seen_in_postgresql": True,
            "absent_from_sqlite": True,
            "delete": "PASS",
            "cleanup": "PASS",
        },
    }


def _spawn_application_canary() -> dict[str, Any]:
    environment = os.environ.copy()
    environment.pop("BM_RADIO_DB_URL", None)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--canary-internal"],
        cwd=str(BACKEND),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        shell=False,
    )
    marker = "CANARY_RESULT="
    line = next((item for item in reversed(result.stdout.splitlines()) if item.startswith(marker)), None)
    if result.returncode != 0 or line is None:
        raise AdoptionBlockedError("isolated PostgreSQL application canary failed")
    try:
        payload = json.loads(line[len(marker):])
    except json.JSONDecodeError as exc:
        raise AdoptionBlockedError("isolated PostgreSQL application canary returned invalid evidence") from exc
    if not isinstance(payload, dict):
        raise AdoptionBlockedError("isolated PostgreSQL application canary returned invalid evidence")
    return payload


def preflight_only() -> int:
    result = active_adoption_preflight()
    print(f"BM-PROD5.4C.3B PRE-ADOPTION GATE: {result['gate']}")
    print("Explicit operator approval received: NO")
    for blocker in result["blockers"]:
        print(f"reason: {blocker}")
    _json(result)
    print("backend/.env modified: NO")
    print("Application startup performed: NO")
    print("Application write canary performed: NO")
    print("SQLite mutated: NO")
    print("Media accessed: NO")
    return 0 if result["gate"] == "PASS" else 2


def approved_adoption(token: str) -> int:
    if token != ADOPT_CONFIRMATION:
        raise AdoptionBlockedError("exact active-adoption confirmation token is required")
    gate = active_adoption_preflight()
    if gate["gate"] != "PASS":
        raise AdoptionBlockedError("active adoption preflight blocked: " + "; ".join(gate["blockers"]))
    original_env = BACKEND_ENV_PATH.read_bytes()
    original_env_sha = hashlib.sha256(original_env).hexdigest()
    sqlite_before_sha = sha256_path(REAL_SQLITE)
    transfer_sha = read_state().get("transfer_verification_sha256")
    before = _database_equality()
    adopted = False
    try:
        with _temporary_canary_roots():
            adoption = adopt_persistent_target(token)
            adopted = True
            adopted_env = BACKEND_ENV_PATH.read_bytes()
            adopted_env_sha = hashlib.sha256(adopted_env).hexdigest()
            if _without_database_target(original_env) != _without_database_target(adopted_env):
                raise AdoptionBlockedError("active adoption changed settings other than BM_RADIO_DB_URL")
            target = env_target_summary()
            if target.get("dialect") != "postgresql" or target.get("driver") != "psycopg":
                raise AdoptionBlockedError("adopted .env did not resolve PostgreSQL through Psycopg")
            canary = _spawn_application_canary()
            after_startup_2 = _database_equality()
            _require_unchanged(before, after_startup_2, label="isolated application startup and write canaries")
            if sha256_path(REAL_SQLITE) != sqlite_before_sha:
                raise AdoptionBlockedError("SQLite changed during active PostgreSQL adoption proof")
            _alembic_check()
            state = read_state()
            validate_rollback_files(state)
            if sha256_path(BACKEND_ENV_BEFORE_PATH) != state.get("backend_env_before_sha256"):
                raise AdoptionBlockedError("rollback snapshot hash verification failed")
            artifact = {
                "version": 1,
                "created_utc": utc_now(),
                "phase": "BM-PROD5.4C.3B",
                "source_commit": gate["source_commit"],
                "transfer_verification_sha256": transfer_sha,
                "backend_env_before_sha256": original_env_sha,
                "backend_env_adopted_sha256": adopted_env_sha,
                "database_target_safe_display": adoption["safe_display"],
                "database_dialect": adoption["dialect"],
                "database_driver": adoption["driver"],
                "database_policy": adoption["policy"],
                "target_revision": after_startup_2["database"]["revision"],
                "target_rows_before_startup": before["target_total_rows"],
                "application_startup_1": canary["application_startup_1"],
                "application_startup_2": canary["application_startup_2"],
                "startup_row_delta": canary["startup_row_delta"],
                "read_canaries": canary["read_canaries"],
                "write_canary": canary["write_canary"],
                "target_rows_after_canary_cleanup": after_startup_2["target_total_rows"],
                "target_data_restored_after_canary": True,
                "sqlite_unchanged": True,
                "rollback_snapshot_verified": True,
                "media_access": {"scanner": False, "streaming": False, "metadata_probe": False, "file_open": False},
                "alembic_drift": "PASS",
            }
            finalized = finalize_active_adoption(artifact)
            print("ACTIVE-POSTGRES-ADOPTION: PASS")
            _json({**finalized, "target_rows": EXPECTED_SOURCE_ROWS, "sqlite_unchanged": True, "backend_env_target": target})
            return 0
    except Exception:
        if adopted:
            rollback_configuration()
            failed = read_state()
            failed.update({"phase": "BM-PROD5.4C.3B-failed-rolled-back", "application_adopted": False, "active_database": "sqlite", "failed_utc": utc_now()})
            write_state(failed)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.4C.3B guarded active PostgreSQL adoption")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--approve", metavar="TOKEN")
    mode.add_argument("--canary-internal", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.preflight_only:
            return preflight_only()
        if args.canary_internal:
            print("CANARY_RESULT=" + json.dumps(_run_application_canary(), sort_keys=True))
            return 0
        return approved_adoption(str(args.approve))
    except AdoptionBlockedError as exc:
        print("ACTIVE-POSTGRES-ADOPTION: BLOCKED")
        print(f"reason: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
