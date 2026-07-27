# BM-PROD5.3B - Migration-Authoritative Startup and Database Readiness

Owner: Bonny Makaniankhondo
Date: 2026-07-16
Starting SHA: `4c71b724407482b04f9623e2a358eda59adfb133`

## Status

BM-PROD5.3B status: PASS

Alembic is now the sole schema authority for BM Radio startup. Application import performs no database mutation, and application startup validates readiness before any profile seed writes.

## Files Changed

- `personal-radio/backend/app/database_readiness.py`
- `personal-radio/backend/app/main.py`
- `personal-radio/backend/app/routes/health.py`
- `personal-radio/backend/scripts/database_readiness.py`
- `personal-radio/backend/scripts/check_prod5_3b_migration_authoritative_startup.py`
- `personal-radio/backend/scripts/check_prod5_3a_migration_framework.py`
- `personal-radio/backend/scripts/check_prod5_3a_1_schema_parity_hardening.py`
- `personal-radio/backend/migrations/README.md`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD5.3B_Migration_Authoritative_Startup_and_Database_Readiness.md`

## Authority Split

Old import-time DDL removed from normal startup:

- `models.Base.metadata.create_all(bind=db.engine)`
- `ensure_manifest_ingestion_columns(db.engine)`
- `ensure_scan_reconciliation_columns(db.engine)`
- `ensure_playback_identity_columns(db.engine)`
- `ensure_recording_feedback_columns(db.engine)`
- `ensure_performance_indexes()`

New policy:

- Operators run explicit Alembic upgrade or reviewed adoption/stamp commands.
- Application startup runs a read-only migration and schema readiness check.
- Only ready databases are allowed to serve requests.
- Startup never creates tables, columns, schema indexes, Alembic stamps, or Alembic upgrades.

## Readiness States

Implemented in `app/database_readiness.py`:

- `ready`
- `uninitialized`
- `legacy_unversioned`
- `revision_behind`
- `revision_unknown`
- `schema_drift`
- `database_unreachable`

Failure messages are actionable and do not include credentials, database URLs, database file paths, or media paths.

## Startup Behavior

`app.main` now creates the FastAPI app at import with no schema mutation. Its lifespan startup performs:

1. `assert_database_ready(db.engine)`
2. if ready, stores readiness on `app.state.database_readiness`
3. only then seeds default radio profiles

Failed readiness produces zero profile writes.

## Operator Workflows

Documented in `backend/migrations/README.md`:

Fresh database:

```powershell
python -m alembic -x db_url=<EXPLICIT_DATABASE_URL> upgrade head
python scripts/migration_status.py check --db-url <EXPLICIT_DATABASE_URL>
python scripts/database_readiness.py --db-url <EXPLICIT_DATABASE_URL>
```

Compatible unversioned database:

```powershell
python scripts/check_migration_schema_compatibility.py --db-url <EXPLICIT_DATABASE_URL>
python -m alembic -x db_url=<EXPLICIT_DATABASE_URL> stamp 0001_current_schema_baseline
python scripts/migration_status.py check --db-url <EXPLICIT_DATABASE_URL>
python scripts/database_readiness.py --db-url <EXPLICIT_DATABASE_URL>
```

Versioned database behind head:

```powershell
python -m alembic -x db_url=<EXPLICIT_DATABASE_URL> upgrade head
python scripts/migration_status.py check --db-url <EXPLICIT_DATABASE_URL>
```

No application code exposes upgrade or stamp flags.

## Proofs

Fresh migrated startup: PASS

- Temporary DB upgraded to head.
- Startup succeeded.
- Readiness status was `ready`.
- Default profile seeding happened after readiness.
- Second startup was idempotent.
- Schema remained compatible after startup.

Empty database proof: PASS

- Startup failed as `uninitialized`.
- No application tables were created.
- No `alembic_version` table was created.
- No profiles were written.

Legacy unversioned proof: PASS

- Compatible unversioned temporary schema failed closed as `legacy_unversioned`.
- No automatic stamp or upgrade occurred.
- Row counts and representative legacy values remained unchanged.
- Explicit temporary stamp enabled startup.

Unknown revision proof: PASS

- Disposable unknown `alembic_version` failed as `revision_unknown`.
- Database remained unchanged.

Behind revision proof: PASS

- Controlled temporary two-revision history classified a known older revision as `revision_behind`.
- No fake production revision was added.

Drift proof: PASS

- Temporary migrated DB at head with changed server default failed as `schema_drift`.
- No profile writes or repair attempt occurred.

Unreachable proof: PASS

- Deterministic invalid SQLite target returned `database_unreachable`.
- Message excluded path and credential-like text.

Import-time safety: PASS

- Importing `app.main` with a missing SQLite target did not create a file, connect, create tables, create indexes, seed profiles, or run Alembic.

Readiness CLI: PASS

- `python scripts/database_readiness.py --db-url <EXPLICIT_DATABASE_URL>` returns 0 only for ready databases.
- Missing `--db-url` fails closed.
- CLI inspection is read-only.
- Migration status and readiness agree on ready temporary databases.

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

The real local `bm_radio.db` is compatible but unversioned. It was not changed. BM Radio will reject it until an explicit reviewed adoption/stamp step is performed.

The refactored lifespan was not started against the real DB during this task.

No media roots were scanned or mutated.

## Validation

Backend compile:

```text
python -m compileall app scripts migrations
PASS
```

Targeted regression:

```text
python scripts/check_prod5_3b_migration_authoritative_startup.py
PASS: BM-PROD5.3B migration-authoritative startup (30 checks)
```

BM-PROD5.3A.1 regression:

```text
python scripts/check_prod5_3a_1_schema_parity_hardening.py
PASS
```

BM-PROD5.3A regression:

```text
python scripts/check_prod5_3a_migration_framework.py
PASS
```

Readiness CLI help:

```text
python scripts/database_readiness.py --help
PASS
```

Migration status helper help:

```text
python scripts/migration_status.py --help
PASS
```

Compatibility helper help:

```text
python scripts/check_migration_schema_compatibility.py --help
PASS
```

Full production gate:

```text
python scripts/check_prod0_baseline.py
BM-PROD0 BASELINE GATE: PASS
Mandatory: 47 passed, 0 failed
Optional/integration: 4 skipped
```

Frontend build: PASS

Frontend lint: PASS, 0 errors and 8 warnings

Git whitespace: PASS
