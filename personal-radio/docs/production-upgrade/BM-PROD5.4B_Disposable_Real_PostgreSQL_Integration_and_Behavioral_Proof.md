# BM-PROD5.4B - Disposable Real PostgreSQL Integration and Behavioral Proof

Date: 2026-07-17  
Starting SHA: `3809dac82b09de9c337c1c07cf10f2d4eb1bf91c`  
Implementation commit: `5ed527888a4d1623696240f8807acba257ca9828`
Status: PASS

## Scope

BM-PROD5.4B proves the current migration, readiness, startup, ORM, service, and listener API contracts against one local disposable PostgreSQL server. It does not switch BM Radio's active database or create a persistent PostgreSQL service.

## Proven Fixes

- Dialect-neutral primary-key reflection
- PostgreSQL `thumbvalue` enum cleanup during downgrade
- Correct online downgrade invocation
- Harness and API expectation corrections
- Credential-safe diagnostics

## Safety Contract

- Docker context: verified local for the completed live proof
- PostgreSQL image: official `postgres:16`
- Storage: disposable container tmpfs at `/var/lib/postgresql/data`
- Network: dynamically assigned `127.0.0.1` port only
- Credentials: random per run, environment-file input, never logged or reported
- Test databases: independent fresh, stale, and roundtrip databases
- Synthetic roots: ignored empty directories under `backend/tmp_tests/prod5_4b/`
- Real SQLite, `.env`, tracked configuration, media, and scanners: protected from mutation
- Cleanup: mandatory in `finally`; `--keep-on-failure` is explicit debug-only behavior

## Live Results

- Official PostgreSQL 16 disposable server: PASS
- Online Alembic upgrade: PASS
- Live schema compatibility: PASS
- Alembic drift check: PASS
- Stale to ready readiness transition: PASS
- FastAPI startup and second startup: PASS
- Default profile seeding idempotence: PASS
- Constraint, transaction, and concurrency matrix: PASS
- Listener service and API matrix: PASS
- Downgrade to base and re-upgrade: PASS
- `database_unreachable` behavior: PASS
- Container and resource cleanup: PASS

Evidence artifact (ignored): `backend/tmp_tests/prod5_4b/postgresql_integration_report.json`

## Protected State

- Real SQLite protected: PASS
- `.env` protected: PASS
- Tracked configuration protected: PASS
- Git worktree comparison: PASS
- Real media access or mutation: none

## Validation Closure

The BM-PROD5.4B static contract and live disposable integration completed successfully, including the prior migration regressions and protected-state checks. This record closes only the disposable PostgreSQL compatibility proof.

Recovery note — 2026-08-15 recovered workstation: PROD0 = 50 passed / 0 failed / 4 skipped.

No permanent PostgreSQL database exists after this task.  
No active database switch occurred.
