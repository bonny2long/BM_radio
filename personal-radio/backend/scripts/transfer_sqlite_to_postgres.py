from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


BACKEND = Path(__file__).resolve().parents[1]
REAL_SQLITE = BACKEND / "bm_radio.db"
TARGET_ENV = "BM_RADIO_TRANSFER_TARGET_URL"
TRANSFER_CONFIRMATION = "TRANSFER-TO-EXPLICIT-POSTGRES-TARGET"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database_dialect import require_supported_database_url  # noqa: E402
from app.database_transfer import (  # noqa: E402
    TransferBlockedError,
    database_inventory,
    inventory_counts,
    inventory_digests,
    sqlite_foreign_key_violations,
    transfer_database,
    verify_database_transfer,
)
from app.migration_contract import engine_for_url, read_only_sqlite_url_for_path  # noqa: E402
from app.sqlite_adoption import snapshot_sqlite_database  # noqa: E402


def _source_engine(path: Path):
    if not path.is_file():
        raise TransferBlockedError("SQLite source file is missing")
    return engine_for_url(read_only_sqlite_url_for_path(path))


def _target_engine():
    raw = os.environ.get(TARGET_ENV)
    if not raw:
        raise TransferBlockedError(f"explicit PostgreSQL target is required through {TARGET_ENV}")
    target = require_supported_database_url(raw)
    if not target.is_postgresql or target.driver != "psycopg":
        raise TransferBlockedError("transfer target must use postgresql+psycopg")
    return engine_for_url(raw), target.safe_display


def _inspect(path: Path) -> dict:
    engine = _source_engine(path)
    try:
        snapshot = snapshot_sqlite_database(path, logical_path=path.name)
        inventory = database_inventory(engine)
    finally:
        engine.dispose()
    violations = sqlite_foreign_key_violations(path)
    return {
        "logical_source": path.name,
        "integrity": snapshot.integrity_check,
        "quick_check": snapshot.quick_check,
        "readiness": snapshot.readiness_status,
        "revision": snapshot.current_revision,
        "compatibility": snapshot.compatibility,
        "application_tables": len(snapshot.application_tables),
        "application_rows": sum(inventory_counts(inventory).values()),
        "per_table_row_counts": inventory_counts(inventory),
        "per_table_canonical_digests": inventory_digests(inventory),
        "foreign_key_check": "PASS" if not violations else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="BM Radio SQLite-to-PostgreSQL transfer utility")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    inspect_parser = subparsers.add_parser("inspect", help="read-only privacy-safe SQLite inventory")
    inspect_parser.add_argument("--source", type=Path, default=REAL_SQLITE)
    for mode in ("rehearse", "transfer", "verify"):
        subparser = subparsers.add_parser(mode, help=f"{mode} against an explicit PostgreSQL target")
        subparser.add_argument("--source", type=Path, required=True, help="verified SQLite backup path")
        if mode == "transfer":
            subparser.add_argument("--confirm", required=True)
    args = parser.parse_args()

    try:
        if args.mode == "inspect":
            result = _inspect(args.source)
        else:
            source = _source_engine(args.source)
            target, safe_display = _target_engine()
            try:
                if args.mode == "rehearse":
                    result = transfer_database(source, target, dry_run=True).as_dict()
                elif args.mode == "transfer":
                    if args.confirm != TRANSFER_CONFIRMATION:
                        raise TransferBlockedError("exact transfer confirmation token is required")
                    result = transfer_database(source, target).as_dict()
                else:
                    result = verify_database_transfer(source, target)
            finally:
                source.dispose()
                target.dispose()
            result["target"] = safe_display
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except TransferBlockedError as exc:
        print(f"{args.mode.upper()} GATE: BLOCKED")
        print(f"reason: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
