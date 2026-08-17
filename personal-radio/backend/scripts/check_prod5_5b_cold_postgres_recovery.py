from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.postgres_backup_restore import BackupRestoreBlockedError, _database_snapshot  # noqa: E402
from app.postgres_recovery import (  # noqa: E402
    ACCEPTED_BACKUP_SHA256,
    ACCEPTED_MANIFEST_SHA256,
    ACCEPTED_BACKUP_VERIFICATION_SHA256,
    EXPECTED_SOURCE_ROWS,
    MEDIA_ROOT_KEYS,
    RECOVERY_APPROVAL,
    STARTING_COMMIT,
    RecoveryBlockedError,
    _alembic_check,
    active_container_identity,
    cleanup_recovery_resources,
    create_recovery_target,
    pre_recovery_gate,
    protected_hashes,
    protected_snapshot,
    prove_active_unreachable,
    recreate_from_recovery_volume,
    restore_retained_backup,
    start_active_container,
    stop_active_container,
    utc_now,
    verify_recovered_database,
    volume_identity,
    write_recovery_verification,
)
from app.local_postgres_adoption import (  # noqa: E402
    BACKEND_ENV_PATH,
    CONTAINER_NAME,
    HOST,
    HOST_PORT,
    VOLUME_NAME,
    container_status,
    target_url_from_secret_file,
)
from scripts.check_prod5_5a_postgres_backup_restore import _spawn_application_canary  # noqa: E402


RECONNECT_MARKER = "BM_PROD5_5B_RECONNECT_RESULT="


def _json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _run_original_reconnect_canary() -> dict[str, Any]:
    """Run only in a fresh child with the real adopted .env and temporary roots."""
    from fastapi.testclient import TestClient
    from app import db
    from app.config import settings
    from app.main import app

    if (
        db.engine.dialect.name != "postgresql"
        or db.engine.url.drivername != "postgresql+psycopg"
        or db.engine.url.host != HOST
        or db.engine.url.port != HOST_PORT
        or settings.BM_RADIO_DB_POLICY_STATUS != "postgresql_supported"
    ):
        raise RecoveryBlockedError("original application reconnect did not use adopted PostgreSQL")
    before = _database_snapshot(db.engine)
    with TestClient(app) as client:
        health = client.get("/api/health")
        if health.status_code != 200 or not health.json().get("database_ready"):
            raise RecoveryBlockedError("original application reconnect health/readiness failed")
    after = _database_snapshot(db.engine)
    if (
        before["application_total_rows"] != EXPECTED_SOURCE_ROWS
        or after["application_total_rows"] != EXPECTED_SOURCE_ROWS
        or before["per_table_row_counts"] != after["per_table_row_counts"]
        or before["per_table_canonical_digests"] != after["per_table_canonical_digests"]
    ):
        raise RecoveryBlockedError("original application reconnect changed active PostgreSQL data")
    return {
        "result": "PASS",
        "database_dialect": "postgresql",
        "database_driver": "psycopg",
        "readiness": after["readiness"],
        "health_readiness": "PASS",
        "zero_row_delta": True,
        "rows": after["application_total_rows"],
        "media_access": {"streaming": False, "scanner": False, "metadata_probe": False, "file_open": False},
    }


def _spawn_original_reconnect_canary() -> dict[str, Any]:
    environment = os.environ.copy()
    environment.pop("BM_RADIO_DB_URL", None)
    with tempfile.TemporaryDirectory(prefix="bm-prod5-5b-reconnect-") as temporary:
        root = Path(temporary)
        for index, name in enumerate(MEDIA_ROOT_KEYS):
            directory = root / f"empty-root-{index}"
            directory.mkdir()
            environment[name] = str(directory)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--reconnect-internal"],
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
    line = next((item for item in reversed(result.stdout.splitlines()) if item.startswith(RECONNECT_MARKER)), None)
    if result.returncode != 0 or line is None:
        raise RecoveryBlockedError("fresh child original-application reconnect canary failed")
    try:
        payload = json.loads(line[len(RECONNECT_MARKER) :])
    except json.JSONDecodeError as exc:
        raise RecoveryBlockedError("original-application reconnect evidence is invalid") from exc
    if not isinstance(payload, dict):
        raise RecoveryBlockedError("original-application reconnect evidence is invalid")
    return payload


def preflight_only() -> int:
    result = pre_recovery_gate()
    print(f"BM-PROD5.5B PRE-RECOVERY GATE: {result['gate']}")
    for blocker in result["blockers"]:
        print(f"reason: {blocker}")
    _json(result)
    print("Explicit interruption approval received: NO")
    print("Active PostgreSQL stopped: NO")
    print("Active PostgreSQL modified: NO")
    print("SQLite modified: NO")
    print("Media accessed: NO")
    print("STOP: exact APPROVE-BM-PROD5.5B-COLD-RECOVERY token required before outage")
    return 0 if result["gate"] == "PASS" else 2


def _safe_resource(resource: dict[str, Any]) -> dict[str, Any]:
    omitted = {"password", "credential_path", "url_a", "url_b"}
    return {key: value for key, value in resource.items() if key not in omitted}


def approved_cold_recovery(token: str) -> int:
    if token != RECOVERY_APPROVAL:
        raise RecoveryBlockedError("exact cold-recovery interruption approval token is required")
    gate = pre_recovery_gate()
    if gate["gate"] != "PASS":
        raise RecoveryBlockedError("pre-recovery gate blocked: " + "; ".join(gate["blockers"]))

    retained = gate["retained_backup"]
    before = gate["protected_snapshot"]
    hashes_before = protected_hashes()
    original_container = gate["active_container_identity"]
    original_volume = gate["active_volume_identity"]
    resource: dict[str, Any] | None = None
    recovery_cleanup: dict[str, Any] | None = None
    active_stopped = False
    try:
        outage = stop_active_container()
        active_stopped = True
        unavailable = prove_active_unreachable()

        resource = create_recovery_target()
        restore_retained_backup(resource)
        recovery_a = verify_recovered_database(resource["url_a"], retained)
        resource = recreate_from_recovery_volume(resource)
        recovery_b = verify_recovered_database(resource["url_b"], retained)
        application = _spawn_application_canary(resource["url_b"])
        recovery_after_application = verify_recovered_database(resource["url_b"], retained)

        recovery_cleanup = cleanup_recovery_resources(resource)
        if not all(
            recovery_cleanup.get(key)
            for key in ("container_a_removed", "container_b_removed", "volume_removed", "ports_closed", "credentials_removed")
        ):
            raise RecoveryBlockedError("recovery resource cleanup was incomplete")

        start_active_container()
        active_stopped = False
        after = protected_snapshot()
        _alembic_check(target_url_from_secret_file())
        hashes_after = protected_hashes()
        final_container = active_container_identity()
        final_volume = volume_identity()
        if original_container != final_container:
            raise RecoveryBlockedError("original active container identity changed during rehearsal")
        if original_volume != final_volume:
            raise RecoveryBlockedError("original active volume identity changed during rehearsal")
        if before["active_postgresql"] != after["active_postgresql"]:
            raise RecoveryBlockedError("original active PostgreSQL data changed during rehearsal")
        if before["sqlite_fallback"] != after["sqlite_fallback"]:
            raise RecoveryBlockedError("SQLite fallback changed during rehearsal")
        if hashes_before != hashes_after:
            raise RecoveryBlockedError("active configuration or adoption evidence changed during rehearsal")
        reconnect = _spawn_original_reconnect_canary()
        if protected_hashes() != hashes_before:
            raise RecoveryBlockedError("original application reconnect changed protected local state")

        artifact = {
            "version": 1,
            "phase": "BM-PROD5.5B",
            "created_utc": utc_now(),
            "source_commit": STARTING_COMMIT,
            "backup_filename": retained["backup_filename"],
            "backup_sha256": ACCEPTED_BACKUP_SHA256,
            "manifest_sha256": ACCEPTED_MANIFEST_SHA256,
            "backup_verification_sha256": ACCEPTED_BACKUP_VERIFICATION_SHA256,
            "active_container_stopped": outage["container_stopped"],
            "active_target_unreachable": unavailable["readiness"] == "database_unreachable",
            "recovery_resources": {
                "container_a": resource["container_a"],
                "container_b": resource["container_b"],
                "volume": resource["volume"],
                "database": resource["database"],
                "role": resource["role"],
                "loopback_dynamic_ports": True,
            },
            "postgresql_version": resource["postgresql_version"],
            "restore_result": "PASS",
            "restored_revision": recovery_a["snapshot"]["revision"],
            "restored_rows": recovery_a["snapshot"]["application_total_rows"],
            "count_equality": recovery_a["count_equality"],
            "canonical_digest_equality": recovery_a["canonical_digest_equality"],
            "fk_verification": recovery_a["foreign_key_validation"],
            "sequence_verification": recovery_a["sequence_verification"],
            "alembic_check": recovery_a["alembic_check"],
            "container_a_removed": resource["container_a_removed"],
            "recovery_volume_retained": resource["recovery_volume_retained"],
            "container_b_recreated": True,
            "post_recreation_count_equality": recovery_b["count_equality"],
            "post_recreation_digest_equality": recovery_b["canonical_digest_equality"],
            "application_startup_1": application["startup_1"],
            "application_startup_2": application["startup_2"],
            "application_read_canaries": application["read_canaries"],
            "application_write_canary": application["write_canary"],
            "recovery_post_canary_equality": {
                "counts": recovery_after_application["count_equality"],
                "digests": recovery_after_application["canonical_digest_equality"],
            },
            "recovery_cleanup": recovery_cleanup,
            "original_active_restart": {
                "container": CONTAINER_NAME,
                "volume": VOLUME_NAME,
                "healthy": container_status()["healthy"],
                "exact_data_equality": before["active_postgresql"] == after["active_postgresql"],
                "volume_identity_unchanged": original_volume == final_volume,
            },
            "original_application_reconnect": reconnect,
            "sqlite_exact_equality": before["sqlite_fallback"] == after["sqlite_fallback"],
            "configuration_exact_equality": hashes_before == hashes_after,
            "media_access": {"streaming": False, "scanner": False, "metadata_probe": False, "file_open": False},
        }
        artifact_sha = write_recovery_verification(artifact)
        result = {
            "status": "COLD-RECOVERY REHEARSAL PASS",
            "source_commit": STARTING_COMMIT,
            "retained_backup": retained,
            "outage": {**outage, **unavailable},
            "recovery_target": _safe_resource(resource),
            "recovery_a": recovery_a,
            "recovery_b": recovery_b,
            "recovered_application": application,
            "recovery_after_application": recovery_after_application,
            "recovery_cleanup": recovery_cleanup,
            "original_active_restart": artifact["original_active_restart"],
            "original_application_reconnect": reconnect,
            "protected_state": {
                "active_postgresql_unchanged": True,
                "active_volume_identity_unchanged": True,
                "sqlite_unchanged": True,
                "configuration_evidence_unchanged": True,
            },
            "recovery_verification_sha256": artifact_sha,
        }
        print("BM-PROD5.5B COLD-RECOVERY REHEARSAL: PASS")
        _json(result)
        return 0
    except Exception:
        try:
            recovery_cleanup = cleanup_recovery_resources(resource)
        finally:
            if active_stopped or (container_status().get("exists") and not container_status().get("running")):
                start_active_container()
                active_stopped = False
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.5B approval-gated cold PostgreSQL recovery rehearsal")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--approve", metavar="TOKEN")
    mode.add_argument("--reconnect-internal", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    try:
        if arguments.preflight_only:
            return preflight_only()
        if arguments.reconnect_internal:
            print(RECONNECT_MARKER + json.dumps(_run_original_reconnect_canary(), sort_keys=True))
            return 0
        return approved_cold_recovery(str(arguments.approve))
    except (RecoveryBlockedError, BackupRestoreBlockedError) as exc:
        print("BM-PROD5.5B COLD-RECOVERY REHEARSAL: BLOCKED")
        print(f"reason: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
