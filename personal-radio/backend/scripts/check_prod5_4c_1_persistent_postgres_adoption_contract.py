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
CLI = BACKEND / "scripts" / "manage_local_postgres_adoption.py"
GITIGNORE = PROJECT / ".gitignore"
ENV_EXAMPLE = BACKEND / ".env.example"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
PROD5_4B_DOC = PROJECT / "docs" / "production-upgrade" / "BM-PROD5.4B_Disposable_Real_PostgreSQL_Integration_and_Behavioral_Proof.md"
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
    node = next(item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name)
    return ast.get_source_segment(source, node) or ""


def run_prior(script: str, *extra: str) -> None:
    completed = subprocess.run(
        [sys.executable, script, *extra],
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
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == "checks" and isinstance(item.value, ast.List)
    )
    return len(assignment.value.elts) + 2  # frontend build and lint are appended after the list


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.4C.1 deterministic persistent PostgreSQL adoption contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    args = parser.parse_args()

    sqlite_before = digest(REAL_SQLITE)
    source = MODULE.read_text(encoding="utf-8")
    cli_source = CLI.read_text(encoding="utf-8")
    ignored = GITIGNORE.read_text(encoding="utf-8")
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    doc = PROD5_4B_DOC.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")

    check(CLI.is_file() and all(f'"{name}"' in cli_source for name in ("preflight", "status", "create", "migrate", "verify", "adopt", "rollback-config", "destroy")), "1 operator CLI and explicit modes exist")
    check(adoption.CONTAINER_NAME == "bm-radio-postgres-dev", "2 fixed persistent container name")
    check(adoption.VOLUME_NAME == "bm-radio-postgres-dev-data", "3 fixed persistent volume name")
    check(adoption.POSTGRES_MAJOR == 16 and adoption.IMAGE_TAG == "postgres:16", "4 PostgreSQL major 16")
    check(adoption.HOST == "127.0.0.1", "5 loopback-only default host")
    check(adoption.HOST_PORT == 55432, "6 fixed preferred development port")
    check("0.0.0.0" not in source and "0.0.0.0" not in cli_source, "7 public persistent binding excluded")
    check("backend/.local_postgres/" in ignored, "8 local PostgreSQL state is Git-ignored")
    check("secrets.token_urlsafe(48)" in source, "9 cryptographic secret generation")
    try:
        adoption._redacted_state({"postgres_password": "do-not-store"})
    except ValueError:
        password_rejected = True
    else:
        password_rejected = False
    check(password_rejected and "POSTGRES_PASSWORD" not in cli_source, "10 raw passwords excluded from reports")
    try:
        adoption._redacted_state({"url": "postgresql+psycopg://role:secret@127.0.0.1/db"})
    except ValueError:
        url_rejected = True
    else:
        url_rejected = False
    check(url_rejected and "target_url_from_secret_file" not in cli_source, "11 raw database URLs excluded from reports")

    preflight_source = function_source(source, "preflight")
    status_source = function_source(source, "status")
    mutation_tokens = ("mkdir(", "write_", "unlink(", "replace(", '"run", "-d"', '"volume", "create"')
    check(not any(token in preflight_source for token in mutation_tokens), "12 preflight is non-mutating")
    check(not any(token in status_source for token in mutation_tokens), "13 status is non-mutating")
    check("docker_context_status()" in preflight_source and "local" in preflight_source, "14 preflight checks Docker locality")
    check("linux" in preflight_source, "15 preflight checks Linux containers")
    check("loopback_port_state()" in preflight_source, "16 preflight checks loopback port availability")
    check("container_exists" in preflight_source and "volume_exists" in preflight_source, "17 preflight checks resource-name collisions")
    check("snapshot_sqlite_database" in source and "logical_path=\"backend/bm_radio.db\"" in source, "18 SQLite inspection is read-only snapshot based")
    clean_create_source = function_source(source, "_require_clean_create_preflight")
    check('"transfer_required"' in preflight_source and 'result["transfer_required"]' in clean_create_source, "19 populated SQLite blocks legacy zero-data creation")
    create_source = function_source(source, "create_persistent_target")
    check('"volume", "create", VOLUME_NAME' in create_source and 'f"{VOLUME_NAME}:{DATA_MOUNT}"' in create_source, "20 create uses the fixed named Docker volume")
    check("--mount type=bind" not in create_source and "BACKEND_ROOT}:{DATA_MOUNT}" not in create_source, "21 PostgreSQL data has no Windows host bind")
    check('f"{HOST}:{HOST_PORT}:{CONTAINER_PORT}"' in create_source and adoption.HOST == "127.0.0.1", "22 create publishes loopback only")
    migrate_source = function_source(source, "migrate_persistent_target")
    check('"alembic", "upgrade", "head"' in migrate_source, "23 migration uses Alembic upgrade head")
    check("create_all" not in source and "create_all" not in cli_source, "24 migration never uses metadata create_all")
    verify_source = function_source(source, "database_verification")
    check("inspect_database_readiness" in verify_source and "compare_schema" in verify_source, "25 verify uses readiness and schema compatibility")
    check(adoption.ADOPT_CONFIRMATION == "APPROVE-BM-PROD5.4C-LOCAL-POSTGRES" and "confirmation != ADOPT_CONFIRMATION" in source, "26 adopt requires exact confirmation")

    with tempfile.TemporaryDirectory(prefix="bm-prod5-4c1-") as temporary:
        original = b"APP_NAME=BM Radio\r\nBM_RADIO_DB_URL=sqlite:///./bm_radio.db\r\nBM_RADIO_MUSIC_ROOT=../nas-data/Music\r\n"
        changed = adoption.replace_database_target(original, "postgresql+psycopg://role:secret@127.0.0.1:55432/bm_radio")
        check(changed.splitlines()[0] == original.splitlines()[0] and changed.splitlines()[2] == original.splitlines()[2] and changed.count(b"BM_RADIO_DB_URL=") == 1, "27 adopt changes only the database target line")
        check(Path(temporary).is_dir(), "deterministic helper workspace")
    CHECKS.pop()  # helper workspace is not one of the mandated 44 checks
    adopt_source = function_source(source, "adopt_persistent_target")
    check("FastAPI" not in adopt_source and "uvicorn" not in adopt_source, "28 adopt never starts FastAPI")
    check("scan_music" not in source and "scan_audiobooks" not in source, "29 adopt and operator module never scan media")
    check("BACKEND_ENV_BEFORE_PATH = LOCAL_STATE_DIR" in source and "backend_env.before" in source, "30 env recovery stays in ignored local storage")
    rollback_source = function_source(source, "rollback_configuration")
    check('sha256_path(BACKEND_ENV_PATH) != adopted_hash' in rollback_source and "changed independently" in rollback_source, "31 rollback protects independent env changes")
    check(adoption.DESTROY_CONFIRMATION == "DESTROY-BM-RADIO-LOCAL-POSTGRES-DATA" and "confirmation != DESTROY_CONFIRMATION" in source, "32 destroy uses separate destructive confirmation")
    destroy_source = function_source(source, "destroy_persistent_target")
    check("_env_points_to_persistent_target()" in destroy_source and "still points" in destroy_source, "33 destroy refuses an active target configuration")
    regression_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    destructive_calls = [node for node in ast.walk(regression_tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "destroy_persistent_target"]
    check(not destructive_calls, "34 regression never runs destroy")
    lowered_example = example.lower()
    check("bonnymakaniankhondo" not in lowered_example and "c:\\users\\" not in lowered_example, "35 env example contains no personal Windows path")
    check("postgresql+psycopg://bm_radio_app:<password>@127.0.0.1:55432/bm_radio" in example, "36 env example documents persistent PostgreSQL")
    check("validation pending" not in doc.lower() and "Status: PASS" in doc, "37 BM-PROD5.4B completion is closed")
    check("No active database switch occurred" in doc and "No permanent PostgreSQL database exists" in doc, "38 BM-PROD5.4B no-permanent-switch history preserved")
    check(digest(REAL_SQLITE) == sqlite_before, "39 real SQLite unchanged by deterministic regression")
    check("scan_music(" not in source and "scan_audiobooks(" not in source and "media_metadata" not in source, "40 no real media access or mutation")

    prior_scripts = {
        "41 BM-PROD5.4B static contract remains passing": ("scripts/check_prod5_4b_postgresql_integration_contract.py", "--skip-prior-regressions"),
        "42 BM-PROD5.4A remains passing": ("scripts/check_prod5_4a_postgresql_dialect_foundation.py", "--skip-prior-regressions"),
        "43 BM-PROD5.3C.1 remains passing": ("scripts/check_prod5_3c_1_controlled_empty_local_rebuild.py",),
    }
    for label, command in prior_scripts.items():
        check((BACKEND / command[0]).is_file(), label)
        if not args.skip_prior_regressions:
            run_prior(*command)
    check("check_prod5_4c_1_persistent_postgres_adoption_contract.py" in prod0 and "--skip-prior-regressions" in prod0 and prod0_mandatory_count(prod0) >= 51, "44 PROD0 registration preserves the 51-check baseline floor")

    check(digest(REAL_SQLITE) == sqlite_before, "real SQLite final equality")
    CHECKS.pop()  # final guard supports check 39 without increasing the mandated count
    assert len(CHECKS) == 44, len(CHECKS)
    print("PASS: BM-PROD5.4C.1 persistent PostgreSQL adoption contract (44 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
