# BM-PROD4.2C - Station-Intent-Aware Large-Library Candidate Coverage

Owner: Bonny Makaniankhondo
Date: 2026-07-16
Starting commit: `50e6b51988bd6e2194d696833f7f7ac25b8ace4d`
Ending state: working tree with BM-PROD4.2C candidate-intent changes, not committed
Depends on: BM-PROD4.2B

BM-PROD4.2C changes Song, Artist, and Genre Radio candidate retrieval from one global newest-Recording pool to deterministic station-intent Recording buckets.

The public request contract, queue payload contract, scoring logic, listener signals, version affinity, Recording source preference, and non-seeded station behavior remain unchanged.

Favorites Radio, Recently Added, Deep Cuts, station listing, and station counts continue using the BM-PROD4.2B global candidate policy.

The real BM Radio database remained empty.

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/station_candidate_intent.py`
- `personal-radio/backend/app/station_seed_knowledge.py`
- `personal-radio/backend/app/station_candidates.py`
- `personal-radio/backend/app/station_context.py`
- `personal-radio/backend/app/station_engine.py`
- `personal-radio/backend/app/station_perf_benchmark.py`
- `personal-radio/backend/scripts/check_prod4_2c_station_intent_candidate_coverage.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD4.2C_Station_Intent_Aware_Large_Library_Candidate_Coverage.md`

BM-PROD4.2A/B files already present in the working tree were preserved.

## Implementation

Added `StationCandidateIntent`, an immutable normalized intent contract with these modes:

- `global`
- `song`
- `artist`
- `genre`

Intent derivation is server-side only:

- Song Radio uses the seed Track, seed Recording ID, seed artist/album artist, scoped seed track radio profile, related artists, and genre-family tokens.
- Artist Radio uses the normalized seed artist, one scoped `ArtistRadioProfile` lookup when present, related artists, fallback genre knowledge, and genre-family tokens.
- Genre Radio uses the normalized target genre and genre-family tokens.
- Non-seeded station paths pass no intent and remain global.

Shared station fallback knowledge now lives in `station_seed_knowledge.py`, so `station_engine.py` and `station_candidate_intent.py` use the same `ARTIST_GENRE_FALLBACKS` and `RELATED_ARTISTS` data.

The candidate selector now keeps BM-PROD4.2B's global path as the fallback and adds intent buckets only when the eligible logical Recording count is above the 5,000 cap. This preserves below-cap output checksums.

Intent buckets select `MusicRecording.id` only. They still apply:

- available Track filter
- automatic `included` participation policy
- Recording exclusions
- deterministic order
- final 5,000 Recording cap
- source resolution only after the final pool is selected

Bucket selection records debug metrics in `station_candidate_projection_metrics` and debug responses now include `candidate_intent` summaries for Song, Artist, and Genre debug routes.

## Coverage

BM-PROD4.2B at 50K preserved the global pool:

- Artist coverage inside bounded pool: 6 / 87
- Genre coverage inside bounded pool: 1001 / 7500

BM-PROD4.2C single-iteration 50K benchmark result:

- Artist Radio logical candidate coverage: 74 / 74 eligible seed-artist Recordings inside the pool
- Artist Radio full available seed-artist fixture count: 87
- Genre Radio logical candidate coverage: 5000 / 7500 available target-genre Recordings inside the capped pool
- Genre Radio eligible target-genre fixture count: 6297
- Favorites Radio stayed global: 6 seed-artist / 1001 target-genre Recordings inside the pool
- `stations.list` stayed global

The 87 artist fixture rows include Recordings that are not automatically eligible because participation policy still excludes non-`included` states. BM-PROD4.2C intentionally keeps that production safety rule.

## Benchmark

Benchmark report: `personal-radio/backend/tmp_tests/perf/prod4_2c_station_intent_coverage.json`

Command:

```bash
cd personal-radio/backend
python scripts/benchmark_prod4_station_scale.py --sizes 1000,10000,50000 --iterations 1 --warmups 0 --refill-count 1 --include-debug --include-listing --output tmp_tests/perf/prod4_2c_station_intent_coverage.json
```

### 50K Highlights

- `station.artist.initial`: 3902.897 ms wall, 2572.479 ms candidate projection, 702.055 ms source resolution, 57 SELECTs
- `station.genre.initial`: 4346.030 ms wall, 2740.923 ms candidate projection, 730.807 ms source resolution, 59 SELECTs
- `station.favorites.initial`: 2586.553 ms wall, 1641.462 ms candidate projection, 596.416 ms source resolution, 52 SELECTs
- `stations.list`: 2971.524 ms wall, 1718.860 ms candidate projection, 612.230 ms source resolution, 51 SELECTs
- Benchmark read-only table counts unchanged: true

Bucket counts:

- Artist Radio: `seed_artist=74`, `related_artists=750`, `exact_genre=750`, `genre_family=3000`, `global_fallback=426`, query count `5`
- Genre Radio: `exact_genre=3500`, `genre_family=1500`, query count `2`
- Favorites Radio: `global=5000`
- `stations.list`: `global=5000`

## Regression

Added:

```bash
cd personal-radio/backend
python scripts/check_prod4_2c_station_intent_candidate_coverage.py
```

The regression verifies:

- 1K below-cap queue checksum equivalence for all station request types
- 1K below-cap debug checksum equivalence for Song, Artist, and Genre
- below-cap intent path reports `below_cap_global_equivalent`
- 50K Artist Radio uses artist intent and includes every eligible seed-artist Recording
- 50K Genre Radio uses genre intent and reaches the full 5,000 capped target-genre pool
- 50K Favorites Radio remains global
- debug responses expose intent bucket summaries
- bucket query counts remain small and fixed

The PROD0 baseline gate now includes this regression after BM-PROD4.2B, raising mandatory checks from 40 to 41.

## Validation

Targeted:

```bash
cd personal-radio/backend
python -m compileall app scripts
python scripts/check_prod4_2b_station_candidate_projection_scope.py
python scripts/check_prod4_2c_station_intent_candidate_coverage.py
python scripts/benchmark_prod4_station_scale.py --sizes 1000,10000,50000 --iterations 1 --warmups 0 --refill-count 1 --include-debug --include-listing --output tmp_tests/perf/prod4_2c_station_intent_coverage.json
```

Results:

- Python compileall: PASS
- BM-PROD4.2B regression: PASS
- BM-PROD4.2C regression: PASS
- BM-PROD4.2C benchmark JSON: written successfully
- `git diff --check`: PASS
- Full production gate: PASS, 41 mandatory passed, 0 failed, 4 skipped
- Frontend production build: PASS
- Frontend lint: PASS, 0 errors and 8 warnings
- Real `bm_radio.db` read-only emptiness check: PASS, no nonzero tables

Note: the first sandboxed full-gate run reached frontend build and failed with Vite `spawn EPERM`. The required escalated rerun completed successfully with the PASS result above.
