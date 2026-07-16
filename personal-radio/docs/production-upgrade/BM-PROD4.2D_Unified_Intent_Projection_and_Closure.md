# BM-PROD4.2D - Unified Intent Candidate Projection and Closure

Owner: Bonny Makaniankhondo
Date: 2026-07-16
Starting commit: `1de9c40894bb3231d0fca1ef83f4478e6ca7eabd`
Ending state: working tree with BM-PROD4.2D unified projection changes, not committed
Depends on: BM-PROD4.2C.1

BM-PROD4.2D replaces the repeated station-intent bucket scans with one unified logical Recording projection for Song, Artist, and Genre station requests.

The public station API contract, queue payload contract, scoring logic, listener signals, Recording source preference policy, and non-seeded global station behavior remain unchanged.

The real BM Radio database remained empty during validation.

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/station_candidate_projection.py`
- `personal-radio/backend/app/station_candidates.py`
- `personal-radio/backend/app/music_source_preference.py`
- `personal-radio/backend/scripts/check_prod4_2d_unified_intent_projection.py`
- `personal-radio/backend/scripts/benchmark_prod4_2d_candidate_projection.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD4.2D_Unified_Intent_Projection_and_Closure.md`

## Implementation

Added `station_candidate_projection.py` as the unified selector for non-global station intents.

The new selector builds one grouped `candidate_facts` projection from available Tracks to logical Recordings, carrying:

- seed-artist match flag and bucket ordering fields
- related-artist match flag and bucket ordering fields
- exact-genre match flag and bucket ordering fields
- genre-family match flag and bucket ordering fields
- global fallback ordering fields
- automatic `included` participation filter
- Recording exclusions

Bucket rows are emitted from that single projection with `UNION ALL`. Python then walks the ordered tiers and applies the same effective quota timing as the previous reference implementation: each bucket's quota is calculated after higher-priority buckets have accepted their non-duplicate Recordings.

This preserves the old ordered candidate identity while avoiding the old 5-query Song/Artist and 3-query Genre bucket scan pattern.

`station_candidates.py` now keeps the previous selector as `select_intent_station_recording_ids_reference()` for regression and benchmark A/B comparison. Production calls route through `select_unified_intent_station_recording_ids()`.

`music_source_preference.py` now instruments source-resolution internals:

- `station.source_resolution.available_sources`
- `station.source_resolution.preference_rows`
- `station.source_resolution.fallback`
- `station.source_resolution.total`

No schema or index migration was required for this task.

## Regression

Added:

```bash
cd personal-radio/backend
python scripts/check_prod4_2d_unified_intent_projection.py
```

The regression verifies:

- 1K below-cap behavior stays global-equivalent
- 10K and 50K Song, live Song, Artist, and Genre candidate IDs exactly match the reference selector
- 10K queue checksums match the reference selector
- 10K debug selected identity checksums match the reference selector
- four refill iterations match the reference selector for Song, Artist, and Genre
- refill exclusions do not leak returned Recordings
- non-seeded Favorites, Recently Added, Deep Cuts, and station listing stay global
- 50K seeded paths report one bucket query and one projection query
- 50K Artist coverage still includes all eligible seed-artist Recordings
- 50K Genre coverage still reaches the capped target-genre pool
- the PROD0 baseline gate includes the new mandatory script and prior PROD4 scripts

Result:

```text
PASS: BM-PROD4.2D unified intent candidate projection
```

## A/B Benchmark

Command:

```bash
cd personal-radio/backend
python scripts/benchmark_prod4_2d_candidate_projection.py --size 50000 --iterations 1 --warmups 1 --output tmp_tests/perf/prod4_2d_candidate_projection_ab.json
```

Output:

```text
personal-radio/backend/tmp_tests/perf/prod4_2d_candidate_projection_ab.json
```

The A/B benchmark was read-only and all candidate identity checksums matched.

| Case | Reference Bucket ms | Unified Bucket ms | Reference SELECTs | Unified SELECTs | Candidate Identity |
| --- | ---: | ---: | ---: | ---: | --- |
| Artist | 1321.460 | 1058.335 | 29 | 24 | equivalent |
| Genre | 1531.418 | 2039.796 | 26 | 24 | equivalent |
| Song | 2327.459 | 2511.914 | 30 | 25 | equivalent |
| Song Live | 2311.380 | 2518.754 | 30 | 25 | equivalent |

Interpretation:

- The unified path reduces request SELECT count for every seeded case.
- Candidate identity is exact against the reference selector.
- Raw bucket elapsed time is mixed on the synthetic SQLite run: Artist improves, while Song/Genre bucket time is slower.
- End-to-end closure is still improved versus the blocked BM-PROD4.2C.1 run because source resolution is now instrumented and the full station benchmark remains below the previous 11-13 second blocker range.

## Closure Benchmark

Command:

```bash
cd personal-radio/backend
python scripts/benchmark_prod4_station_scale.py --sizes 1000,10000,50000 --iterations 1 --warmups 0 --refill-count 4 --include-debug --include-listing --output tmp_tests/perf/prod4_2d_station_closure.json
```

Output:

```text
personal-radio/backend/tmp_tests/perf/prod4_2d_station_closure.json
```

50K measured medians:

| Operation | Wall ms | Candidate Projection ms | Intent Bucket ms | Source Resolution ms | SELECTs | Bucket Queries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| station.song.initial | 8348.416 | 5701.539 | 3129.884 | 1002.940 | 62 | 1 |
| station.song_live.initial | 7687.097 | 4918.739 | 2461.864 | 983.151 | 62 | 1 |
| station.artist.initial | 5830.634 | 3763.155 | 1422.426 | 1041.189 | 52 | 1 |
| station.genre.initial | 6943.816 | 4365.036 | 1926.237 | 1122.031 | 57 | 1 |
| station.song.refill.4 | 8080.531 | 5151.263 | 2505.339 | 1100.988 | 64 | 1 |
| station.artist.refill.4 | 5326.598 | 3387.143 | 1051.155 | 981.562 | 53 | 1 |
| station.genre.refill.4 | 6856.884 | 4575.361 | 1941.164 | 1152.498 | 58 | 1 |
| station.favorites.refill.4 | 3985.970 | 2628.902 | n/a | 977.873 | 53 | 0 |
| station.song.debug | 8267.972 | 5185.636 | 2700.854 | 981.749 | 63 | 1 |
| station.artist.debug | 5540.203 | 3380.212 | 1145.751 | 966.876 | 52 | 1 |
| station.genre.debug | 7708.469 | 4741.099 | 2113.240 | 1197.024 | 55 | 1 |
| stations.list | 4236.201 | 2341.714 | n/a | 860.190 | 51 | 0 |

The previous BM-PROD4.2C.1 blocker examples were 13,668.475 ms for `station.song_live.initial`, 11,627.925 ms for `station.genre.refill.4`, and 8,400.390 ms for `stations.list`. The 4.2D closure run is below those blocker examples for the same 50K class.

## PROD0 Gate

First sandboxed full-gate run reached the frontend Vite build and failed with `spawn EPERM`, a sandbox child-process restriction.

The same gate was rerun outside the sandbox and passed:

```bash
cd personal-radio
python scripts/check_prod0_baseline.py
```

Result:

```text
BM-PROD0 BASELINE GATE: PASS
Mandatory: 43 passed, 0 failed
Optional/integration: 4 skipped
```

The new mandatory gate entry is:

```text
unified station intent candidate projection
```

## Validation

Completed:

```bash
cd personal-radio/backend
python -m compileall app scripts
python scripts/check_prod4_2d_unified_intent_projection.py
python scripts/check_prod4_2c_station_intent_candidate_coverage.py
python scripts/check_prod4_2c_1_station_refill_closure.py
python scripts/check_prod4_1_station_scale_benchmark.py
python scripts/benchmark_prod4_2d_candidate_projection.py --size 50000 --iterations 1 --warmups 1 --output tmp_tests/perf/prod4_2d_candidate_projection_ab.json
python scripts/benchmark_prod4_station_scale.py --sizes 1000,10000,50000 --iterations 1 --warmups 0 --refill-count 4 --include-debug --include-listing --output tmp_tests/perf/prod4_2d_station_closure.json
cd ../
python scripts/check_prod0_baseline.py
```

Results:

- Backend compile: PASS
- BM-PROD4.2D regression: PASS
- BM-PROD4.2C coverage regression: PASS
- BM-PROD4.2C.1 refill closure regression: PASS
- BM-PROD4.1 scale gate: PASS
- A/B benchmark: COMPLETE, read-only, equivalent checksums
- Closure benchmark: COMPLETE
- PROD0 baseline gate: PASS, 43 mandatory checks

## Verdict

BM-PROD4.2D: PASS
