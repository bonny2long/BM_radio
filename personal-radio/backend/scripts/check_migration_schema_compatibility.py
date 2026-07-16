from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.migration_contract import compare_schema, engine_for_url, read_only_sqlite_url_for_path


def _url_from_args(args: argparse.Namespace) -> str:
    if bool(args.db_url) == bool(args.db_path):
        raise SystemExit('provide exactly one of --db-url or --db-path')
    if args.db_path:
        path = Path(args.db_path)
        if not path.exists():
            raise SystemExit(f'database path does not exist: {path}')
        return read_only_sqlite_url_for_path(path)
    return args.db_url


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only BM Radio schema compatibility verifier')
    parser.add_argument('--db-url', help='explicit SQLAlchemy database URL to inspect')
    parser.add_argument('--db-path', help='explicit SQLite database path to inspect read-only')
    parser.add_argument('--json', action='store_true', help='emit JSON details')
    args = parser.parse_args()
    url = _url_from_args(args)
    engine = engine_for_url(url)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def _sqlite_read_only(dbapi_connection, connection_record):
            dbapi_connection.execute('PRAGMA query_only = ON')
    try:
        issues = compare_schema(engine)
    except Exception as exc:
        print(f'FAIL: schema inspection failed: {exc}', file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    if args.json:
        print(json.dumps({'compatible': not issues, 'issues': [issue.as_dict() for issue in issues]}, indent=2, sort_keys=True))
    if issues:
        print('FAIL: incompatible schema')
        for issue in issues[:100]:
            print(f' - {issue.category}: {issue.detail}')
        return 1
    print('PASS: compatible BM Radio schema')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
