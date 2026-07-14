# BM-PROD1.3B Music Scan-Run and Reconciliation

Owner: Bonny Makaniankhondo
Project: BM Radio Production Upgrade
Date: 2026-07-14
Scope: Music scanner ScanRun integration and safe Track availability reconciliation

## Baseline

| Item | Value |
| --- | --- |
| Starting commit | `7ffdfd7b8a932a9a94a18ad6a1f123df483199cf` |
| Starting worktree | Clean |
| Ending state | Pending working-tree changes |

Pre-change gate result:

```text
python scripts/check_prod0_baseline.py
PASS when run outside the Windows sandbox Vite spawn restriction
13 mandatory passed, 0 failed, 4 integration checks skipped
```

## Real Database Safety

The real BM Radio application database was not scanned or populated.

Observed local database counts after implementation validation:

```text
personal-radio/backend/bm_radio.db
tracks: 0
scan_runs: table missing
audiobooks: 0
```

All BM-PROD1.3B reconciliation testing used temporary SQLite databases and temporary music roots under `backend/tmp_tests`.

## Music Scan Lifecycle

`scan_music()` now creates a durable music `ScanRun` for every music scan attempt.

Lifecycle:

```text
resolve configured music roots
determine existing roots
start ScanRun(media_kind=music)
scan only existing approved roots
mark every indexed present Track as seen
if error-free and at least one root was scanned:
  reconcile unseen available Tracks inside scanned roots only
  complete ScanRun as succeeded
else:
  complete no reconciliation
  mark ScanRun as failed
```

The scan result now includes:

```text
status
scan_run_id
scan_run_status
tracks_scanned
tracks_added
tracks_updated
tracks_unavailable
roots_scanned
skipped_roots
legacy_discography_scan_enabled
errors
```

Existing duplicate/title/parser diagnostic fields are preserved.

## Successful Scan Definition

Unseen-row reconciliation runs only when:

```text
at least one configured music root exists and was scanned
no fatal scanner exception occurred
no per-file processing errors were recorded
```

On success, `ScanRun` counters are set as:

```text
items_discovered = tracks_scanned
items_added = tracks_added
items_updated = tracks_updated
items_unavailable = tracks_unavailable
error_count = 0
```

## Failed Scan Behavior

Zero-root scans, per-file errors, and fatal exceptions fail closed:

```text
ScanRun.status = failed
items_unavailable = 0
tracks_unavailable = 0
```

Failed scans do not mark unseen Tracks unavailable.

## Zero-Root Behavior

If no configured music scan root exists on disk, `scan_music()` records a failed music `ScanRun`, returns a clear error, and performs no reconciliation. This protects missing NAS/container mounts from turning an indexed library unavailable.

## Partial-Root Behavior

If one configured root exists and another is missing, the scanner scans the existing root and reports the missing root in `skipped_roots`.

Reconciliation is limited to roots actually scanned. A missing configured MP3 root does not make MP3 rows unavailable when only FLAC was scanned.

## Root-Scoped Reconciliation

`reconcile_unseen_tracks()` was added in:

```text
personal-radio/backend/app/scan_runs.py
```

It considers only:

```text
Track rows
library_availability = available
paths narrowed by scanned-root SQL prefixes
paths confirmed by path-aware root containment
last_seen_scan_id not equal to the current scan run
```

It never deletes Track rows or user-state rows.

Path-boundary protection is covered: `FLAC-OLD` is not treated as inside `FLAC`.

## Exact-Path Before Duplicate Rule

`scan_music()` now builds one scan-local exact-path map from existing Tracks, including unavailable rows.

For every scanned file, exact path lookup happens before duplicate suppression. If an exact path exists, that row is updated and marked seen even if another row has the same release/recording identity.

Duplicate suppression for new candidate paths still applies, but unavailable old duplicate rows do not block a currently present new path by themselves.

## Returning-File Restoration

When a previously unavailable exact-path Track is seen again, the same row is restored:

```text
library_availability = available
unavailable_since = null
last_seen_scan_id = current scan run id
```

Track id and user state are preserved.

## User-State Preservation

The targeted regression verifies Track favorites and thumbs survive this cycle:

```text
available -> unavailable -> available
```

No playlist, playback, radio-profile, favorite, or thumb rows are deleted by reconciliation.

## Remaining Scalability Concern

BM-PROD1.3B avoids adding more per-file Track-by-path queries by using one scan-local exact-path lookup.

The scanner still builds full scan-local Track identity maps for exact-path and duplicate checks. That is acceptable for this safety phase and remains a BM-PROD3 large-library optimization concern.

## Files Changed

```text
personal-radio/backend/app/scan_runs.py
personal-radio/backend/app/scanner/music_scanner.py
personal-radio/backend/scripts/check_prod1_3b_music_scan_reconciliation.py
personal-radio/scripts/check_prod0_baseline.py
personal-radio/docs/production-upgrade/BM-PROD1.3B_Music_Scan_Run_and_Reconciliation.md
```

## Tests Run

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS before implementation | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 13 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python scripts/check_prod1_3b_music_scan_reconciliation.py` | PASS | Proves cases A-O: first scan, idempotent rescan, unavailable marking, returning restoration, user-state survival, outside-root safety, path-boundary safety, missing-root safety, zero-root fail-closed, per-file error failure, exact-path precedence, unavailable duplicate handling, legacy disabled/enabled scope, and no file mutation. |
| `cd backend; python scripts/check_prod1_3a_scan_run_foundation.py` | PASS | Foundation preserved. |
| `cd backend; python scripts/check_prod1_2b_runtime_safety.py` | PASS | Runtime safety preserved. |
| `cd backend; python scripts/check_prod1_2a_config_contract.py` | PASS | Production config contract preserved. |
| `cd backend; python scripts/check_prod1_1_canonical_music_roots.py` | PASS | Canonical music roots preserved. |
| `cd backend; python scripts/check_aa_manifest_music_import.py` | PASS | Archive Assistant music manifest import preserved. |
| `cd backend; python scripts/check_aa_manifest_audiobook_import.py` | PASS | Audiobook manifest import preserved. |
| `cd backend; python scripts/check_audiobook_multibook_ordering.py` | PASS | Audiobook ordering preserved. |
| `cd backend; python scripts/check_audiobook_progress_reset.py` | PASS | Audiobook progress reset preserved. |
| `cd backend; python -m compileall app scripts` | PASS | Backend app and scripts compiled. |
| `cd frontend; npm run build` | PASS | TypeScript and Vite production build completed. |
| `cd frontend; npm run lint` | PASS | 0 errors, 8 existing baseline warnings. |
| `python scripts/check_prod0_baseline.py` | PASS | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 14 mandatory passed, 0 failed, 4 skipped. |

## Explicit Non-Goals

BM-PROD1.3B does not implement audiobook reconciliation.

BM-PROD1.3B does not hide unavailable Tracks from reader endpoints; query policy remains BM-PROD1.3D.

BM-PROD1.3B does not delete Track rows or media files.

BM-PROD1.3B does not move, rename, retag, rewrite, or mutate archive media.

BM-PROD1.3B does not perform a real full-library scan or populate Bonny's real BM Radio database.

BM-PROD1.3B does not add PostgreSQL migrations, Alembic, Archive Assistant changes, or Cleaner changes.