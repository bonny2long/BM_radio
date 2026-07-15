# BM-PROD1.4C2 - Scanner-Driven Preference Re-evaluation

Owner: Bonny Makaniankhondo
Date: 2026-07-15
Status: PASS

## Scope

BM-PROD1.4C2 integrates conservative preferred-source re-evaluation into successful authoritative music scans. It keeps `MusicRecordingPreference` rows current for the MusicRecordings actually affected by a scan, without changing library browsing, search, queues, playlists, stations, playback, media streaming, frontend, or public override APIs.

## Starting Point

- Starting SHA: `972107d5f84a68b5671bbf15af66bd6b8d05b954`
- Ending state: working tree contains C2 implementation and regression checks.
- Real application database: `personal-radio/backend/bm_radio.db`
- Real DB population: not performed.
- Real DB read-only census: all existing media and user-state tables remained at 0 rows.

## Affected Recording Definition

The scanner now builds a bounded `affected_recording_ids` set from scan-local changes only:

- pre-materialization Recording IDs for observed exact-path Tracks
- post-materialization Recording IDs for all observed Tracks
- Recording IDs for Tracks discovered as newly unseen and about to be reconciled unavailable

The set is deduplicated and passed explicitly to `evaluate_music_recording_preferences()`. The scanner does not call full-library preference evaluation.

## Shared Helpers

`scan_runs.find_unseen_track_ids()` now exposes the exact Track IDs that `reconcile_unseen_tracks()` will mark unavailable. `reconcile_unseen_tracks()` uses that shared helper, preserving existing path-scope and root-boundary behavior.

`music_source_preference.music_recording_ids_for_track_ids()` provides a chunked Track-to-Recording lookup using grouped `IN (...)` queries and no per-Track SELECT loop.

## Scanner Transaction Order

Successful music scans now run:

1. Start `ScanRun`.
2. Scan physical files, create/update Tracks, and mark observed Tracks seen.
3. Fail early on per-file scanner errors with no reconciliation or preference evaluation.
4. Capture pre-materialization Recording IDs for observed Track IDs.
5. Persist technical profiles.
6. Batch materialize/rebind the identity graph.
7. Capture post-materialization Recording IDs.
8. Discover unseen Track IDs and capture their Recording IDs.
9. Reconcile unseen Tracks unavailable.
10. Evaluate preferences only for the affected Recording ID union.
11. Complete `ScanRun` succeeded.
12. Commit.

If preference evaluation raises an internal exception, the scan rolls back uncommitted mutations, marks the `ScanRun` failed, reports `tracks_unavailable = 0`, and leaves no newly-unavailable reconciliation or partial preference state committed.

## Scanner Counters

The scanner result now includes bounded preference counters:

- `preference_recordings_affected`
- `preferences_evaluated`
- `preferences_created`
- `preferences_updated`

No per-recording preference dumps are returned.

## Behavior Confirmed

- New single source creates a preference.
- Unchanged rescans are idempotent.
- Adding FLAC to MP3 refreshes the affected Recording preference to the unique lossless source.
- Adding a second lossless source clears the stale automatic winner and marks the decision ambiguous.
- Missing preferred source re-evaluates to the remaining available source.
- Ambiguous two-lossless source state can become single-source preferred when one source disappears.
- Returning exact paths reuse Track, technical profile, and identity rows when identity is unchanged.
- Identity rebinds re-evaluate both old and new Recordings.
- User override storage is preserved through automatic re-evaluation and availability changes.

## Boundaries

The real BM Radio database remained empty.

C2 re-evaluates only MusicRecordings affected by the authoritative music scan. C2 does not perform a full-library preference evaluation on every scan. C2 re-evaluates both old and new Recording identities when metadata causes a Track identity rebind. C2 re-evaluates Recordings whose physical Tracks become unavailable. C2 preserves user-preferred Track overrides while refreshing automatic preference decisions.

C2 does not change library, search, queue, playlist, station, playback, media-streaming, or frontend behavior.

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/scan_runs.py`
- `personal-radio/backend/app/music_source_preference.py`
- `personal-radio/backend/app/scanner/music_scanner.py`
- `personal-radio/backend/scripts/check_prod1_4c2_scanner_preference_reevaluation.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.4C2_Scanner_Driven_Preference_Reevaluation.md`

## Verification

- Targeted C2 regression: PASS
  - `cd personal-radio/backend; python scripts/check_prod1_4c2_scanner_preference_reevaluation.py`
- C1 regression: PASS
  - `python scripts/check_prod1_4c1_preferred_source_policy.py`
- B1 regression: PASS
  - `python scripts/check_prod1_4b1_music_technical_profile.py`
- A2 regression: PASS
  - `python scripts/check_prod1_4a2_scanner_identity_integration.py`
- A1 regression: PASS
  - `python scripts/check_prod1_4a1_music_identity_graph.py`
- D1 regression: PASS
  - `python scripts/check_prod1_3d1_core_availability_policy.py`
- D2 regression: PASS
  - `python scripts/check_prod1_3d2_active_playback_candidates.py`
- D3 regression: PASS
  - `python scripts/check_prod1_3d3_integrity_reporting.py`
- Music reconciliation regression: PASS
  - `python scripts/check_prod1_3b_music_scan_reconciliation.py`
- Audiobook regressions: PASS
  - `python scripts/check_prod1_3c1_audiobook_scan_progress_safety.py`
  - `python scripts/check_prod1_3c2_audiobook_reconciliation.py`
  - `python scripts/check_aa_manifest_audiobook_import.py`
  - `python scripts/check_audiobook_multibook_ordering.py`
  - `python scripts/check_audiobook_progress_reset.py`
- Backend compile: PASS
  - `python -m compileall app scripts`
- Frontend build: PASS
  - `npm run build`
- Frontend lint: PASS, 0 errors, 8 existing warnings
  - `npm run lint`
- Full production gate: PASS, 25 mandatory passed, 0 failed, 4 skipped
  - `python scripts/check_prod0_baseline.py`
- Diff quality: PASS
  - `git diff --check`

## Deferred Work

- Public manual override API and operator controls.
- Participation states: included / library_only / archived / blocked.
- Active library/search preferred-source presentation.
- Active queue/playback preferred-source resolution.
- Recording-first station engine.
- Live/acoustic/remix station affinity.
- Release/edition-family refinement where stronger evidence exists.
- Large-library scanner and station performance.
- Controlled real-media canary after preference pipeline completion.