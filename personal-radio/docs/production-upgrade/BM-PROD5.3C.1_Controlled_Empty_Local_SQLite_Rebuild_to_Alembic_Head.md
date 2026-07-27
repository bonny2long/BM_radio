# BM-PROD5.3C.1 - Controlled Empty Local SQLite Rebuild to Alembic Head

Owner: Bonny Makaniankhondo
Date: 2026-07-16
Starting SHA: d9f1af311b2c1fa2ae9549f5a06efa6074a42f10

## Status

BM-PROD5.3C stamp adoption remains blocked and documented. The old local database was healthy and empty, but incompatible with the current Alembic baseline, so it was not stamped and was not upgraded in place.

BM-PROD5.3C.1 completed the controlled empty local SQLite rebuild path after explicit operator approval.

## Legacy Pre-Rebuild State

- Integrity: ok
- Quick check: ok
- Readiness: legacy_incompatible
- Compatibility: FAIL
- Application tables: 13 legacy application tables
- Application rows: 0
- Alembic version: absent
- SHA-256: f7ffade6809f8413754260357229049ff738d7fa41b737694ddde27fb8c558ef
- Schema fingerprint: 2556f6648a2e46a148c3fa676e44f206d789545c4e965912c249d5019fd3c512
- Compatibility issue summary: 8 missing tables, 12 missing columns, 9 missing indexes, 3 missing foreign keys

## Backup

- Method: SQLite online backup API
- Logical filename: bm_radio.pre_empty_rebuild.20260717T023911Z.db
- Manifest: bm_radio.pre_empty_rebuild.20260717T023911Z.manifest.json
- Backup SHA-256: 6066432e89b32c5b836ab098cf54a5f624208cc2918c90325e823a436b37e17b
- Integrity: ok
- Quick check: ok
- Schema fingerprint: 2556f6648a2e46a148c3fa676e44f206d789545c4e965912c249d5019fd3c512
- Application rows: 0
- Backup location: ignored `.local_backups/`

The approved real replacement also archived the old database as:

- bm_radio.pre_empty_rebuild_approved.20260717T024731Z.db

The archived old database retained the approved SHA-256 and schema fingerprint.

## Fresh Candidate

- Built by: Alembic `upgrade head` only
- Compatibility: PASS
- Readiness: ready
- Revision: 0001_current_schema_baseline
- Application tables: 21 application tables
- Application rows: 0
- Alembic version rows: one row at `0001_current_schema_baseline`
- Schema fingerprint: ca0a8e0f8a2962e3a935ce1645ab535b4a7b8e718b461df1c2fac800c3e3d38e
- SHA-256 after real placement: 3c4bd99209faf37b051fc910e74a87985910b92041e3036512fbaf9751a4f362

## Rehearsals

- Startup canary on disposable fresh copy: PASS
- Canary seeding idempotence: PASS
- Replacement candidate remained unseeded: PASS
- Restore rehearsal to legacy incompatible state: PASS
- Replacement rehearsal: PASS
- Rollback rehearsal: PASS
- Populated incompatible legacy DB blocks rebuild: PASS

## Explicit Approval and Real Replacement

Explicit operator approval was granted before real replacement.

Real mutation performed:

1. Rechecked the real DB SHA-256 and schema fingerprint against approved values.
2. Built a brand-new zero-row candidate through Alembic `upgrade head`.
3. Verified candidate compatibility, readiness, revision, and zero rows.
4. Archived the old `bm_radio.db` and associated sidecars.
5. Atomically placed the fresh candidate at `bm_radio.db`.
6. Verified the new real DB immediately.

No old SQLite sidecars were present.

The real FastAPI application was not started against the real database. Default profiles were not seeded into the real database. No scanner or media access was performed.

## Post-Rebuild Real DB State

- Integrity: ok
- Quick check: ok
- Compatibility: PASS
- Readiness: ready
- Current revision: 0001_current_schema_baseline
- Head revision: 0001_current_schema_baseline
- Application tables: 21
- Application rows: 0
- Alembic version rows: one row at `0001_current_schema_baseline`
- Schema fingerprint: ca0a8e0f8a2962e3a935ce1645ab535b4a7b8e718b461df1c2fac800c3e3d38e
- SHA-256: 3c4bd99209faf37b051fc910e74a87985910b92041e3036512fbaf9751a4f362

## Regression Updates

Prior migration and station regressions now use exact read-only real-DB snapshots and require the real DB to be ready, at head, compatible, and healthy. They no longer require the obsolete pre-Alembic 13-table/no-version real DB shape.

BM-PROD5.3C.1 was added to the PROD0 mandatory gate.

## Validation

- BM-PROD5.3C.1 regression: PASS, 29 checks
- BM-PROD5.3B regression: PASS, 30 checks
- BM-PROD5.3A.1 regression: PASS, 20 checks
- BM-PROD5.3A regression: PASS, 23 checks
- BM-PROD4.1 regression after guard update: PASS
- BM-PROD4.2C.1 regression after guard update: PASS
- BM-PROD4.2E regression after guard update: PASS, 26 checks
- Full PROD0 gate: PASS, 48 mandatory passed, 0 failed, 4 skipped
- Backend compile: PASS
- Frontend build: PASS
- Frontend lint: PASS, 0 errors and 8 warnings
- git diff --check: PASS

## Media Safety

No real application startup was run. No scanner was run. No media roots were accessed or mutated.

BM-PROD5.3C.1 RESULT: PASS