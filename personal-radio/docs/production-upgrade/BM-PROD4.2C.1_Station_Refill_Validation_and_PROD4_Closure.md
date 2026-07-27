# BM-PROD4.2C.1 - Station Refill Validation and BM-PROD4 Closure

Owner: Bonny Makaniankhondo
Date: 2026-07-16
Starting commit: `e4ed4dc911162098215a8d5e2e1f289c12ca23c9`
Ending state: working tree with closure regression/report changes, not committed
Depends on: BM-PROD4.2C

BM-PROD4.2C.1 completed the requested multi-iteration benchmark and added a deterministic refill closure smoke regression.

No production station-selection logic was changed in this task.

## Files Changed

- `personal-radio/backend/scripts/check_prod4_2c_1_station_refill_closure.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD4.2C.1_Station_Refill_Validation_and_PROD4_Closure.md`

## Environment

- OS: Windows-11-10.0.26200-SP0
- Python: 3.14.3 64-bit AMD64
- CPU count: 8
- Benchmark DB: temporary SQLite fixtures under `personal-radio/backend/tmp_tests`
- Real application DB: `personal-radio/backend/bm_radio.db`, verified read-only empty by the closure regression

## Required Benchmark

Command:

```bash
cd personal-radio/backend
python scripts/benchmark_prod4_station_scale.py --sizes 1000,10000,50000 --iterations 3 --warmups 1 --refill-count 4 --include-debug --include-listing --output tmp_tests/perf/prod4_2c_1_station_closure.json
```

Output:

```text
personal-radio/backend/tmp_tests/perf/prod4_2c_1_station_closure.json
```

The benchmark JSON is valid and contains:

- sizes: 1K, 10K, 50K
- measured iterations: 3
- warmups: 1
- refill windows: 4
- debug enabled
- listing/count operations enabled

The shell wrapper timed out after the script printed `WROTE`, but the JSON file was complete and parseable.

## Functional Results

Benchmark table-count verification:

- 1K read-only table counts unchanged: true
- 10K read-only table counts unchanged: true
- 50K read-only table counts unchanged: true

50K refill invariants from benchmark metrics:

| Operation | Refill 4 Excludes | Returned | Unique Recordings | Excluded Recording Overlap | Remaining | Intent | Bucket Queries |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Song | 200 | 50 | 50 | 0 | 3831 | song | 5 |
| Artist | 200 | 50 | 50 | 0 | 781 | artist | 5 |
| Genre | 200 | 50 | 50 | 0 | 4799 | genre | 2 |
| Favorites | 200 | 50 | 50 | 0 | 280 | global | 0 |

50K candidate intent coverage by refill:

| Operation | Refill | Intent Buckets | Coverage |
| --- | ---: | --- | --- |
| Song | 1 | seed_artist 96, related 750, exact 1000, family 2850, global 304 | target genre 4038 / 7500 |
| Song | 4 | seed_artist 65, related 750, exact 1000, family 2850, global 335 | target genre 4003 / 7500 |
| Artist | 1 | seed_artist 52, related 750, exact 750, family 3000, global 448 | seed artist 52 / 74 eligible |
| Artist | 4 | seed_artist 34, related 750, exact 750, family 3000, global 466 | seed artist 34 / 74 eligible after exclusions |
| Genre | 1 | exact 3500, family 1500 | target genre 5000 / 7500 |
| Genre | 4 | exact 3500, family 1500 | target genre 5000 / 7500 |
| Favorites | 4 | global 5000 | global policy preserved |

The targeted closure regression also proved:

- four Song refill requests execute
- four Artist refill requests execute
- four Genre refill requests execute
- four Favorites refill requests execute
- last-200 physical exclusion contract is applied
- alternate physical source cannot bypass Recording exclusion
- seed Recording remains excluded from Song output
- refill windows are Recording-unique
- Song/Artist/Genre intent remains active on every refill
- Favorites remains global
- candidate bucket query counts remain bounded
- source resolution remains <= 5,000 Recordings
- operations are read-only
- normal/debug candidate intent agreement holds
- deterministic refill checksums hold for same request and operation seed
- Artist output is not seed-only when alternatives exist
- real app DB remains empty

## 50K Timing Results

BM-PROD4.1 reference:

- slowest initial: 11076.649 ms
- slowest refill: 13398.068 ms
- stations.list: 15201.235 ms

BM-PROD4.2B reference:

- candidate projection: 1858.219 ms
- source resolution: 681.795 ms
- slowest initial: 3042.137 ms
- slowest refill: 3095.885 ms
- stations.list: 3000.567 ms

Required BM-PROD4.2C.1 50K measured medians:

| Operation | Wall ms | Candidate Projection ms | Source Resolution ms | SELECTs |
| --- | ---: | ---: | ---: | ---: |
| station.song.initial | 7694.906 | 4791.320 | 1034.369 | 68 |
| station.song_live.initial | 13668.475 | 8619.528 | 1948.759 | 68 |
| station.artist.initial | 10432.645 | 6924.499 | 1844.952 | 57 |
| station.genre.initial | 10656.071 | 7167.487 | 1727.180 | 59 |
| station.genre.refill.4 | 11627.925 | 7384.466 | 1974.293 | 60 |
| station.favorites.refill.4 | 8663.918 | 4635.632 | 1638.664 | 53 |
| stations.list | 8400.390 | 4819.227 | 1903.646 | 51 |

## Closure Blocker

BM-PROD4.2C.1 is blocked by the required benchmark performance acceptance.

Failing operation examples:

```text
station.song_live.initial
fixture size: 50K
expected: seeded initial operation remains materially below BM-PROD4.1-era 11-13 second result
actual: 13,668.475 ms median
candidate projection: 8,619.528 ms
source resolution: 1,948.759 ms
SELECT count: 68
```

```text
station.genre.refill.4
fixture size: 50K
refill number: 4
expected: seeded refill operation remains materially below BM-PROD4.1-era 11-13 second result
actual: 11,627.925 ms median
candidate projection: 7,384.466 ms
source resolution: 1,974.293 ms
SELECT count: 60
```

Additional concern:

```text
stations.list
fixture size: 50K
expected: materially comparable to BM-PROD4.2B stations.list around 3,000.567 ms
actual: 8,400.390 ms median
candidate projection: 4,819.227 ms
source resolution: 1,903.646 ms
SELECT count: 51
```

Query counts remain bounded, so this does not look like an obvious per-candidate N+1. The dominant regressions are elapsed time in candidate projection and source resolution at 50K under the required multi-iteration run.

Recommended focused fix task:

- profile 50K candidate projection and source resolution under the required benchmark shape
- compare sandbox vs unsandboxed timings if needed
- isolate whether intent bucket SQL, source preference resolution, or SQLite fixture state causes the multi-iteration slowdown
- preserve current functional 4.2C behavior and refill-safety invariants

## Validation Run

Completed:

```bash
cd personal-radio/backend
python -m compileall app scripts
python scripts/check_prod4_2c_1_station_refill_closure.py
```

Results:

- Backend compile: PASS
- Targeted BM-PROD4.2C.1 regression: PASS
- `git diff --check`: PASS
- Required benchmark JSON: COMPLETE and parseable
- Stale Python process check after benchmark: PASS, none running

Not run after blocker:

- Full production gate with new 42-check expectation
- Frontend build/lint repeat
- 100K benchmark

Reason: the required 50K closure benchmark exposed a performance acceptance blocker. Per the roadmap, production behavior was not changed to fix it inside BM-PROD4.2C.1.

## Verdict

BM-PROD4 CLOSURE: BLOCKED
