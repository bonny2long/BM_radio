from __future__ import annotations

import argparse
from pathlib import Path
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.migration_contract import compare_schema, engine_for_url


def _config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))


def _require_url(args: argparse.Namespace) -> str:
    if not args.db_url:
        raise SystemExit('--db-url is required for this command')
    return args.db_url


def _head() -> str:
    script = ScriptDirectory.from_config(_config())
    heads = script.get_heads()
    if len(heads) != 1:
        raise SystemExit(f'expected exactly one head, found {heads}')
    return heads[0]


def main() -> int:
    parser = argparse.ArgumentParser(description='Safe BM Radio migration status helper')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('heads', help='print migration heads without connecting to a database')
    current = sub.add_parser('current', help='print current revision for an explicit database URL')
    current.add_argument('--db-url', required=True)
    check = sub.add_parser('check', help='check current revision and schema compatibility for an explicit database URL')
    check.add_argument('--db-url', required=True)
    args = parser.parse_args()

    if args.command == 'heads':
        print(_head())
        return 0

    url = _require_url(args)
    engine = engine_for_url(url)
    try:
        with engine.connect() as conn:
            revision = MigrationContext.configure(conn).get_current_revision()
            if args.command == 'current':
                print(revision or '<base>')
                return 0
            head = _head()
            issues = compare_schema(engine)
            if revision != head:
                print(f'FAIL: current revision {revision!r} != head {head!r}')
                return 1
            if issues:
                print('FAIL: schema drift detected')
                for issue in issues[:100]:
                    print(f' - {issue.category}: {issue.detail}')
                return 1
            print(f'PASS: current revision is head {head} and schema is compatible')
            return 0
    finally:
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
