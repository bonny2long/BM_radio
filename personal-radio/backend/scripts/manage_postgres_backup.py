from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


BACKEND = Path(__file__).resolve().parents[1]
LIVE_PROOF = BACKEND / "scripts" / "check_prod5_5a_postgres_backup_restore.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.local_postgres_adoption import target_url_from_secret_file  # noqa: E402
from app.postgres_backup_restore import (  # noqa: E402
    BACKUP_DIR,
    BackupRestoreBlockedError,
    _alembic_check,
    active_preflight,
    create_logical_backup,
    inspect_backup,
    protected_snapshot,
    verify_retained_backup,
)


def _json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _preflight() -> int:
    result = active_preflight()
    print(f"BM-PROD5.5A BACKUP PREFLIGHT: {result['gate']}")
    _json(result)
    return 0 if result["gate"] == "PASS" else 2


def _backup() -> int:
    preflight = active_preflight()
    if preflight["gate"] != "PASS":
        raise BackupRestoreBlockedError("backup preflight blocked")
    source = protected_snapshot()
    _alembic_check(target_url_from_secret_file())
    result = create_logical_backup(source, preflight)
    _json({key: value for key, value in result.items() if key not in ("backup_path", "manifest_path", "manifest")})
    return 0


def _selected_backup(value: str | None) -> Path:
    if value:
        selected = Path(value)
        if not selected.is_absolute():
            selected = BACKUP_DIR / selected
        return selected
    candidates = sorted(BACKUP_DIR.glob("*.dump"))
    if not candidates:
        raise BackupRestoreBlockedError("no retained PostgreSQL logical backup exists")
    return candidates[-1]


def _inspect(value: str | None) -> int:
    selected = _selected_backup(value)
    _json({"logical_backup_filename": selected.name, "archive_inventory": inspect_backup(selected), "result": "PASS"})
    return 0


def _restore_rehearsal() -> int:
    result = subprocess.run(
        [sys.executable, str(LIVE_PROOF), "--run"],
        cwd=str(BACKEND),
        shell=False,
    )
    return result.returncode


def _verify(value: str | None) -> int:
    _json(verify_retained_backup(_selected_backup(value)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage BM Radio PostgreSQL logical backup and disposable restore proofs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight", help="validate active backup prerequisites without changing data")
    subparsers.add_parser("backup", help="create and inspect a retained custom-format logical backup")
    inspect_parser = subparsers.add_parser("inspect", help="inspect a retained custom-format archive")
    inspect_parser.add_argument("--backup", help="logical filename under the ignored backup directory")
    subparsers.add_parser("restore-rehearsal", help="run the isolated disposable restore proof")
    verify_parser = subparsers.add_parser("verify", help="verify a retained archive and manifest hash")
    verify_parser.add_argument("--backup", help="logical filename under the ignored backup directory")
    arguments = parser.parse_args()
    try:
        if arguments.command == "preflight":
            return _preflight()
        if arguments.command == "backup":
            return _backup()
        if arguments.command == "inspect":
            return _inspect(arguments.backup)
        if arguments.command == "restore-rehearsal":
            return _restore_rehearsal()
        return _verify(arguments.backup)
    except BackupRestoreBlockedError as exc:
        print("BM-PROD5.5A BACKUP OPERATION: BLOCKED")
        print(f"reason: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
