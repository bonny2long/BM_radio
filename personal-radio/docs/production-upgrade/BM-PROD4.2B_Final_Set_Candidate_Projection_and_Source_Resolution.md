# BM-PROD4.2B - Final-Set Candidate Projection and Source Resolution

Owner: Bonny Makaniankhondo
Date: 2026-07-16
Starting commit: `8cb2233bb7e68c3d97a2196419c0941bc36af21d`
Ending state: working tree with BM-PROD4.2B candidate-projection changes, not committed
Depends on: BM-PROD4.2A

BM-PROD4.2B selects the final eligible bounded MusicRecording ID set before source resolution, profile Track selection, Track hydration, and MusicRecording hydration.

Automatic participation and Recording exclusions are applied in SQL.

The station source-preference engine remains read-only and authoritative.

BM-PROD4.2B does not change the 5,000 Recording candidate cap, deterministic candidate order, station scoring, version affinity, participation semantics, source-preference semantics, queue responses, or frontend behavior.

BM-PROD4.2B intentionally does not correct artist/genre large-library coverage. That work remains BM-PROD4.2C.

No process-global candidate/source cache was added.

The real BM Radio database remained empty.

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/station_candidates.py`
- `personal-radio/backend/app/station_context.py`
- `personal-radio/backend/app/station_perf_benchmark.py`
- `personal-radio/backend/scripts/check_prod4_2b_station_candidate_projection_scope.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD4.2B_Final_Set_Candidate_Projection_and_Source_Resolution.md`

BM-PROD4.2A files remain in the working tree from the prior task and are not reverted.

## Implementation

The old active production path selected up to `bounded * 3` Recording IDs, then loaded participation rows, filtered participation and exclusions in Python, and source-resolved/profile-hydrated IDs that might never enter the final 5,000-candidate pool.

The new path adds `select_station_recording_ids()`:

- joins available `Track` rows to `MusicTrackIdentity`
- outer-joins `MusicRecordingParticipation`
- filters no-row/default and `included` participation in SQL
- filters excluded Recording IDs in SQL
- groups by `MusicTrackIdentity.recording_id`
- preserves deterministic order by first available Track `created_at` descending, then stable Track ID ascending
- applies `LIMIT bounded` to the final eligible Recording ID set

Only that selected final set is passed to:

- `resolve_effective_music_sources_read_only()`
- deterministic profile Track selection
- `MusicRecording` metadata hydration
- physical Track hydration

Identity-less legacy Tracks remain supported. Legacy Track exclusions are now applied before the legacy query `LIMIT`, so an excluded legacy Track cannot consume a fallback slot.

## Metrics

Candidate projection metrics now include:

- `candidate_limit`
- `excluded_recording_ids`
- `excluded_legacy_track_ids`
- `recording_ids_selected`
- `recording_ids_source_resolved`
- `recording_rows_loaded`
- `profile_track_ids_selected`
- `effective_track_ids_selected`
- `track_rows_hydrated`
- `legacy_track_rows_selected`
- `final_candidate_pool_size`
- `candidate_cap_reached`

At 10K and 50K, the max selected/resolved Recording count was 5,000.

No schema/index change was made. The SQL-scope correction was sufficient for the measured 50K bottleneck, so no index was added by intuition.

## Benchmark

Benchmark report: `personal-radio/backend/tmp_tests/perf/prod4_2b_candidate_projection.json`

Command:

```bash
cd personal-radio/backend
python scripts/benchmark_prod4_station_scale.py --sizes 1000,10000,50000 --iterations 3 --warmups 1 --refill-count 4 --include-debug --include-listing --output tmp_tests/perf/prod4_2b_candidate_projection.json
```

### 1K

- Max candidate-projection phase: BM-PROD4.2A 338.904 ms -> BM-PROD4.2B 350.230 ms
- Max source-resolution phase: BM-PROD4.2A 116.135 ms -> BM-PROD4.2B 176.505 ms
- Max profile-cache phase: 126.861 ms
- Slowest initial: `station.song.initial`, median 523.288 ms
- Slowest refill: `station.favorites.refill.1`, median 417.055 ms
- `stations.list`: median 564.806 ms
- Max Recording IDs selected/resolved: 630 / 630
- Queue checksum diffs vs BM-PROD4.2A: 0
- Debug payload checksum diffs vs BM-PROD4.2A: 0

### 10K

- Max candidate-projection phase: BM-PROD4.2A 2998.454 ms -> BM-PROD4.2B 2710.542 ms
- Max source-resolution phase: BM-PROD4.2A 1340.149 ms -> BM-PROD4.2B 1149.103 ms
- Max profile-cache phase: 1056.595 ms
- Slowest initial: `station.artist.initial`, median 4677.407 ms
- Slowest refill: `station.artist.refill.1`, median 4730.490 ms
- `stations.list`: median 2807.840 ms
- Max Recording IDs selected/resolved: 5,000 / 5,000
- Queue checksum diffs vs BM-PROD4.2A: 0
- Debug payload checksum diffs vs BM-PROD4.2A: 0

### 50K

- Max candidate-projection phase: BM-PROD4.2A 5573.030 ms -> BM-PROD4.2B 1858.219 ms
- Max source-resolution phase: BM-PROD4.2A 1976.067 ms -> BM-PROD4.2B 681.795 ms
- Max profile-cache phase: 691.534 ms
- Slowest initial: `station.genre.initial`, median 3042.137 ms
- Slowest refill: `station.artist.refill.1`, median 3095.885 ms
- `stations.list`: median 3000.567 ms
- Max Recording IDs selected/resolved: 5,000 / 5,000
- Queue checksum diffs vs BM-PROD4.2A: 0
- Debug payload checksum diffs vs BM-PROD4.2A: 1 full-payload hash difference on `station.artist.debug`

The 50K final Recording ID set was separately compared to the old conceptual 3x-overfetch policy and matched exactly: 5,000 IDs, no ordering difference. The debug-payload difference did not indicate a candidate selection change.

## Coverage

BM-PROD4.2B intentionally preserves the existing global candidate policy and does not add station-type-aware candidate reservations.

50K coverage remained equivalent to BM-PROD4.2A:

- Artist coverage inside bounded pool: 6 / 87
- Genre coverage inside bounded pool: 1001 / 7500

BM-PROD4.2C should address large-library station-intent-aware candidate coverage.

## Validation

Targeted:

```bash
cd personal-radio/backend
python -m compileall app scripts
python scripts/check_prod4_2b_station_candidate_projection_scope.py
python scripts/check_prod4_2a_scoped_station_profiles.py
python scripts/check_prod4_1_station_scale_benchmark.py
python scripts/check_prod1_5a_recording_first_station_candidates.py
python scripts/check_prod1_5b_station_version_affinity.py
```

Full production gate:

```bash
cd personal-radio
python scripts/check_prod0_baseline.py
```

Results:

- Targeted BM-PROD4.2B regression: PASS
- BM-PROD4.2A regression: PASS
- BM-PROD4.1 benchmark smoke: PASS
- BM-PROD1.5A regression: PASS
- BM-PROD1.5B regression: PASS
- Full production gate: PASS, 40 mandatory passed, 0 failed, 4 skipped
- Frontend build: PASS
- Frontend lint: PASS, 0 errors and 8 warnings

## 100K

Status: NOT RUN.

Reason: the required 1K/10K/50K benchmark and the full gate completed successfully. The 50K run already showed the final-set source-resolution fix clearly, and the next work item is station-intent-aware candidate coverage rather than more raw-scale timing.

## Remaining Dominant Phase

At 50K, candidate projection/source resolution are no longer the dominant multi-second phases they were in BM-PROD4.2A.

Remaining work should focus on BM-PROD4.2C: station-intent-aware candidate coverage and retrieval. The current global 5,000 Recording candidate window still under-represents some artist/genre stations at large library sizes.

## Known Deferred Work

- BM-PROD4.2C station-intent-aware candidate coverage
- listener substring/full-text search only if later justified
- explicit listener-selectable version controls only if later desired
- release/edition-family refinement
- PostgreSQL and deployment hardening
- controlled real-media canary
