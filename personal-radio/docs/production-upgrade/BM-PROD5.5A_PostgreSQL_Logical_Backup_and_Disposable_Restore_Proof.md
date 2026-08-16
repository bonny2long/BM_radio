# BM-PROD5.5A PostgreSQL Logical Backup and Disposable Restore Proof

## Result

- BM-PROD5.5A status: **LOGICAL-BACKUP-RESTORE PASS**
- Starting SHA: `ae0aa471d71e53d4e2609944e1f7e15d55a0e6b7`
- Ending SHA / working-tree state: HEAD remains `ae0aa471d71e53d4e2609944e1f7e15d55a0e6b7`; the BM-PROD5.5A implementation is present as intentional uncommitted working-tree changes.
- BM-PROD5.4C.3B implementation SHA correction: PASS; the prior report now records `ae0aa471d71e53d4e2609944e1f7e15d55a0e6b7`.

## Active PostgreSQL preflight

- Container: `bm-radio-postgres-dev`
- Volume: `bm-radio-postgres-dev-data`
- Health: healthy and running
- Binding: `127.0.0.1:55432 -> 5432/tcp` only
- Docker context/engine: `desktop-linux`; local Linux engine
- Server: PostgreSQL 16.15
- Revision: `0001_current_schema_baseline`
- Readiness: ready
- Compatibility: PASS
- Application tables: 21
- Application rows: 1,257
- Per-table counts/digests: PASS; canonical packed inventory SHA-256 `8cae3d6fd0a4780c1418541fd3b89cc66bfb270a5075f3ee71436efec2ac9da1`
- Foreign keys: PASS
- Alembic drift/check: PASS
- Backend writer quiescence: PASS; no long-running BM Radio backend writer detected

## Active configuration and protected evidence

- Dialect: PostgreSQL
- Driver: Psycopg
- Policy: `postgresql_supported`
- `backend/.env` SHA-256: `1d87e58b633f6dd2f34c9e6bc3c1fbde5b837529a0851e928e56d2ffa1526317`
- Adoption state phase: `BM-PROD5.4C.3B`
- State SHA-256: `7b159500c55d180d9143334225693ccdbad63ad9a3fb4ce387697f44e37b36b1`
- Transfer-verification SHA-256: `e832accb0350b37746a55a32de9fb03cefe5e11f2198801bf539e14b14ad6fc0`
- Adoption-verification SHA-256: `587aa7c119a6f9639ef304c0793f6de1788c65e1cb72e94ef4f93ded6b9f8f34`
- `backend_env.before` SHA-256: `a668b6dc50b63ab6e23e5ccb0b743ccd41c581eecdf0e94dfef94f826441db3e`

## SQLite fallback preflight

- SHA-256: `e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619`
- Schema fingerprint: `bd34f4cf845273954a42a4febd9d0340ae52d221f8f07b9b77eeb3cd04125678`
- Revision: `0001_current_schema_baseline`
- Readiness/compatibility: ready / PASS
- Application tables: 21
- Application rows: 1,257
- Per-table counts/digests: PASS; canonical packed inventory SHA-256 `8cae3d6fd0a4780c1418541fd3b89cc66bfb270a5075f3ee71436efec2ac9da1`

## Backup

- Tool: PostgreSQL 16 `pg_dump` from the persistent container image
- Tool version: `pg_dump (PostgreSQL) 16.15 (Debian 16.15-1.pgdg13+2)`
- Format: custom (`PGDMP`)
- Logical filename: `bm_radio.postgres.logical.20260816T221250Z.8268bb.dump`
- SHA-256: `32cedd69db4927756b61795e793f0a919f4856cd54195cc953c635cda67cadfe`
- Byte size: 124,671
- Manifest: `bm_radio.postgres.logical.20260816T221250Z.8268bb.manifest.json`
- Manifest SHA-256: `3d33ecd199ca19abfbc8ab8799c07525d44723d22f50f0e965673fc47af66327`
- Archive inventory: PASS; includes `alembic_version`, all 21 tables and table-data entries, sequences/state, indexes, constraints, and the `thumbvalue` enum/type
- Retained-backup verification: PASS

## Disposable restore

- Container: `bm-prod5-5a-restore-9cfb30d70f` (removed)
- Database: `bm_radio_restore_9cfb30d70f` (disposed with the container)
- Storage: disposable tmpfs; no named volume created
- Binding: loopback-only dynamic host port; active port 55432 was not reused
- PostgreSQL version: 16.15
- Restore command policy: `pg_restore --exit-on-error --no-owner --no-privileges`
- Restore result: PASS
- Revision: `0001_current_schema_baseline`
- Readiness: ready
- Compatibility: PASS
- Tables: 21
- Rows: 1,257

## Restored-data proof

- Per-table counts: exact equality PASS
- Per-table canonical digests: exact equality PASS
- Foreign keys: PASS
- Unique constraints: structure and rollback behavior canary PASS
- Check constraints: structure and rollback behavior canary PASS, including a zero-row-safe insert canary
- `thumbvalue` enum: archive presence and invalid-value rollback canary PASS
- Boolean normalization/round trip: PASS
- Datetime normalization/round trip: PASS
- Null/text equality: PASS
- Integer primary-key sequences: PASS for every generated sequence, including valid uncalled empty-sequence state
- `tracks` next-ID canary: generated ID exceeded the imported maximum; insert rolled back and sequence state restored
- Alembic current/head/check: PASS

## Restored application proof

- Startup #1: PASS; zero per-table row delta
- Startup #2: PASS; zero per-table row delta
- Database routing: `postgresql+psycopg`; ready
- Temporary media/cache roots: process-local empty directories
- Read canaries: PASS for health/readiness, library summary, artists, albums/releases, search, playlists, stations, recording controls, and audiobooks
- Streaming/scanning/media probing/file opens: not performed
- Write canary: temporary playlist create/delete through the application API PASS
- Write cleanup: PASS
- Rows returned to 1,257: PASS
- Canonical digests restored: PASS

## Protected-state proof after rehearsal

- Active PostgreSQL unchanged: PASS; 21 tables, 1,257 rows, exact counts/digests, ready, compatible
- SQLite fallback unchanged: PASS; exact file SHA, schema fingerprint, revision, counts, and digests
- `backend/.env` unchanged: PASS
- Adoption state/evidence unchanged: PASS
- `backend_env.before` unchanged: PASS
- Persistent PostgreSQL container/volume unchanged and healthy: PASS

## Disposable cleanup

- Container removed: PASS
- Volume removed/not created: PASS; tmpfs storage was used
- Network removed/not created: PASS; default disposable networking only
- Dynamic restore port closed: PASS
- Temporary canary roots removed: PASS
- Final Docker inventory: no `bm-prod5-5a-restore-*` container, volume, or network remains

## Retained evidence

- Verified logical backup retained under ignored `backend/.local_backups/postgresql/`: PASS
- Privacy-safe manifest retained: PASS
- `backend/.local_postgres/backup_verification.json` created: PASS
- `backup_verification.json` SHA-256: `ee70daf7f74bcadc460c7f365c016f74ac72a875d8bb59de2345fb83daa46c56`
- Active adoption `state.json` phase was not changed.

## Validation

- Backend compile (`python -m compileall app scripts migrations`): PASS
- BM-PROD5.5A non-live contract: PASS, 51 checks
- BM-PROD5.5A live preflight: PASS
- BM-PROD5.5A live backup/restore: PASS
- BM-PROD5.4C.3B contract: PASS, 54 checks
- BM-PROD5.4C.3A contract: PASS, 55 checks
- Full PROD0: PASS, 55 mandatory passed / 0 failed / 4 skipped
- Frontend production build: PASS
- Frontend lint: PASS, 0 errors / 8 existing warnings
- `git diff --check`: PASS
- Final Git status: expected BM-PROD5.5A module, operator/live/contract scripts, PROD0 registration, 5.4C.3B report/contract compatibility updates, and this report remain uncommitted

The first two implementation diagnostics failed closed and cleaned up their disposable containers: one exposed a zero-row check-canary assumption, and one exposed incorrect handling of valid uncalled empty sequences. The corrected proof then passed. A first full PROD0 attempt also encountered a transient timeout in an older nested SQLite/Alembic regression; that check passed in isolation, and the complete PROD0 rerun passed 55/0/4.

## Next action

Review and commit the exact BM-PROD5.5A implementation and verified retained backup before BM-PROD5.5B controlled disaster-recovery rehearsal. Do not begin active database replacement, persistent-volume destruction, SQLite retirement, production container deployment, TrueNAS deployment, or real-media scanning as part of this phase.
