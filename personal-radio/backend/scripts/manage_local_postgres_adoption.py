from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.local_postgres_adoption import (  # noqa: E402
    ADOPT_CONFIRMATION,
    DESTROY_CONFIRMATION,
    PERSISTENT_TRANSFER_CONFIRMATION,
    AdoptionBlockedError,
    adopt_persistent_target,
    create_persistent_target,
    create_verified_persistent_transfer,
    database_verification,
    destroy_persistent_target,
    migrate_persistent_target,
    persistent_transfer_preflight,
    preflight,
    rollback_configuration,
    status,
)


SAFETY_OUTCOME = (
    "Persistent PostgreSQL created: NO",
    "Persistent Docker volume created: NO",
    "backend/.env modified: NO",
    "Active DB switch performed: NO",
    "Real SQLite mutated: NO",
    "Media accessed: NO",
)


def _json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _preflight() -> int:
    result = preflight()
    if result["transfer_required"]:
        result = persistent_transfer_preflight()
        print(f"BM-PROD5.4C.3A PRE-CREATION GATE: {result['gate']}")
        print("Explicit operator approval received: NO")
    else:
        print(f"PRE-ADOPTION GATE: {result['gate']}")
    for reason in result["blockers"]:
        print(f"reason: {reason}")
    _json(result)
    for line in SAFETY_OUTCOME:
        print(line)
    return 0 if result["gate"] == "PASS" else 2


def _status() -> int:
    print("PERSISTENT LOCAL POSTGRESQL STATUS (read-only)")
    _json(status())
    return 0


def _mutating_result(label: str, operation: Any) -> int:
    result = operation()
    print(f"{label}: PASS")
    _json(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded BM Radio persistent local PostgreSQL adoption operator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight", help="strictly read-only pre-adoption safety gate")
    subparsers.add_parser("status", help="read-only persistent-target status")
    subparsers.add_parser("create", help="create the approved named-volume PostgreSQL target")
    transfer_parser = subparsers.add_parser("persistent-transfer", help="create and populate the exact persistent target after approval")
    transfer_parser.add_argument("--confirm", required=True, help=f"must exactly equal {PERSISTENT_TRANSFER_CONFIRMATION}")
    subparsers.add_parser("migrate", help="run explicit Alembic upgrade head and verify")
    subparsers.add_parser("verify", help="read-only persistent PostgreSQL verification")
    adopt_parser = subparsers.add_parser("adopt", help="switch only backend/.env database target after verification")
    adopt_parser.add_argument("--confirm", required=True, help=f"must exactly equal {ADOPT_CONFIRMATION}")
    subparsers.add_parser("rollback-config", help="hash-safe restoration of the ignored backend/.env snapshot")
    destroy_parser = subparsers.add_parser("destroy", help="irreversibly remove stopped persistent PostgreSQL data")
    destroy_parser.add_argument("--confirm", required=True, help=f"must exactly equal {DESTROY_CONFIRMATION}")
    args = parser.parse_args()

    try:
        if args.command == "preflight":
            return _preflight()
        if args.command == "status":
            return _status()
        if args.command == "create":
            return _mutating_result("CREATE", create_persistent_target)
        if args.command == "persistent-transfer":
            return _mutating_result("PERSISTENT-TRANSFER", lambda: create_verified_persistent_transfer(args.confirm))
        if args.command == "migrate":
            return _mutating_result("MIGRATE", migrate_persistent_target)
        if args.command == "verify":
            print("VERIFY: PASS")
            _json(database_verification())
            return 0
        if args.command == "adopt":
            return _mutating_result("ADOPT", lambda: adopt_persistent_target(args.confirm))
        if args.command == "rollback-config":
            return _mutating_result("ROLLBACK-CONFIG", rollback_configuration)
        if args.command == "destroy":
            return _mutating_result(
                "DESTROY",
                lambda: destroy_persistent_target(args.confirm, announce=lambda preview: (print("DESTROY PREVIEW"), _json(preview))),
            )
    except AdoptionBlockedError as exc:
        print(f"{args.command.upper()} GATE: BLOCKED")
        print(f"reason: {exc}")
        return 2
    raise AssertionError("unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())
