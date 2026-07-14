# BM-PROD1.3C1 Audiobook ScanRun and Progress-Safe Rescan

Owner: Bonny Makaniankhondo
Project: BM Radio Production Upgrade
Date: 2026-07-14
Scope: Audiobook ScanRun integration, stable audiobook/chapter identity, and progress-safe rescanning

## Baseline

| Item | Value |
| --- | --- |
| Starting commit | `47f5aecc689e4897392f2d5203091c0f9c9b1bf2` |
| Starting worktree | Clean |
| Ending state | Pending working-tree changes |

Pre-change gate result:

```text
python scripts/check_prod0_baseline.py
PASS when run outside the Windows sandbox Vite spawn restriction
14 mandatory passed, 0 failed, 4 integration checks skipped
```

## Real Database Safety

The real BM Radio application database was not scanned or populated.

Observed local database counts after validation:

```text
personal-radio/backend/bm_radio.db
tracks: 0
audiobooks: 0
scan_runs: table missing
```

All BM-PROD1.3C1 validation used temporary SQLite databases and temporary audiobook roots.

## Audiobook ScanRun Lifecycle

`scan_audiobooks()` now creates a durable audiobook `ScanRun` for every audiobook scan attempt.

Lifecycle:

```text
resolve configured audiobook root
verify root exists
start ScanRun(media_kind=audiobook)
discover audiobook object folders
for each object:
  resolve exact path first
  update/create Audiobook safely
  mark audiobook seen
  update current chapter rows by exact chapter path
if no errors:
  complete ScanRun as succeeded
else:
  mark ScanRun as failed
```

BM-PROD1.3C1 never marks unseen audiobooks unavailable.

## Exact-Path-First Rule

For a scanned audiobook folder, exact path lookup now happens before duplicate/work/edition suppression.

If the exact path already exists, the scanner:

```text
preserves Audiobook.id
preserves Audiobook.status
preserves Audiobook.favorite
preserves AudiobookProgress rows
preserves PlaybackEvent rows
updates scanner-owned metadata fields
calls mark_audiobook_seen()
updates chapters non-destructively
```

## Duplicate Cleanup Changes

The scanner no longer deletes an exact-path `Audiobook` row or wholesale deletes its chapters when duplicate heuristics match another row.

For a new candidate path with no exact existing row, duplicate suppression can still skip creation and record diagnostics without deleting existing rows.

Duplicate/work maps prefer currently available rows plus rows observed during the current scan. Existing unavailable old identities do not suppress a present new candidate by themselves.

## Stable Audiobook Identity

Identical rescans preserve the same `Audiobook.id` and advance `last_seen_scan_id` through the current audiobook `ScanRun`.

`Audiobook.library_availability` is restored to `available` for exact paths observed by the scan, but no missing-book reconciliation runs yet.

## Stable Chapter Identity

Existing chapter rows are reconciled by exact chapter path.

For currently discovered chapter files:

```text
existing exact path -> update AudiobookChapter in place
new exact path -> add AudiobookChapter row
```

Scanner-owned fields updated in place:

```text
relative_path
title
chapter_number
duration_seconds
sort_order
```

Repeated identical scans preserve `AudiobookChapter.id` values.

## Progress Preservation

The targeted regression proves an `AudiobookProgress` row keeps:

```text
row id
audiobook_id
chapter_id
position_seconds
progress_percent
status
```

across identical rescans and metadata refreshes.

## Favorite, Status, and Playback Preservation

Audiobook rescans preserve:

```text
Audiobook.status
Audiobook.favorite
PlaybackEvent.audiobook_id
AudiobookProgress
Audiobook.id
```

`Audiobook.status` remains listener state only.

## AA Manifest Preservation

Archive Assistant audiobook metadata remains authoritative through the existing sidecar/manifest flow:

```text
load_aa_manifest_context()
extract_audiobook_manifest_metadata()
load_audiobook_sidecar()
```

The AA audiobook manifest regression remains passing.

## Missing Chapter Temporary Policy

BM-PROD1.3C1 intentionally does not delete previously indexed chapter rows when a chapter file is no longer present.

This is temporary and deliberate. Final missing-chapter policy belongs to BM-PROD1.3C2, where it can be designed with audiobook availability reconciliation and progress preservation.

The real database is empty, so this temporary behavior does not accumulate production stale chapters during this phase.

## Remaining Scalability Concern

The scanner avoids new per-object and per-chapter exact-path queries by building scan-local audiobook and chapter path maps.

It still uses in-memory identity maps for duplicate/work/edition checks. Full large-library optimization remains BM-PROD3 work.

## Files Changed

```text
personal-radio/backend/app/scanner/audiobook_scanner.py
personal-radio/backend/scripts/check_prod1_3c1_audiobook_scan_progress_safety.py
personal-radio/scripts/check_prod0_baseline.py
personal-radio/docs/production-upgrade/BM-PROD1.3C1_Audiobook_ScanRun_and_Progress_Safe_Rescan.md
```

## Tests Run

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS before implementation | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 14 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python scripts/check_prod1_3c1_audiobook_scan_progress_safety.py` | PASS | Proves cases A-R: ScanRun lifecycle, stable audiobook ID, stable chapter IDs, progress preservation, favorite/status/playback preservation, metadata refresh, new chapter add, missing chapter not deleted, duplicate safety, variants, unavailable old identity guard, zero-root failure, processing-error failure, ordering, AA metadata, and no file mutation. |
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
| `python scripts/check_prod0_baseline.py` | PASS | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 15 mandatory passed, 0 failed, 4 skipped. |

## Explicit Non-Goals

BM-PROD1.3C1 does not mark missing `Audiobook` rows unavailable.

BM-PROD1.3C1 does not implement returning-missing-book lifecycle or final missing-chapter cleanup policy.

BM-PROD1.3C1 does not hide unavailable audiobooks from reader endpoints or block playback.

BM-PROD1.3C1 does not change frontend UI, music reconciliation behavior, database schema, PostgreSQL migration, Alembic, Archive Assistant, Cleaner, or real media canary behavior.

No archive audiobook file was deleted, moved, renamed, retagged, rewritten, or mutated.