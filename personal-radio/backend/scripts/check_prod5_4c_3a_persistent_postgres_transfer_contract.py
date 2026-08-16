from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path
import subprocess
import sys


BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
ADOPTION = BACKEND / "app" / "local_postgres_adoption.py"
TRANSFER = BACKEND / "app" / "database_transfer.py"
CLI = BACKEND / "scripts" / "manage_local_postgres_adoption.py"
REPORT_5_4C_2 = PROJECT / "docs" / "production-upgrade" / "BM-PROD5.4C.2_Populated_SQLite_to_PostgreSQL_Transfer_Rehearsal.md"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
REAL_SQLITE = BACKEND / "bm_radio.db"
CHECKS: list[str] = []

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import local_postgres_adoption as adoption  # noqa: E402


def check(condition: bool, label: str) -> None:
    assert condition, label
    CHECKS.append(label)


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    return ast.get_source_segment(source, node) or ""


def run_prior(script: str, *arguments: str) -> None:
    completed = subprocess.run(
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
    assert completed.returncode == 0 and "PASS" in completed.stdout, completed.stdout


def prod0_mandatory_count(source: str) -> int:
    tree = ast.parse(source)
    main = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "main")
    assignment = next(
        item for item in ast.walk(main)
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and item.target.id == "checks"
        and isinstance(item.value, ast.List)
    )
    return len(assignment.value.elts) + 2


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.4C.3A deterministic persistent-transfer contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    args = parser.parse_args()

    sqlite_before = digest(REAL_SQLITE)
    source = ADOPTION.read_text(encoding="utf-8")
    transfer = TRANSFER.read_text(encoding="utf-8")
    cli = CLI.read_text(encoding="utf-8")
    report = REPORT_5_4C_2.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")
    preflight = function_source(source, "persistent_transfer_preflight")
    operation = function_source(source, "create_verified_persistent_transfer")
    evidence = function_source(source, "validate_transfer_evidence")
    adopt = function_source(source, "adopt_persistent_target")

    check("5fa5db5122bcca19fe8260ac4f8527da71e75c4f" in report and "working-tree implementation is not committed" not in report, "1 5.4C.2 implementation commit corrected")
    check(adoption.CONTAINER_NAME == "bm-radio-postgres-dev" and adoption.VOLUME_NAME == "bm-radio-postgres-dev-data", "2 canonical persistent resource names")
    check(adoption.PERSISTENT_TRANSFER_CONFIRMATION == "APPROVE-BM-PROD5.4C.3A-PERSISTENT-CREATION" and "confirmation != PERSISTENT_TRANSFER_CONFIRMATION" in operation, "3 exact approval token required")
    mutation_tokens = ("mkdir(", "write_", "unlink(", "replace(", '"run", "-d"', '"volume", "create"')
    check(not any(token in preflight for token in mutation_tokens), "4 pre-creation mode is non-mutating")
    check(adoption.EXPECTED_SOURCE_SHA256 == "e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619" and "EXPECTED_SOURCE_SHA256" in function_source(source, "accepted_source_evidence"), "5 exact source SHA gate")
    check(adoption.EXPECTED_SOURCE_SCHEMA_FINGERPRINT == "bd34f4cf845273954a42a4febd9d0340ae52d221f8f07b9b77eeb3cd04125678" and "EXPECTED_SOURCE_SCHEMA_FINGERPRINT" in source, "6 exact schema fingerprint gate")
    check(adoption.EXPECTED_SOURCE_ROWS == 1257 and "EXPECTED_SOURCE_ROWS" in source, "7 exact source row-count gate")
    check("per_table_canonical_digests" in function_source(source, "accepted_source_evidence") and "accepted_match" in source, "8 exact source digest gate")
    check("if not expected_identity or not accepted_match or not foreign_keys_valid" in source and "BLOCKED" not in operation, "9 changed source blocks before creation")
    check("source_quiescence_status()" in preflight and "writer_detected" in preflight, "10 source quiescence check")
    base_preflight = function_source(source, "preflight")
    check("docker_context_status()" in base_preflight and 'docker["local"]' in base_preflight and 'docker["linux"]' in base_preflight, "11 local Linux Docker context gate")
    check("container_exists" in base_preflight and adoption.CONTAINER_NAME in source, "12 container collision gate")
    check("volume_exists" in base_preflight and adoption.VOLUME_NAME in source, "13 volume collision gate")
    check("loopback_port_state()" in base_preflight and "occupied" in base_preflight, "14 port collision gate")
    check(operation.index("confirmation != PERSISTENT_TRANSFER_CONFIRMATION") < operation.index("create_verified_sqlite_backup") and 'label="pre_persistent_postgres"' in operation, "15 fresh verified backup after approval")
    check("read_only_sqlite_url_for_path(backup)" in operation and "transfer_database(source_engine, target_engine)" in operation, "16 transfer reads backup rather than live SQLite")
    check("generate_secret()" in operation and "secrets.token_urlsafe(48)" in source, "17 credentials generated cryptographically")
    check("write_secret_environment(generate_secret())" in operation and "POSTGRES_ENV_PATH = LOCAL_STATE_DIR" in source, "18 credentials stay in ignored local state")
    check('"volume", "create", VOLUME_NAME' in operation and 'f"{VOLUME_NAME}:{DATA_MOUNT}"' in operation, "19 named Docker volume")
    check("--mount type=bind" not in operation and "BACKEND_ROOT}:{DATA_MOUNT}" not in operation, "20 Windows database bind mount prohibited")
    check('f"{HOST}:{HOST_PORT}:{CONTAINER_PORT}"' in operation and adoption.HOST == "127.0.0.1", "21 loopback-only PostgreSQL publication")
    check(adoption.POSTGRES_MAJOR == 16 and adoption.IMAGE_TAG == "postgres:16" and 'initial["server_major"] != POSTGRES_MAJOR' in operation, "22 PostgreSQL 16 required")
    check('_run_alembic(target_url, "upgrade", "head")' in operation and "create_all" not in operation and '"stamp"' not in operation, "23 target schema through Alembic only")
    check('initial["application_table_count"] != 0' in operation and 'migrated["application_row_count"] == 0' in operation, "24 target empty before transfer")
    check("from .database_transfer import" in operation and "transfer_database" in operation, "25 accepted transfer engine reused")
    check("_table(table_name).insert(), rows" in transfer and "primary_key" in transfer, "26 exact primary-key preservation")
    check("source_counts != target_counts" in transfer and "per_table_row_counts" in operation, "27 per-table count equality")
    check("source_digests != target_digests" in transfer and "per_table_canonical_digests" in operation, "28 canonical digest equality")
    check("foreign_key_violations" in transfer and '"foreign_key_validation": "PASS"' in transfer, "29 foreign-key validation")
    check("_repair_sequences" in transfer and "sequence_repairs" in operation, "30 sequence repair")
    check("_insert_rollback_sequence_canary" in transfer and "next_id_rollback_canary" in operation, "31 next-ID rollback canary")
    check('_run_alembic(target_url, "check")' in operation and '"alembic_drift": "PASS"' in operation, "32 Alembic drift check")
    check('_docker("stop", CONTAINER_NAME' in operation and '_docker("start", CONTAINER_NAME' in operation, "33 persistent stop/start proof")
    check("restart_verification" in operation and "per_table_row_counts" in operation, "34 post-restart count equality")
    check("restart_verification" in operation and "per_table_canonical_digests" in operation, "35 post-restart digest equality")
    check("TRANSFER_VERIFICATION_PATH" in source and "_write_transfer_verification(artifact)" in operation, "36 safe transfer verification artifact")
    safe_writer = function_source(source, "_write_transfer_verification")
    check(all(token in safe_writer for token in ("postgres_password", "postgresql+psycopg://", "c:\\\\users\\\\")) and "raw" not in operation.lower(), "37 artifact excludes secrets and raw data")
    check('"transfer_verification_sha256": artifact_sha' in operation and "sha256_path(TRANSFER_VERIFICATION_PATH)" in evidence, "38 artifact hash stored and validated")
    check('"application_adopted": False' in operation and 'state.get("application_adopted") is not False' in evidence, "39 state requires application_adopted false")
    check("BACKEND_ENV_PATH.read_bytes() != env_before" in operation and "replace_database_target" not in operation, "40 backend env exact equality")
    check("source_after != source_before" in operation and "accepted_source_evidence()" in operation, "41 live SQLite exact equality")
    check("FastAPI" not in operation and "uvicorn" not in operation, "42 no FastAPI persistent startup")
    check("scan_music(" not in operation and "scan_audiobooks(" not in operation, "43 no scanner invocation")
    check("mutagen" not in operation.lower() and "ffprobe" not in operation.lower() and "media" not in operation.lower(), "44 no media access or probing")
    check("if not transfer_verified" in operation and '_docker("volume", "rm", VOLUME_NAME)' in operation, "45 pre-verification cleanup is scoped")
    check("if not transfer_verified" in operation and operation.count('_docker("volume", "rm", VOLUME_NAME)') == 2, "46 post-verification failure retains volume")
    check("validate_transfer_evidence()" in adopt and "populated_source" in adopt, "47 populated adoption requires transfer verification")
    check("source_matches" in evidence and "live SQLite does not match" in evidence, "48 evidence must match live SQLite")
    check("target_matches" in evidence and "persistent PostgreSQL does not match" in evidence, "49 evidence must match persistent PostgreSQL")
    contract_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    forbidden_calls = [node for node in ast.walk(contract_tree) if isinstance(node, ast.Call) and getattr(node.func, "id", "") in {"create_verified_persistent_transfer", "adopt_persistent_target"}]
    check(not forbidden_calls and 'args.command == "adopt"' in cli, "50 contract never executes transfer or adoption")

    prior = {
        "51 BM-PROD5.4C.2 contract remains passing": ("scripts/check_prod5_4c_2_sqlite_postgres_transfer_contract.py", "--skip-prior-regressions"),
        "52 BM-PROD5.4C.1 contract remains passing": ("scripts/check_prod5_4c_1_persistent_postgres_adoption_contract.py", "--skip-prior-regressions"),
        "53 BM-PROD5.4B contract remains passing": ("scripts/check_prod5_4b_postgresql_integration_contract.py", "--skip-prior-regressions"),
        "54 BM-PROD5.4A remains passing": ("scripts/check_prod5_4a_postgresql_dialect_foundation.py", "--skip-prior-regressions"),
    }
    for label, command in prior.items():
        check((BACKEND / command[0]).is_file(), label)
        if not args.skip_prior_regressions:
            run_prior(*command)
    check("check_prod5_4c_3a_persistent_postgres_transfer_contract.py" in prod0 and prod0_mandatory_count(prod0) >= 53, "55 PROD0 preserves the 53-check baseline floor")

    assert digest(REAL_SQLITE) == sqlite_before, "real SQLite changed during deterministic contract"
    assert len(CHECKS) == 55, len(CHECKS)
    print("PASS: BM-PROD5.4C.3A persistent PostgreSQL transfer contract (55 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
