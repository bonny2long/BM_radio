# BM-PROD5.3A - Alembic Migration Framework and Current-Schema Baseline

Owner: Bonny Makaniankhondo
Date: 2026-07-16
Starting SHA: `66edc33d37c270f6ec91134c985b3b984b7a9646`
Working-tree state: ready to commit after validation

## Status

BM-PROD5.3A targeted migration framework: PASS
Full production gate: PASS

The Alembic framework, baseline migration, schema verifier, migration status helper, and targeted regression were implemented without mutating the real `bm_radio.db` and without media access.

## Files Changed

- `personal-radio/backend/alembic.ini`
- `personal-radio/backend/migrations/env.py`
- `personal-radio/backend/migrations/script.py.mako`
- `personal-radio/backend/migrations/README.md`
- `personal-radio/backend/migrations/versions/0001_current_schema_baseline.py`
- `personal-radio/backend/app/migration_contract.py`
- `personal-radio/backend/scripts/check_migration_schema_compatibility.py`
- `personal-radio/backend/scripts/migration_status.py`
- `personal-radio/backend/scripts/check_prod5_3a_migration_framework.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD5.3A_Alembic_Migration_Framework_and_Current_Schema_Baseline.md`

## Alembic Layout

Created the required backend-local Alembic layout under `personal-radio/backend/`.

Baseline revision: `0001_current_schema_baseline`
Migration heads: 1
Metadata source: `app.models.Base.metadata`

`migrations/env.py` supports online and offline migrations and resolves the database URL in this order:

1. `-x db_url=...`
2. explicit `BM_RADIO_DB_URL`
3. fail closed if omitted

`alembic.ini` does not contain a default local database URL, secret, credential, or hard-coded `bm_radio.db` URL.

## Runtime DDL Inventory

The baseline migration represents the current committed schema created by these sources:

- SQLAlchemy model metadata from `app.models.Base.metadata`
- `schema_maintenance.ensure_manifest_ingestion_columns`
- `schema_maintenance.ensure_scan_reconciliation_columns`
- `schema_maintenance.ensure_playback_identity_columns`
- `schema_maintenance.ensure_recording_feedback_columns`
- `perf.ensure_performance_indexes`

BM-PROD5.3A preserves current startup behavior. `app/main.py` still uses `Base.metadata.create_all(...)` and the schema/performance maintenance helpers. No Alembic migration runs automatically at API import or startup.

## Proofs

Fresh temporary SQLite upgrade: PASS
Second upgrade idempotence: PASS
`alembic current` reports head: PASS
Schema parity: PASS
Foreign-key and constraint parity: PASS
Index parity: PASS
Disposable downgrade: PASS
Compatibility verifier read-only behavior: PASS
Legacy schema compatibility fixture: PASS
Legacy data preservation after stamp plus upgrade: PASS
Model-to-migration drift check: PASS
Incompatible schema failure path: PASS
No media access or mutation: PASS
BM-PROD4.2E regression remains in PROD0 gate: PASS

Targeted regression command:

```powershell
cd personal-radio/backend
python scripts/check_prod5_3a_migration_framework.py
```

Result:

```text
PASS: BM-PROD5.3A migration framework (23 checks)
```

## Real DB Safety

`personal-radio/backend/bm_radio.db` was inspected read-only before and after validation.

Before:

```text
13 user tables
0 total rows
no alembic_version table
```

After:

```text
13 user tables
0 total rows
no alembic_version table
```

The real DB was not stamped, upgraded, downgraded, deleted, seeded, or otherwise mutated.

## Validation

Backend compile:

```text
python -m compileall app scripts migrations
PASS
```

Migration framework regression:

```text
python scripts/check_prod5_3a_migration_framework.py
PASS: BM-PROD5.3A migration framework (23 checks)
```

Compatibility helper help:

```text
python scripts/check_migration_schema_compatibility.py --help
PASS
```

Migration status helper help:

```text
python scripts/migration_status.py --help
PASS
```

Migration heads helper:

```text
python scripts/migration_status.py heads
0001_current_schema_baseline
```

Frontend build:

```text
npm run build
PASS
```

Frontend lint:

```text
npm run lint
PASS - 0 errors, 8 warnings
```

Git whitespace:

```text
git diff --check
PASS
```

Full production gate:

```text
python -u scripts/check_prod0_baseline.py
BM-PROD0 BASELINE GATE: PASS
Mandatory: 45 passed, 0 failed
Optional/integration: 4 skipped
```

The gate was run outside the sandbox because the sandboxed Vite build path can fail on Windows with `spawn EPERM`. The rerun completed successfully after the machine stayed awake.

## Deferred Work

- BM-PROD5.3B migration-authoritative startup policy
- BM-PROD5.4 PostgreSQL migration
- BM-PROD5.5 backup and restore proof
- BM-PROD5.6 production Docker image
- BM-PROD5.7 TrueNAS read-only media mounts
- BM-PROD5.8 health checks, logs, startup, and rollback
