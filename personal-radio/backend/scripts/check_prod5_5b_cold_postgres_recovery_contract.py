from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys


BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
MODULE = BACKEND / "app" / "postgres_recovery.py"
BACKUP_MODULE = BACKEND / "app" / "postgres_backup_restore.py"
OPERATOR = BACKEND / "scripts" / "manage_postgres_recovery.py"
LIVE = BACKEND / "scripts" / "check_prod5_5b_cold_postgres_recovery.py"
LIVE_5A = BACKEND / "scripts" / "check_prod5_5a_postgres_backup_restore.py"
REPORT_5A = PROJECT / "docs" / "production-upgrade" / "BM-PROD5.5A_PostgreSQL_Logical_Backup_and_Disposable_Restore_Proof.md"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
CHECKS: list[str] = []

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import postgres_recovery as recovery  # noqa: E402


def check(condition: bool, label: str) -> None:
    assert condition, label
    CHECKS.append(label)


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name)
    return ast.get_source_segment(source, node) or ""


def run_prior(script: str, *arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, script, *arguments],
        cwd=str(BACKEND),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=1200,
        shell=False,
    )
    assert result.returncode == 0 and "PASS" in result.stdout, result.stdout


def prod0_mandatory_count(source: str) -> int:
    tree = ast.parse(source)
    main = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "main")
    assignment = next(
        item
        for item in ast.walk(main)
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and item.target.id == "checks"
        and isinstance(item.value, ast.List)
    )
    return len(assignment.value.elts) + 2


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.5B deterministic cold-recovery safety contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    arguments = parser.parse_args()

    source = MODULE.read_text(encoding="utf-8")
    backup_source = BACKUP_MODULE.read_text(encoding="utf-8")
    operator = OPERATOR.read_text(encoding="utf-8")
    live = LIVE.read_text(encoding="utf-8")
    live_5a = LIVE_5A.read_text(encoding="utf-8")
    report = REPORT_5A.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")
    gate = function_source(source, "pre_recovery_gate")
    independent = function_source(source, "independent_archive_inspection")
    retained = function_source(source, "verify_retained_recovery_input")
    stop_active = function_source(source, "stop_active_container")
    start_active = function_source(source, "start_active_container")
    unreachable = function_source(source, "prove_active_unreachable")
    names = function_source(source, "_safe_recovery_names")
    credentials = function_source(source, "_write_recovery_credentials")
    run_container = function_source(source, "_run_recovery_container")
    create_target = function_source(source, "create_recovery_target")
    restore = function_source(source, "restore_retained_backup")
    verify = function_source(source, "verify_recovered_database")
    recreate = function_source(source, "recreate_from_recovery_volume")
    cleanup = function_source(source, "cleanup_recovery_resources")
    approved = function_source(live, "approved_cold_recovery")
    reconnect = function_source(live, "_run_original_reconnect_canary")
    reconnect_spawn = function_source(live, "_spawn_original_reconnect_canary")
    application = function_source(live_5a, "_run_application_canary")
    evidence = function_source(source, "write_recovery_verification")

    commit = "789964e841ad06663e96e02f57cb53b259c93283"
    check(commit in report and "uncommitted working-tree changes" not in report, "1 5.5A report records accepted implementation commit")
    check(recovery.RECOVERY_APPROVAL == "APPROVE-BM-PROD5.5B-COLD-RECOVERY" and "token != RECOVERY_APPROVAL" in approved, "2 exact recovery approval token is required")
    check("stop_active_container" not in gate and "start_active_container" not in gate and "PRE-RECOVERY GATE" in live, "3 pre-recovery gate does not interrupt active PostgreSQL")
    check(recovery.ACCEPTED_BACKUP_SHA256 in source and "sha256_file(BACKUP_PATH)" in retained, "4 retained backup SHA must match accepted 5.5A backup")
    check(recovery.ACCEPTED_MANIFEST_SHA256 in source and "sha256_file(MANIFEST_PATH)" in retained, "5 retained manifest SHA must match")
    check(recovery.ACCEPTED_BACKUP_VERIFICATION_SHA256 in source and "sha256_file(BACKUP_VERIFICATION_PATH)" in retained, "6 backup_verification SHA must match")
    check("CONTAINER_NAME" not in independent and "HELPER_CONTAINER_PREFIX" in independent and '"pg_restore", "--list"' in independent, "7 backup inspection is independent of active container")
    check("IMAGE_TAG" in independent and '"PostgreSQL) 16."' in independent and recovery.POSTGRES_MAJOR == 16, "8 PostgreSQL 16 helper/recovery tooling is required")
    check('"stop", CONTAINER_NAME' in stop_active and '"start", CONTAINER_NAME' in start_active, "9 active container operations are limited to stop/start")
    check("container\", \"rm\", CONTAINER_NAME" not in source and "container == CONTAINER_NAME" not in cleanup, "10 active container cannot be removed")
    check("volume\", \"rm\", VOLUME_NAME" not in source and "volume == VOLUME_NAME" in cleanup, "11 active volume cannot be removed")
    check("volume_identity()" in gate and '"active_volume_identity"' in gate, "12 active volume identity is snapshotted")
    check("DATABASE_UNREACHABLE" in unreachable and "_port_closed(HOST_PORT)" in unreachable and "prove_active_unreachable()" in approved, "13 active database unreachable proof is required")
    check(all(prefix in source for prefix in ("bm-prod5-5b-recovery-", "bm-prod5-5b-recovery-data-", "bm-prod5-5b-helper-")), "14 recovery resources use dedicated prefixes")
    check("== CONTAINER_NAME" in names and "== VOLUME_NAME" in names and "overlaps active resources" in names, "15 recovery names cannot equal active names")
    check("port_a == HOST_PORT" in create_target and "port_b == HOST_PORT" in recreate, "16 recovery ports cannot use 55432")
    check('"127.0.0.1::5432"' in run_container and "_dynamic_port(container)" in run_container, "17 recovery PostgreSQL is loopback-only")
    check("secrets.token_urlsafe" in create_target and "credential" in credentials.lower() and "chmod(0o600)" in credentials, "18 recovery credentials are ephemeral and protected")
    check('"volume", "create"' in create_target and '"type=volume,source=' in run_container, "19 recovery uses a named volume")
    check("type=bind" not in run_container.lower() and "DATA_MOUNT" in run_container, "20 Windows host database bind mounts are prohibited")
    check("BACKUP_PATH" in restore and recovery.ACCEPTED_BACKUP_FILENAME in source, "21 restore uses the accepted retained logical backup")
    check("alembic" not in restore.lower() and "pg_restore" in restore, "22 no Alembic bootstrap occurs before restore")
    check('"--exit-on-error"' in restore, "23 restore is fail-on-error")
    check('snapshot["revision"] != EXPECTED_REVISION' in verify, "24 recovered revision equality is required")
    check("len(APP_TABLES)" in verify and len(recovery.APP_TABLES) == 21, "25 21-table equality is required")
    check("EXPECTED_SOURCE_ROWS" in verify and recovery.EXPECTED_SOURCE_ROWS == 1257, "26 1,257-row equality is required")
    check('snapshot["per_table_row_counts"] != retained["manifest_counts"]' in verify, "27 per-table count equality is required")
    check('snapshot["per_table_canonical_digests"] != retained["manifest_digests"]' in verify, "28 per-table digest equality is required")
    check("foreign_key_validation" in verify, "29 foreign-key validation is required")
    check("_constraint_and_type_canaries(engine)" in verify, "30 constraint/type validation is required")
    check("_sequence_state(engine)" in verify and "next_id_canary" in verify, "31 sequence validation is required")
    check("_alembic_check(database_url)" in verify, "32 Alembic check is required")
    check('"container", "rm", container_a' in recreate and "recovery named volume did not survive" in recreate, "33 container A removal preserves recovery volume")
    check('resource["container_b"]' in recreate and 'resource["volume"]' in recreate and "_run_recovery_container" in recreate, "34 container B recreates from the same volume")
    check('recovery_b = verify_recovered_database(resource["url_b"]' in approved, "35 post-recreation count/digest equality is required")
    check("startup #1" in application and '"startup_1"' in application, "36 recovered application startup #1 is required")
    check("startup #2" in application and '"startup_2"' in application, "37 recovered application startup #2 is required")
    check("startup_zero_row_delta" in application and "_row_delta" in application, "38 recovered application zero-row-delta is required")
    check(all(path in application for path in ("/api/health", "/api/library/summary", "/api/library/artists", "/api/library/albums", "/api/search", "/api/playlists", "/api/stations/", "/api/audiobooks/")), "39 recovered application read canaries are required")
    check('"streaming": False' in application and '"scanner": False' in application and "/scan" not in application, "40 media access is prohibited")
    check("second_client.post" in application and "second_client.delete" in application and '"/api/playlists"' in application, "41 reversible application write canary is required")
    check('recovery_after_application = verify_recovered_database(resource["url_b"]' in approved and "canonical_digests_restored" in application, "42 recovery DB returns to exact backup state")
    check("volume.startswith(RECOVERY_VOLUME_PREFIX)" in cleanup and "volume == VOLUME_NAME" in cleanup, "43 cleanup can delete only recovery-prefixed volume")
    check(approved.index("cleanup_recovery_resources(resource)") < approved.index("start_active_container()"), "44 recovery/helper resources are cleaned before active restart")
    check("except Exception:" in approved and "finally:" in approved and "start_active_container()" in approved[approved.index("except Exception:") :], "45 active container restart is guaranteed in failure handling")
    check('before["active_postgresql"] != after["active_postgresql"]' in approved, "46 original active database exact equality is required")
    check("original_volume != final_volume" in approved, "47 original active volume identity must remain unchanged")
    check("_spawn_original_reconnect_canary()" in approved and "real adopted .env" in reconnect and "environment.pop(\"BM_RADIO_DB_URL\"" in reconnect_spawn, "48 adopted application reconnect canary is required")
    check('before["sqlite_fallback"] != after["sqlite_fallback"]' in approved, "49 SQLite exact equality is required")
    check("protected_hashes()" in approved and "backend_env_sha256" in source, "50 backend/.env exact equality is required")
    check(all(token in source for token in ("state_sha256", "transfer_verification_sha256", "adoption_verification_sha256", "backup_verification_sha256", "backend_env_before_sha256")), "51 adoption evidence/state exact equality is required")
    check("_privacy_check(payload" in evidence and "_write_safe_json(RECOVERY_VERIFICATION_PATH" in evidence and "FORBIDDEN_EVIDENCE_TOKENS" in source, "52 recovery evidence is privacy-safe")
    check('"replace-active"' not in operator and "replace_active" not in operator, "53 no active replacement command exists")
    check('"destroy-active"' not in operator and "destroy_active" not in operator, "54 no active destruction command exists")

    prior = {
        "55 BM-PROD5.5A contract remains passing": ("scripts/check_prod5_5a_postgres_backup_restore_contract.py", "--skip-prior-regressions"),
        "56 BM-PROD5.4C.3B contract remains passing": ("scripts/check_prod5_4c_3b_active_postgres_adoption_contract.py", "--skip-prior-regressions"),
    }
    for label, command in prior.items():
        check((BACKEND / command[0]).is_file(), label)
        if not arguments.skip_prior_regressions:
            run_prior(*command)
    check("check_prod5_5b_cold_postgres_recovery_contract.py" in prod0 and prod0_mandatory_count(prod0) >= 56, "57 full PROD0 preserves at least 56 mandatory checks")

    assert len(CHECKS) == 57, len(CHECKS)
    print("PASS: BM-PROD5.5B cold PostgreSQL disaster-recovery contract (57 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
