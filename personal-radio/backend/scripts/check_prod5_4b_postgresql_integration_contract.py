from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
HARNESS = BACKEND / "scripts" / "check_prod5_4b_disposable_postgresql_integration.py"
GATE = PROJECT / "scripts" / "check_prod0_baseline.py"
GITIGNORE = PROJECT / ".gitignore"
CHECKS: list[str] = []


def require(source: str, token: str, label: str) -> None:
    assert token in source, f"missing {label}: {token}"
    CHECKS.append(label)


def run_prior(script: str, *extra: str) -> None:
    result = subprocess.run(
        [sys.executable, script, *extra],
        cwd=BACKEND,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=900,
    )
    assert result.returncode == 0 and "PASS" in result.stdout, result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.4B static PostgreSQL integration safety contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    args = parser.parse_args()

    assert HARNESS.is_file()
    source = HARNESS.read_text(encoding="utf-8")
    gate = GATE.read_text(encoding="utf-8")
    ignored = GITIGNORE.read_text(encoding="utf-8")
    required = {
        "local Docker context requirement": "local_docker_preflight",
        "remote Docker rejection": 'host.startswith(("tcp://", "ssh://"))',
        "Linux container requirement": 'server_os != "linux"',
        "loopback-only publication": '"-p", "127.0.0.1::5432"',
        "dynamic loopback verification": 'raw.startswith("127.0.0.1:")',
        "random ephemeral credentials": "secrets.token_urlsafe(32)",
        "environment-file secret input": '"--env-file", str(env_file)',
        "raw URL environment transport": 'env["BM_RADIO_DB_URL"] = url',
        "protected SQLite snapshot": "snapshot_sqlite_database(REAL_DB",
        "protected env snapshot": "ENV_FILES",
        "tracked configuration snapshot": "PROTECTED_CONFIG",
        "empty synthetic roots": '"music_root", "audiobook_root", "book_root", "cache_root", "artwork_cache_root"',
        "separate disposable databases": 'for key in ("fresh", "stale", "roundtrip")',
        "online Alembic upgrade": 'alembic(url, "upgrade", "head")',
        "Alembic drift check": 'alembic(url, "check")',
        "live schema comparison": "compare_schema(engine)",
        "isolated application child": '"--child-behavior"',
        "startup idempotence": 'checks["second_startup"] = "PASS"',
        "primary-key test": 'checks["primary_key_generation"]',
        "foreign-key test": 'checks["foreign_key_rejection"]',
        "unique test": 'checks["unique_rejection"]',
        "UNKNOWN default test": 'checks["server_default_unknown"]',
        "boolean test": 'checks["boolean_roundtrip"]',
        "timestamp test": 'checks["timestamp_roundtrip"]',
        "rollback test": 'checks["transaction_rollback"]',
        "concurrent-session test": 'checks["concurrent_sessions"]',
        "service behavior matrix": 'checks["recording_occurrence_projection"]',
        "HTTP behavior matrix": 'checks["http_matrix"]',
        "separate downgrade and re-upgrade": 'alembic(url, "downgrade", "base")',
        "unreachable readiness": "DATABASE_UNREACHABLE",
        "finally cleanup": "finally:",
        "container cleanup": 'docker("rm", "-f", container_name',
        "closed-port proof": '"port_closed": port is None or port_closed(port)',
        "credential scan": '"credential_scan": credential_scan(TMP_ROOT, password)',
        "opt-in keep-on-failure": 'parser.add_argument("--keep-on-failure", action="store_true"',
        "exact SQLite equality": '"sqlite_exact_equality": before["sqlite"] == after["sqlite"]',
        "exact env equality": '"env_exact_equality": before["env"] == after["env"]',
        "no scanner invocation": 'checks["scanner_started"] = False',
        "no real media access": 'checks["real_media_access"] = False',
        "sanitized evidence report": "postgresql_integration_report.json",
        "home-path diagnostic redaction": 'replace(str(Path.home()), "<home>")',
        "tmpfs PostgreSQL storage": '"--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=512m"',
    }
    for label, token in required.items():
        require(source, token, label)
    migration_source = (BACKEND / "app" / "migration_contract.py").read_text(encoding="utf-8")
    require(migration_source, "get_pk_constraint", "dialect-neutral primary-key reflection")
    baseline_source = (BACKEND / "migrations" / "versions" / "0001_current_schema_baseline.py").read_text(encoding="utf-8")
    require(baseline_source, "DROP TYPE IF EXISTS thumbvalue", "PostgreSQL enum downgrade cleanup")

    for token in ("scan_music(", "scan_audiobooks(", "0.0.0.0::5432", "docker-compose", "compose.yaml"):
        assert token not in source, f"forbidden live-harness token: {token}"
    CHECKS.append("scanner and deployment exclusions")
    assert "backend/tmp_tests/" in ignored
    CHECKS.append("generated evidence ignored")
    require(gate, "check_prod5_4b_postgresql_integration_contract.py", "PROD0 registration")
    require(gate, "--skip-prior-regressions", "PROD0 nonrecursive prior policy")
    assert not any((PROJECT / name).exists() for name in ("Dockerfile", "compose.yaml", "docker-compose.yml"))
    CHECKS.append("no production deployment files")

    if not args.skip_prior_regressions:
        run_prior("scripts/check_prod5_4a_postgresql_dialect_foundation.py", "--skip-prior-regressions")
        run_prior("scripts/check_prod5_3c_1_controlled_empty_local_rebuild.py")
        CHECKS.extend(("BM-PROD5.4A remains passing", "BM-PROD5.3C.1 remains passing"))

    assert len(CHECKS) >= 45, len(CHECKS)
    print(f"PASS: BM-PROD5.4B PostgreSQL integration static contract ({len(CHECKS)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
