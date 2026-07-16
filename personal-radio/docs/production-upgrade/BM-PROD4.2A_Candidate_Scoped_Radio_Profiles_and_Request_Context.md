# BM-PROD4.2A - Candidate-Scoped Radio Profiles and Request Context

Owner: Bonny Makaniankhondo
Date: 2026-07-16
Starting commit: `dac5f354890b22b016a1e699d85d6224404cbe9d`
Ending state: working tree with BM-PROD4.2A scoped profile/context changes, not committed
Depends on: BM-PROD4.1

BM-PROD4.2A removes full radio-profile table loading from station requests and builds a request-scoped station context for normal generation, refill, debug paths, and station listing.

The full `load_radio_profile_cache(db)` API remains available for non-station/admin uses.

The real BM Radio database remained empty.

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/radio_profiles.py`
- `personal-radio/backend/app/station_context.py`
- `personal-radio/backend/app/station_engine.py`
- `personal-radio/backend/app/routes/stations.py`
- `personal-radio/backend/app/station_perf_benchmark.py`
- `personal-radio/backend/scripts/check_prod4_2a_scoped_station_profiles.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD4.2A_Candidate_Scoped_Radio_Profiles_and_Request_Context.md`

## Implementation

`load_radio_profile_cache_for_tracks()` now loads only the Artist, Album, and Track radio profiles relevant to the supplied candidate/seed Tracks. Track profile IDs include physical Track IDs, `_station_effective_track_id`, and `_station_profile_track_id`, deduplicated and queried in chunks.

Artist and album profile lookups preserve normalized/case-insensitive behavior. Album profile loading uses bounded artist and album key sets, then applies an exact normalized `(artist, album)` pair guard so unrelated artist/album cross-products cannot enter the cache.

`StationRequestContext` is request-scoped. It bundles the bounded station candidate pool, scoped profile cache, and requested listener signals without a process-global ORM cache. Profile edits and source preference changes are visible on the next request.

Station listing now builds one request context and reuses the candidate/profile work for count maps and favorite/feedback station counts.

## Semantics

Candidate identity, candidate cap, ordering policy, source preference, included-only participation, Recording-level exclusions, scoring, version affinity, spacing/window assembly, and response contracts were preserved.

The BM-PROD4.2A benchmark was compared against the saved BM-PROD4.1 benchmark checksums:

- 1K queue checksum diffs: 0
- 10K queue checksum diffs: 0
- 50K queue checksum diffs: 0

Initial and refill checksum probes were also run during development at 1K after restoring the prior recent-play scoring scope for Song, Genre, Favorites, and Deep Cuts.

## Benchmark

Benchmark report: `personal-radio/backend/tmp_tests/perf/prod4_2a_station_profiles.json`

Command:

```bash
cd personal-radio/backend
python scripts/benchmark_prod4_station_scale.py --sizes 1000,10000,50000 --iterations 3 --warmups 1 --refill-count 4 --include-debug --include-listing --output tmp_tests/perf/prod4_2a_station_profiles.json
```

### 1K

- Slowest initial: `station.artist.initial`, median 458.953 ms
- Slowest refill: `station.song.refill.1`, median 581.122 ms
- `stations.list`: median 372.553 ms
- Max profile-cache phase: 141.497 ms
- Profile rows loaded: 632 of 1,000 Track profile rows
- BM-PROD4.1 profile rows loaded: 1,000
- Checksum diffs vs BM-PROD4.1: 0

### 10K

- Slowest initial: `station.artist.initial`, median 3983.677 ms
- Slowest refill: `station.favorites.refill.2`, median 4043.688 ms
- `stations.list`: median 4485.097 ms
- Max profile-cache phase: 885.202 ms
- Profile rows loaded: 5,010 of 10,000 Track profile rows
- BM-PROD4.1 profile rows loaded: 10,000
- Checksum diffs vs BM-PROD4.1: 0

### 50K

- Slowest initial: `station.song.initial`, median 7112.948 ms
- Slowest refill: `station.artist.refill.3`, median 6159.134 ms
- `stations.list`: median 6199.916 ms
- Max profile-cache phase: 1113.042 ms
- BM-PROD4.1 max profile-cache phase: 6687.633 ms
- Profile rows loaded: 5,001 of 50,000 Track profile rows
- BM-PROD4.1 profile rows loaded: 50,000
- Checksum diffs vs BM-PROD4.1: 0

## Comparison To BM-PROD4.1

At 50K, full Track radio-profile loading was eliminated from station requests:

- BM-PROD4.1 loaded 50,000 Track profile rows per full-cache station profile load.
- BM-PROD4.2A loaded at most 5,001 Track profile rows for the bounded station candidate/seed context.

The measured 50K profile-cache phase improved from 6687.633 ms to 1113.042 ms in the same benchmark harness.

`stations.list` improved from 15201.235 ms to 6199.916 ms by reusing a single request-scoped candidate/profile context.

The remaining dominant hot path is candidate projection/source resolution:

- 50K max candidate-projection phase: 5573.030 ms
- 50K max source-resolution phase: 1976.067 ms

That is the recommended BM-PROD4.2B target.

## Validation

Targeted checks run:

```bash
cd personal-radio/backend
python -m compileall app scripts
python scripts/check_prod4_2a_scoped_station_profiles.py
python scripts/benchmark_prod4_station_scale.py --sizes 1000,10000,50000 --iterations 3 --warmups 1 --refill-count 4 --include-debug --include-listing --output tmp_tests/perf/prod4_2a_station_profiles.json
```

Targeted BM-PROD4.2A regression: PASS.

The permanent production gate includes `scripts/check_prod4_2a_scoped_station_profiles.py` after BM-PROD4.1.

## Known Deferred Work

- BM-PROD4.2B candidate projection/source-resolution optimization
- large-library candidate coverage correction
- listener substring/full-text search only if later justified
- explicit listener-selectable version controls only if later desired
- release/edition-family refinement
- PostgreSQL and deployment hardening
- controlled real-media canary