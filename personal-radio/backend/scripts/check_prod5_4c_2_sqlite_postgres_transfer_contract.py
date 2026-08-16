from __future__ import annotations

import argparse
import ast
from datetime import datetime
import enum
import hashlib
from pathlib import Path
import subprocess
import sys

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, Integer, String


BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
MODULE = BACKEND / "app" / "database_transfer.py"
CLI = BACKEND / "scripts" / "transfer_sqlite_to_postgres.py"
REHEARSAL = BACKEND / "scripts" / "check_prod5_4c_2_sqlite_postgres_transfer_rehearsal.py"
ADOPTION = BACKEND / "app" / "local_postgres_adoption.py"
ADOPTION_DOC = PROJECT / "docs" / "production-upgrade" / "BM-PROD5.4C.1_Persistent_Local_PostgreSQL_Adoption_Tooling_and_Preflight.md"
TRANSFER_DOC = PROJECT / "docs" / "production-upgrade" / "BM-PROD5.4C.2_Populated_SQLite_to_PostgreSQL_Transfer_Rehearsal.md"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
REAL_DB = BACKEND / "bm_radio.db"
CHECKS: list[str] = []

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import models  # noqa: E402
from app.database_transfer import canonical_value, dependency_order  # noqa: E402


def check(condition: bool, label: str) -> None:
    assert condition, label
    CHECKS.append(label)


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
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
        item for item in ast.walk(main)
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == "checks" and isinstance(item.value, ast.List)
    )
    return len(assignment.value.elts) + 2


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.4C.2 deterministic transfer contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    args = parser.parse_args()

    real_before = digest(REAL_DB)
    source = MODULE.read_text(encoding="utf-8")
    cli = CLI.read_text(encoding="utf-8")
    rehearsal = REHEARSAL.read_text(encoding="utf-8")
    adoption = ADOPTION.read_text(encoding="utf-8")
    adoption_doc = ADOPTION_DOC.read_text(encoding="utf-8")
    transfer_doc = TRANSFER_DOC.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")

    check(MODULE.is_file() and "class TransferPlan" in source and "def transfer_database" in source, "1 transfer module exists")
    check(CLI.is_file() and all(f'"{mode}"' in cli for mode in ("inspect", "rehearse", "transfer", "verify")), "2 transfer CLI exists")
    check(REHEARSAL.is_file() and "PRE-TRANSFER GATE" in rehearsal, "3 real transfer rehearsal exists")
    check("mode=ro" in source and "read_only_sqlite_url_for_path" in rehearsal, "4 source is read-only and protected by verified backup")
    check("source_connection.backup(backup_connection)" in source, "5 SQLite online backup API")
    check("create_verified_sqlite_backup(REAL_DB" in rehearsal and "read_only_sqlite_url_for_path(backup)" in rehearsal, "6 transfer reads the verified backup")
    check('target_engine.dialect.name != "postgresql"' in source and "BM_RADIO_TRANSFER_TARGET_URL" in cli, "7 explicit PostgreSQL target required")
    check("readiness.current_revision != readiness.head_revision" in source, "8 target must be at Alembic head")
    check("require_empty" in source and "PostgreSQL transfer target must be empty" in source, "9 empty transfer target required")
    order = dependency_order()
    check(len(order) == 21 and set(order) == set(models.Base.metadata.tables), "10 deterministic FK-aware table order")
    lowered = source.lower() + rehearsal.lower()
    check("disable trigger" not in lowered, "11 FK enforcement is never disabled")
    check("session_" + "replication_role" not in lowered, "12 no replication-role bypass")
    check("dict(row)" in source and "_table(table_name).insert(), rows" in source, "13 primary keys are preserved")
    check("select(table)" in source and "for column in table.columns" in source, "14 all application columns are copied")
    check("isinstance(column.type, Boolean)" in source and canonical_value(Column(Boolean), 1) == ["boolean", True], "15 explicit boolean normalization")
    check("astimezone(UTC)" in source and canonical_value(Column(DateTime(timezone=True)), datetime(2026, 8, 15, 12, 0)) == ["datetime", "2026-08-15T12:00:00.000000"], "16 explicit datetime normalization")
    check("invalid enum value" in source and canonical_value(Column(Enum(models.ThumbValue)), models.ThumbValue.up) == ["enum", "up"], "17 explicit enum validation")
    check(canonical_value(Column(String), '{"b": 2, "a": 1}') == ["text", '{"b": 2, "a": 1}'], "18 JSON-as-text is not reformatted")
    check(canonical_value(Column(String), None) == ["null", None] and canonical_value(Column(String), "") == ["text", ""], "19 null and empty-string semantics remain distinct")
    check("def canonical_value" in source and '"table": table_name' in source and '"columns":' in source, "20 canonical per-row serializer")
    check("def canonical_table_digest" in source and "sha256" in function_source(source, "canonical_table_digest"), "21 per-table canonical digest")
    check("source_counts != target_counts" in source, "22 count equality required")
    check("source_digests != target_digests" in source, "23 digest equality required")
    check("pg_get_serial_sequence" in source and "setval" in source, "24 PostgreSQL sequences repaired")
    check("_insert_rollback_sequence_canary" in source and "table.insert().returning" in source and "nested.rollback()" in source, "25 next-ID insert/rollback canary")
    check("with target_engine.begin() as target" in source and "transactional transfer failed" in source, "26 transactional fail-closed transfer")
    check('alembic(urls[name], "check")' in rehearsal, "27 Alembic drift check")
    check("compare_schema(engine)" in source and "compare_schema(engine)" in rehearsal, "28 schema compatibility verification")
    check("inspect_database_readiness" in source and 'readiness.status != READY' in source, "29 readiness verification")
    check('"-p", "127.0.0.1::5432"' in rehearsal and 'raw.startswith("127.0.0.1:")' in rehearsal, "30 disposable PostgreSQL loopback only")
    check("secrets.token_urlsafe(40)" in rehearsal and '"--env-file", str(env_file)' in rehearsal, "31 ephemeral file-transported credentials")
    check("finally:" in function_source(rehearsal, "main") and 'docker("rm", "-f", container' in rehearsal, "32 cleanup occurs in finally")
    container_start = rehearsal[rehearsal.index('docker(\n            "run"'):rehearsal.index("container_started = True")]
    check('"--name", container' in container_start and "bm-radio-postgres-dev" not in container_start, "33 rehearsal never uses persistent resource names")
    check('BACKEND / ".env"' in rehearsal and 'BACKEND / ".env").write' not in rehearsal, "34 backend env is snapshot-only")
    check("live_before == live_after" in rehearsal and "protected_state_exact_equality" in rehearsal, "35 real SQLite mutation protection")
    check("scan_music(" not in rehearsal and "scan_audiobooks(" not in rehearsal, "36 no scanner invocation")
    check("mutagen" not in rehearsal.lower() and "ffprobe" not in rehearsal.lower(), "37 no media metadata or probe invocation")
    check('"synthetic_roots"' in rehearsal and 'APP_ENV": "test"' in rehearsal, "38 startup uses synthetic empty roots")
    check('("transfer", "startup_canary")' in rehearsal and "urls[\"startup_canary\"]" in rehearsal, "39 separately imported startup database")
    check("with TestClient(app) as second_client" in rehearsal and "first_counts == second_counts" in rehearsal, "40 second-startup seed idempotence")
    check('client.get("/api/media' not in rehearsal and '"media_streamed": False' in rehearsal, "41 read/API canary never streams media")
    check("password in serialized" in rehearsal and "Path.home()" in rehearsal and "raw DB rows" not in rehearsal, "42 privacy-safe report validation")
    check("live_before == live_after_cleanup" in rehearsal and "per_table_canonical_digests" in rehearsal, "43 exact live-source before/after protection")
    check('"transfer_required"' in adoption and "validate_transfer_evidence()" in adoption, "44 populated source requires verified evidence before direct adoption")
    check("persistent transfer verification" in adoption and "does not match" in adoption, "45 populated adoption fails closed on mismatched evidence")
    check("5fa5db5122bcca19fe8260ac4f8527da71e75c4f" in transfer_doc and "working-tree implementation is not committed" not in transfer_doc, "46 historical report has actual implementation commit")

    prior = {
        "47 BM-PROD5.4C.1 contract remains passing": ("scripts/check_prod5_4c_1_persistent_postgres_adoption_contract.py", "--skip-prior-regressions"),
        "48 BM-PROD5.4B contract remains passing": ("scripts/check_prod5_4b_postgresql_integration_contract.py", "--skip-prior-regressions"),
        "49 BM-PROD5.4A remains passing": ("scripts/check_prod5_4a_postgresql_dialect_foundation.py", "--skip-prior-regressions"),
        "50 BM-PROD5.3C.1 remains passing": ("scripts/check_prod5_3c_1_controlled_empty_local_rebuild.py",),
    }
    for label, command in prior.items():
        check((BACKEND / command[0]).is_file(), label)
        if not args.skip_prior_regressions:
            run_prior(*command)
    check("check_prod5_4c_2_sqlite_postgres_transfer_contract.py" in prod0 and prod0_mandatory_count(prod0) >= 52, "51 PROD0 registration preserves the 52-check baseline floor")

    assert digest(REAL_DB) == real_before, "real SQLite changed during deterministic contract"
    assert len(CHECKS) == 51, len(CHECKS)
    print("PASS: BM-PROD5.4C.2 SQLite-to-PostgreSQL transfer contract (51 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
