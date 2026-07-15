# BM-PROD1.4A2 - Scanner Identity Integration and Physical-Source Preservation

Owner: Bonny Makaniankhondo
Date: 2026-07-14
Status: PASS

## Scope

BM-PROD1.4A2 integrates the A1 music identity graph into successful music scans and changes legacy duplicate heuristics so they no longer silently discard legitimate distinct physical sources.

## Starting Point

- Starting SHA: `d383512e3632d5d5dde7a1f1863f67e6d2b9ca01`
- Ending state: working tree contains A2 implementation and regression checks.
- Real application database: `personal-radio/backend/bm_radio.db`
- Real DB population: not performed.
- Real DB read-only census: all existing media and user-state tables remained at 0 rows.

## Old Heuristic Behavior

Before A2, a new candidate path could be skipped when the scanner saw the same legacy release key and duration bucket. That incremented `duplicates_skipped` and prevented creation of a durable `Track` row for a distinct physical file.

## New Physical-Source Rule

One distinct approved physical file path may own one durable `Track` row.

- Exact existing `Track.path` rows are updated first, marked seen, and identity-materialized.
- New distinct approved paths create new `Track` rows.
- Legacy release, recording, duration, artist/title/album, or codec similarity is diagnostic only.
- Former same-release/same-duration skip candidates now increment `physical_sources_preserved` and emit `physical_source_preserved` warnings.
- `duplicates_skipped` is preserved for API compatibility but no longer increments for valid distinct physical sources.

## Scanner Identity Stage

Successful music scans now follow this order:

1. Start a `ScanRun`.
2. Scan approved physical files.
3. Create or update `Track` rows.
4. Mark observed Tracks seen.
5. If file processing errors occurred, fail the scan and skip unseen reconciliation.
6. If file processing succeeded, batch materialize identity rows for observed Track IDs.
7. If identity materialization fails, fail the scan and skip unseen reconciliation.
8. If identity materialization succeeds, reconcile unseen Tracks unavailable.
9. Complete the `ScanRun` as succeeded.

The scanner result now includes:

- `identity_tracks_materialized`
- `physical_sources_preserved`

Existing fields remain:

- `duplicates_skipped`
- `duplicates_suspected`
- `variants_detected`
- `duplicate_warnings`

## Batch Materialization Strategy

`materialize_music_identity_graph()` now uses a bounded batch path:

- Load selected Tracks in fixed chunks.
- Derive Release, Edition, and Recording descriptors in Python.
- Query existing Releases, Editions, Recordings, and Track identity links by chunked `IN (...)` lookups.
- Create missing nodes.
- Create or update one `MusicTrackIdentity` per Track.
- Refresh affected Edition aggregate fields from linked physical Tracks.

`materialize_music_identity_for_track()` remains available for one-Track rebinding and delegates to the batch path.

The batch chunk size is `500`. The A2 regression verifies more than one chunk and verifies identity SELECT counts do not scale as four SELECTs per Track.

## Edition Aggregation

`MusicEdition.source_format_family` is deterministic across linked physical Tracks:

- all unknown: `UNKNOWN`
- one known family, with or without unknowns: that known family
- multiple known families: `MIXED`

`MusicEdition.source_manifest_path` is deterministic:

- one shared non-null manifest path: stored
- conflicting non-null manifest paths: `null`

## Availability Lifecycle

- Observed Tracks materialize identity whether they are newly added or returning from unavailable state.
- A returning Track keeps the same `Track.id` and keeps the same `MusicTrackIdentity.id` when its derived identity is unchanged.
- When a Track becomes unavailable during reconciliation, its identity graph rows are preserved.
- Unavailable old sources do not suppress present new sources.

## Temporary Boundary

The real BM Radio database remained empty.

A2 preserves legitimate distinct physical source paths as `Track` rows. Heuristic duplicate keys are diagnostics, not authority to discard a valid distinct physical source. A2 materializes Release/Edition/Recording identity after successful file processing.

A2 does not score quality. A2 does not select a preferred Track or Edition. Until the preference and recording-first playback phases are complete, do not populate the real library because preserved physical variants could still appear as separate Track candidates in legacy Track-centric playback logic.

No archive media file was written, moved, renamed, retagged, or deleted.

## Files Changed

- `personal-radio/backend/app/music_identity_graph.py`
- `personal-radio/backend/app/scanner/music_scanner.py`
- `personal-radio/backend/scripts/check_prod1_4a2_scanner_identity_integration.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.4A2_Scanner_Identity_Integration_and_Physical_Source_Preservation.md`

## Verification

- Targeted A2 regression: PASS
  - `cd personal-radio/backend; python scripts/check_prod1_4a2_scanner_identity_integration.py`
- A1 regression: PASS
  - `python scripts/check_prod1_4a1_music_identity_graph.py`
- Music reconciliation regression: PASS
  - `python scripts/check_prod1_3b_music_scan_reconciliation.py`
- D1 regression: PASS
  - `python scripts/check_prod1_3d1_core_availability_policy.py`
- D2 regression: PASS
  - `python scripts/check_prod1_3d2_active_playback_candidates.py`
- D3 regression: PASS
  - `python scripts/check_prod1_3d3_integrity_reporting.py`
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
- Full production gate: PASS, 22 mandatory passed, 0 failed, 4 skipped
  - `python scripts/check_prod0_baseline.py`
- Diff quality: PASS
  - `git diff --check`

## Deferred Work

- BM-PROD1.4B objective technical quality signal extraction.
- BM-PROD1.4C automatic preferred-source resolution and manual override foundation.
- BM-PROD1.4D active library/playback/UI integration.
- BM-PROD1.5 recording-first station-engine review and live/acoustic/remix affinity.
- BM-PROD3/BM-PROD4 large-library and station performance.
- Controlled real-media canary after the preference pipeline is complete.