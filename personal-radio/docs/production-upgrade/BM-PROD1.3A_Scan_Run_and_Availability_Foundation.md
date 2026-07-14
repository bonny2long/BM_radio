# BM-PROD1.3A Scan-Run and Availability Foundation

Owner: Bonny Makaniankhondo
Project: BM Radio Production Upgrade
Date: 2026-07-14
Scope: Durable scan-run audit model, separate media availability fields, service helpers, and additive SQLite upgrade foundation

## Baseline

| Item | Value |
| --- | --- |
| Starting commit | `d79077cbd7c1f6f97bb879ff6f91f885153fb70e` |
| Starting worktree | Clean |
| Ending state | Pending working-tree changes |

Pre-change gate result:

```text
python scripts/check_prod0_baseline.py
PASS when run outside the Windows sandbox Vite spawn restriction
12 mandatory passed, 0 failed, 4 integration checks skipped
```

## ScanRun Model

BM-PROD1.3A adds a durable `ScanRun` ORM model backed by:

```text
scan_runs
```

The model records:

```text
media_kind
status
started_at
completed_at
roots_json
items_discovered
items_added
items_updated
items_unavailable
error_count
error_summary
```

Supported foundation semantics:

```text
media_kind: music / audiobook
status: running / succeeded / failed
```

`roots_json` stores the configured roots associated with the run so future reconciliation can stay scoped to the roots actually scanned.

## Separate Library Availability

BM-PROD1.3A adds these fields to both `Track` and `Audiobook`:

```text
library_availability
last_seen_scan_id
unavailable_since
```

Default and upgrade behavior:

```text
library_availability = available
last_seen_scan_id = null
unavailable_since = null
```

This is separate from `Track.last_indexed_at`, `Audiobook.last_indexed_at`, and audiobook playback progress state.

## Audiobook Status Preservation

`Audiobook.status` remains the existing listener progress field:

```text
available
in_progress
finished
```

It is not reused for filesystem/library availability. The regression proves an audiobook can remain `status = in_progress` while mark-seen restores `library_availability = available`.

## Service Layer

BM-PROD1.3A adds:

```text
personal-radio/backend/app/scan_runs.py
```

Public helpers:

```text
start_scan_run()
mark_track_seen()
mark_audiobook_seen()
complete_scan_run()
fail_scan_run()
```

The mark-seen helpers update only index-state fields:

```text
library_availability
last_seen_scan_id
unavailable_since
```

They do not modify favorites, thumbs, playback history, playlist membership, radio profiles, audiobook progress, or `Audiobook.status`.

## Existing SQLite Upgrade

Startup still uses the existing pre-Alembic pattern:

```text
models.Base.metadata.create_all(bind=db.engine)
ensure_manifest_ingestion_columns(db.engine)
ensure_scan_reconciliation_columns(db.engine)
```

`ensure_scan_reconciliation_columns()` is additive and SQLite-only. It adds missing columns to existing `tracks` and `audiobooks`, backfills null `library_availability` values to `available`, and creates the required reconciliation indexes idempotently.

No tables are dropped, rebuilt, or reset.

## Required Indexes

Fresh and upgraded SQLite databases receive indexes for future reconciliation queries:

```text
ix_tracks_library_availability
ix_tracks_last_seen_scan_id
ix_audiobooks_library_availability
ix_audiobooks_last_seen_scan_id
ix_scan_runs_media_kind
ix_scan_runs_status
ix_scan_runs_started_at
```

## Files Changed

```text
personal-radio/backend/app/models.py
personal-radio/backend/app/schema_maintenance.py
personal-radio/backend/app/main.py
personal-radio/backend/app/scan_runs.py
personal-radio/backend/scripts/check_prod1_3a_scan_run_foundation.py
personal-radio/scripts/check_prod0_baseline.py
personal-radio/docs/production-upgrade/BM-PROD1.3A_Scan_Run_and_Availability_Foundation.md
```

## Tests Run

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS before implementation | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 12 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python scripts/check_prod1_3a_scan_run_foundation.py` | PASS | Proves new schema, defaults, lifecycle, failure semantics, mark-seen helpers, legacy SQLite upgrade, idempotency, required indexes, no reconciliation, and audiobook progress separation. |
| `cd backend; python scripts/check_prod1_2b_runtime_safety.py` | PASS | BM-PROD1.2B runtime safety preserved. |
| `cd backend; python scripts/check_prod1_2a_config_contract.py` | PASS | BM-PROD1.2A configuration contract preserved. |
| `cd backend; python scripts/check_prod1_1_canonical_music_roots.py` | PASS | BM-PROD1.1 canonical music roots preserved. |
| `cd backend; python scripts/check_aa_manifest_audiobook_import.py` | PASS | Audiobook manifest import preserved. |
| `cd backend; python scripts/check_audiobook_multibook_ordering.py` | PASS | Audiobook ordering preserved. |
| `cd backend; python scripts/check_audiobook_progress_reset.py` | PASS | Audiobook progress reset preserved. |
| `cd backend; python -m compileall app scripts` | PASS | Backend app and scripts compiled. |
| `cd frontend; npm run build` | PASS | TypeScript and Vite production build completed. |
| `cd frontend; npm run lint` | PASS | 0 errors, 8 existing baseline warnings. |
| `python scripts/check_prod0_baseline.py` | PASS | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 13 mandatory passed, 0 failed, 4 skipped. |

## Explicit Non-Goals

BM-PROD1.3A does not integrate scan runs into `scan_music()` or `scan_audiobooks()`.

BM-PROD1.3A does not mark unseen rows unavailable.

BM-PROD1.3A does not delete stale database rows or media files.

BM-PROD1.3A does not move, rename, retag, or mutate media files.

BM-PROD1.3A does not filter library, playback, station, queue, media, or UI behavior by availability.

BM-PROD1.3A does not add PostgreSQL migrations, Alembic, book scanning, Archive Assistant changes, or Cleaner changes.