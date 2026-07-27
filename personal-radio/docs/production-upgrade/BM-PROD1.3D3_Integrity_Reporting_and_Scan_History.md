# BM-PROD1.3D3 - Integrity Reporting and Scan History

Owner: Bonny Makaniankhondo
Date: 2026-07-14
Status: PASS

## Scope

BM-PROD1.3D3 extends the read-only library integrity surface so the app can report active library health, historical user-state references, and scan-run history without repairing, deleting, rescanning, or mutating media rows.

## Starting Point

- Starting SHA: `beb73818c8f119dc809253e169f952e6073b045f`
- Ending state: working tree contains D3 implementation and regression checks.
- Real application database: `personal-radio/backend/bm_radio.db`
- Real DB population: not performed.
- Real DB read-only census:
  - `tracks`: 0
  - `audiobooks`: 0
  - `audiobook_chapters`: 0
  - `audiobook_progress`: 0
  - `playlists`: 0
  - `playlist_tracks`: 0
  - `stations`: 0
  - `track_favorites`: 0
  - `track_thumbs`: 0
  - `playback_events`: 0
  - `album_radio_profiles`: 0
  - `artist_radio_profiles`: 0
  - `track_radio_profiles`: 0

## Backend Result

- Preserved existing duplicate, variant, and metadata integrity diagnostics.
- Extended `/api/library/integrity` as a read-only report with:
  - `generated_at`
  - `read_only: true`
  - `availability_policy: "available"`
  - active and historical summary counts
  - album availability counts
  - audiobook chapter availability counts
  - latest music and audiobook scan summaries
  - bounded issue samples
  - stable issue IDs
- Added `/api/library/scan-runs` as a read-only scan history endpoint with:
  - `media_kind` filter
  - `status` filter
  - bounded `limit`
  - newest-first ordering
  - sanitized error summaries
  - malformed roots JSON safety
- Added D3 issue types:
  - `unavailable_tracks`
  - `unavailable_audiobooks`
  - `partial_audiobooks`
  - `audiobook_progress_on_unavailable_chapter`
  - `historical_state_on_unavailable_tracks`
  - `stale_scan_runs`
  - `failed_scan_runs`
- Implemented stale running scan detection without mutating scan rows.
- Used SQL aggregation for the new count surfaces.
- Removed the audiobook chapter-count N+1 path from the integrity report.
- Left real media files untouched.
- Left user-state and library rows untouched.

## Frontend Result

- Updated integrity API types for summary, issues, latest scans, and scan-run records.
- Added scan-run history API client.
- Reworked the Library Integrity page to show:
  - read-only diagnostics notice
  - generated timestamp and active-library policy
  - active availability summary cards
  - latest music and audiobook scan cards
  - scan history table/list
  - issue filtering and bounded samples
  - empty-library state
- No repair, delete, rescan, mark-available, or other mutation controls were added.

## Files Changed

- `personal-radio/backend/app/routes/library_integrity.py`
- `personal-radio/backend/scripts/check_prod1_3d3_integrity_reporting.py`
- `personal-radio/frontend/src/api.ts`
- `personal-radio/frontend/src/pages/LibraryIntegrityPage.tsx`
- `personal-radio/frontend/scripts/check_prod1_3d3_integrity_ui.mjs`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.3D3_Integrity_Reporting_and_Scan_History.md`

## Verification

- D3 backend regression: PASS
  - `cd personal-radio/backend; python scripts/check_prod1_3d3_integrity_reporting.py`
- D3 frontend regression: PASS
  - `cd personal-radio/frontend; node scripts/check_prod1_3d3_integrity_ui.mjs`
- D1 regression: PASS
  - `python scripts/check_prod1_3d1_core_availability_policy.py`
- D2 regression: PASS
  - `python scripts/check_prod1_3d2_active_playback_candidates.py`
- Music reconciliation regression: PASS
  - `python scripts/check_prod1_3b_music_scan_reconciliation.py`
- Audiobook C1 regression: PASS
  - `python scripts/check_prod1_3c1_audiobook_scan_progress_safety.py`
- Audiobook C2 regression: PASS
  - `python scripts/check_prod1_3c2_audiobook_reconciliation.py`
- Backend compile: PASS
  - `python -m compileall app scripts`
- Frontend build: PASS
  - `npm run build`
- Frontend lint: PASS, 0 errors, 8 existing warnings
  - `npm run lint`
- Full production gate: PASS, 20 mandatory passed, 0 failed, 4 skipped
  - `python scripts/check_prod0_baseline.py`
- Whitespace check: PASS
  - `git diff --check`

## Deferred Work

- Controlled small real-media canary.
- BM-PROD3 large-library scanner and query optimization.
- BM-PROD4 station-engine scale optimization.
- PostgreSQL migration and NAS deployment hardening.
