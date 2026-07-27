# BM-PROD4.1 - Station Generation and Refill Performance Baseline

Owner: Bonny Makaniankhondo
Date: 2026-07-15
Starting commit: `061a7bcd970efc6ea3839e10536c2313ef531029`
Ending state: working tree with BM-PROD4.1 benchmark/instrumentation changes, not committed

BM-PROD4.1 measures the existing Recording-first station engine without changing station behavior.

The real BM Radio database remained empty.

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/perf.py`
- `personal-radio/backend/app/perf_fixtures.py`
- `personal-radio/backend/app/station_candidates.py`
- `personal-radio/backend/app/station_engine.py`
- `personal-radio/backend/app/station_perf_benchmark.py`
- `personal-radio/backend/scripts/benchmark_prod4_station_scale.py`
- `personal-radio/backend/scripts/check_prod4_1_station_scale_benchmark.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD4.1_Station_Generation_and_Refill_Performance_Baseline.md`

## Environment

- Machine: Windows / PowerShell workspace
- Python: 3.14.3
- SQLite: 3.50.4
- Benchmark DBs: temporary SQLite under `personal-radio/backend/tmp_tests/`
- Real DB row count after validation: 0

## Methodology

Initial generation and refill are measured separately.

Refill benchmarks reproduce the frontend contract: limit 50 and the last 200 queued physical Track IDs as exclusions.

Logical Recording identity is used to verify exclusion correctness.

All station benchmark operations are read-only.

No station cache, candidate-query optimization, profile-cache optimization, response-contract change, or frontend change was implemented.

The benchmark uses production helpers directly:

- `build_station_queue()` for normal station generation and refill
- `build_station_debug()` for debug generation
- `get_stations()` and `logical_station_count()` for listing/counts
- `load_station_candidate_tracks()` and current source-preference resolution for candidate projection

Instrumentation uses `time.perf_counter()`, SQLAlchemy engine events, `tracemalloc`, and optional `perf_segment` collection. Segment collection is inactive unless a benchmark collector enables it.

## Fixture

Fixture seed: `41041`

Synthetic fixture ratios:

- Recordings: 75% of physical Track count
- Releases: about 1 per 10 physical Tracks
- Artists: about 1 per 50 physical Tracks, bounded by the existing fixture cap
- Physical source variants: repeated Recording IDs across physical Tracks
- Codecs: about one third FLAC, two thirds MP3
- Library areas: majority `Library`, minority `Discographies`
- Participation: included majority; `library_only` every 11th Recording, `archived` every 23rd, `blocked` every 29th
- Preferences: every 4th Recording gets an automatic preferred source; some get user overrides
- Favorites: every 13th Recording
- Thumbs: every 17th Recording, with down-votes on every 34th
- Qualified-play history: every 3rd Recording
- Track radio profiles: one profile per physical Track
- Stations: deterministic favorites, recently-added, deep-cuts, artist, and genre rows

Seed selection is deterministic and drawn from the bounded station candidate pool so large-library runs do not accidentally measure empty/fallback stations caused only by arbitrary row order.

## Commands

Targeted smoke:

```bash
cd personal-radio/backend
python scripts/check_prod4_1_station_scale_benchmark.py
python scripts/check_prod1_5a_recording_first_station_candidates.py
python scripts/check_prod1_5b_station_version_affinity.py
```

Extended benchmark:

```bash
cd personal-radio/backend
python scripts/benchmark_prod4_station_scale.py --sizes 1000,10000,50000 --iterations 3 --warmups 1 --refill-count 4 --include-debug --include-listing --output tmp_tests/perf/prod4_1_station_baseline.json
```

Full gate:

```bash
cd personal-radio
python scripts/check_prod0_baseline.py
```

## Results Summary

Benchmark report: `personal-radio/backend/tmp_tests/perf/prod4_1_station_baseline.json`

### 1K

- Slowest initial: `station.artist.initial`, median 439.732 ms
- Slowest refill: `station.artist.refill.1`, median 418.809 ms
- `stations.list`: median 590.385 ms
- Candidate cap: not reached
- Max profile-cache phase median: 79.821 ms
- Max candidate-projection phase median: 237.267 ms
- Max source-resolution phase median: 180.038 ms

### 10K

- Slowest initial: `station.song_live.initial`, median 4037.574 ms
- Slowest refill: `station.artist.refill.1`, median 4265.902 ms
- `stations.list`: median 6935.861 ms
- Candidate cap: reached
- Max profile-cache phase median: 807.942 ms
- Max candidate-projection phase median: 2716.155 ms
- Max source-resolution phase median: 2379.275 ms
- Artist coverage inside pool: 51 of 87 full-fixture candidate Recordings
- Genre coverage inside pool: 1000 of 1500 full-fixture candidate Recordings

### 50K

- Slowest initial: `station.song_live.initial`, median 11076.649 ms
- Slowest refill: `station.song.refill.3`, median 13398.068 ms
- `stations.list`: median 15201.235 ms
- Candidate cap: reached
- Max profile-cache phase median: 6269.271 ms
- Max candidate-projection phase median: 6245.196 ms
- Max source-resolution phase median: 3822.215 ms
- Artist coverage inside pool: 6 of 87 full-fixture candidate Recordings
- Genre coverage inside pool: 1001 of 7500 full-fixture candidate Recordings

### 100K

Status: NOT RUN.

Reason: the required 1K/10K/50K benchmark completed successfully but took 1600.7 seconds with debug/listing enabled. The first BM-PROD4.1 baseline has enough evidence to choose BM-PROD4.2 without spending another long run on 100K.

## Refill Observations

At 10K, refill timing was mostly stable as exclusions grew to 200 IDs:

- Song refill median: 3988.423 ms, 3891.081 ms, 3897.809 ms, 3881.646 ms
- Artist refill median: 4265.902 ms, 4021.296 ms, 4031.100 ms, 4024.930 ms
- Genre refill median: 3887.271 ms, 3938.293 ms, 3865.193 ms, 3887.563 ms
- Favorites refill median: 3718.822 ms, 3632.813 ms, 3632.253 ms, 3619.898 ms

At 50K, Song refill rose through 150 exclusions then dropped at 200:

- Song refill median: 10549.731 ms, 12847.145 ms, 13398.068 ms, 9392.690 ms
- Genre refill median stayed near 9.4-10.1 seconds
- Favorites refill median stayed near 9.0-9.2 seconds
- Artist refill returned 0 after the initial 50 exclusions for the selected benchmark artist, while still spending about 9.5-9.8 seconds in the current path

All refill metrics recorded `exclude_count`, `returned`, `exhausted`, and `remaining_estimate`.

Recording-level exclusions held: excluded physical Track IDs mapped to Recording identities, and source variants of excluded Recordings did not reappear in measured refill windows.

## Candidate-Cap And Coverage

The 5,000 logical candidate cap keeps scoring/window assembly bounded, but candidate projection remains library-size sensitive.

The cap is reached at 10K and 50K. At 50K, relevant coverage is materially reduced by the current recent-recording candidate policy:

- Benchmark artist: 6 inside the bounded pool out of 87 full-fixture candidates
- Benchmark genre: 1001 inside the bounded pool out of 7500 full-fixture candidates

This is an observational finding only. BM-PROD4.1 does not change candidate selection policy.

## Dominant Hot Path

Dominant measured phases:

- 10K: candidate projection and source resolution dominate, with profile-cache loading also significant.
- 50K: profile-cache loading and candidate projection dominate, each exceeding 6 seconds in worst measured median phase values.

Dominant SQL/query family:

- Bounded candidate identity selection
- Recording participation/source-preference resolution
- deterministic profile-track resolution and Track hydration
- full radio-profile cache loading

The listing/count path is significant: `stations.list` reached 15.201 seconds median at 50K.

## Recommended BM-PROD4.2 Optimization

Prioritize the current station hot path in this order:

1. Scope or cache radio-profile loading so each request does not load the full profile table when the bounded candidate pool only needs a subset.
2. Reduce repeated candidate projection/source-resolution work shared by initial generation, refill, debug generation, listing, and count paths.
3. Preserve the Recording-first exclusion semantics and source preference behavior while measuring any change against this baseline.

Do not start with frontend changes or response-contract changes. The measured bottleneck is backend station data preparation, not the frontend refill trigger.

## Validation

- Targeted BM-PROD4.1 regression: PASS
- BM-PROD1.5A station regression: PASS
- BM-PROD1.5B station regression: PASS
- Full production gate: PASS, 38 mandatory passed, 0 failed, 4 skipped
- Backend compile: PASS
- Frontend build: PASS
- Frontend lint: PASS, 0 errors and 8 warnings

Known deferred work:

- benchmark-driven BM-PROD4.2 station optimization
- listener substring/full-text search only if later justified
- explicit listener-selectable version controls only if later desired
- release/edition-family refinement
- PostgreSQL and deployment hardening
- controlled real-media canary
