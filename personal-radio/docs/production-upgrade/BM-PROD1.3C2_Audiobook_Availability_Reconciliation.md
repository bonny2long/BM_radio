# BM-PROD1.3C2 Audiobook Availability Reconciliation

Owner: Bonny Makaniankhondo
Project: BM Radio Production Upgrade
Date: 2026-07-14
Scope: Audiobook and audiobook-chapter availability reconciliation only

## Baseline

| Item | Value |
| --- | --- |
| Starting commit | `22e8dc9dc833e5e425fea7d2a50d3580052283fd` |
| Starting worktree | Clean |
| Ending state | Pending working-tree changes |

Pre-change gate result:

```text
python scripts/check_prod0_baseline.py
PASS when run outside the Windows sandbox Vite spawn restriction
15 mandatory passed, 0 failed, 4 integration checks skipped
```

## Real Database Safety

The real BM Radio application database was not scanned, initialized for this task, or populated.

Observed local database counts after validation:

```text
personal-radio/backend/bm_radio.db
tracks: 0
audiobooks: 0
audiobook_chapters: 0
scan_runs: table missing
```

All C2 validation used temporary SQLite databases and temporary audiobook roots.

## Chapter Availability Schema

BM-PROD1.3C2 adds durable availability fields to `AudiobookChapter`:

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

`AudiobookChapter.library_availability` is separate from `Audiobook.library_availability`, `Audiobook.status`, and `ScanRun.status`.

## Additive Migration

`ensure_scan_reconciliation_columns()` now also upgrades existing SQLite `audiobook_chapters` tables additively.

It preserves existing chapter ids, paths, and progress references, backfills null chapter `library_availability` to `available`, and creates indexes:

```text
ix_audiobook_chapters_library_availability
ix_audiobook_chapters_last_seen_scan_id
```

No table is dropped, rebuilt, or reset.

## Whole-Audiobook Missing Policy

After a successful error-free audiobook scan, an available indexed `Audiobook` under the scanned root that was not seen in the current `ScanRun` becomes:

```text
library_availability = unavailable
unavailable_since = reconciliation timestamp
```

Its currently available chapter rows also become unavailable with the same timestamp.

Rows are retained. `Audiobook.id`, `Audiobook.status`, favorites, progress, playback events, metadata, path, and chapters are preserved.

`ScanRun.items_unavailable` counts newly unavailable Audiobook rows only.

## Missing-Chapter Policy

For an audiobook seen in the current scan, available chapter rows not seen in the current `ScanRun` become unavailable.

A missing chapter does not make the whole audiobook unavailable.

Missing chapter rows are retained as unavailable historical index objects so `AudiobookProgress.chapter_id` remains valid.

## Returning Restoration

A returning exact-path audiobook restores the same `Audiobook.id`:

```text
library_availability = available
unavailable_since = null
last_seen_scan_id = current ScanRun id
```

A returning exact-path chapter restores the same `AudiobookChapter.id` with the same availability reset.

No guessed identity migration is performed for renamed chapter files.

## Failed-Scan Rule

Audiobook and chapter reconciliation runs only after a successful, error-free scan with an existing root.

Failed scans produce:

```text
ScanRun.status = failed
audiobooks_unavailable = 0
chapters_unavailable = 0
ScanRun.items_unavailable = 0
```

Existing availability timestamps are not rewritten by failed scans.

## Root Scope

Reconciliation is restricted to the configured audiobook root that was successfully scanned.

Path-aware containment protects boundaries such as:

```text
Audiobooks/Library
Audiobooks/Library-OLD
```

`Library-OLD` is not reconciled as part of `Library`.

## Renamed Chapter Policy

A renamed chapter is treated non-destructively:

```text
old exact path -> existing chapter row becomes unavailable
new exact path -> new available chapter row
```

Progress/history rows are not deleted or reassigned automatically.

## Files Changed

```text
personal-radio/backend/app/models.py
personal-radio/backend/app/schema_maintenance.py
personal-radio/backend/app/scan_runs.py
personal-radio/backend/app/scanner/audiobook_scanner.py
personal-radio/backend/scripts/check_prod1_3c2_audiobook_reconciliation.py
personal-radio/scripts/check_prod0_baseline.py
personal-radio/docs/production-upgrade/BM-PROD1.3C2_Audiobook_Availability_Reconciliation.md
```

## Tests Run

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS before implementation | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 15 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python scripts/check_prod1_3c2_audiobook_reconciliation.py` | PASS | Proves fresh schema, legacy upgrade, indexes, seen-state, whole-book missing/returning, missing/returning chapter, progress preservation, failed-scan safety, root scope, empty folder, renamed chapter, variant independence, and no file mutation. |
| `cd backend; python scripts/check_prod1_3c1_audiobook_scan_progress_safety.py` | PASS | C1 progress-safe rescan behavior preserved. |
| `cd backend; python scripts/check_aa_manifest_audiobook_import.py` | PASS | AA audiobook manifest import preserved. |
| `cd backend; python scripts/check_audiobook_multibook_ordering.py` | PASS | Multi-book ordering preserved. |
| `cd backend; python scripts/check_audiobook_progress_reset.py` | PASS | Progress reset behavior preserved. |
| `cd backend; python scripts/check_prod1_3b_music_scan_reconciliation.py` | PASS | Music reconciliation preserved. |
| `cd backend; python scripts/check_prod1_3a_scan_run_foundation.py` | PASS | ScanRun foundation preserved. |
| `cd backend; python scripts/check_prod1_2b_runtime_safety.py` | PASS | Runtime safety preserved. |
| `cd backend; python scripts/check_prod1_2a_config_contract.py` | PASS | Production config contract preserved. |
| `cd backend; python scripts/check_prod1_1_canonical_music_roots.py` | PASS | Canonical music roots preserved. |
| `cd backend; python -m compileall app scripts` | PASS | Backend app and scripts compiled. |
| `cd frontend; npm run build` | PASS | TypeScript and Vite production build completed. |
| `cd frontend; npm run lint` | PASS | 0 errors, 8 existing baseline warnings. |
| `python scripts/check_prod0_baseline.py` | PASS | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 16 mandatory passed, 0 failed, 4 skipped. |

## Explicit Non-Goals

BM-PROD1.3C2 does not add unavailable-media filtering in audiobook, music, station, playback, or library routes.

BM-PROD1.3C2 does not implement automatic chapter rename identity migration, audiobook path migration, or edition merging.

BM-PROD1.3C2 does not delete database media/user-state rows.

BM-PROD1.3C2 does not delete, move, rename, retag, rewrite, or mutate archive audiobook files.

BM-PROD1.3C2 does not add PostgreSQL migrations, Alembic, Archive Assistant changes, Cleaner changes, real DB population, or real audiobook library scanning.

Reader/query behavior for unavailable media is deferred to BM-PROD1.3D.