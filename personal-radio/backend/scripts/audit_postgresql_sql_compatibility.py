from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Iterable

BACKEND = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (BACKEND / 'app', BACKEND / 'migrations')
SQLITE_ISOLATED = {
    'app/perf.py',
    'app/perf_fixtures.py',
    'app/schema_maintenance.py',
    'app/sqlite_adoption.py',
    'app/sqlite_rebuild.py',
    'app/station_perf_benchmark.py',
}
POSTGRESQL_COMPATIBLE = {
    'app/migration_contract.py',
    'app/station_candidate_projection.py',
    'migrations/versions/0001_current_schema_baseline.py',
}
PATTERNS = (
    ('pragma', re.compile(r'\bPRAGMA\b', re.IGNORECASE)),
    ('insert_or_ignore', re.compile(r'\bINSERT\s+OR\s+IGNORE\b', re.IGNORECASE)),
    ('insert_or_replace', re.compile(r'\bINSERT\s+OR\s+REPLACE\b', re.IGNORECASE)),
    ('autoincrement', re.compile(r'\bAUTOINCREMENT\b', re.IGNORECASE)),
    ('sqlite_master', re.compile(r'\bsqlite_master\b', re.IGNORECASE)),
    ('sqlite_sequence', re.compile(r'\bsqlite_sequence\b', re.IGNORECASE)),
    ('datetime_function', re.compile(r'\bdatetime\s*\(', re.IGNORECASE)),
    ('strftime', re.compile(r'\bstrftime\s*\(', re.IGNORECASE)),
    ('julianday', re.compile(r'\bjulianday\s*\(', re.IGNORECASE)),
    ('group_concat', re.compile(r'\bgroup_concat\s*\(', re.IGNORECASE)),
    ('json_extract', re.compile(r'\bjson_extract\s*\(', re.IGNORECASE)),
    ('collate_nocase', re.compile(r'\bCOLLATE\s+NOCASE\b', re.IGNORECASE)),
    ('glob', re.compile(r'\bGLOB\b', re.IGNORECASE)),
    ('ifnull', re.compile(r'\bIFNULL\s*\(', re.IGNORECASE)),
    ('last_insert_rowid', re.compile(r'\blast_insert_rowid\s*\(', re.IGNORECASE)),
    ('on_conflict', re.compile(r'\bON\s+CONFLICT\b', re.IGNORECASE)),
    ('boolean_numeric_comparison', re.compile(r'\b(?:[A-Za-z_][\w.]*|true|false)\s*(?:=|!=|<>)\s*[01]\b', re.IGNORECASE)),
    ('double_quoted_identifier', re.compile(r'\b(?:FROM|JOIN|UPDATE|INTO|TABLE|INDEX)\s+"[^"]+"', re.IGNORECASE)),
    ('create_index_if_not_exists', re.compile(r'\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\b', re.IGNORECASE)),
    ('drop_index_if_exists', re.compile(r'\bDROP\s+INDEX\s+IF\s+EXISTS\b', re.IGNORECASE)),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    category: str
    excerpt: str


def _string_nodes(tree: ast.AST) -> Iterable[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            try:
                yield node.lineno, ast.unparse(node)
            except Exception:
                continue


def _category(path: str) -> str:
    if path in SQLITE_ISOLATED:
        return 'sqlite_isolated'
    if path in POSTGRESQL_COMPATIBLE:
        return 'postgresql_compatible'
    return 'requires_refactor'


def audit() -> list[Finding]:
    findings: list[Finding] = []
    files = sorted(
        path
        for root in SCAN_ROOTS
        for path in root.rglob('*.py')
        if '__pycache__' not in path.parts
    )
    for path in files:
        relative = path.relative_to(BACKEND).as_posix()
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=relative)
        for line, value in _string_nodes(tree):
            compact = ' '.join(value.split())
            for rule, pattern in PATTERNS:
                if pattern.search(value):
                    findings.append(
                        Finding(
                            path=relative,
                            line=line,
                            rule=rule,
                            category=_category(relative),
                            excerpt=compact[:180],
                        )
                    )
    return sorted(findings, key=lambda item: (item.path, item.line, item.rule, item.excerpt))


def payload(findings: list[Finding]) -> dict[str, object]:
    category_counts = Counter(item.category for item in findings)
    rule_counts = Counter(item.rule for item in findings)
    return {
        'scan_roots': [root.relative_to(BACKEND).as_posix() for root in SCAN_ROOTS],
        'finding_count': len(findings),
        'category_counts': dict(sorted(category_counts.items())),
        'rule_counts': dict(sorted(rule_counts.items())),
        'requires_refactor_count': category_counts.get('requires_refactor', 0),
        'findings': [asdict(item) for item in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit BM Radio raw SQL for PostgreSQL compatibility')
    parser.add_argument('--json-output', type=Path, help='write the deterministic JSON inventory')
    parser.add_argument('--json', action='store_true', help='print the full JSON inventory')
    args = parser.parse_args()

    result = payload(audit())
    if args.json_output:
        output = args.json_output if args.json_output.is_absolute() else BACKEND / args.json_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"PostgreSQL SQL compatibility findings: {result['finding_count']}")
        for category, count in result['category_counts'].items():
            print(f'  {category}: {count}')
        print(f"Unresolved production refactors: {result['requires_refactor_count']}")
    return 1 if result['requires_refactor_count'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
