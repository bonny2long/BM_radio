# BM-PROD4.2D.1 - Final Controlled Rebenchmark and PROD4 Closure

Owner: Bonny Makaniankhondo
Date: 2026-07-16
Starting commit: `7ba8e96f4661ae72c6a318a0b7ef5f684fb49cdb`
Ending state: working tree with this report only, not committed
Depends on: BM-PROD4.2D

BM-PROD4.2D.1 ran the exact required controlled A/B benchmark and the exact required full closure benchmark.

Production station logic was not modified. No code under `backend/app`, station scoring, source preference policy, version affinity, public API contracts, or frontend source was changed.

The real BM Radio database remained empty. No real media roots were accessed or mutated.

## Files Changed

- `personal-radio/docs/production-upgrade/BM-PROD4.2D.1_Final_Controlled_Rebenchmark_and_PROD4_Closure.md`

Generated benchmark artifacts are under ignored `personal-radio/backend/tmp_tests/perf` paths:

- `prod4_2d_1_candidate_projection_ab.json`
- `prod4_2d_1_station_closure.json`

## Environment

- OS: Windows-11-10.0.26200-SP0
- Python: 3.14.3 64-bit AMD64
- CPU count: 8
- Benchmark database: temporary SQLite fixtures under `personal-radio/backend/tmp_tests`
- Real application DB: `personal-radio/backend/bm_radio.db`, opened read-only for row counts

## Manual Approval and Timing Notes

Codex command wall durations captured by the tool:

| Operation | Outer shell duration |
| --- | ---: |
| Exact controlled A/B benchmark | 820.9 s |
| Exact full closure benchmark | 1140.2 s |
| Full PROD0 gate, sandboxed attempt | 728.0 s |
| Full PROD0 gate, approved outside sandbox | 1255.9 s |
| Explicit frontend build, approved outside sandbox | 11.8 s |

The sandboxed full gate failed only at Vite child-process spawning with `spawn EPERM`; the identical gate passed outside the sandbox after approval.

Internal benchmark medians below are the authoritative performance measurements.

## Exact Controlled A/B Benchmark

Command:

```bash
cd personal-radio/backend
python scripts/benchmark_prod4_2d_candidate_projection.py --size 50000 --iterations 5 --warmups 1 --output tmp_tests/perf/prod4_2d_1_candidate_projection_ab.json
```

Result:

```text
WROTE tmp_tests/perf/prod4_2d_1_candidate_projection_ab.json
```

Benchmark shape:

- size: 50,000 physical tracks
- measured iterations argument: 5
- warmups: 1
- measured rows: 120
- cases: Song, Live Song, Artist, Genre
- selectors: reference and unified
- read-only table counts unchanged: true
- operation order: alternating `unified, reference, reference, unified, unified, reference` rotated by iteration; raw ordinal/order is preserved in the JSON artifact

## A/B Correctness

All cases preserved exact ordered candidate identity and bucket/tier counts.

| Case | Ordered checksum | Bucket counts | Candidate identity |
| --- | --- | --- | --- |
| Song | `2a0b0defc762a036` | seed 134, related 750, exact 1000, family 2850, global 266 | equivalent |
| Live Song | `4b2b6b96584741ab` | seed 141, related 750, exact 1000, family 2850, global 259 | equivalent |
| Artist | `79d43f1254a3e2e8` | seed 74, related 750, exact 750, family 3000, global 426 | equivalent |
| Genre | `a22b287df6e91cbd` | exact 3500, family 1500 | equivalent |

Candidate cap and exclusion behavior remained identical. Source-resolved candidate counts stayed within the 5,000 cap.

## A/B Performance

Percentage calculation:

```text
(reference_median - unified_median) / reference_median * 100
```

Controlled A/B bucket-phase results:

| Case | Reference median ms | Unified median ms | Change | Decision |
| --- | ---: | ---: | ---: | --- |
| Artist | 927.085 | 844.865 | +8.87% | measurement-equivalent / slight improvement |
| Genre | 1041.009 | 1368.980 | -31.51% | material regression |
| Song | 1588.461 | 1763.136 | -11.00% | material regression |
| Live Song | 1593.959 | 1850.691 | -16.11% | material regression |

Controlled A/B wall-time results:

| Case | Selector | Min ms | Median ms | P95 ms | Max ms | SELECTs | Peak bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Artist | reference | 2441.310 | 2674.928 | 4019.373 | 4026.013 | 29 | 23470616 |
| Artist | unified | 2226.502 | 2495.692 | 3770.495 | 3860.253 | 24 | 23347967 |
| Genre | reference | 2589.129 | 2746.910 | 4463.188 | 4587.855 | 26 | 23436735 |
| Genre | unified | 2908.944 | 3168.393 | 4855.031 | 4878.410 | 24 | 23440216 |
| Song | reference | 3031.630 | 3495.778 | 4939.892 | 4988.925 | 30 | 23617396 |
| Song | unified | 3194.935 | 3649.825 | 5201.382 | 5557.008 | 25 | 23358244 |
| Live Song | reference | 3023.034 | 3288.592 | 5007.035 | 5227.093 | 30 | 23615912 |
| Live Song | unified | 3188.076 | 3524.791 | 5275.854 | 5461.913 | 25 | 23374336 |

Controlled A/B source-resolution medians:

| Case | Reference ms | Unified ms |
| --- | ---: | ---: |
| Artist | 726.066 | 668.356 |
| Genre | 737.718 | 748.829 |
| Song | 809.887 | 668.854 |
| Live Song | 776.434 | 721.434 |

A/B interpretation:

- Unified uses fewer SELECTs in every case.
- Candidate identity and bucket counts are exact.
- The required A/B performance criterion does not pass: Genre, Song, and Live Song are materially slower in the controlled bucket phase.
- Per the roadmap, this requires a blocked closure verdict unless production logic is changed, and production logic changes are prohibited in BM-PROD4.2D.1.

## Exact Full Closure Benchmark

Command:

```bash
cd personal-radio/backend
python scripts/benchmark_prod4_station_scale.py --sizes 1000,10000,50000 --iterations 3 --warmups 1 --refill-count 4 --include-debug --include-listing --output tmp_tests/perf/prod4_2d_1_station_closure.json
```

Result:

```text
WROTE tmp_tests/perf/prod4_2d_1_station_closure.json
```

Benchmark shape:

- sizes: 1K, 10K, 50K physical tracks
- measured iterations: 3
- warmups: 1
- refill windows: 4
- debug enabled
- station listing and logical count operations enabled

## Full Closure Results

### 1K Summary

| Operation | Wall median ms | SELECTs | Returned | Excluded overlap |
| --- | ---: | ---: | ---: | ---: |
| slowest initial: station.song.initial | 592.151 | 26 | 50 | 0 |
| slowest refill: station.favorites.refill.4 | 402.339 | 18 | 0 | 0 |
| stations.list | 456.492 | 17 | 26 | 0 |

### 10K Summary

| Operation | Wall median ms | SELECTs | Returned | Bucket queries | Excluded overlap |
| --- | ---: | ---: | ---: | ---: | ---: |
| slowest initial: station.song.initial | 4322.107 | 59 | 50 | 1 | 0 |
| slowest refill: station.genre.refill.2 | 4533.536 | 53 | 50 | 1 | 0 |
| stations.list | 4220.215 | 51 | 26 | n/a | 0 |

### 50K Summary

| Operation | Wall median ms | P95 ms | SELECTs | Returned | Candidate projection ms | Intent bucket ms | Source resolution ms | Bucket queries | Excluded overlap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| station.song.initial | 7139.842 | 7236.551 | 63 | 50 | 4515.625 | 2227.016 | 940.145 | 1 | 0 |
| station.song_live.initial | 7235.122 | 7642.700 | 63 | 50 | 4593.896 | 2170.745 | 1005.582 | 1 | 0 |
| station.artist.initial | 5197.931 | 5229.953 | 52 | 50 | 3313.518 | 1003.127 | 880.581 | 1 | 0 |
| station.genre.initial | 6419.370 | 6523.519 | 57 | 50 | 4187.076 | 1676.729 | 1120.575 | 1 | 0 |
| station.song.refill.4 | 7215.739 | 7569.465 | 64 | 50 | 4654.119 | 2216.406 | 938.401 | 1 | 0 |
| station.artist.refill.4 | 3741.581 | 3766.409 | 53 | 50 | 2467.580 | 789.296 | 680.581 | 1 | 0 |
| station.genre.refill.4 | 4766.518 | 4922.412 | 58 | 50 | 3102.056 | 1310.729 | 792.507 | 1 | 0 |
| station.favorites.refill.4 | 4268.806 | 4409.650 | 53 | 50 | 2864.258 | n/a | 1044.986 | 0 | 0 |
| station.song.debug | 8162.625 | 8546.775 | 63 | 0 | 4938.705 | 2462.602 | 1058.666 | 1 | 0 |
| station.artist.debug | 6040.877 | 6158.156 | 52 | 0 | 3834.001 | 1160.842 | 1081.252 | 1 | 0 |
| station.genre.debug | 5101.384 | 5233.274 | 55 | 0 | 3119.935 | 1338.131 | 782.090 | 1 | 0 |
| stations.list | 2951.381 | 3060.886 | 51 | 26 | 1713.980 | n/a | 638.295 | 0 | 0 |

50K closure comparison:

| Requirement reference | Value | 4.2D.1 result |
| --- | ---: | ---: |
| BM-PROD4.1 slowest initial | 11076.649 ms | 7235.122 ms |
| BM-PROD4.1 slowest refill | 13398.068 ms | 7222.952 ms |
| BM-PROD4.1 stations.list | 15201.235 ms | 2951.381 ms |
| BM-PROD4.2C.1 blocked song_live.initial | 13668.475 ms | 7235.122 ms |
| BM-PROD4.2C.1 blocked genre.refill.4 | 11627.925 ms | 4766.518 ms |
| BM-PROD4.2C.1 blocked stations.list | 8400.390 ms | 2951.381 ms |

End-to-end closure benchmark interpretation:

- 50K seeded initial/refill medians stayed materially below BM-PROD4.1.
- No 50K operation returned to the 11-13 second blocked range.
- `stations.list` is materially below BM-PROD4.1 and below the prior BM-PROD4.2C.1 blocked run.
- Candidate projection and source resolution remained bounded.
- Seeded intent bucket query count is 1 for seeded above-cap paths.
- No excluded-Recording overlap was observed.

## Functional Closure Requirements

Preserved by targeted regressions and closure metrics:

- zero excluded-Recording overlap
- zero physical-source exclusion bypass
- unique Recording identities per queue
- seed Recording exclusion
- participation safety
- thumbs-down safety
- deterministic checksums
- intent coverage through refill
- non-seeded global behavior
- read-only benchmark table counts

## Required Validation

Completed:

```bash
cd personal-radio/backend
python -m compileall app scripts
python scripts/check_prod4_2d_unified_intent_projection.py
python scripts/check_prod4_2c_1_station_refill_closure.py
python scripts/check_prod4_2c_station_intent_candidate_coverage.py
python scripts/check_prod4_2b_station_candidate_projection_scope.py
python scripts/check_prod4_2a_scoped_station_profiles.py
python scripts/check_prod4_1_station_scale_benchmark.py
```

Results:

- Backend compile: PASS
- BM-PROD4.2D unified regression: PASS
- BM-PROD4.2C.1 refill closure: PASS
- BM-PROD4.2C intent coverage: PASS
- BM-PROD4.2B projection/source-resolution scope: PASS
- BM-PROD4.2A scoped station profiles: PASS
- BM-PROD4.1 station scale benchmark: PASS

One parallel validation attempt made `check_prod4_2a_scoped_station_profiles.py` fail because it launched `check_prod4_1_station_scale_benchmark.py` while a parallel 4.1 process held `tmp_tests/prod4_1_smoke/station_scale.db`. The standalone rerun passed.

## Full Gate and Frontend

Sandboxed full gate:

```text
frontend production build failed with Vite spawn EPERM
Mandatory: 42 passed, 1 failed
```

Approved outside-sandbox full gate:

```text
BM-PROD0 BASELINE GATE: PASS
Mandatory: 43 passed, 0 failed
Optional/integration: 4 skipped
```

Explicit frontend commands:

```bash
cd personal-radio/frontend
npm run build
npm run lint
```

Results:

- `npm run build`: PASS outside sandbox
- `npm run lint`: PASS, 0 errors, 8 existing warnings

## Real DB and Media Safety

Read-only DB verification:

```text
personal-radio/backend/bm_radio.db
user tables: 13
total rows: 0
nonzero tables: {}
```

Media safety:

- no real media root access was required
- no write, move, rename, retag, transcode, or delete operation was performed

## Diff Quality

```bash
git diff --check
```

Result: PASS

## Final Completion Report

```text
BM-PROD4.2D.1 status: BLOCKED

Starting SHA:
7ba8e96f4661ae72c6a318a0b7ef5f684fb49cdb

Ending SHA or working-tree state:
working tree with report-only change, not committed

Production logic changes:
Result: NONE

Controlled A/B exact command:
Result: COMPLETE, wrote tmp_tests/perf/prod4_2d_1_candidate_projection_ab.json

A/B iterations and warmups:
Result: iterations=5, warmups=1

Song reference/unified:
Result: 1588.461 ms / 1763.136 ms bucket median, -11.00%, material regression

Live Song reference/unified:
Result: 1593.959 ms / 1850.691 ms bucket median, -16.11%, material regression

Artist reference/unified:
Result: 927.085 ms / 844.865 ms bucket median, +8.87%, measurement-equivalent slight improvement

Genre reference/unified:
Result: 1041.009 ms / 1368.980 ms bucket median, -31.51%, material regression

A/B SELECT counts:
Result: unified lower in every case: Song 30->25, Live Song 30->25, Artist 29->24, Genre 26->24

Candidate checksum equivalence:
Result: PASS, exact ordered checksums and bucket counts in every case

Operation-order/environment findings:
Result: alternating selector order with raw ordinals in JSON; mixed A/B result is not explained by identity drift or extra SELECTs

Full closure exact command:
Result: COMPLETE, wrote tmp_tests/perf/prod4_2d_1_station_closure.json

Closure iterations/warmups/refills:
Result: iterations=3, warmups=1, refill_count=4

1K benchmark:
Result: PASS, slowest initial 592.151 ms, slowest refill 402.339 ms, stations.list 456.492 ms

10K benchmark:
Result: PASS, slowest initial 4322.107 ms, slowest refill 4533.536 ms, stations.list 4220.215 ms

50K benchmark:
Result: end-to-end PASS, but closure verdict still blocked by A/B rule

Four-window refill safety:
Result: PASS, zero excluded overlap and seeded bucket query count 1 where applicable

50K slowest initial:
Result: 7235.122 ms, station.song_live.initial

50K slowest refill:
Result: 7222.952 ms, station.song.refill.1

50K stations.list:
Result: 2951.381 ms

50K candidate projection:
Result: slowest listed median 4938.705 ms, station.song.debug

50K source resolution:
Result: slowest listed median 1120.575 ms, station.genre.initial

Read-only behavior:
Result: PASS

Real application DB:
Result: PASS, 13 user tables, 0 rows

Full production gate:
Result: PASS outside sandbox, 43 mandatory passed, 0 failed, 4 skipped

Backend compile:
Result: PASS

Frontend build:
Result: PASS outside sandbox

Frontend lint:
Result: PASS, 0 errors, 8 warnings

git diff --check:
Result: PASS

Closure verdict:
See final line below.
```

BM-PROD4 CLOSURE: BLOCKED
