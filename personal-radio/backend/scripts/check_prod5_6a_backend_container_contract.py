from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys


BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
DOCKERFILE = BACKEND / "Dockerfile"
DOCKERIGNORE = BACKEND / ".dockerignore"
RUNTIME_REQUIREMENTS = BACKEND / "requirements-runtime.txt"
DEV_REQUIREMENTS = BACKEND / "requirements-dev.txt"
ENV_EXAMPLE = BACKEND / ".env.container.example"
SERVER = BACKEND / "app" / "server.py"
HEALTHCHECK = BACKEND / "app" / "container_healthcheck.py"
MAIN = BACKEND / "app" / "main.py"
RECOVERY = BACKEND / "app" / "postgres_recovery.py"
LIVE = BACKEND / "scripts" / "check_prod5_6a_backend_container.py"
REPORT_5B = PROJECT / "docs" / "production-upgrade" / "BM-PROD5.5B_Cold_PostgreSQL_Disaster_Recovery_Rehearsal.md"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
CHECKS: list[str] = []
RESOURCE_PREFIX = "bm-prod5-6a-"


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
    parser = argparse.ArgumentParser(description="BM-PROD5.6A deterministic backend-container contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    arguments = parser.parse_args()

    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")
    runtime = RUNTIME_REQUIREMENTS.read_text(encoding="utf-8")
    dev = DEV_REQUIREMENTS.read_text(encoding="utf-8")
    environment = ENV_EXAMPLE.read_text(encoding="utf-8")
    server = SERVER.read_text(encoding="utf-8")
    health = HEALTHCHECK.read_text(encoding="utf-8")
    app_main = MAIN.read_text(encoding="utf-8")
    recovery = RECOVERY.read_text(encoding="utf-8")
    live = LIVE.read_text(encoding="utf-8")
    report_5b = REPORT_5B.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")
    run_arguments = function_source(live, "_backend_run_arguments")
    hardening = function_source(live, "_assert_hardening")
    build_run = function_source(live, "build_and_run")
    cleanup = function_source(live, "_cleanup")
    image_inspection = function_source(live, "_inspect_image")
    negative = function_source(live, "_negative_canary")

    check("bc444f3b06c8006189d63607c139f6e90672d7f9" in report_5b and "intentional uncommitted working-tree changes" not in report_5b, "1 5.5B report records bc444f3 implementation commit")
    check(DOCKERFILE.is_file(), "2 production Dockerfile exists")
    check(DOCKERIGNORE.is_file(), "3 build-context protection exists")
    check(RUNTIME_REQUIREMENTS.is_file() and DEV_REQUIREMENTS.is_file() and "-r requirements-runtime.txt" in dev, "4 runtime/dev dependency split exists")
    check(".env" in dockerignore and "!.env.container.example" in dockerignore, "5 real .env files are excluded")
    check(".local_postgres/" in dockerignore, "6 local PostgreSQL state is excluded")
    check(".local_backups/" in dockerignore and "*.dump" in dockerignore, "7 local backups are excluded")
    check(all(pattern in dockerignore for pattern in ("bm_radio.db", "*.db", "*.sqlite", "*.sqlite3")), "8 SQLite databases are excluded")
    check("media/" in dockerignore and "cache/" in dockerignore, "9 media and cache are excluded")
    check(".git/" in dockerignore, "10 Git metadata is excluded")
    check("reload=True" not in server and "--reload" not in dockerfile and "reload=False" in server, "11 reload mode is prohibited")
    check('CMD ["python", "-m", "app.server"]' in dockerfile and SERVER.is_file(), "12 deterministic production runner exists")
    check("USER 10001:10001" in dockerfile and "useradd" in dockerfile, "13 explicit non-root image user exists")
    check("--uid 10001" in dockerfile and "--gid 10001" in dockerfile, "14 stable UID/GID is documented")
    check("EXPOSE 8094" in dockerfile and 'BM_RADIO_API_PORT != 8094' in server, "15 port 8094 is explicit")
    check("HEALTHCHECK" in dockerfile and "app.container_healthcheck" in dockerfile, "16 Docker healthcheck exists")
    check('payload.get("database_ready") is True' in health, "17 healthcheck requires database readiness")
    check("TIMEOUT_SECONDS = 3.0" in health and "timeout=TIMEOUT_SECONDS" in health, "18 healthcheck timeout is bounded")
    check("APP_ENV=production" in environment and "postgresql+psycopg://" in environment, "19 production PostgreSQL example exists")
    check("target.is_postgresql" in server and "production container requires postgresql+psycopg" in server, "20 production SQLite is rejected")
    check("BM_RADIO_CACHE_ROOT=/app-cache" in environment and "BM_RADIO_MUSIC_ROOT=/media/Music" in environment, "21 cache is outside media")
    check(all(path in environment for path in ("/media/Music", "/media/Audiobooks/Library", "/media/Books")), "22 container media paths are explicit")
    check("readonly" in run_arguments and all(path in run_arguments for path in ("/media/Music", "/media/Audiobooks/Library", "/media/Books")), "23 live media mounts are read-only")
    check('"--read-only"' in run_arguments and "ReadonlyRootfs" in hardening, "24 live root filesystem is read-only")
    check('"--tmpfs"' in run_arguments and '"/tmp:rw' in run_arguments, "25 writable /tmp exception is explicit")
    check("target=/app-cache" in run_arguments and "cache mount is not writable" in hardening.lower(), "26 writable cache exception is explicit")
    check("source bind mount detected" in hardening and "source_bind_mount" in hardening, "27 source-code bind mounts are prohibited")
    check("real environment/source/media mount detected" in hardening and "real_env_mount" in hardening, "28 real .env mounts are prohibited")
    check("COPY --chown=10001:10001 migrations/ ./migrations/" in dockerfile and "alembic.ini" in dockerfile, "29 migrations are included in the image")
    check("create_all" not in server + app_main, "30 startup has no create_all")
    check("stamp" not in server.lower() + app_main.lower(), "31 startup has no Alembic stamp")
    check("alembic upgrade" not in server.lower() + app_main.lower() and "command.upgrade" not in server + app_main, "32 startup has no automatic Alembic upgrade")
    check("unreachable_postgresql" in build_run and RESOURCE_MARKER(live, "missing"), "33 unreachable PostgreSQL negative canary exists")
    check("production_sqlite" in build_run and "sqlite:////tmp/bm-prod5-6a.sqlite" in build_run, "34 production SQLite negative canary exists")
    check("stale_postgresql" in build_run and "bm_radio_stale" in live, "35 stale PostgreSQL negative canary exists")
    check('POSTGRES_IMAGE = "postgres:16"' in live, "36 disposable DB uses PostgreSQL 16")
    check("active_target_used" in build_run and "CONTAINER_NAME.startswith(RESOURCE_PREFIX)" in live, "37 disposable DB cannot be the active resource")
    check('RESOURCE_PREFIX = "bm-prod5-6a-"' in live, "38 task resource prefixes are isolated")
    check('"network", "create", "--driver", "bridge"' in build_run and '"--network"' in run_arguments, "39 a user-defined bridge network is required")
    check('"127.0.0.1::8094"' in run_arguments and "Docker port was not published to loopback" in live, "40 backend publication is loopback-only")
    check('config.get("User") != "10001:10001"' in hardening, "41 live backend non-root identity is required")
    check('host.get("ReadonlyRootfs") is not True' in hardening, "42 live read-only root is verified")
    check("expected_ro" in hardening and 'get("RW") is not False' in hardening, "43 synthetic media read-only state is verified")
    check("real environment/source/media mount detected" in hardening and "personal-radio\\\\media" in hardening, "44 real media mounts are prohibited")
    check(all(path in build_run for path in ("/api/health", "/api/library/summary", "/api/library/artists", "/api/library/albums", "/api/search", "/api/playlists", "/api/stations/", "/api/audiobooks/", "/control")), "45 HTTP read canaries exist")
    check('method="POST"' in build_run and "Container Canary" in build_run, "46 HTTP write canary exists")
    check("verify_recovered_database(host_url, retained)" in build_run and "rows_restored" in build_run and "digests_restored" in build_run, "47 exact write cleanup is required")
    check('"restart", api_name' in build_run and "_wait_healthy(api_name)" in build_run, "48 container restart proof exists")
    check("image filesystem inspection" in image_inspection and "bad_paths" in image_inspection and "personal_path_hits" in image_inspection, "49 image filesystem secret inspection exists")
    check('"history", "--no-trunc"' in image_inspection and "forbidden_history" in image_inspection, "50 image history secret inspection exists")
    check('before != after' in build_run and "active_postgresql_unchanged" in build_run, "51 active PostgreSQL before/after equality is required")
    check('before != after' in build_run and "sqlite_unchanged" in build_run, "52 SQLite before/after equality is required")
    check("backend_env_sha256" in recovery and "protected_hashes()" in live and "environment_and_evidence_unchanged" in build_run, "53 .env before/after equality is required")
    check("recovery_rehearsal_verification_sha256" in live and "protected_hashes()" in live, "54 durable evidence before/after equality is required")
    check("name != CONTAINER_NAME" in cleanup and "network.startswith(RESOURCE_PREFIX)" in cleanup, "55 cleanup cannot delete active PostgreSQL resources")
    check("published_remotely" in image_inspection and '"push"' not in build_run, "56 local image is never pushed")
    check("truenas" not in live.lower() and "push" not in build_run.lower(), "57 no TrueNAS deployment occurs")

    prior = {
        "58 BM-PROD5.5B contract remains passing": ("scripts/check_prod5_5b_cold_postgres_recovery_contract.py", "--skip-prior-regressions"),
        "59 BM-PROD5.5A contract remains passing": ("scripts/check_prod5_5a_postgres_backup_restore_contract.py", "--skip-prior-regressions"),
        "60 BM-PROD5.4C.3B contract remains passing": ("scripts/check_prod5_4c_3b_active_postgres_adoption_contract.py", "--skip-prior-regressions"),
    }
    for label, command in prior.items():
        check((BACKEND / command[0]).is_file(), label)
        if not arguments.skip_prior_regressions:
            run_prior(*command)
    check("check_prod5_6a_backend_container_contract.py" in prod0 and prod0_mandatory_count(prod0) >= 57, "61 full PROD0 preserves at least 57 mandatory checks")

    assert len(CHECKS) == 61, len(CHECKS)
    print("PASS: BM-PROD5.6A production backend container contract (61 checks)")
    return 0


def RESOURCE_MARKER(source: str, marker: str) -> bool:
    return f"{RESOURCE_PREFIX}{marker}" in source or marker in source


if __name__ == "__main__":
    raise SystemExit(main())
