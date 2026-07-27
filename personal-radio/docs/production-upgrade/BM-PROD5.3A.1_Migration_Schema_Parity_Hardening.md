# BM-PROD5.3A.1 - Migration Schema-Parity Hardening

Owner: Bonny Makaniankhondo
Date: 2026-07-16
Starting SHA: `97b8eb26dd056baf18ce8d8d171933f273ff99db`

## Status

BM-PROD5.3A.1 status: PASS

This corrective pass closes the BM-PROD5.3A schema-verifier gap before migration-authoritative startup work begins.

## Files Changed

- `personal-radio/backend/app/migration_contract.py`
- `personal-radio/backend/migrations/env.py`
- `personal-radio/backend/scripts/check_prod5_3a_1_schema_parity_hardening.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD5.3A.1_Migration_Schema_Parity_Hardening.md`

## Gaps Closed

Nullability gap: `expected_columns()` already recorded nullable state, but `compare_schema()` did not enforce it.

Server-default gap: required server defaults were not represented in the column contract, so missing or changed defaults could pass compatibility checks.

## Normalization Policy

Nullability comparison now uses effective nullability. Primary-key columns normalize to non-nullable on both expected and actual contracts to avoid SQLite reflection noise. Non-primary-key columns are compared directly.

Server defaults are compared with narrow normalization only:

- balanced outer parentheses are ignored
- surrounding whitespace is ignored
- `now()`, `CURRENT_TIMESTAMP`, and `CURRENT_TIMESTAMP()` are equivalent
- matching string/numeric defaults may differ by SQLite quote formatting

Unrelated missing, unexpected, or changed defaults fail as `incompatible_server_default`.

## Alembic Drift Configuration

`migrations/env.py` keeps `compare_type=True` and now enables `compare_server_default=True` for online and offline migration configuration. Explicit DB URL safety remains unchanged.

## Targeted Fixtures

Nullable mismatch fixture: PASS

- Changed `scan_runs.media_kind` from `NOT NULL` to nullable in a disposable SQLite schema.
- Compatibility failed with `incompatible_nullability`.
- Verifier left the database unchanged.

NOT-NULL mismatch fixture: PASS

- Changed nullable `tracks.title` to `NOT NULL` in a disposable SQLite schema.
- Compatibility failed with `incompatible_nullability`.

Missing-default fixture: PASS

- Removed required `scan_runs.status` default.
- Compatibility failed with `incompatible_server_default`.

Changed-default fixture: PASS

- Changed required `scan_runs.status` default from `running` to `queued`.
- Compatibility failed with `incompatible_server_default`.

Equivalent default formatting fixture: PASS

- Changed SQLite formatting from `DEFAULT 'running'` to `DEFAULT ('running')`.
- Compatibility passed.

Primary-key nullability noise fixture: PASS

- Fresh SQLite migration reflection did not create false `tracks.id` nullability drift.

## Drift Detection

Head migration versus current model metadata: PASS

Controlled nullable drift: PASS

Controlled server-default drift: PASS

The drift cases alter disposable migrated databases only. Production models were not edited to prove drift detection.

## Baseline Revision

Baseline revision: `0001_current_schema_baseline`

Result: unchanged.

No second Alembic revision was created. The stricter verifier proved the fresh migrated schema and legacy current schema remain compatible, so no baseline schema defect was found.

Migration heads: 1

## Compatibility

Fresh migration schema compatibility: PASS

Legacy current schema compatibility: PASS

Original BM-PROD5.3A regression: PASS, 23 checks

Targeted corrective regression: PASS, 20 checks

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

The real DB was not stamped, upgraded, downgraded, seeded, or mutated.

## Validation

Backend compile:

```text
python -m compileall app scripts migrations
PASS
```

Original migration framework regression:

```text
python scripts/check_prod5_3a_migration_framework.py
PASS: BM-PROD5.3A migration framework (23 checks)
```

Corrective hardening regression:

```text
python scripts/check_prod5_3a_1_schema_parity_hardening.py
PASS: BM-PROD5.3A.1 schema parity hardening (20 checks)
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

Full production gate:

```text
python -u scripts/check_prod0_baseline.py
BM-PROD0 BASELINE GATE: PASS
Mandatory: 46 passed, 0 failed
Optional/integration: 4 skipped
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

No media access/mutation: PASS

BM-PROD5.3A FINAL ACCEPTANCE: PASS
