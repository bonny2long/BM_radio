# BM-PROD5.4C.1 — Persistent Local PostgreSQL Adoption Tooling and Preflight

Date: 2026-08-15

BM-PROD5.4C.1 status: PRE-ADOPTION GATE BLOCKED

The tooling and deterministic safety contract are complete. Live adoption is blocked because the local Docker engine is unavailable and the active recovered SQLite database contains 1,257 application rows. A populated SQLite database requires a separately reviewed data-transfer plan; zero-data adoption must not proceed.

## Repository Baseline

- Starting SHA: `980bfb4e39181741c3abddf1e55c6f4210ebd00d`
- Implementation commit: `e21fdd97760072187e5e23ad6c93c230f4df17b5`
- Ending SHA: `e21fdd97760072187e5e23ad6c93c230f4df17b5`
- Recovered PROD0 entry baseline: 50 passed / 0 failed / 4 skipped
- BM-PROD5.4B documentation closure: PASS

## Files Changed

- `.gitignore`
- `backend/.env.example`
- `backend/app/local_postgres_adoption.py`
- `backend/scripts/manage_local_postgres_adoption.py`
- `backend/scripts/check_prod5_4c_1_persistent_postgres_adoption_contract.py`
- `scripts/check_prod0_baseline.py`
- `docs/production-upgrade/BM-PROD5.4B_Disposable_Real_PostgreSQL_Integration_and_Behavioral_Proof.md`
- `docs/production-upgrade/BM-PROD5.4C.1_Persistent_Local_PostgreSQL_Adoption_Tooling_and_Preflight.md`

## Persistent Target Contract

- Container: `bm-radio-postgres-dev`
- Volume: `bm-radio-postgres-dev-data`
- Database: `bm_radio`
- Role: `bm_radio_app`
- PostgreSQL major: 16
- Port: 55432
- Binding: `127.0.0.1` only

## Preflight Evidence

- Docker CLI: present
- Docker context: `default`
- Docker locality: local endpoint classification
- Docker Linux engine: unavailable; not verifiable
- PostgreSQL image availability: official `postgres:16` identified; local image availability not verifiable while the engine is unavailable
- `.local_postgres` ignore: PASS
- `backend/.env` ignore: PASS
- Preferred loopback port: free
- Persistent container collision: not inspectable while the local Docker engine is unavailable
- Persistent volume collision: not inspectable while the local Docker engine is unavailable

## SQLite Evidence

- SQLite exists: YES
- SQLite integrity: `ok`
- SQLite quick check: `ok`
- SQLite readiness: `ready`
- SQLite compatibility: PASS
- SQLite revision: `0001_current_schema_baseline`
- SQLite application tables: 21
- SQLite application rows: 1,257
- SQLite SHA-256: `e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619`
- SQLite schema fingerprint: `bd34f4cf845273954a42a4febd9d0340ae52d221f8f07b9b77eeb3cd04125678`
- Zero-data adoption eligible: BLOCKED

## Mutation Boundary Results

- Persistent container created: NO
- Persistent volume created: NO
- `backend/.env` modified: NO
- Active database switched: NO
- Real SQLite mutated: NO
- Media accessed: NO
- Local `.local_postgres` state directory created: NO

## Validation

- Backend compile: PASS
- BM-PROD5.4C.1 static contract: PASS — 44 checks
- BM-PROD5.4B static contract: PASS — 51 checks
- BM-PROD5.4A: PASS — 35 checks
- BM-PROD5.3C.1: PASS — 30 checks
- PROD0: PASS — 51 passed / 0 failed / 4 skipped
- Frontend build: PASS
- Frontend lint: PASS — 0 errors / 8 warnings
- `git diff --check`: PASS
- Final git status: expected tracked edits and new BM-PROD5.4C.1 files only

## Next Required Action

Do not create or adopt persistent PostgreSQL yet. First review and approve a dedicated SQLite-to-PostgreSQL data-transfer design for the 1,257 application rows. Docker Desktop must also be running with the verified local Linux engine before a later approved create operation. Persistent creation/adoption still requires explicit operator approval after both blockers are resolved.
