# BM-PROD5.4C.2 — Populated SQLite to PostgreSQL Transfer Rehearsal

Date: 2026-08-15

BM-PROD5.4C.2 status: PRE-TRANSFER GATE PASS

## Repository and Historical Correction

- Starting SHA: `e21fdd97760072187e5e23ad6c93c230f4df17b5`
- Ending SHA / implementation commit: `5fa5db5122bcca19fe8260ac4f8527da71e75c4f`
- BM-PROD5.4C.1 implementation SHA correction: PASS
- Correct implementation commit recorded: `5fa5db5122bcca19fe8260ac4f8527da71e75c4f`
- The historical 5.4C.1 PRE-ADOPTION GATE remains correctly recorded as BLOCKED.

## Docker Safety

- Docker CLI: present, version 29.7.2
- Docker context: `desktop-linux`
- Docker engine: Docker Desktop local Linux engine 29.7.2
- Docker locality: PASS — local named pipe
- PostgreSQL image: official `postgres:16`
- Image ID/digest: `sha256:11a9d238fbb48bab14599c57e41123254452b1a2d93c6c8595bce96f346bd082`
- PostgreSQL server: PostgreSQL 16.15
- Publication: dynamic `127.0.0.1` port only

## Live SQLite Pre-check

- Source quiescence: PASS — no BM Radio writer detected
- Integrity: `ok`
- Quick check: `ok`
- Revision: `0001_current_schema_baseline`
- Readiness: `ready`
- Compatibility: PASS
- Application tables: 21
- Application rows: 1,257
- SHA-256: `e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619`
- Schema fingerprint: `bd34f4cf845273954a42a4febd9d0340ae52d221f8f07b9b77eeb3cd04125678`
- Source foreign-key check: PASS

## Verified Backup

- Result: PASS
- Logical filename: `bm_radio.pre_postgres_transfer.20260816T032427462421Z.db`
- Manifest: `bm_radio.pre_postgres_transfer.20260816T032427462421Z.manifest.json`
- Integrity and quick check: `ok`
- Revision: `0001_current_schema_baseline`
- Rows: 1,257
- Per-table count equality with source: PASS
- Per-table canonical digest equality with source: PASS
- Backup storage: ignored `.local_backups` only

## Transfer Proof

- FK-aware deterministic table order: PASS — 21 tables, parents before children
- Disposable PostgreSQL online Alembic migration: PASS
- Target revision: `0001_current_schema_baseline`
- Target readiness: `ready`
- Target compatibility: PASS
- Target application tables: 21
- Transferred source rows: 1,257
- Transferred target rows: 1,257
- Per-table count equality: PASS
- Per-table canonical digest equality: PASS
- Foreign-key validation: PASS
- Unique and check constraints: PASS
- Primary-key preservation: PASS
- Boolean normalization: PASS
- Datetime normalization: PASS
- Enum validation: PASS; the current populated source has no `track_thumbs` rows
- Float canonicalization: PASS
- Text/JSON-as-text and null preservation: PASS
- Transactional fail-closed load: PASS
- Sequence repair: PASS for all 21 integer primary-key sequences
- Next-ID canary: PASS — imported track maximum 192, generated canary ID 193, canary row rolled back
- Alembic drift check after transfer: PASS

## Imported Startup and Read Canaries

- Separately imported startup-canary database: PASS
- First startup: PASS
- Second startup: PASS
- Default seed idempotence: PASS
- Startup row delta: zero for all 21 tables
- Existing imported data preserved: PASS
- Health/readiness: PASS
- Library summary: PASS
- Artists: PASS
- Releases/albums: PASS
- Search: PASS
- Playlist listing: PASS
- Station listing: PASS
- Recording preference/participation read: PASS
- Audiobook listing: PASS
- Audiobook progress: not applicable because the source contains no audiobook rows
- Scanner invocation: NO
- Media streaming: NO
- Media metadata/probing: NO

## Protected State and Cleanup

- Live SQLite after rehearsal: exact SHA, schema fingerprint, revision, counts, and canonical digests unchanged
- `backend/.env`: unchanged; SHA-256 `a668b6dc50b63ab6e23e5ccb0b743ccd41c581eecdf0e94dfef94f826441db3e`
- Persistent container created: NO
- Persistent volume created: NO
- Active database switched: NO
- Media accessed: NO
- Disposable container removed: YES
- Disposable volume removed: YES — tmpfs storage used, no named volume created
- Disposable network removed: YES — no custom network created
- Dynamic port closed: YES
- Ephemeral credentials absent from evidence: YES
- Post-rehearsal `docker ps -a`: no containers
- Post-rehearsal `docker volume ls`: no volumes
- Standard Docker networks only: `bridge`, `host`, `none`

## Validation

- BM-PROD5.4C.2 contract: PASS — 51 deterministic checks
- BM-PROD5.4C.1 contract: PASS — 44 checks
- BM-PROD5.4B contract: PASS — 51 checks
- BM-PROD5.4A: PASS — 35 checks
- BM-PROD5.3C.1: PASS — 30 checks
- PROD0: PASS — 52 passed / 0 failed / 4 skipped
- Backend compile: PASS
- Frontend build: PASS
- Frontend lint: PASS — 0 errors / 8 warnings
- `git diff --check`: PASS
- Final git status: expected BM-PROD5.4C.2 tracked edits and new files only

## Next Action

Stop at this PRE-TRANSFER GATE. Review this implementation and the ignored rehearsal artifact before explicitly approving BM-PROD5.4C.3. That later phase may create the persistent PostgreSQL target and perform the verified transfer/adoption; this task did neither.
