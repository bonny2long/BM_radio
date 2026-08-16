# BM-PROD5.4C.3B — Active Application Adoption to Persistent PostgreSQL

Date: 2026-08-16

BM-PROD5.4C.3B status: ACTIVE-POSTGRES-ADOPTION PASS

## Repository

- Starting SHA: `65157583b3b0c8ab74c3c08b697e9da114f114d9`
- Ending SHA / implementation commit: `ae0aa471d71e53d4e2609944e1f7e15d55a0e6b7`
- BM-PROD5.4C.3B implementation commit: `ae0aa471d71e53d4e2609944e1f7e15d55a0e6b7`
- BM-PROD5.4C.3A implementation SHA correction: PASS
- Correct BM-PROD5.4C.3A implementation commit: `65157583b3b0c8ab74c3c08b697e9da114f114d9`

## Pre-adoption SQLite

- SHA-256: `e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619`
- Schema fingerprint: `bd34f4cf845273954a42a4febd9d0340ae52d221f8f07b9b77eeb3cd04125678`
- Revision: `0001_current_schema_baseline`
- Application tables: 21
- Application rows: 1,257
- Per-table counts and canonical digests: exact transfer-evidence match
- Final unchanged result: PASS

## Transfer evidence

- Artifact SHA-256: `e832accb0350b37746a55a32de9fb03cefe5e11f2198801bf539e14b14ad6fc0`
- Entry state phase: `BM-PROD5.4C.3A`
- Entry `application_adopted`: `false`
- Source match: PASS
- Persistent target match: PASS

## Persistent PostgreSQL before adoption

- Container: `bm-radio-postgres-dev`
- Volume: `bm-radio-postgres-dev-data`
- Health: healthy
- Binding: `127.0.0.1:55432 -> 5432` only
- Server: PostgreSQL 16.15
- Revision: `0001_current_schema_baseline`
- Readiness: `ready`
- Compatibility: PASS
- Rows: 1,257
- Per-table counts and canonical digests: exact transfer-evidence match

## Configuration adoption

- Explicit approval token: exact `APPROVE-BM-PROD5.4C-LOCAL-POSTGRES` received
- `backend/.env` before SHA-256: `a668b6dc50b63ab6e23e5ccb0b743ccd41c581eecdf0e94dfef94f826441db3e`
- `backend/.env` before target: SQLite
- `.local_postgres/backend_env.before`: created
- Fallback snapshot SHA verified: PASS; `a668b6dc50b63ab6e23e5ccb0b743ccd41c581eecdf0e94dfef94f826441db3e`
- Adopted `backend/.env` SHA-256: `1d87e58b633f6dd2f34c9e6bc3c1fbde5b837529a0851e928e56d2ffa1526317`
- Only `BM_RADIO_DB_URL` changed persistently: PASS
- Database dialect: `postgresql`
- Driver: `psycopg`
- Policy: `postgresql_supported`
- Safe target: `postgresql+psycopg://bm_radio_app:***@127.0.0.1:55432/bm_radio`

## Application startup canaries

The canaries ran in a fresh bounded child interpreter. The database target came from the adopted `.env`; only temporary empty media/cache roots were supplied through the child process environment.

- Startup #1: PASS
- Startup #1 rows: 1,257
- Startup #1 per-table row delta: zero across all 21 tables
- Startup #1 canonical digests: unchanged
- Startup #2: PASS
- Startup #2 rows: 1,257
- Startup #2 per-table row delta: zero across all 21 tables
- Startup #2 canonical digests: unchanged
- Canary application processes: closed cleanly

## Read canaries

- Health/readiness: PASS
- Library summary: PASS
- Artists: PASS
- Releases/albums: PASS
- Search: PASS
- Playlists: PASS
- Stations: PASS
- Recording controls: PASS
- Audiobooks: PASS

## Application write-routing canary

- Type: temporary playlist with unique run identifier
- Create through application API: PASS
- Seen in PostgreSQL: YES
- Absent from SQLite: YES
- Delete through application API: PASS
- Cleanup: PASS
- PostgreSQL returned to 1,257 rows: YES
- Per-table counts restored: PASS
- Per-table canonical digests restored: PASS

## Media prohibition

- Scanner invocation: NO
- Media streaming: NO
- Metadata probing: NO
- Media file open: NO
- Archive mutation: NO

## PostgreSQL after canaries

- Revision: `0001_current_schema_baseline`
- Readiness: `ready`
- Compatibility: PASS
- Application tables: 21
- Application rows: 1,257
- Counts and canonical digests: exact transfer-evidence match
- Alembic drift: PASS

## SQLite fallback after adoption

- SHA unchanged: PASS
- Schema fingerprint and revision unchanged: PASS
- Rows unchanged at 1,257: PASS
- Counts and canonical digests unchanged: PASS
- SQLite retained as verified fallback: YES

## Rollback readiness

- `backend_env.before` valid: PASS
- Current adopted `.env` hash valid: PASS
- Stored fallback resolves to SQLite: PASS
- Current `.env` resolves to PostgreSQL/Psycopg: PASS
- Deterministic valid rollback guard: PASS
- Independently changed adopted `.env` is blocked: PASS
- Corrupted fallback snapshot is blocked: PASS
- Real rollback was not invoked after successful adoption

## Durable adoption evidence and state

- `.local_postgres/adoption_verification.json`: created
- Adoption artifact SHA-256: `587aa7c119a6f9639ef304c0793f6de1788c65e1cb72e94ef4f93ded6b9f8f34`
- `state.json` phase: `BM-PROD5.4C.3B`
- `application_adopted`: `true`
- `active_database`: `postgresql`
- `application_startup_verified`: `true`
- `application_startup_twice`: `true`
- `write_routing_verified`: `true`
- `sqlite_fallback_preserved`: `true`
- `rollback_snapshot_verified`: `true`
- Transfer-verification SHA preserved: PASS

## Guarded recovery history

The live operator failed closed during three implementation diagnostics before final success: stale parent-process settings, parent drift-check environment routing, and rejection of the required redacted safe-display field. Each failure automatically restored the exact SQLite `.env`, retained both databases and transfer evidence, and marked the attempt rolled back. Each retry required exact hash-verified recovery to the 5.4C.3A entry state and a fresh passing pre-adoption gate. No canary row or database drift remained.

The BM Radio Uvicorn backend found by the writer gate was stopped before adoption. The unrelated Vite frontend was left running. No long-running backend was automatically restarted; only bounded canary lifespans were used for this proof.

## Validation

- BM-PROD5.4C.3B contract: PASS — 54 checks
- BM-PROD5.4C.3A contract: PASS — 55 checks
- BM-PROD5.4C.2 contract: PASS — 51 checks
- BM-PROD5.4C.1 contract: PASS — 44 checks
- BM-PROD5.4B contract: PASS — 51 checks
- PROD0: PASS — 54 mandatory passed, 0 failed, 4 skipped
- Post-PROD0 PostgreSQL rows: 1,257 before and after
- Post-PROD0 canonical evidence SHA-256 before and after: `8cae3d6fd0a4780c1418541fd3b89cc66bfb270a5075f3ee71436efec2ac9da1`
- Post-PROD0 SQLite exact equality: PASS
- Backend compile: PASS
- Frontend production build: PASS
- Frontend lint: PASS — 0 errors, 8 existing warnings
- `git diff --check`: PASS
- Final Git status: BM-PROD5.4C.3B source, scripts, registration, report, and 5.4C.3A report correction are recorded in implementation commit `ae0aa471d71e53d4e2609944e1f7e15d55a0e6b7`

## Outcome

- Active `BM_RADIO_DB_URL` switched to persistent PostgreSQL: YES
- Persistent PostgreSQL remains healthy and canonical: YES
- SQLite fallback preserved exactly: YES
- Rollback snapshot verified: YES
- Media accessed: NO

## Next action

Review and commit the exact BM-PROD5.4C.3B implementation before BM-PROD5.5 PostgreSQL backup/restore and recovery proof. Do not retire or delete SQLite, destroy the persistent volume, deploy to TrueNAS, or begin real-media scanning as part of this phase.
