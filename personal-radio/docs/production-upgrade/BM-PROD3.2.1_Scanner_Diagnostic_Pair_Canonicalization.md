# BM-PROD3.2.1 Scanner Diagnostic Pair Canonicalization

Date: 2026-07-15
Starting commit: 36c36d5e0e0f2ede47cc341d415bcab9c7de2045
Ending state: working tree after BM-PROD3.2.1 implementation

## Scope

BM-PROD3.2 performance results remain valid. BM-PROD3.2.1 changes only diagnostic warning identity and truncation correctness in `backend/app/music_scan_index.py`.

No scanner identity, reconciliation, preference, listener, playback, feedback, station, or version-affinity behavior changed.

The real BM Radio database remained empty. No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `backend/app/music_scan_index.py`
- `backend/scripts/check_prod3_2_1_scanner_diagnostic_pair_canonicalization.py`
- `scripts/check_prod0_baseline.py`
- `docs/production-upgrade/BM-PROD3.2.1_Scanner_Diagnostic_Pair_Canonicalization.md`

## Counter Semantics

`physical_sources_preserved` remains an affected-Track counter: the number of affected scan Tracks that have at least one distinct physical sibling in the same `MusicRecording` and `MusicRelease`.

`duplicates_suspected` remains an affected-Track counter: the number of affected scan Tracks that have at least one sibling in the same `MusicRecording` but a different `MusicRelease`.

These counters are not unique unordered relationship counts. Two affected physical sources may correctly produce `physical_sources_preserved = 2` while `duplicate_warnings` contains one canonical relationship warning.

## Warning Semantics

`duplicate_warnings` is a bounded deterministic sample of unique canonical diagnostic relationships.

Same-release physical-source warnings now use canonical unordered Track-pair identity:

```text
("physical_source_preserved", low_track_id, high_track_id, recording_id, release_id)
```

Cross-release recording duplicate warnings now use canonical Track and Release pair identity:

```text
("recording_duplicate_detected", low_track_id, high_track_id, recording_id, low_release_id, high_release_id)
```

The warning payload preserves compatibility fields:

- `type`
- `media_kind`
- `title`
- `existing_id`
- `candidate_path`
- `reason`
- `recording_id`
- `release_id`

The payload also includes explicit canonical fields:

- `track_ids`
- `release_ids`

## Truncation

`duplicate_warnings_truncated` is true only when the number of unique canonical warning relationships exceeds the emitted sample size.

The optional `duplicate_warning_relationships` field records the unique canonical relationship count.

The sample cap remains `MAX_DUPLICATE_WARNING_SAMPLES = 200`. Reversed A/B and B/A relationships do not consume two sample slots.

## Validation

Passed:

- `python scripts/check_prod3_2_1_scanner_diagnostic_pair_canonicalization.py`
- `python scripts/check_prod3_2_scanner_index_optimization.py`
- `python scripts/check_prod3_1_scale_benchmark_harness.py`
- `python scripts/check_prod1_4a2_scanner_identity_integration.py`
- `python scripts/check_prod1_4c2_scanner_preference_reevaluation.py`
- `python scripts/check_prod1_3b_music_scan_reconciliation.py`
- `python -m compileall app scripts`
- `git diff --check`

Final validation passed:

- `python scripts/check_prod0_baseline.py` - 36 mandatory passed, 0 failed, 4 skipped
- `frontend npm run build`
- `frontend npm run lint` - 0 errors, 8 existing warnings