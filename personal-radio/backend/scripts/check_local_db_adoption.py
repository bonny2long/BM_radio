from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.sqlite_adoption import snapshot_sqlite_database


def sqlite_path_from_url(url: str) -> Path:
    parsed = urlparse(url)
    if parsed.scheme != 'sqlite':
        raise SystemExit('only explicit sqlite database URLs are supported for local adoption checks')
    if parsed.netloc and parsed.netloc != '':
        raise SystemExit('sqlite URL must point to a local file')
    raw = unquote(parsed.path)
    if raw.startswith('/') and len(raw) > 2 and raw[2] == ':':
        raw = raw[1:]
    if not raw:
        raise SystemExit('sqlite URL must include a database file path')
    path = Path(raw)
    if not path.exists():
        raise SystemExit('database file does not exist')
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only local BM Radio SQLite adoption status check')
    parser.add_argument('--db-url', required=True, help='explicit sqlite database URL to inspect')
    parser.add_argument('--json', action='store_true', help='emit JSON adoption status')
    args = parser.parse_args()

    path = sqlite_path_from_url(args.db_url)
    snapshot = snapshot_sqlite_database(path, logical_path='bm_radio.db')
    payload = {
        'integrity_check': snapshot.integrity_check,
        'quick_check': snapshot.quick_check,
        'readiness': snapshot.readiness_status,
        'ready': snapshot.readiness_ready,
        'current_revision': snapshot.current_revision,
        'head_revision': snapshot.head_revision,
        'compatibility': snapshot.compatibility,
        'application_table_count': len(snapshot.application_tables),
        'application_row_count': sum(snapshot.application_row_counts.values()),
        'schema_fingerprint': snapshot.schema_fingerprint,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for key, value in payload.items():
            print(f'{key}: {value}')
    return 0 if payload['integrity_check'] == 'ok' and payload['quick_check'] == 'ok' and payload['compatibility'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
