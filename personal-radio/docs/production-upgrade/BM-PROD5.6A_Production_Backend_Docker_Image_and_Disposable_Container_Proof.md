# BM-PROD5.6A — Production Backend Docker Image and Disposable Container Proof

Date: 2026-08-16  
Owner: Bonny Makaniankhondo  
Status: **BACKEND-CONTAINER PASS**

## Phase identity

- Starting SHA: `bc444f3b06c8006189d63607c139f6e90672d7f9`
- Ending SHA / working-tree state: HEAD remains `bc444f3b06c8006189d63607c139f6e90672d7f9`; the reviewed BM-PROD5.6A implementation is present as intentional uncommitted working-tree changes.
- BM-PROD5.5B implementation SHA correction: PASS; the 5.5B report now records implementation commit `bc444f3b06c8006189d63607c139f6e90672d7f9` while preserving its cold-recovery evidence.

## Docker source audit

- No authoritative Dockerfile or Compose deployment existed in the repository.
- The application default host is loopback for local development; the container-only runner requires `0.0.0.0:8094`.
- Ordinary application startup asserts migration readiness and seeds only already-established default radio profiles. It does not call `create_all`, stamp, or upgrade. The restored accepted database showed a zero-row startup delta.
- Runtime media/scanner routes remain application features, but the proof invoked no scan, stream, metadata probe, real path, or real media access.
- Runtime writes are directed to explicit cache paths. The container uses `/tmp` tmpfs and `/app-cache`; `/app` and all synthetic media mounts are read-only.
- Recovery/adoption, SQLite-transfer, benchmark, test, bytecode, local-state, backup, media, cache, frontend, and Git artifacts are excluded from the image context.

## Runtime dependency split

- `requirements-runtime.txt`: FastAPI, Uvicorn, SQLAlchemy, Psycopg 3 binary, pydantic-settings, python-dotenv, Alembic, and Mutagen.
- `requirements-dev.txt`: includes the runtime contract plus pytest and httpx.
- `requirements.txt`: retains the original literal developer dependency list for compatibility with historical workflows and PROD5.4A static checks.
- The image installs only `requirements-runtime.txt`.

## Image

- Tag: `bm-radio-backend:prod5.6a-bc444f3`
- Base: `python:3.13-slim-bookworm`
- Python: `3.13.15`
- OS/architecture: `linux/amd64`
- Image ID: `sha256:816a00f88e6d06be433c545dd05873847342aa26d6b710c99f1d39cf70188418`
- Image size: `71,149,521` bytes
- Runtime UID/GID: `10001:10001`
- Dockerfile SHA-256: `9f15c3137b17b2cf771b369bd2692819857aea357b9a7b37574de049b2a32373`
- Runtime requirements SHA-256: `773219834cfc93e829b2931e86d6f763ed07860e82c615c2155da586e2c1170b`
- Source commit: `bc444f3b06c8006189d63607c139f6e90672d7f9`
- Published remotely: **NO**

## Image inspection

- Filesystem inventory: PASS; 67 packaged `/app` paths inspected.
- Secrets/local state: PASS; no `.env`, secret environment, state, transfer/adoption/backup/recovery evidence, `.local_postgres`, or personal Windows path.
- SQLite/backups: PASS; no SQLite database or logical dump artifact.
- Media/Git/personal paths: PASS; none present.
- Nested host bytecode was found and blocked on the first build attempt; `.dockerignore` was hardened for recursive `__pycache__`/`*.pyc`, and the final image inspection passed with zero forbidden hits.
- Image history: PASS; no secret, local-state filename, credential URL, or personal path.

## Runtime

- Non-root: PASS, `10001:10001`
- Read-only root: PASS
- Writable `/tmp`: PASS, explicit tmpfs and direct write/delete canary
- Writable cache: PASS for `/app-cache` and `/app-cache/artwork`
- Read-only media: PASS for Music, Audiobooks, and Books synthetic roots
- Port: container `8094`, published to a loopback-only dynamic host port
- Healthcheck: PASS; bounded standard-library request to `/api/health`, requiring HTTP 200 and `database_ready=true`
- Source bind mount: NO
- Real `.env` mount: NO

## Disposable PostgreSQL

- Image: `postgres:16`
- Network: isolated user-defined `bm-prod5-6a-*` bridge
- Storage: task tmpfs; no named volume
- Active target used: NO
- Restore: PASS from `bm_radio.postgres.logical.20260816T221250Z.8268bb.dump`
- Revision: `0001_current_schema_baseline` at head
- Compatibility: PASS
- Tables: 21
- Rows: 1,257
- Per-table counts/digests: exact accepted-manifest equality
- Foreign keys, constraints/types, sequences, next-ID rollback canary, and Alembic check: PASS through the retained restore verifier

## Backend container

- Startup: PASS
- Health: healthy
- Dialect/driver: PostgreSQL/Psycopg
- Production policy: PASS, `APP_ENV=production`, PostgreSQL required
- API docs: disabled (`/docs` returned 404)
- Startup row delta: zero

Read canaries all passed for health/readiness, library summary, artists, albums/releases, search, playlists, stations, recording controls, and audiobooks. No scanning or streaming endpoint was invoked.

The HTTP write canary created a temporary playlist in disposable PostgreSQL, confirmed the row through an independent database connection, deleted it through the API, and returned the database to exactly 1,257 rows with all canonical digests restored.

## Filesystem and restart proof

- Music write: denied
- Audiobooks write: denied
- Books write: denied
- Root filesystem write: denied
- `/tmp` write: succeeded and cleaned
- Cache write: succeeded and cleaned
- Artwork-cache write: succeeded and cleaned
- Restart: PASS; health returned healthy, PostgreSQL routing remained intact, 1,257 rows and digests were unchanged, UID/GID remained `10001:10001`, root remained read-only, tmpfs/cache remained writable, and media remained read-only.

## Negative fail-closed canaries

- Unreachable PostgreSQL: PASS; never healthy, exited nonzero, no SQLite fallback.
- SQLite with `APP_ENV=production`: PASS; rejected, never healthy, exited nonzero.
- Stale/uninitialized PostgreSQL: PASS; readiness refused startup, never healthy, exited nonzero.

## Cleanup and protected state

- Disposable cleanup: PASS.
- Remaining `bm-prod5-6a-*` containers: none.
- Remaining `bm-prod5-6a-*` networks: none.
- Remaining `bm-prod5-6a-*` volumes: none.
- Temporary credential/environment files, synthetic media, cache, and task state: removed.
- Active `bm-radio-postgres-dev` and `bm-radio-postgres-dev-data`: retained and unchanged.
- Protected active PostgreSQL revision/counts/digests: exact before/after equality.
- Protected SQLite bytes/schema/revision/counts/digests: exact before/after equality.
- Protected backend `.env`, state, transfer verification, adoption verification, backup verification, recovery rehearsal verification, and `backend_env.before`: exact SHA equality.
- Locally built image retained: YES, permitted.

## Validation

- Backend compile (`python -m compileall app scripts migrations`): PASS
- BM-PROD5.6A live preflight: PASS
- BM-PROD5.6A live build/run: BACKEND-CONTAINER PASS
- BM-PROD5.6A contract: PASS, 61 checks
- BM-PROD5.5B contract: PASS, 57 checks
- BM-PROD5.5A contract: PASS, 51 checks
- BM-PROD5.4C.3B contract: PASS, 54 checks
- BM-PROD5.4A compatibility check after dependency/runner additions: PASS, 30 checks
- PROD0: PASS — 57 mandatory passed, 0 failed, 4 skipped
- Frontend production build: PASS
- Frontend lint: PASS — 0 errors, 8 existing warnings
- `git diff --check`: PASS
- Final Git status: expected Docker/runtime/environment/dependency files, production runner/healthcheck, live/contract scripts, PROD0 registration, 5.5B report/contract compatibility updates, and this report remain uncommitted for exact-commit review.

## Next action

Review the exact BM-PROD5.6A working-tree diff and commit it if accepted. Only after acceptance, proceed separately to BM-PROD5.6B production frontend image and integrated local stack proof.

**STOP: BM-PROD5.6A BACKEND-CONTAINER PASS. No BM-PROD5.6B, integrated stack, TrueNAS deployment, real-media mount, scan, or SQLite retirement was performed.**
