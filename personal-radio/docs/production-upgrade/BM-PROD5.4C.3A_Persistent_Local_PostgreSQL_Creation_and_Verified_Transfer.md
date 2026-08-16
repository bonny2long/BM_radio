# BM-PROD5.4C.3A — Persistent Local PostgreSQL Creation and Verified Transfer

Date: 2026-08-16

BM-PROD5.4C.3A status: PERSISTENT-TRANSFER GATE PASS

## Repository

- Starting SHA: `5fa5db5122bcca19fe8260ac4f8527da71e75c4f`
- Ending SHA / working-tree state: HEAD remains `5fa5db5122bcca19fe8260ac4f8527da71e75c4f`; the BM-PROD5.4C.3A implementation is present as uncommitted working-tree changes.
- BM-PROD5.4C.2 implementation SHA correction: PASS
- Correct 5.4C.2 implementation commit: `5fa5db5122bcca19fe8260ac4f8527da71e75c4f`

## Pre-creation source

- SHA-256: `e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619`
- Schema fingerprint: `bd34f4cf845273954a42a4febd9d0340ae52d221f8f07b9b77eeb3cd04125678`
- Revision: `0001_current_schema_baseline`
- Readiness: `ready`
- Compatibility: PASS
- Application tables: 21
- Application rows: 1,257
- Counts/digests match BM-PROD5.4C.2: PASS
- Foreign-key check: PASS
- Writer quiescence: PASS; no BM Radio writer detected

## Docker and resource preflight

- Context: `desktop-linux`
- Engine: Docker Desktop local Linux engine 29.7.2
- Local endpoint: PASS
- PostgreSQL image: official `postgres:16`, available locally
- Container collision before approval: none
- Volume collision before approval: none
- Port `127.0.0.1:55432` before approval: free

## Explicit operator approval

- Required token: `APPROVE-BM-PROD5.4C.3A-PERSISTENT-CREATION`
- Result: exact token received from Bonny after `BM-PROD5.4C.3A PRE-CREATION GATE: PASS`

## New SQLite transfer backup

- Logical filename: `bm_radio.pre_persistent_postgres.20260816T145940022734Z.db`
- Manifest: `bm_radio.pre_persistent_postgres.20260816T145940022734Z.manifest.json`
- Integrity and quick check: `ok`
- Source/backup schema, revision, counts, and canonical digests: equal
- Backup foreign-key check: PASS
- Verified: PASS

## Persistent resource

- Container: `bm-radio-postgres-dev`
- Volume: `bm-radio-postgres-dev-data`
- Database: `bm_radio`
- Role: `bm_radio_app`
- Binding: `127.0.0.1` only
- Host port: `55432`
- Container port: `5432`
- PostgreSQL server: PostgreSQL 16.15
- Final container health: healthy

## Alembic migration and persistent transfer

- Migration authority: `alembic upgrade head`
- Revision: `0001_current_schema_baseline`
- Compatibility: PASS
- Application tables before transfer: 21
- Application rows before transfer: 0
- Source rows: 1,257
- Target rows: 1,257
- Primary-key preservation: PASS
- Per-table counts: exact equality
- Per-table canonical digests: exact equality
- Foreign keys: PASS
- Unique/check constraints: PASS
- Sequence repair: PASS for all generated integer primary keys
- Next-ID rollback canary: PASS; generated track ID 193 was greater than imported maximum 192 and was rolled back
- Alembic drift: PASS

## Restart persistence

- Stop: PASS
- Start: PASS
- Readiness after restart: `ready`
- Rows after restart: 1,257
- Per-table counts after restart: exact equality
- Per-table canonical digests after restart: exact equality

## Durable ignored evidence

- `.local_postgres/transfer_verification.json`: created
- Verification SHA-256: `e832accb0350b37746a55a32de9fb03cefe5e11f2198801bf539e14b14ad6fc0`
- `.local_postgres/state.json`: created
- State phase: `BM-PROD5.4C.3A`
- `application_adopted`: `false`
- `.local_postgres/backend_env.before`: does not exist, as required before active adoption

## Protected state

- `backend/.env` SHA-256 before and after: `a668b6dc50b63ab6e23e5ccb0b743ccd41c581eecdf0e94dfef94f826441db3e`
- `backend/.env` database target after transfer: SQLite
- `backend/.env` unchanged: PASS
- Live SQLite SHA-256 after transfer: `e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619`
- Live SQLite schema fingerprint, revision, counts, and canonical digests unchanged: PASS
- Active `BM_RADIO_DB_URL` switched: NO
- BM Radio FastAPI started against persistent target: NO
- Scanner invoked: NO
- Media accessed or probed: NO

## Validation

- BM-PROD5.4C.3A contract: PASS — 55 checks
- BM-PROD5.4C.2 contract: PASS — 51 checks
- BM-PROD5.4C.1 contract: PASS — 44 checks
- BM-PROD5.4B contract: PASS — 51 checks
- BM-PROD5.4A: PASS — 35 checks
- PROD0: PASS — 53 mandatory passed, 0 failed, 4 skipped
- Backend compile: PASS
- Frontend production build: PASS
- Frontend lint: PASS — 0 errors, 8 existing warnings
- `git diff --check`: PASS
- Final Git status: expected BM-PROD5.4C.3A source, contract, registration, and documentation changes remain uncommitted

## Outcome

- Persistent PostgreSQL created: YES
- Persistent named volume created: YES
- Persistent transfer verified: YES
- Restart persistence verified: YES
- Active application database switch performed: NO

## Next action

Review the exact implementation diff and durable transfer evidence before BM-PROD5.4C.3B active application adoption. Do not switch `backend/.env`, start FastAPI against PostgreSQL, retire SQLite, or begin real-media scanning as part of BM-PROD5.4C.3A.
