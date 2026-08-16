from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from typing import Any


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.postgres_backup_restore import (  # noqa: E402
    BACKUP_VERIFICATION_PATH,
    EXPECTED_SOURCE_ROWS,
    MEDIA_ROOT_KEYS,
    BackupRestoreBlockedError,
    _alembic_check,
    _database_snapshot,
    active_preflight,
    cleanup_disposable_restore,
    create_disposable_restore,
    create_logical_backup,
    protected_snapshot,
    write_backup_verification,
)
from app.local_postgres_adoption import target_url_from_secret_file  # noqa: E402


CANARY_MARKER = "BM_PROD5_5A_CANARY_RESULT="


def _json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _response_pass(client: Any, path: str) -> str:
    response = client.get(path)
    if response.status_code != 200:
        raise BackupRestoreBlockedError(f"restored application read canary failed for {path}")
    return "PASS"


def _recording_control_canary(client: Any) -> str:
    from sqlalchemy import text
    from app import db

    with db.engine.connect() as connection:
        recording_id = connection.execute(text("select min(id) from music_recordings")).scalar_one_or_none()
    if recording_id is None:
        return "not_applicable"
    return _response_pass(client, f"/api/music/recordings/{int(recording_id)}/control")


def _require_same_database(before: dict[str, Any], after: dict[str, Any], label: str) -> None:
    if (
        after["application_total_rows"] != EXPECTED_SOURCE_ROWS
        or before["per_table_row_counts"] != after["per_table_row_counts"]
        or before["per_table_canonical_digests"] != after["per_table_canonical_digests"]
        or after["readiness"] != "ready"
        or after["compatibility"] != "PASS"
    ):
        raise BackupRestoreBlockedError(f"{label} changed restored database rows, digests, or readiness")


def _row_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    return {
        name: int(after["per_table_row_counts"][name]) - int(before["per_table_row_counts"][name])
        for name in sorted(before["per_table_row_counts"])
    }


def _run_application_canary() -> dict[str, Any]:
    """Run in a fresh bounded child interpreter using only process-local overrides."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from app import db
    from app.config import settings
    from app.main import app

    if (
        db.engine.dialect.name != "postgresql"
        or db.engine.url.drivername != "postgresql+psycopg"
        or settings.BM_RADIO_DB_POLICY_STATUS != "postgresql_supported"
    ):
        raise BackupRestoreBlockedError("fresh child did not use restored PostgreSQL through Psycopg")

    before = _database_snapshot(db.engine)
    with TestClient(app) as first_client:
        health = first_client.get("/api/health")
        if health.status_code != 200 or not health.json().get("database_ready"):
            raise BackupRestoreBlockedError("restored application startup #1 readiness failed")
    after_startup_1 = _database_snapshot(db.engine)
    _require_same_database(before, after_startup_1, "restored application startup #1")

    canary_name = f"BM-PROD5.5A Restore Canary {secrets.token_hex(8)}"
    canary_id: int | None = None
    canary_deleted = False
    read_canaries: dict[str, str] = {}
    with TestClient(app) as second_client:
        try:
            health = second_client.get("/api/health")
            if health.status_code != 200 or not health.json().get("database_ready"):
                raise BackupRestoreBlockedError("restored application startup #2 readiness failed")
            read_canaries = {
                "health_readiness": "PASS",
                "library_summary": _response_pass(second_client, "/api/library/summary"),
                "artists": _response_pass(second_client, "/api/library/artists"),
                "albums_releases": _response_pass(second_client, "/api/library/albums"),
                "search": _response_pass(second_client, "/api/search?q=restore-canary-no-match"),
                "playlists": _response_pass(second_client, "/api/playlists"),
                "stations": _response_pass(second_client, "/api/stations/"),
                "recording_controls": _recording_control_canary(second_client),
                "audiobooks": _response_pass(second_client, "/api/audiobooks/"),
            }
            created = second_client.post(
                "/api/playlists",
                json={"name": canary_name, "description": "temporary disposable-restore canary"},
            )
            if created.status_code != 200:
                raise BackupRestoreBlockedError("restored application playlist create canary failed")
            canary_id = int(created.json()["id"])
            with db.engine.connect() as connection:
                present = int(
                    connection.execute(
                        text("select count(*) from playlists where id = :playlist_id and name = :name"),
                        {"playlist_id": canary_id, "name": canary_name},
                    ).scalar_one()
                )
            if present != 1:
                raise BackupRestoreBlockedError("playlist write canary did not reach disposable restore database")
            deleted = second_client.delete(f"/api/playlists/{canary_id}")
            if deleted.status_code != 200 or not deleted.json().get("deleted"):
                raise BackupRestoreBlockedError("restored application playlist delete canary failed")
            canary_deleted = True
        finally:
            if canary_id is not None and not canary_deleted:
                cleanup = second_client.delete(f"/api/playlists/{canary_id}")
                canary_deleted = cleanup.status_code == 200 and bool(cleanup.json().get("deleted"))

    after_startup_2 = _database_snapshot(db.engine)
    _require_same_database(before, after_startup_2, "restored application startup #2 and write cleanup")
    return {
        "database_dialect": "postgresql",
        "database_driver": "psycopg",
        "readiness": after_startup_2["readiness"],
        "startup_1": {"result": "PASS", "row_delta": _row_delta(before, after_startup_1)},
        "startup_2": {"result": "PASS", "row_delta": _row_delta(before, after_startup_2)},
        "startup_zero_row_delta": True,
        "read_canaries": read_canaries,
        "media_access": {"streaming": False, "scanner": False, "metadata_probe": False, "file_open": False},
        "write_canary": {
            "type": "temporary_playlist",
            "create": "PASS",
            "delete": "PASS",
            "cleanup": "PASS",
            "rows_returned_to_1257": after_startup_2["application_total_rows"] == EXPECTED_SOURCE_ROWS,
            "canonical_digests_restored": before["per_table_canonical_digests"]
            == after_startup_2["per_table_canonical_digests"],
        },
    }


def _spawn_application_canary(database_url: str) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["BM_RADIO_DB_URL"] = database_url
    with tempfile.TemporaryDirectory(prefix="bm-prod5-5a-canary-") as temporary:
        root = Path(temporary)
        for index, name in enumerate(MEDIA_ROOT_KEYS):
            directory = root / f"empty-root-{index}"
            directory.mkdir()
            environment[name] = str(directory)
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
    line = next((item for item in reversed(result.stdout.splitlines()) if item.startswith(CANARY_MARKER)), None)
    if result.returncode != 0 or line is None:
        raise BackupRestoreBlockedError("fresh child restored-application canary failed")
    try:
        payload = json.loads(line[len(CANARY_MARKER) :])
    except json.JSONDecodeError as exc:
        raise BackupRestoreBlockedError("fresh child restored-application evidence is invalid") from exc
    if not isinstance(payload, dict):
        raise BackupRestoreBlockedError("fresh child restored-application evidence is invalid")
    return payload


def preflight_only() -> int:
    result = active_preflight()
    print(f"BM-PROD5.5A BACKUP PREFLIGHT: {result['gate']}")
    for blocker in result["blockers"]:
        print(f"reason: {blocker}")
    _json(result)
    print("Active PostgreSQL modified: NO")
    print("SQLite modified: NO")
    print("Media accessed: NO")
    return 0 if result["gate"] == "PASS" else 2


def run_backup_restore_proof() -> int:
    preflight = active_preflight()
    if preflight["gate"] != "PASS":
        raise BackupRestoreBlockedError("preflight blocked: " + "; ".join(preflight["blockers"]))
    before = protected_snapshot()
    _alembic_check(target_url_from_secret_file())
    backup = create_logical_backup(before, preflight)
    restore: dict[str, Any] | None = None
    cleanup: dict[str, Any] | None = None
    try:
        restore = create_disposable_restore(backup["backup_path"])
        application = _spawn_application_canary(restore["database_url"])
    finally:
        if restore is not None:
            cleanup = cleanup_disposable_restore(restore)
    if restore is None or cleanup is None:
        raise BackupRestoreBlockedError("disposable restore did not produce complete evidence")
    if not all(cleanup[key] for key in ("container_removed", "volume_removed", "network_removed", "port_closed")):
        raise BackupRestoreBlockedError("disposable restore cleanup was incomplete")

    after = protected_snapshot()
    unchanged = {
        "active_postgresql_unchanged": before["active_postgresql"] == after["active_postgresql"],
        "sqlite_fallback_unchanged": before["sqlite_fallback"] == after["sqlite_fallback"],
        "backend_env_unchanged": before["configuration_hashes"]["backend_env_sha256"]
        == after["configuration_hashes"]["backend_env_sha256"],
        "adoption_state_evidence_unchanged": before["configuration_hashes"] == after["configuration_hashes"],
        "configuration_unchanged": before["configuration_hashes"] == after["configuration_hashes"],
    }
    if not all(unchanged.values()):
        raise BackupRestoreBlockedError("protected active PostgreSQL, SQLite, or adoption state changed")
    artifact, artifact_sha = write_backup_verification(
        backup=backup,
        restore=restore,
        application=application,
        unchanged=unchanged,
        cleanup=cleanup,
        preflight=preflight,
    )
    safe_restore = {key: value for key, value in restore.items() if key not in ("database_url", "port")}
    result = {
        "status": "LOGICAL-BACKUP-RESTORE PASS",
        "source_commit": preflight["source_commit"],
        "preflight": preflight,
        "source": before,
        "backup": {key: value for key, value in backup.items() if key not in ("backup_path", "manifest_path", "manifest")},
        "restore": safe_restore,
        "application": application,
        "protected_state": unchanged,
        "disposable_cleanup": cleanup,
        "backup_verification_filename": BACKUP_VERIFICATION_PATH.name,
        "backup_verification_sha256": artifact_sha,
        "backup_verification": artifact,
    }
    print("BM-PROD5.5A LOGICAL-BACKUP-RESTORE: PASS")
    _json(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.5A PostgreSQL logical backup and disposable restore proof")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--canary-internal", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    try:
        if arguments.preflight_only:
            return preflight_only()
        if arguments.canary_internal:
            print(CANARY_MARKER + json.dumps(_run_application_canary(), sort_keys=True))
            return 0
        return run_backup_restore_proof()
    except BackupRestoreBlockedError as exc:
        print("BM-PROD5.5A LOGICAL-BACKUP-RESTORE: BLOCKED")
        print(f"reason: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
