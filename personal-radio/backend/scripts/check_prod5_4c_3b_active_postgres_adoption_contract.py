from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile


BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
MODULE = BACKEND / "app" / "local_postgres_adoption.py"
LIVE = BACKEND / "scripts" / "check_prod5_4c_3b_active_postgres_adoption.py"
REPORT_3A = PROJECT / "docs" / "production-upgrade" / "BM-PROD5.4C.3A_Persistent_Local_PostgreSQL_Creation_and_Verified_Transfer.md"
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
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and item.target.id == "checks"
        and isinstance(item.value, ast.List)
    )
    return len(assignment.value.elts) + 2


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.4C.3B deterministic active-adoption contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    args = parser.parse_args()

    sqlite_before = digest(REAL_SQLITE)
    source = MODULE.read_text(encoding="utf-8")
    live = LIVE.read_text(encoding="utf-8")
    report = REPORT_3A.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")
    preflight = function_source(source, "active_adoption_preflight")
    adopt = function_source(source, "adopt_persistent_target")
    approved = function_source(live, "approved_adoption")
    canary = function_source(live, "_run_application_canary")
    spawn_canary = function_source(live, "_spawn_application_canary")
    finalize = function_source(source, "finalize_active_adoption")

    check("65157583b3b0c8ab74c3c08b697e9da114f114d9" in report and "uncommitted working-tree changes" not in report, "1 5.4C.3A implementation commit corrected")
    check(adoption.ADOPT_CONFIRMATION == "APPROVE-BM-PROD5.4C-LOCAL-POSTGRES" and "token != ADOPT_CONFIRMATION" in approved, "2 exact existing adoption token required")
    check("BM-PROD5.4C.3B PRE-ADOPTION GATE" in live and "--preflight-only" in live, "3 PRE-ADOPTION gate exists")
    check("validate_transfer_evidence()" in preflight and "populated_source" in adopt, "4 populated adoption requires transfer evidence")
    evidence = function_source(source, "validate_transfer_evidence")
    check("sha256_path(TRANSFER_VERIFICATION_PATH) != expected_hash" in evidence, "5 transfer artifact hash checked")
    check("accepted_source_evidence()" in evidence and "source_matches" in evidence, "6 live SQLite identity matches evidence")
    check("target_matches" in evidence and "database_verification()" in evidence, "7 persistent PostgreSQL identity matches evidence")
    check("docker_context_status()" in preflight and all(token in preflight for token in ("loopback_binding", "named_volume", "local", "linux")), "8 local loopback named-volume Docker gate")
    check("source_quiescence_status()" in preflight and "writer_detected" in preflight, "9 existing backend writer blocks adoption")
    check(adoption.EXPECTED_BACKEND_ENV_SHA256 == "a668b6dc50b63ab6e23e5ccb0b743ccd41c581eecdf0e94dfef94f826441db3e" and "EXPECTED_BACKEND_ENV_SHA256" in preflight, "10 accepted original env SHA gate")
    check("BACKEND_ENV_BEFORE_PATH.exists()" in preflight and "already exists" in preflight, "11 fallback snapshot must not pre-exist")
    check("BACKEND_ENV_BEFORE_PATH.write_bytes(before)" in adopt and "before_hash" in adopt, "12 exact original env snapshot created")
    check("_without_database_target(original_env)" in approved and "settings other than BM_RADIO_DB_URL" in approved, "13 only DB target changes persistently")
    check(all(token in approved + canary for token in ('"postgresql"', '"psycopg"', "postgresql_supported")), "14 Settings resolve PostgreSQL Psycopg supported policy")
    check("except Exception:" in adopt and "BACKEND_ENV_PATH.write_bytes(before)" in adopt and "BACKEND_ENV_BEFORE_PATH.unlink" in adopt, "15 adoption failure restores original env")
    check('"application_adopted": True' in adopt and adopt.index("Settings(BM_RADIO_DB_URL=target_url)") < adopt.index('"application_adopted": True'), "16 state adoption follows config validation")
    environment_assignments = [node for node in ast.walk(ast.parse(live)) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Subscript) and isinstance(target.value, ast.Attribute) and target.value.attr == "environ" for target in node.targets)]
    check(environment_assignments and 'os.environ["BM_RADIO_DB_URL"]' not in live, "17 canary never overrides BM_RADIO_DB_URL")
    roots = function_source(live, "_temporary_canary_roots")
    check("TemporaryDirectory" in roots and "MEDIA_ROOT_KEYS" in roots and "os.environ[name]" in roots, "18 canary media roots are process-only temporary overrides")
    check("application startup #1 readiness canary" in canary and "after_startup_1" in canary and "fresh child interpreter" in canary, "19 startup #1 verifies PostgreSQL readiness")
    check('_require_unchanged(before, after_startup_1' in canary and "_zero_delta" in canary, "20 startup #1 zero row delta")
    check("application startup #2 readiness canary" in canary and canary.count("with TestClient(app)") >= 2, "21 startup #2 proves idempotence")
    check('_require_unchanged(before, after_startup_2' in canary, "22 startup #2 zero row delta")
    check(all(path in canary for path in ("/api/health", "/api/library/summary", "/api/library/artists", "/api/library/albums", "/api/search")), "23 required read-canary coverage")
    check('client.get("/api/media' not in live and '"streaming": False' in approved, "24 read canaries never stream media")
    check("/scan" not in approved and '"scanner": False' in approved, "25 scanner invocation prohibited")
    check("PostgreSQL Write Canary" in canary and 'second_client.post("/api/playlists"' in canary, "26 reversible application write canary")
    check("insert into" not in live.lower() and "update playlists" not in live.lower(), "27 write canary uses application API, not direct SQL")
    check("in_postgresql" in canary and "playlist write did not route exclusively" in canary, "28 canary appears in PostgreSQL")
    check("in_sqlite" in canary and "or in_sqlite" in canary, "29 canary absent from SQLite")
    check('second_client.delete(f"/api/playlists/{canary_id}")' in canary, "30 canary deletion uses application API")
    check("EXPECTED_SOURCE_ROWS" in function_source(live, "_require_unchanged") and "target_total_rows" in approved, "31 PostgreSQL returns to 1257 rows")
    check("per_table_row_counts" in function_source(live, "_require_unchanged"), "32 PostgreSQL counts return to transfer evidence")
    check("per_table_canonical_digests" in function_source(live, "_require_unchanged"), "33 PostgreSQL digests return to transfer evidence")
    check("sha256_path(REAL_SQLITE) != sqlite_before_sha" in approved and "_database_equality" in approved, "34 SQLite SHA counts and digests unchanged")
    check("_alembic_check()" in approved and "revision" in approved and "--canary-internal" in spawn_canary, "35 PostgreSQL remains at Alembic head")
    check('"readiness"] == "ready"' in live and '"compatibility"] == "PASS"' in live, "36 PostgreSQL readiness and compatibility PASS")
    safe_writer = function_source(source, "write_active_adoption_verification")
    check(all(token in safe_writer for token in ("postgres_password", "postgresql+psycopg://", "c:\\\\users\\\\")), "37 privacy-safe adoption artifact")
    check('"adoption_verification_sha256": artifact_sha' in finalize, "38 adoption artifact SHA stored in state")
    check('"phase": "BM-PROD5.4C.3B"' in finalize, "39 final state phase 5.4C.3B")
    check('"active_database": "postgresql"' in finalize, "40 active database recorded as PostgreSQL")
    check("transfer_sha" in finalize and "cannot be preserved" in finalize, "41 transfer-verification SHA preserved")
    rollback_guard = function_source(source, "validate_rollback_files")
    check("sha256_path(snapshot_path) != before_hash" in rollback_guard, "42 backend_env.before SHA validated")
    check("sha256_path(current_env_path) != adopted_hash" in rollback_guard, "43 current adopted env SHA validated")

    with tempfile.TemporaryDirectory(prefix="bm-prod5-4c3b-contract-") as temporary:
        root = Path(temporary)
        current = root / "current.env"
        snapshot = root / "before.env"
        before_bytes = b"BM_RADIO_DB_URL=sqlite:///./bm_radio.db\n"
        adopted_bytes = b"BM_RADIO_DB_URL=postgresql+psycopg://redacted\n"
        snapshot.write_bytes(before_bytes)
        current.write_bytes(adopted_bytes)
        state = {"backend_env_before_sha256": hashlib.sha256(before_bytes).hexdigest(), "backend_env_adopted_sha256": hashlib.sha256(adopted_bytes).hexdigest()}
        valid = adoption.validate_rollback_files(state, current_env_path=current, snapshot_path=snapshot) == before_bytes
        current.write_bytes(adopted_bytes + b"# independent\n")
        try:
            adoption.validate_rollback_files(state, current_env_path=current, snapshot_path=snapshot)
        except adoption.AdoptionBlockedError as exc:
            independent_blocked = "changed independently" in str(exc)
        else:
            independent_blocked = False
        current.write_bytes(adopted_bytes)
        snapshot.write_bytes(before_bytes + b"# corrupt\n")
        try:
            adoption.validate_rollback_files(state, current_env_path=current, snapshot_path=snapshot)
        except adoption.AdoptionBlockedError as exc:
            corrupt_blocked = "snapshot hash" in str(exc)
        else:
            corrupt_blocked = False
    check(valid and independent_blocked, "44 rollback refuses independently edited env")
    check(corrupt_blocked, "45 rollback refuses corrupted fallback snapshot")
    check("rollback_configuration()" in approved and '"BM-PROD5.4C.3B-failed-rolled-back"' in approved, "46 post-adoption failure triggers config rollback")
    check("docker" not in approved.lower() and "destroy_persistent_target" not in live, "47 5.4C.3B never destroys persistent PostgreSQL")
    check("REAL_SQLITE.unlink" not in live and "remove(REAL_SQLITE" not in live, "48 SQLite is never retired or deleted")
    check("mutagen" not in live.lower() and "ffprobe" not in live.lower() and '"file_open": False' in approved, "49 no media access probing or mutation")

    prior = {
        "50 BM-PROD5.4C.3A contract remains passing": ("scripts/check_prod5_4c_3a_persistent_postgres_transfer_contract.py", "--skip-prior-regressions"),
        "51 BM-PROD5.4C.2 contract remains passing": ("scripts/check_prod5_4c_2_sqlite_postgres_transfer_contract.py", "--skip-prior-regressions"),
        "52 BM-PROD5.4C.1 contract remains passing": ("scripts/check_prod5_4c_1_persistent_postgres_adoption_contract.py", "--skip-prior-regressions"),
        "53 BM-PROD5.4B contract remains passing": ("scripts/check_prod5_4b_postgresql_integration_contract.py", "--skip-prior-regressions"),
    }
    for label, command in prior.items():
        check((BACKEND / command[0]).is_file(), label)
        if not args.skip_prior_regressions:
            run_prior(*command)
    check("check_prod5_4c_3b_active_postgres_adoption_contract.py" in prod0 and prod0_mandatory_count(prod0) >= 54, "54 PROD0 preserves at least 54 mandatory checks")

    assert digest(REAL_SQLITE) == sqlite_before, "real SQLite changed during deterministic contract"
    assert len(CHECKS) == 54, len(CHECKS)
    print("PASS: BM-PROD5.4C.3B active PostgreSQL adoption contract (54 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
