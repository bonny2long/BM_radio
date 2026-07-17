# BM-PROD5.4A - PostgreSQL Dialect Foundation and Offline Migration Proof

Status: PASS
Date: 2026-07-17
Starting SHA: `c6faf07b94052d15cd81a133c81cc1f240960132`
Ending state: implementation complete and validated; commit recorded after this report is finalized

## Scope

BM-PROD5.4A establishes explicit offline support for SQLAlchemy URLs using the Psycopg 3 dialect without connecting to a PostgreSQL server, creating a PostgreSQL database, copying SQLite data, changing `BM_RADIO_DB_URL`, starting the real application, or accessing media.

The accepted real local SQLite database remains the active development target.

## Files changed

- `backend/requirements.txt`
- `backend/app/database_dialect.py`
- `backend/app/config.py`
- `backend/app/db.py`
- `backend/app/migration_contract.py`
- `backend/app/perf.py`
- `backend/app/schema_maintenance.py`
- `backend/app/sqlite_adoption.py`
- `backend/app/sqlite_rebuild.py`
- `backend/migrations/env.py`
- `backend/migrations/versions/0001_current_schema_baseline.py`
- `backend/scripts/audit_postgresql_sql_compatibility.py`
- `backend/scripts/check_prod5_4a_postgresql_dialect_foundation.py`
- `backend/scripts/migration_status.py`
- `scripts/check_prod0_baseline.py`
- `docs/production-upgrade/BM-PROD5.4A_PostgreSQL_Dialect_Foundation_and_Offline_Migration_Proof.md`

Generated and ignored artifacts:

- `backend/tmp_tests/prod5_4a/postgresql_sql_audit.json`
- `backend/tmp_tests/prod5_4a/postgresql_upgrade_head.sql`
- `backend/tmp_tests/prod5_4a/postgresql_downgrade_base.sql`

## Driver and URLs

Psycopg 3 is declared as:

```text
psycopg[binary]
```

Accepted active URL forms are:

```text
sqlite:///...
sqlite+pysqlite:///...
postgresql+psycopg://user:password@host:port/database
```

`postgresql://...` is classified as PostgreSQL but rejected for active engine construction because it does not explicitly select the supported Psycopg 3 driver. Unsupported dialects and unsupported drivers fail closed.

Safe URL rendering hides passwords, redacts query values, and removes personal absolute SQLite paths.

## Engine and configuration policy

SQLite engines preserve `check_same_thread=False`.

PostgreSQL engines use:

```text
pool_pre_ping = true
connect_timeout = 5 seconds
no SQLite connect arguments
no aggressive pool sizing
```

Alembic online construction, future migration CLI connections, readiness inspection, and normal application construction share the same dialect policy. Offline Alembic mode parses and validates the explicit URL without connecting.

Development defaults remain `sqlite:///./bm_radio.db`. The legacy `DATABASE_URL` alias remains resolved to `BM_RADIO_DB_URL`. Production-like `APP_ENV` values reject SQLite rather than claiming production database readiness.

## SQLite-only boundary

SQLite adoption, rebuild, backup, restore, sidecar, PRAGMA, legacy schema-maintenance, and legacy performance-index operations now reject PostgreSQL targets clearly. Normal PostgreSQL startup and migration paths do not import or invoke adoption or rebuild helpers.

The accepted local SQLite rollback path remains available.

## Raw SQL inventory

The deterministic AST-based inventory scans SQL string literals under `backend/app` and `backend/migrations`.

Final bounded inventory:

```text
total findings: 100
sqlite_isolated: 51
postgresql_compatible: 49
sqlalchemy_portable: 0
needs_real_postgres_test: 0
requires_refactor: 0
```

The PostgreSQL-compatible findings are the experimental unified station projection, migration-authoritative `CREATE INDEX IF NOT EXISTS` statements, and inspector-controlled quoted identifiers. SQLite-only findings are confined to approved legacy maintenance, adoption/rebuild, fixture, and benchmark modules.

No normal API, scanner, station, playback/history, playlist, favorite, startup-readiness, or migration-status path has an unresolved PostgreSQL SQL blocker.

## Schema and index contract

Index expectations are separated into:

- model-declared portable indexes;
- migration-authoritative baseline indexes;
- SQLite legacy/runtime compatibility indexes.

Fresh schema comparison uses only migration-authoritative indexes for both accepted dialects. SQLite legacy raw index parsing no longer defines PostgreSQL expectations.

Schema comparison automatically selects a supported dialect policy and normalizes integer affinity, booleans, datetime/timestamp types, text/varchar types, PostgreSQL casts on server defaults, reflected unique/check constraints, index names, and primary-key nullability. PostgreSQL-generated integer primary-key defaults are treated as generated identity behavior rather than model drift. Other differences remain reportable.

SQLite migrated and legacy parity regressions remain passing.

## Baseline migration audit

Exactly one migration head remains:

```text
0001_current_schema_baseline
```

The accepted baseline revision changed in one place. `music_editions.source_format_family` previously rendered `DEFAULT UNKNOWN`, which PostgreSQL would interpret as an identifier. It now renders the intended string literal `DEFAULT 'UNKNOWN'`.

This is a correction to the same intended initial schema before any PostgreSQL deployment exists. No revision ID, table, column, constraint, index, or migration-head topology changed.

## Offline PostgreSQL proof

Offline upgrade command:

```powershell
python -m alembic -x db_url=postgresql+psycopg://user:redacted@127.0.0.1:1/bm_radio_offline upgrade head --sql
```

Result: PASS.

The generated SQL contains:

- `CREATE TABLE alembic_version`;
- all 21 application tables;
- PostgreSQL `SERIAL`, timestamp, boolean, foreign-key, unique, check, and index DDL;
- Alembic revision insertion;
- the corrected `DEFAULT 'UNKNOWN'`.

It contains no `PRAGMA`, `sqlite_master`, SQLite file path, personal path, or credential.

Offline downgrade command:

```powershell
python -m alembic -x db_url=postgresql+psycopg://user:redacted@127.0.0.1:1/bm_radio_offline downgrade 0001_current_schema_baseline:base --sql
```

Result: PASS. The output contains revision deletion, index/table teardown, and no SQLite-only statement.

## SQLAlchemy compile proof

All 21 model `CREATE TABLE` statements and every model index compile with SQLAlchemy's PostgreSQL dialect.

Representative parameterized SELECT, INSERT, UPDATE, and DELETE statements compile successfully. Recording identity, station candidate, and scanner availability query shapes also compile without SQLite-only SQL. Values remain bound parameters.

## Readiness and CLI boundary

A syntactically valid PostgreSQL URL is classified without SQLite path handling. A loopback port-1 unreachable fixture returns:

```text
status = database_unreachable
ready = false
```

The attempt is bounded by the five-second connection timeout, performs no SQLite PRAGMA or snapshot operation, and returns a credential-safe message.

`migration_status.py`, `database_readiness.py`, and `check_migration_schema_compatibility.py` accept explicit supported PostgreSQL URLs. Commands requiring a live database connect only when their operation requires inspection. Alembic offline mode does not connect.

## Real SQLite database

Before and after BM-PROD5.4A:

```text
SHA-256: 3c4bd99209faf37b051fc910e74a87985910b92041e3036512fbaf9751a4f362
schema fingerprint: ca0a8e0f8a2962e3a935ce1645ab535b4a7b8e718b461df1c2fac800c3e3d38e
readiness: ready
compatibility: PASS
revision: 0001_current_schema_baseline
application tables: 21
application rows: 0
integrity_check: ok
quick_check: ok
```

The real database was not started, seeded, migrated, replaced, or otherwise mutated.

## Validation

```text
backend compileall: PASS
SQL compatibility inventory: PASS, 100 findings, 0 requires_refactor
targeted BM-PROD5.4A: PASS, 35 checks
BM-PROD5.3C.1: PASS, 29 checks
BM-PROD5.3B: PASS, 30 checks
BM-PROD5.3A.1: PASS, 20 checks
BM-PROD5.3A: PASS, 23 checks
BM-PROD4.2E: PASS, 26 checks
PROD0 full gate: PASS, 49 mandatory passed, 0 failed, 4 skipped
frontend build: PASS
frontend lint: PASS, 0 errors, 8 warnings
git diff --check: PASS
```

The first sandboxed full-gate run passed all 48 backend/contract checks but Vite encountered the known Windows sandbox `spawn EPERM`. The complete gate was rerun outside that restriction and passed 49/49.

No Python process remained after validation. Two editor-associated Node processes had no listening TCP ports. No BM Radio API, frontend server, scanner, or benchmark process remained active.

No PostgreSQL server was contacted. No PostgreSQL database was created. No media was accessed or mutated.

## Deferred work

- BM-PROD5.4B: disposable real PostgreSQL integration and behavioral proof
- BM-PROD5.4C: controlled database migration and active database selection
- BM-PROD5.5: backup and restore proof
- BM-PROD5.6: production Docker image
- BM-PROD5.7: TrueNAS read-only mounts
- BM-PROD5.8: health, logging, startup, and rollback operations

BM-PROD5.4A status: PASS
