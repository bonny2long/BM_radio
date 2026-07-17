from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database_readiness import inspect_database_readiness
from app.migration_contract import engine_for_url


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only BM Radio database readiness check')
    parser.add_argument('--db-url', required=True, help='explicit SQLAlchemy database URL to inspect')
    parser.add_argument('--json', action='store_true', help='emit JSON readiness details')
    args = parser.parse_args()

    engine = engine_for_url(args.db_url)
    try:
        readiness = inspect_database_readiness(engine)
    finally:
        engine.dispose()

    if args.json:
        print(json.dumps(readiness.as_dict(), indent=2, sort_keys=True))
    else:
        print(f'status: {readiness.status}')
        print(f'ready: {str(readiness.ready).lower()}')
        print(f'current_revision: {readiness.current_revision or "<none>"}')
        print(f'head_revision: {readiness.head_revision}')
        print(f'schema_issue_count: {readiness.schema_issue_count}')
        if readiness.schema_issues:
            print('schema_issues:')
            for issue in readiness.schema_issues[:10]:
                print(f' - {issue.category}: {issue.detail}')
        print(f'message: {readiness.message}')
    return 0 if readiness.ready else 1


if __name__ == '__main__':
    raise SystemExit(main())
