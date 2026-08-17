# BM-PROD5.5B Cold PostgreSQL Disaster-Recovery Rehearsal

## Result

- BM-PROD5.5B status: **COLD-RECOVERY REHEARSAL PASS**
- Starting SHA: `789964e841ad06663e96e02f57cb53b259c93283`
- Ending SHA / implementation commit: `bc444f3b06c8006189d63607c139f6e90672d7f9`.
- BM-PROD5.5A implementation SHA correction: PASS; the prior report now records implementation commit `789964e841ad06663e96e02f57cb53b259c93283`.

## Retained backup

- Filename: `bm_radio.postgres.logical.20260816T221250Z.8268bb.dump`
- SHA-256: `32cedd69db4927756b61795e793f0a919f4856cd54195cc953c635cda67cadfe`
- Manifest: `bm_radio.postgres.logical.20260816T221250Z.8268bb.manifest.json`
- Manifest SHA-256: `3d33ecd199ca19abfbc8ab8799c07525d44723d22f50f0e965673fc47af66327`
- 5.5A `backup_verification.json` SHA-256: `ee70daf7f74bcadc460c7f365c016f74ac72a875d8bb59de2345fb83daa46c56`
- Independent archive inspection: PASS using `pg_restore` 16.15 in a task-scoped official `postgres:16` helper; the active PostgreSQL container was not used
- Archive inventory: PASS for custom `PGDMP`, `alembic_version`, all 21 application tables and data entries, sequences/state, indexes, constraints, and `thumbvalue`
- Retained backup/manifest were not changed or deleted.

## Pre-outage active PostgreSQL

- Container: `bm-radio-postgres-dev`
- Container identity: `b48a29b323785a57559b3c7d26408c7d01a537d65ffe86c3822e0738bfc54d81`
- Volume: `bm-radio-postgres-dev-data`
- Volume identity SHA-256: `e34d0042e448c5d9efc49db559bb142d045833f86ce64bd8e5fcd97e4ace6b2f`
- Volume created: `2026-08-16T14:59:50Z`
- Health: running and healthy
- Binding: `127.0.0.1:55432 -> 5432/tcp` only
- PostgreSQL: 16.15
- Revision: `0001_current_schema_baseline`
- Readiness/compatibility: ready / PASS
- Application tables: 21
- Application rows: 1,257
- Counts/digests: PASS; canonical packed inventory SHA-256 `8cae3d6fd0a4780c1418541fd3b89cc66bfb270a5075f3ee71436efec2ac9da1`
- Alembic check: PASS
- Writer quiescence: PASS

## SQLite pre-outage

- SHA-256: `e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619`
- Schema fingerprint: `bd34f4cf845273954a42a4febd9d0340ae52d221f8f07b9b77eeb3cd04125678`
- Revision: `0001_current_schema_baseline`
- Application tables/rows: 21 / 1,257
- Counts/digests: PASS; canonical packed inventory SHA-256 `8cae3d6fd0a4780c1418541fd3b89cc66bfb270a5075f3ee71436efec2ac9da1`

## Configuration pre-outage

- `backend/.env` SHA-256: `1d87e58b633f6dd2f34c9e6bc3c1fbde5b837529a0851e928e56d2ffa1526317`
- State SHA-256: `7b159500c55d180d9143334225693ccdbad63ad9a3fb4ce387697f44e37b36b1`
- Transfer-verification SHA-256: `e832accb0350b37746a55a32de9fb03cefe5e11f2198801bf539e14b14ad6fc0`
- Adoption-verification SHA-256: `587aa7c119a6f9639ef304c0793f6de1788c65e1cb72e94ef4f93ded6b9f8f34`
- `backend_env.before` SHA-256: `a668b6dc50b63ab6e23e5ccb0b743ccd41c581eecdf0e94dfef94f826441db3e`
- Active routing: PostgreSQL/Psycopg; state phase remains `BM-PROD5.4C.3B`

## Explicit approval

- Required token: `APPROVE-BM-PROD5.5B-COLD-RECOVERY`
- Result: exact token received after a passing non-mutating pre-recovery gate
- PostgreSQL interruption before approval: none

## Active outage

- Original container stopped: PASS
- Original container retained: PASS
- Original volume retained: PASS
- Port 55432 closed: PASS
- Adopted active target readiness: `database_unreachable`, PASS
- Original container/volume were never removed, replaced, or restored into.

## Recovery target A

- Container: `bm-prod5-5b-recovery-b9957b1ae6-a`
- Named volume: `bm-prod5-5b-recovery-data-b9957b1ae6`
- Volume identity SHA-256: `aca09f3ba7540a9b3a88c3698491b27e2eefc859b08f621a939338111a3a5f9e`
- Binding: `127.0.0.1:64789 -> 5432/tcp`
- Database: `bm_radio`
- PostgreSQL: 16.15
- Restore: PASS with `pg_restore --exit-on-error --no-owner --no-privileges`; no Alembic bootstrap occurred first
- Revision: `0001_current_schema_baseline`
- Readiness/compatibility: ready / PASS
- Application tables/rows: 21 / 1,257
- Counts/digests: exact manifest equality PASS
- Foreign keys: PASS
- Constraints/types: PASS
- Sequences: all 21 generated integer-PK sequences PASS
- `tracks` next-ID rollback canary: PASS; generated ID exceeded imported maximum and sequence state was restored
- Alembic check: PASS

## Container-loss simulation

- Container A stopped and removed: PASS
- Recovery named volume retained after container A removal: PASS
- Container B created from the same volume: `bm-prod5-5b-recovery-b9957b1ae6-b`
- New binding: `127.0.0.1:64798 -> 5432/tcp`
- Post-recreation readiness/compatibility: ready / PASS
- Post-recreation tables/rows: 21 / 1,257
- Post-recreation counts/digests: exact manifest equality PASS
- Post-recreation foreign keys, constraints/types, sequences, and Alembic: PASS

## Recovered application

- Startup #1: PASS; zero per-table row delta
- Startup #2: PASS; zero per-table row delta
- Routing: PostgreSQL/Psycopg to recovery container B through process-only environment
- Read canaries: PASS for health/readiness, library summary, artists, albums/releases, search, playlists, stations, recording controls, and audiobooks
- Write canary: temporary recovery playlist create/delete through application API PASS
- Write cleanup: PASS
- Rows restored to 1,257: PASS
- Canonical digests restored: PASS
- Final recovery-database verification after application canary: PASS
- Media access: no scanning, streaming, metadata probing, or real file opens

## Recovery cleanup

- Container B removed: PASS
- Recovery named volume removed: PASS
- Independent helper resources removed: PASS
- Recovery credential file removed: PASS; zero credential files remain
- Recovery ports 64789 and 64798 closed: PASS
- Final Docker inventory contains no `bm-prod5-5b-*` container or volume.

## Original active restart

- Container: `bm-radio-postgres-dev`
- Original container identity retained: PASS
- Original named volume retained: PASS; identity unchanged
- Binding: `127.0.0.1:55432 -> 5432/tcp`
- Health: healthy
- PostgreSQL: 16.15
- Revision: `0001_current_schema_baseline`
- Readiness/compatibility: ready / PASS
- Application tables/rows: 21 / 1,257
- Counts/digests: exact pre-outage equality PASS
- Canonical packed inventory SHA-256: `8cae3d6fd0a4780c1418541fd3b89cc66bfb270a5075f3ee71436efec2ac9da1`
- Alembic check: PASS

## Original application reconnect

- Fresh bounded child using the real adopted `.env`: PASS
- PostgreSQL/Psycopg routing: PASS
- Health/readiness: PASS
- Row delta: zero
- Persistent backend process left running: no
- Media access: none

## Final protected-state equality

- SQLite exact equality: PASS
- `backend/.env` exact equality: PASS
- State, transfer evidence, adoption evidence, backup evidence, and `backend_env.before` exact equality: PASS
- Original active PostgreSQL exact equality: PASS
- Original container and volume identity equality: PASS
- Only the new ignored 5.5B evidence and intended source/report changes differ.

## Recovery evidence

- `.local_postgres/recovery_rehearsal_verification.json` created: PASS
- Created UTC: `2026-08-17T00:08:32.885709+00:00`
- SHA-256: `24bdde3b75cab96ca05cfab0546ad85f5fb7e8e8fb3f8d6cd132165dea484bc1`
- Privacy/credential check: PASS
- Adoption `state.json` phase was not changed.

## Validation

- Backend compile (`python -m compileall app scripts migrations`): PASS
- BM-PROD5.5B pre-recovery gate: PASS
- BM-PROD5.5B approved live rehearsal: PASS
- BM-PROD5.5B non-live contract: PASS, 57 checks
- BM-PROD5.5A contract: PASS, 51 checks
- BM-PROD5.4C.3B contract: PASS, 54 checks
- Full PROD0: PASS, 56 mandatory passed / 0 failed / 4 skipped
- Frontend production build: PASS
- Frontend lint: PASS, 0 errors / 8 existing warnings
- `git diff --check`: PASS
- Final Git status at acceptance: the BM-PROD5.5B implementation was committed as `bc444f3b06c8006189d63607c139f6e90672d7f9`.

## Next action

Review and commit the exact BM-PROD5.5B implementation and recovery evidence. After exact commit review, BM-PROD5.5 is locally closed. Continue next to BM-PROD5.6 production Docker image/container packaging. Do not retire SQLite yet, replace the active PostgreSQL volume, deploy to TrueNAS, or begin real-media scanning as part of this phase.
