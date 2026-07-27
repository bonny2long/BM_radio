# BM-PROD1.3D1 Core Active-Library Availability Policy

Owner: Bonny Makaniankhondo
Project: BM Radio Production Upgrade
Date: 2026-07-14
Scope: Core active-library availability policy for library, search, audiobook reader, and direct media-serving routes

## Baseline

| Item | Value |
| --- | --- |
| Starting commit | `f23a04edf280d179e5aaaafafe1ddad60b649b8f` |
| Starting worktree | Pending BM-PROD1.3C2 work already applied in the branch state |
| Ending state | Pending working-tree changes |

Pre-change gate result for this task:

```text
python scripts/check_prod0_baseline.py
PASS when run outside the Windows sandbox Vite spawn restriction
Mandatory: 16 passed, 0 failed
Optional/integration: 4 skipped
```

## Real Database Safety

No real library scan, canary, or data population was performed.

Read-only inspection of `personal-radio/backend/bm_radio.db` after validation:

```text
tracks: 0
audiobooks: 0
audiobook_chapters: 0
scan_runs: table missing
```

## Central Availability Policy

Added `backend/app/availability.py` as the single active-media policy surface.

The active state is:

```text
library_availability == "available"
```

The module exposes constants, composable SQLAlchemy filters, active query helpers, and row-level predicates for:

```text
Track
Audiobook
AudiobookChapter
```

No global ORM loader criteria, model-level default scope, or row deletion was added. Integrity and internal diagnostics can still query historical unavailable rows explicitly.

## Music Library Policy

Default Track browsing now starts from active Tracks only.

Affected core reader/library surfaces include:

```text
/api/library/tracks
/api/library/tracks-page
/api/library/search
/api/library/album-tracks
artist detail/track pages
album/recent-album aggregates
library summary counts
```

Artist and album aggregate counts now count only available Tracks. Artists or albums with only unavailable Tracks do not appear as active library groups.

## Global Search Policy

Global music search now filters Tracks, artist counts, album counts, and station suggestions through available Track rows.

Global audiobook search now filters to available Audiobooks. Chapter-title matching joins only available chapter rows, so an unavailable historical chapter title cannot create an active audiobook search hit.

## Audiobook Reader Policy

Default audiobook list and recent/progress reader surfaces now include only available Audiobooks.

Audiobook summary active counts use available Audiobooks only for:

```text
available
not_started
in_progress
finished
favorites
```

`total_listening_seconds` intentionally remains historical user state and still sums preserved progress across available and unavailable books.

Available audiobook detail returns only available chapters in the playable chapter list. If stored progress points to an unavailable chapter, the stored row remains unchanged and normal active `latest_progress` is null.

Unavailable audiobook detail returns HTTP 409 with:

```text
Audiobook is unavailable in the current library
```

Progress writes are rejected with HTTP 409 when the Audiobook is unavailable or when the supplied chapter row exists but is unavailable. Existing progress rows are not deleted or rewritten.

Favorite, finished, and explicit reset behavior remains user-state behavior and was not broadly blocked by availability.

## Media Serving Policy

Direct media serving now checks known database availability before filesystem serving.

Unavailable Track stream/cover requests return HTTP 409 before path checks or folder walking.

Album cover lookup selects from available Tracks only.

Unavailable Audiobook chapter stream requests return HTTP 409 when either the Audiobook or Chapter is unavailable.

Unavailable Audiobook cover requests return HTTP 409 before walking historical source folders.

Music media roots remain scoped to the configured active library root. Legacy Discographies is included only when legacy discography scanning is enabled.

## Serializer Fields

Normal serializers now include explicit availability state:

```text
track_item: library_availability, unavailable_since
chapter_item: library_availability, unavailable_since
audiobook_item: library_availability, unavailable_since
```

No absolute filesystem paths or scan-run internals were added to normal serializers.

## Files Changed

```text
personal-radio/backend/app/availability.py
personal-radio/backend/app/routes/library.py
personal-radio/backend/app/routes/search.py
personal-radio/backend/app/routes/audiobooks.py
personal-radio/backend/app/routes/media.py
personal-radio/backend/app/routes/serializers.py
personal-radio/backend/scripts/check_prod1_3d1_core_availability_policy.py
personal-radio/scripts/check_prod0_baseline.py
personal-radio/docs/production-upgrade/BM-PROD1.3D1_Core_Active_Library_Availability_Policy.md
```

## Tests Run

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS | Pre-change D1 baseline outside sandbox; 16 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python scripts/check_prod1_3d1_core_availability_policy.py` | PASS | Proves central policy and Cases A-Y with temp DB/media only. |
| `cd backend; python scripts/check_prod1_3b_music_scan_reconciliation.py` | PASS | Music reconciliation preserved. |
| `cd backend; python scripts/check_prod1_3c1_audiobook_scan_progress_safety.py` | PASS | Audiobook C1 progress-safe rescan preserved. |
| `cd backend; python scripts/check_prod1_3c2_audiobook_reconciliation.py` | PASS | Audiobook C2 reconciliation preserved. |
| `cd backend; python scripts/check_aa_manifest_audiobook_import.py` | PASS | AA audiobook manifest import preserved. |
| `cd backend; python scripts/check_audiobook_multibook_ordering.py` | PASS | Multi-book ordering preserved. |
| `cd backend; python scripts/check_audiobook_progress_reset.py` | PASS | Explicit reset behavior preserved. |
| `cd backend; python scripts/check_prod1_3a_scan_run_foundation.py` | PASS | Scan-run foundation preserved. |
| `cd backend; python scripts/check_prod1_2b_runtime_safety.py` | PASS | Runtime API safety preserved. |
| `cd backend; python scripts/check_prod1_2a_config_contract.py` | PASS | Production config contract preserved. |
| `cd backend; python scripts/check_prod1_1_canonical_music_roots.py` | PASS | Canonical music root policy preserved. |
| `cd backend; python -m compileall app scripts` | PASS | Backend app and scripts compiled. |
| `cd frontend; npm run build` | PASS | Required outside sandbox due known Windows Vite `spawn EPERM`. |
| `cd frontend; npm run lint` | PASS | 0 errors, 8 existing baseline warnings. |
| `python scripts/check_prod0_baseline.py` | PASS | Full post-change gate outside sandbox; 17 mandatory passed, 0 failed, 4 skipped. |
| `git diff --check` | PASS | No whitespace errors. |

## Explicit Non-Goals

BM-PROD1.3D1 does not implement queue, station, playlist, smart-playlist, recent playback, or playback-event availability policy. That remains BM-PROD1.3D2.

BM-PROD1.3D1 does not redesign `/api/library/integrity`, unavailable-media diagnostics, scan-run history UI/API, or operator repair controls. That remains BM-PROD1.3D3.

BM-PROD1.3D1 does not delete media rows, user-state rows, playback history, progress, favorites, status, or archive files.

BM-PROD1.3D1 does not run a real library scan, populate the real database, or start the controlled real-media canary.

BM-PROD3 large-library scanner/query optimization remains deferred.