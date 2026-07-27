# BM-PROD5.4B - Disposable Real PostgreSQL Integration and Behavioral Proof

Date: 2026-07-17  
Starting SHA: `3809dac82b09de9c337c1c07cf10f2d4eb1bf91c`  
Status: validation pending

## Scope

BM-PROD5.4B proves the current migration, readiness, startup, ORM, service, and listener API contracts against one local disposable PostgreSQL server. It does not switch BM Radio's active database or create a persistent PostgreSQL service.

## Safety Contract

- Docker context: pending live validation
- PostgreSQL image: `postgres:16`; resolved ID pending report capture
- Storage: disposable container tmpfs at `/var/lib/postgresql/data`
- Network: dynamically assigned `127.0.0.1` port only
- Credentials: random per run, environment-file input, never logged or reported
- Test databases: independent fresh, stale, and roundtrip databases
- Synthetic roots: ignored empty directories under `backend/tmp_tests/prod5_4b/`
- Real SQLite, `.env`, tracked configuration, media, and scanners: protected from mutation
- Cleanup: mandatory in `finally`; `--keep-on-failure` is explicit debug-only behavior

## Live Results

The following values will be replaced from the sanitized evidence artifact after the live run:

- Online upgrade: pending
- Live schema compatibility: pending
- Alembic check: pending
- Stale readiness before/after upgrade: pending
- First and second FastAPI startup: pending
- Default profile seed idempotence: pending
- Constraint and transaction matrix: pending
- Listener service and HTTP matrix: pending
- Downgrade/re-upgrade: pending
- Connection-loss readiness: pending
- Container, volume, network, port, and credential cleanup: pending

Evidence artifact (ignored): `backend/tmp_tests/prod5_4b/postgresql_integration_report.json`

## Protected State

- Real SQLite before/after: pending
- `.env` before/after: pending
- Tracked configuration before/after: pending
- Git worktree before/after harness: pending
- Media access or mutation: none authorized

## Validation

- Backend compile: pending
- Static BM-PROD5.4B contract: pending
- Live BM-PROD5.4B integration: pending
- BM-PROD5.4A: pending
- BM-PROD5.3C.1: pending
- BM-PROD5.3B: pending
- BM-PROD5.3A.1: pending
- BM-PROD5.3A: pending
- PROD0: pending
- Frontend build/lint: pending
- `git diff --check`: pending

No permanent PostgreSQL database exists after this task.  
No active database switch occurred.
