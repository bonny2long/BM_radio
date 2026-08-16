from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys


BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
MODULE = BACKEND / "app" / "postgres_backup_restore.py"
OPERATOR = BACKEND / "scripts" / "manage_postgres_backup.py"
LIVE = BACKEND / "scripts" / "check_prod5_5a_postgres_backup_restore.py"
REPORT_3B = PROJECT / "docs" / "production-upgrade" / "BM-PROD5.4C.3B_Active_Application_Adoption_to_Persistent_PostgreSQL.md"
GITIGNORE = PROJECT / ".gitignore"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
CHECKS: list[str] = []

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import postgres_backup_restore as backup_restore  # noqa: E402


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
        timeout=900,
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
    parser = argparse.ArgumentParser(description="BM-PROD5.5A deterministic logical backup/restore safety contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    arguments = parser.parse_args()

    source = MODULE.read_text(encoding="utf-8")
    operator = OPERATOR.read_text(encoding="utf-8")
    live = LIVE.read_text(encoding="utf-8")
    report = REPORT_3B.read_text(encoding="utf-8")
    ignored = GITIGNORE.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")
    preflight = function_source(source, "active_preflight")
    backup = function_source(source, "create_logical_backup")
    inspect_archive = function_source(source, "inspect_backup")
    validate_listing = function_source(source, "_validate_archive_listing")
    restore_create = function_source(source, "create_disposable_restore")
    restore_archive = function_source(source, "_restore_archive")
    dispose = function_source(source, "_dispose_restore")
    constraints = function_source(source, "_constraint_and_type_canaries")
    sequences = function_source(source, "_sequence_state")
    app_canary = function_source(live, "_run_application_canary")
    spawn_canary = function_source(live, "_spawn_application_canary")
    run_proof = function_source(live, "run_backup_restore_proof")
    verify_writer = function_source(source, "write_backup_verification")

    commit = "ae0aa471d71e53d4e2609944e1f7e15d55a0e6b7"
    check(commit in report and "uncommitted working-tree changes" not in report, "1 5.4C.3B report records accepted implementation commit")
    check(OPERATOR.is_file() and all(command in operator for command in ('"preflight"', '"backup"', '"inspect"', '"restore-rehearsal"', '"verify"')), "2 backup operator CLI exists")
    check(LIVE.is_file() and "--preflight-only" in live and 'mode.add_argument("--run"' in live, "3 live integration script exists")
    check("backend/.local_backups/" in ignored and backup_restore.BACKUP_DIR.name == "postgresql", "4 PostgreSQL backup directory is ignored")
    check('"--format=custom"' in backup and 'b"PGDMP"' in backup, "5 backup uses PostgreSQL custom format")
    check('f"--dbname={DATABASE_NAME}"' in backup and backup_restore.DATABASE_NAME == "bm_radio", "6 backup is scoped to bm_radio")
    check('"--env-file"' in restore_create and "POSTGRES_PASSWORD" not in backup and "password" not in restore_archive.lower(), "7 credentials stay out of visible pg_dump/pg_restore arguments")
    check(backup_restore.POSTGRES_MAJOR == 16 and all(token in preflight for token in ("pg_dump_version", "pg_restore_version", "server_version")), "8 PostgreSQL 16-compatible tools are required")
    check("sha256_file(backup_path)" in backup and "backup_sha256" in backup, "9 backup SHA-256 is calculated")
    check("manifest =" in backup and "_write_safe_json" in backup and all(token in backup for token in ("per_table_row_counts", "per_table_canonical_digests", "transfer_verification_sha256", "adoption_verification_sha256")), "10 privacy-safe backup manifest exists")
    check('"pg_restore", "--list"' in inspect_archive and "_validate_archive_listing" in inspect_archive, "11 pg_restore archive-list inspection exists")
    check("database == DATABASE_NAME" in restore_create and "overlaps the active database" in restore_create, "12 restore never targets active bm_radio")
    check('"--tmpfs"' in restore_create and "IMAGE_TAG" in restore_create and "RESTORE_PREFIX" in restore_create, "13 restore uses disposable PostgreSQL")
    check("container == CONTAINER_NAME" in restore_create and "container.startswith(RESTORE_PREFIX)" in restore_create, "14 disposable names cannot equal persistent names")
    check('"127.0.0.1::5432"' in restore_create and "_dynamic_port(container)" in restore_create, "15 restore uses loopback-only dynamic port")
    check('"--exit-on-error"' in restore_archive, "16 restore is fail-on-error")
    check("alembic" not in restore_archive.lower() and "pg_restore" in restore_archive, "17 restore does not depend on pre-running Alembic")
    check("restored[\"revision\"] != EXPECTED_REVISION" in restore_create, "18 restored revision must equal backup revision")
    check("restored[\"readiness\"] != READY" in restore_create, "19 restored readiness must be ready")
    check('restored["compatibility"] != "PASS"' in restore_create, "20 restored compatibility must PASS")
    check("len(APP_TABLES)" in restore_create and "all_application_tables" in validate_listing, "21 21-table equality is required")
    check("EXPECTED_SOURCE_ROWS" in restore_create and backup_restore.EXPECTED_SOURCE_ROWS == 1257, "22 1,257-row equality is required")
    check("verify_database_transfer(" in restore_create and "active_engine" in restore_create and "restored_engine" in restore_create and "_require_same_database" in app_canary, "23 per-table count equality is required")
    check("canonical_digests" in app_canary and "canonical_digest_equality" in verify_writer, "24 per-table canonical digest equality is required")
    check("foreign_key_violations" in source and "foreign_key_validation" in verify_writer, "25 foreign-key validation is required")
    check("expected_unique_constraints" in constraints and "expected_check_constraints" in constraints and "unique_behaves" in constraints and "check_behaves" in constraints, "26 unique/check validation exists and behaves")
    check("thumbvalue" in constraints and "enum_behaves" in constraints and "thumbvalue_enum" in validate_listing, "27 enum/type validation is required")
    check("pg_get_serial_sequence" in sequences and "valid_next_state" in sequences, "28 all integer PK sequences are validated")
    check("tracks" in sequences and "begin_nested" in sequences and "rolled_back" in sequences and "sequence_state_restored" in sequences, "29 next-ID rollback canary is required")
    check("_alembic_check(restored_url)" in restore_create and '"alembic_check": "PASS"' in restore_create, "30 Alembic check is required on restored DB")
    check("startup #1" in app_canary and '"startup_1"' in app_canary, "31 application startup #1 is required")
    check("startup #2" in app_canary and '"startup_2"' in app_canary and app_canary.count("with TestClient(app)") >= 2, "32 application startup #2 is required")
    check("_row_delta" in app_canary and "startup_zero_row_delta" in app_canary, "33 startup zero-row-delta is required")
    check(all(path in app_canary for path in ("/api/health", "/api/library/summary", "/api/library/artists", "/api/library/albums", "/api/search", "/api/playlists", "/api/stations/", "/api/audiobooks/")), "34 required read canaries exist")
    check('client.get("/api/media' not in live and '"streaming": False' in app_canary, "35 streaming is prohibited")
    check("/scan" not in app_canary and '"scanner": False' in app_canary, "36 scanner invocation is prohibited")
    check('second_client.post(' in app_canary and '"/api/playlists"' in app_canary and "second_client.delete" in app_canary, "37 reversible application write canary is required")
    check("canonical_digests_restored" in app_canary and "_require_same_database" in app_canary, "38 write cleanup restores exact digests")
    check('"active_postgresql_unchanged"' in run_proof and 'before["active_postgresql"] == after["active_postgresql"]' in run_proof, "39 active PostgreSQL before/after equality is required")
    check('"sqlite_fallback_unchanged"' in run_proof and 'before["sqlite_fallback"] == after["sqlite_fallback"]' in run_proof, "40 SQLite before/after equality is required")
    check('"backend_env_unchanged"' in run_proof and "backend_env_sha256" in run_proof, "41 backend/.env before/after equality is required")
    check('"adoption_state_evidence_unchanged"' in run_proof and 'before["configuration_hashes"] == after["configuration_hashes"]' in run_proof, "42 adoption state/evidence equality is required")
    check("finally:" in run_proof and "cleanup_disposable_restore(restore)" in run_proof and "_dispose_restore(container, port)" in restore_create, "43 disposable cleanup is guaranteed in finally")
    check("backup_path.unlink" not in source and "BACKUP_DIR.mkdir" in backup, "44 verified logical backup is retained")
    check("_write_safe_json(" in verify_writer and "BACKUP_VERIFICATION_PATH" in verify_writer and "FORBIDDEN_EVIDENCE_TOKENS" in source, "45 backup_verification.json is privacy-safe")
    check("replace" not in " ".join(('"preflight"', '"backup"', '"inspect"', '"restore-rehearsal"', '"verify"')) and "destroy" not in operator.lower(), "46 no active restore/replacement command exists")
    check("container == CONTAINER_NAME" in restore_create and "container == CONTAINER_NAME" in dispose and "VOLUME_NAME" not in dispose, "47 persistent PostgreSQL destruction is prohibited")

    prior = {
        "48 BM-PROD5.4C.3B contract remains passing": ("scripts/check_prod5_4c_3b_active_postgres_adoption_contract.py", "--skip-prior-regressions"),
        "49 BM-PROD5.4C.3A contract remains passing": ("scripts/check_prod5_4c_3a_persistent_postgres_transfer_contract.py", "--skip-prior-regressions"),
        "50 BM-PROD5.4C.2 contract remains passing": ("scripts/check_prod5_4c_2_sqlite_postgres_transfer_contract.py", "--skip-prior-regressions"),
    }
    for label, command in prior.items():
        check((BACKEND / command[0]).is_file(), label)
        if not arguments.skip_prior_regressions:
            run_prior(*command)
    check("check_prod5_5a_postgres_backup_restore_contract.py" in prod0 and prod0_mandatory_count(prod0) == 55, "51 full PROD0 preserves 55 mandatory checks")

    assert len(CHECKS) == 51, len(CHECKS)
    print("PASS: BM-PROD5.5A PostgreSQL logical backup and disposable restore contract (51 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
