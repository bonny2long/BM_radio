from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


BACKEND = Path(__file__).resolve().parents[1]
LIVE = BACKEND / "scripts" / "check_prod5_5b_cold_postgres_recovery.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.postgres_backup_restore import BackupRestoreBlockedError  # noqa: E402
from app.postgres_recovery import (  # noqa: E402
    RECOVERY_APPROVAL,
    RecoveryBlockedError,
    pre_recovery_gate,
    recovery_status,
    verify_retained_recovery_input,
)


def _json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _preflight() -> int:
    result = pre_recovery_gate()
    print(f"BM-PROD5.5B PRE-RECOVERY GATE: {result['gate']}")
    _json(result)
    print("Active PostgreSQL stopped: NO")
    return 0 if result["gate"] == "PASS" else 2


def _verify_backup() -> int:
    result = verify_retained_recovery_input(inspect_archive=True)
    _json(result)
    return 0


def _rehearse(token: str) -> int:
    if token != RECOVERY_APPROVAL:
        raise RecoveryBlockedError("exact cold-recovery interruption approval token is required")
    result = subprocess.run(
        [sys.executable, str(LIVE), "--approve", token],
        cwd=str(BACKEND),
        shell=False,
    )
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage BM Radio approval-gated PostgreSQL recovery proofs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight", help="validate cold-recovery prerequisites without an outage")
    subparsers.add_parser("verify-backup", help="independently verify the accepted retained backup")
    rehearse = subparsers.add_parser("rehearse", help="run the exact-token-gated cold recovery rehearsal")
    rehearse.add_argument("--approve", required=True, metavar="TOKEN")
    subparsers.add_parser("status", help="show active and task-scoped recovery resource status")
    arguments = parser.parse_args()
    try:
        if arguments.command == "preflight":
            return _preflight()
        if arguments.command == "verify-backup":
            return _verify_backup()
        if arguments.command == "rehearse":
            return _rehearse(str(arguments.approve))
        _json(recovery_status())
        return 0
    except (RecoveryBlockedError, BackupRestoreBlockedError) as exc:
        print("BM-PROD5.5B RECOVERY OPERATION: BLOCKED")
        print(f"reason: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
