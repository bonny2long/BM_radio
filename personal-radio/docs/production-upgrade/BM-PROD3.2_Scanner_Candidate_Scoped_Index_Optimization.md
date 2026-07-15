# BM-PROD3.2 Scanner Candidate-Scoped Index Optimization

Date: 2026-07-15
Starting commit: e4147e2689cc81c8f848b170c3ebfc09ea2f39e1
Ending state: working tree after BM-PROD3.2 implementation

## Scope

BM-PROD3.2 removes the normal music scanner's unfiltered full Track ORM startup load. Exact existing Track identity is resolved by indexed candidate-path lookup in bounded batches.

The real BM Radio database remained empty. All validation and benchmarks used temporary SQLite databases and temporary music roots.

BM-PROD3.2 does not delete, merge, archive, block, move, rename, retag, or transcode media. Listener-library, playback, feedback, station, and version-affinity behavior are unchanged.

## Files Changed

- `backend/app/music_scan_index.py`
- `backend/app/scanner/music_scanner.py`
- `backend/app/perf_benchmark.py`
- `backend/scripts/check_prod3_2_scanner_index_optimization.py`
- `scripts/check_prod0_baseline.py`
- `docs/production-upgrade/BM-PROD3.2_Scanner_Candidate_Scoped_Index_Optimization.md`

## Startup Path Removed

The prior scanner startup path loaded every Track ORM row with `db.query(models.Track).all()`, then built full-library `exact_path_tracks`, `release_seen`, and `recording_seen` maps before processing the current scan's files.

The new scanner path discovers current scan candidates, processes them in `SCAN_PATH_BATCH_SIZE = 500` batches, and calls `tracks_by_exact_paths()` for each batch. The helper deduplicates paths, chunks SQL `IN` clauses with `EXACT_PATH_LOOKUP_CHUNK_SIZE = 500`, and includes unavailable Tracks so returning exact paths preserve Track identity and user state.

## Diagnostics

Duplicate and variant diagnostics now run after technical profile persistence and first-class identity materialization. `collect_music_scan_identity_diagnostics()` starts from the current scan's affected Track IDs, expands only to their MusicRecording IDs, and reads sibling Track/Edition/Release rows for those recordings.

Compatibility counters remain:

- `physical_sources_preserved`
- `duplicates_suspected`
- `duplicate_warnings`

New bounded proof counters:

- `duplicate_warnings_truncated`
- `identity_diagnostic_recordings`
- `identity_diagnostic_tracks`
- `scan_path_batches`
- `exact_path_lookup_queries`
- `exact_path_tracks_loaded`

Warning samples are deterministic and bounded by `MAX_DUPLICATE_WARNING_SAMPLES = 200`; full counters remain truthful.

## Benchmark Comparison

BM-PROD3.1 committed baseline:

| Size | Metric | Median ms | Peak MiB |
| --- | --- | ---: | ---: |
| 1K | scanner.startup_state | 644.1 | 2.2 |
| 1K | scanner.incremental.50 | 2,805.4 | 5.3 |
| 10K | scanner.startup_state | 13,254.8 | 23.3 |
| 10K | scanner.incremental.50 | 19,973.8 | 40.7 |

BM-PROD3.2 result on the same development machine:

| Size | Metric | Median ms | Peak MiB | SELECTs |
| --- | --- | ---: | ---: | ---: |
| 1K | scanner.startup_state | 4.608 | 0.026 | 1 |
| 1K | scanner.incremental.50 | 2,190.442 | 1.568 | 25 |
| 10K | scanner.startup_state | 1.763 | 0.026 | 1 |
| 10K | scanner.incremental.50 | 1,952.602 | 1.327 | 25 |
| 50K | scanner.startup_state | 5.354 | 0.053 | 1 |
| 50K | scanner.incremental.50 | 2,238.944 | 1.544 | 25 |

Benchmark outputs:

- `backend/tmp_tests/perf/prod3_2_scanner_1k_10k.json`
- `backend/tmp_tests/perf/prod3_2_scanner_50k.json`

## Remaining Hot Phase

After removing full-library startup materialization, `scanner.incremental.50` is roughly flat from 10K to 50K. The remaining measured cost is inside fixed per-file scan work, identity materialization, technical-profile persistence, reconciliation checks, preference evaluation, and transaction work for the 50 affected files, not startup index construction over the total Track table.

## Validation

Passed:

- `python scripts/check_prod3_2_scanner_index_optimization.py`
- `python scripts/check_prod3_1_scale_benchmark_harness.py`
- `python scripts/check_prod1_4a2_scanner_identity_integration.py`
- `python scripts/check_prod1_4c2_scanner_preference_reevaluation.py`
- `python scripts/check_prod1_3b_music_scan_reconciliation.py`
- `python -m compileall app scripts/check_prod3_2_scanner_index_optimization.py`

Final validation passed:

- `python scripts/check_prod0_baseline.py` - 35 mandatory passed, 0 failed, 4 skipped
- `python -m compileall app scripts`
- `frontend npm run build`
- `frontend npm run lint` - 0 errors, 8 existing warnings
- `git diff --check`

## Explicit Guarantees

BM-PROD3.2 preserves scan reconciliation, identity rebind, preference re-evaluation, and rollback semantics. Exact-path lookup includes unavailable Tracks. Physical-source variants remain preserved. Same Recording across Releases remains preserved as diagnostics only.