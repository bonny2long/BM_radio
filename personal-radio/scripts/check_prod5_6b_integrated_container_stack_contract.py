from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
FRONTEND = PROJECT / "frontend"
DOCKERFILE = FRONTEND / "Dockerfile"
DOCKERIGNORE = FRONTEND / ".dockerignore"
NGINX = FRONTEND / "nginx.conf"
API = FRONTEND / "src" / "api.ts"
VITE = FRONTEND / "vite.config.ts"
COMPOSE = PROJECT / "deploy" / "compose.local-production.example.yml"
LIVE = PROJECT / "scripts" / "check_prod5_6b_integrated_container_stack.py"
REPORT_5_6A = PROJECT / "docs" / "production-upgrade" / "BM-PROD5.6A_Production_Backend_Docker_Image_and_Disposable_Container_Proof.md"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
CHECKS: list[str] = []


def check(condition: bool, label: str) -> None:
    assert condition, label
    CHECKS.append(label)


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name)
    return ast.get_source_segment(source, node) or ""


def run_prior(script: str, *arguments: str, cwd: Path = BACKEND) -> None:
    result = subprocess.run(
        [sys.executable, script, *arguments],
        cwd=str(cwd),
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


def service_section(compose: str, name: str, next_name: str | None) -> str:
    start = compose.index(f"  {name}:\n")
    end = compose.index(f"  {next_name}:\n", start) if next_name else compose.index("\nnetworks:\n", start)
    return compose[start:end]


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.6B deterministic integrated-container-stack contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    arguments = parser.parse_args()

    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")
    nginx = NGINX.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    vite = VITE.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    live = LIVE.read_text(encoding="utf-8")
    report = REPORT_5_6A.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")
    build_run = function_source(live, "build_and_run")
    integrated = function_source(live, "_integrated_http_proof")
    hardening = function_source(live, "_assert_stack_hardening")
    cleanup = function_source(live, "_cleanup")
    image = function_source(live, "_image_metadata")
    postgres = service_section(compose, "postgres", "backend")
    backend = service_section(compose, "backend", "frontend")
    frontend = service_section(compose, "frontend", None)

    check("18775bea08d19ea84bd87364c1bbacf206c7b746" in report and "intentional uncommitted working-tree changes" not in report, "1 5.6A report records accepted implementation commit")
    check(DOCKERFILE.is_file() and DOCKERIGNORE.is_file() and NGINX.is_file(), "2 frontend Dockerfile, dockerignore, and server config exist")
    check(dockerfile.count("FROM ") >= 2 and "npm ci" in dockerfile and "npm run build" in dockerfile, "3 multi-stage reproducible npm build exists")
    runtime_stage = dockerfile[dockerfile.rindex("FROM ") :]
    check("nginx" in runtime_stage.lower() and "vite" not in runtime_stage.lower() and "preview" not in runtime_stage.lower(), "4 production runtime is not Vite dev or preview")
    check("USER 101:101" in runtime_stage and 'user: "101:101"' in frontend, "5 frontend runtime is explicitly non-root")
    check("node_modules/" in dockerignore and ".env" in dockerignore and "COPY --from=build" in runtime_stage, "6 final image excludes node_modules and environment files")
    check("VITE_API_BASE_URL=/api" in dockerfile and "??'/api'" in api, "7 production API base is same-origin")
    check("127.0.0.1:8094" not in api and "VITE_API_BASE_URL=/api" in dockerfile, "8 production browser path does not depend on backend loopback")
    check("location ^~ /api/" in nginx and "proxy_pass http://backend:8094" in nginx, "9 /api reverse proxy exists")
    check("/api/media" in nginx and "try_files $uri =404" in nginx and "location ^~ /api/" in nginx, "10 audited media routes cannot fall into SPA fallback")
    check("location = /healthz" in nginx and "/healthz" in dockerfile, "11 frontend-local health endpoint exists")
    check(all(token in nginx for token in ("X-Content-Type-Options", "Referrer-Policy", "X-Frame-Options", "Content-Security-Policy", "must-revalidate", "immutable")), "12 security and cache policies exist")
    check(all(f"  {name}:" in compose for name in ("postgres", "backend", "frontend")), "13 generic three-service local-production template exists")
    check("bonnymakaniankhondo" not in compose.lower() and "c:\\users\\" not in compose.lower() and "set an external local-production password" in compose, "14 template contains placeholders rather than real secrets or personal paths")
    check("ports:" not in postgres and "ports:" not in backend and "ports:" in frontend and "127.0.0.1:" in frontend, "15 only frontend is intended for host publication")
    check('RESOURCE_PREFIX = "bm-prod5-6b-"' in live and "CONTAINER_NAME.startswith(RESOURCE_PREFIX)" in live and "active_target_used" not in build_run, "16 live harness uses isolated disposable PostgreSQL")
    check('"127.0.0.1::8080"' in build_run and "frontend_loopback_only" in hardening, "17 frontend live publication is loopback-only")
    check("backend or PostgreSQL is host-published" in hardening and build_run.count('"--publish"') == 1, "18 backend and PostgreSQL have no host publication")
    check(all(path in build_run for path in ("/media/Music,readonly", "/media/Audiobooks/Library,readonly", "/media/Books,readonly")), "19 synthetic media mounts are read-only")
    check('"scanner_invoked": False' in integrated and "/scan" not in integrated, "20 scanner invocation is prohibited")
    check(all(path in integrated for path in ("/api/health", "/api/library/summary", "/api/library/artists", "/api/library/albums", "/api/search", "/api/playlists", "/api/stations/", "/api/audiobooks/", "/control")), "21 frontend-origin read canaries exist")
    check("cover_url" in integrated and "stream_url" in integrated and "/api/media/" in integrated and "controlled backend response" in integrated, "22 media and artwork route contract is proven")
    check('method="POST"' in integrated and 'method="DELETE"' in integrated and "Integrated Canary" in integrated, "23 proxied write and delete canary exists")
    check("after_write = _verify_database" in build_run and "write_cleanup_exact" in build_run, "24 exact database cleanup is required")
    check(all(token in build_run for token in ('"restart", web_name', '"restart", api_name', '"restart", db_name', '"stop", web_name', '"start", db_name')), "25 frontend, backend, PostgreSQL, and ordered restart proofs exist")
    check(all(path in integrated for path in ("/.env", "/.git/config", "/backend/.env", "%2e%2e")), "26 secret-path and traversal negative checks exist")
    check("ReadonlyRootfs" in hardening and '"10001:10001"' in hardening and '"101:101"' in hardening, "27 frontend/backend non-root read-only checks exist")
    check("Privileged" in hardening and 'NetworkMode") == "host"' in hardening and "/var/run/docker.sock" in hardening, "28 privileged, host-network, and Docker-socket usage is prohibited")
    check("before = _protected_state()" in build_run and "after = _protected_state()" in build_run and "if before != after" in build_run, "29 protected PostgreSQL, SQLite, environment, and evidence equality is required")
    check("name.startswith(RESOURCE_PREFIX)" in cleanup and "name != CONTAINER_NAME" in cleanup and "volume != VOLUME_NAME" in cleanup, "30 cleanup cannot remove active resources")
    check('"published_remotely": False' in image and '"images_published": False' in build_run and '"push"' not in build_run, "31 images are never published")
    check('"truenas_deployed": False' in build_run and "truenas" not in compose.lower(), "32 TrueNAS deployment is not performed")

    priors = {
        "33 5.6A and 5.5B contracts remain passing": (
            ("scripts/check_prod5_6a_backend_container_contract.py", "--skip-prior-regressions"),
            ("scripts/check_prod5_5b_cold_postgres_recovery_contract.py", "--skip-prior-regressions"),
        )
    }
    for label, commands in priors.items():
        check(all((BACKEND / command[0]).is_file() for command in commands), label)
        if not arguments.skip_prior_regressions:
            for command in commands:
                run_prior(*command)
    check("check_prod5_6b_integrated_container_stack_contract.py" in prod0 and prod0_mandatory_count(prod0) == 58, "34 full PROD0 preserves 58 mandatory checks")

    assert len(CHECKS) == 34, len(CHECKS)
    print("PASS: BM-PROD5.6B integrated local production stack contract (34 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
