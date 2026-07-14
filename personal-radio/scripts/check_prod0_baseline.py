from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Result:
    name: str
    status: str
    details: str = ""


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
FRONTEND = PROJECT_ROOT / "frontend"


def npm_executable() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def command_text(command: list[str]) -> str:
    return " ".join(command)


def print_failure_output(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print("--- stdout ---")
        print(result.stdout.rstrip())
    if result.stderr:
        print("--- stderr ---")
        print(result.stderr.rstrip())


def run_command(name: str, command: list[str], cwd: Path) -> tuple[Result, subprocess.CompletedProcess[str] | None]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except FileNotFoundError as exc:
        details = f"missing executable for {command_text(command)}: {exc}"
        print(f"[FAIL] {name} - {details}")
        return Result(name, "FAIL", details), None

    if result.returncode == 0:
        print(f"[PASS] {name}")
        return Result(name, "PASS"), result

    details = f"exit code {result.returncode} from {command_text(command)}"
    print(f"[FAIL] {name} - {details}")
    print_failure_output(result)
    return Result(name, "FAIL", details), result


def run_lint() -> Result:
    name = "frontend lint"
    npm = npm_executable()
    if not shutil.which(npm):
        details = f"{npm} not found; install Node/npm before running the gate"
        print(f"[FAIL] {name} - {details}")
        return Result(name, "FAIL", details)
    if not (FRONTEND / "node_modules").is_dir():
        details = "frontend/node_modules is missing; run npm install explicitly before this gate"
        print(f"[FAIL] {name} - {details}")
        return Result(name, "FAIL", details)

    result = subprocess.run(
        [npm, "run", "lint"],
        cwd=str(FRONTEND),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    warning_count = len(re.findall(r": warning ", output))
    if result.returncode == 0:
        print(f"[PASS] {name} - 0 errors, {warning_count} warnings")
        return Result(name, "PASS", f"0 errors, {warning_count} warnings")

    details = f"exit code {result.returncode}; warnings observed before failure: {warning_count}"
    print(f"[FAIL] {name} - {details}")
    print_failure_output(result)
    return Result(name, "FAIL", details)


def run_npm_build() -> Result:
    name = "frontend production build"
    npm = npm_executable()
    if not shutil.which(npm):
        details = f"{npm} not found; install Node/npm before running the gate"
        print(f"[FAIL] {name} - {details}")
        return Result(name, "FAIL", details)
    if not (FRONTEND / "node_modules").is_dir():
        details = "frontend/node_modules is missing; run npm install explicitly before this gate"
        print(f"[FAIL] {name} - {details}")
        return Result(name, "FAIL", details)

    result, _ = run_command(name, [npm, "run", "build"], FRONTEND)
    return result


def main() -> int:
    if not BACKEND.is_dir() or not FRONTEND.is_dir():
        print("[FAIL] BM-PROD0 prerequisites - run this from a checkout containing personal-radio/backend and frontend")
        return 1

    checks: list[tuple[str, list[str], Path]] = [
        ("python compileall", [sys.executable, "-m", "compileall", "app", "scripts"], BACKEND),
        ("AA music manifest import", [sys.executable, "scripts/check_aa_manifest_music_import.py"], BACKEND),
        ("canonical music scan roots", [sys.executable, "scripts/check_prod1_1_canonical_music_roots.py"], BACKEND),
        ("production config contract", [sys.executable, "scripts/check_prod1_2a_config_contract.py"], BACKEND),
        ("runtime API safety", [sys.executable, "scripts/check_prod1_2b_runtime_safety.py"], BACKEND),
        ("scan-run foundation", [sys.executable, "scripts/check_prod1_3a_scan_run_foundation.py"], BACKEND),
        ("music scan reconciliation", [sys.executable, "scripts/check_prod1_3b_music_scan_reconciliation.py"], BACKEND),
        ("audiobook scan progress safety", [sys.executable, "scripts/check_prod1_3c1_audiobook_scan_progress_safety.py"], BACKEND),
        ("AA audiobook manifest import", [sys.executable, "scripts/check_aa_manifest_audiobook_import.py"], BACKEND),
        ("audiobook multi-book ordering", [sys.executable, "scripts/check_audiobook_multibook_ordering.py"], BACKEND),
        ("audiobook progress reset", [sys.executable, "scripts/check_audiobook_progress_reset.py"], BACKEND),
        ("safe media roots", [sys.executable, "scripts/check_bm_radio_safe_roots.py"], BACKEND),
        ("frontend mojibake", [sys.executable, "scripts/check_frontend_mojibake.py"], BACKEND),
    ]

    results: list[Result] = []
    for name, command, cwd in checks:
        result, _ = run_command(name, command, cwd)
        results.append(result)

    results.append(run_npm_build())
    results.append(run_lint())

    skipped = [
        Result("imported metadata mojibake", "SKIP", "requires initialized or populated local BM Radio database"),
        Result("station genre families M5.1", "SKIP", "depends on populated library/profile fixture state"),
        Result("station logic M5", "SKIP", "depends on populated library/profile fixture state"),
        Result("station logic M5.2", "SKIP", "depends on populated library/profile fixture state"),
    ]
    for item in skipped:
        print(f"[SKIP] {item.name} - {item.details}")

    passed = sum(1 for result in results if result.status == "PASS")
    failed = sum(1 for result in results if result.status == "FAIL")

    print()
    if failed:
        print("BM-PROD0 BASELINE GATE: FAIL")
    else:
        print("BM-PROD0 BASELINE GATE: PASS")
    print(f"Mandatory: {passed} passed, {failed} failed")
    print(f"Optional/integration: {len(skipped)} skipped")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
