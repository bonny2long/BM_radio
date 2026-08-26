# BM-PROD6E — Whole-App Scale, Soak, Mobile, Recovery, and Operational Readiness

Status: **WHOLE-APP-HARDENING PASS**

Starting SHA: `fa384a007cadd80d3195035e6d01f5b2bf29fdfb`
Ending implementation commit: `5a05ac7e28b1c2f86a913595e0b2a0b407d96444`

## PROD6E.1

- Implementation: `0189dbaa8caf5f5a2a3ac6a140d19887b4dd507e`.
- Report: `fa384a007cadd80d3195035e6d01f5b2bf29fdfb`.
- PostgreSQL 16 is the production station-performance acceptance source.

## Station regression

- Initial worst p95: 1,037.4 ms (Song Live; required <= 2,500 ms).
- Refill worst p95: 1,231.1 ms (Genre with 200 exclusions; required <= 2,000 ms).
- Candidate budget: normal 50-track request uses 500 candidates; hard ceiling remains 5,000.
- Quality: PASS for all deterministic PROD6B quality assertions.
- Profile scope: artist, album, and track profiles remain candidate-scoped; listener station requests do not load full profile tables.

## PostgreSQL listener API scale

The deterministic 10,000-physical-track benchmark ran against disposable PostgreSQL 16 at Alembic head. Fixture construction was excluded from request latency, every response/query/memory bound passed, and the active environment plus SQLite fallback were unchanged.

| Operation | p95 |
|---|---:|
| Home | 103.283 ms |
| Artists | 97.326 ms |
| Albums | 132.652 ms |
| Songs | 150.339 ms |
| Search | 333.823 ms |
| Artist detail | 107.679 ms |
| Album detail | 35.299 ms |
| Playlist | 125.248 ms |
| Favorites | 364.243 ms |
| Recently Added | 275.606 ms |
| Deep Cuts | 368.093 ms |

## Larger-scale smoke

- Size: 50,000 physical tracks / 37,500 logical recordings.
- Station: Song station p95 715.934 ms.
- Search: global search p95 1,712.067 ms.
- Songs page: p95 413.355 ms.
- Memory: bounded; per-operation Python peak remained far below the 256 MiB ceiling.
- Query scope: bounded responses, <= 100 SELECTs, no full-table Python materialization, and station candidate budget 500.

## Real-media latency and pool safety

- Music cold: 722.3 ms.
- Music transition p95: 454.0 ms.
- M4B initial playing: 4,005.4 ms.
- M4B metadata: 3,980.7 ms.
- M4B resume: 29.2 ms.
- M4B seek: 34.9 ms.
- 18-stream pool: PASS; 18 concurrent unconsumed range streams and `database_pool_exhausted=false`.
- Accepted range policy: 4 MiB initial open range, then 64 KiB bounded follow-up ranges. Authentication resolves lazily and releases database work before streaming.

## 60-minute mixed soak

- Duration: 60 minutes; PASS.
- Backend memory start/end/peak: 101,219,041 / 111,463,628 / 124,046,540 bytes; bounded.
- Frontend memory start/end/peak: 8,642,363 / 9,007,267 / 17,437,818 bytes; bounded.
- PostgreSQL memory start/end/peak: 46,472,888 / 51,642,368 / 52,523,171 bytes; bounded.
- PostgreSQL connections start/end/peak: 7 / 6 / 7.
- HTTP requests: 2,841; unexpected 5xx: 0.
- Music events: 149; audiobook events: 296; playback failures: 0; queue duplicate failures: 0.
- Station requests/refills: 149 / 149.
- Audiobook progress rows: 1 authoritative row.
- Resource trend: bounded with no connection leak.

## Browser music soak and clients

- Duration: 30 minutes in real Google Chrome.
- Transitions: 10 loads and 10 playing events.
- Refills: at least one refill appended; no queue restart after exhaustion.
- Stalls: 0; media errors: 0.
- Two clients: PASS for simultaneous music and audiobook streams, health, and audiobook checkpoint.

## Responsive and manual listener acceptance

- 360x800: PASS.
- 390x844: PASS.
- 768x1024: PASS.
- Desktop 1366+: PASS.
- Player overlap controls: PASS.
- Source-action sheet mobile behavior: PASS.
- Audiobook mobile progress, seek, and speed controls: PASS.
- Physical phone: `deferred_to_PROD6F`.
- Human listener result: PASS. Google Chrome played the real M4B correctly with initial playback, resume, and seek. The isolated VS Code embedded Electron failure was a codec limitation of that embedded browser, not BM Radio.

## Recovery and live rescan

- Frontend restart: PASS.
- Backend restart: PASS.
- PostgreSQL restart: PASS.
- Whole-stack restart: PASS; Alembic revision retained and no duplicate schema rows.
- Temporary outage: PASS; no frontend retry storm, queue corruption, or lost state.
- Music rescan during use: PASS; 255 tracks updated, none added/unavailable, no reader errors.
- Audiobook rescan during use: PASS; one audiobook/one chapter updated, none added/unavailable.
- Duplicates: zero duplicate audiobooks and unchanged logical/physical counts.
- State preservation: playlist, favorite, and audiobook progress all PASS.

## Images, privacy, operations, and protection

- Backend image regression: PASS; linux/amd64, healthy, UID/GID 10001, read-only root, not published.
- Frontend image regression: PASS; linux/amd64, healthy, UID/GID 101, read-only root, not published.
- Log/privacy audit: PASS; zero findings and zero traceback loops.
- Operational checklist: PASS; see `BM-PROD6E_Local_Operations_Checklist.md`.
- Copied source and final media equality: PASS.
- Active PostgreSQL, SQLite fallback, `.env`, and durable evidence protection: PASS.
- Cleanup: PASS after exact-path retry; zero `bm-prod6e-*` containers, networks, or volumes remain and task runtime state is gone. The disposable test database volume was intentionally removed and is not recoverable; protected PostgreSQL and retained evidence were untouched.
- TrueNAS work: none. No images were published.

## Permanent gates and closeout

- PROD6E contract: PASS (45 non-live checks).
- PROD6D: PASS.
- PROD6C: PASS.
- PROD6B: PASS.
- PROD6A: PASS.
- Final PROD0 single invocation: **63 passed / 0 failed / 4 skipped**.
- Compile: PASS.
- Frontend build: PASS.
- Frontend lint: PASS.
- `git diff --check`: PASS.
- Git status: expected implementation/report closeout changes only.

BM-PROD6E stops at **WHOLE-APP-HARDENING PASS**. Physical-phone and TrueNAS deployment work remain deferred to PROD6F or a separately approved task.
