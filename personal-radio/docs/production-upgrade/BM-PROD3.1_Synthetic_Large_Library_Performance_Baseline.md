# BM-PROD3.1 - Synthetic Large-Library Performance Baseline

Owner: Bonny Makaniankhondo
Date: 2026-07-15
Starting commit: 4dc9baa60b897c3f289d26a86c806bd471a14cd0
Ending state: working tree implementation for BM-PROD3.1

## Summary

BM-PROD3.1 adds a repeatable synthetic benchmark harness for the post-1.5B BM Radio architecture. The harness measures listener-library projections and scanner startup/incremental behavior using temporary SQLite databases and deterministic synthetic paths.

The real BM Radio database remained empty. No real NAS path or real media file was scanned. No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/perf_fixtures.py`
- `personal-radio/backend/app/perf_benchmark.py`
- `personal-radio/backend/scripts/benchmark_prod3_scale.py`
- `personal-radio/backend/scripts/check_prod3_1_scale_benchmark_harness.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD3.1_Synthetic_Large_Library_Performance_Baseline.md`

## Environment

- Python: 3.14.3
- SQLite: 3.50.4
- OS summary: Windows 11

No personal absolute paths, real media names, secrets, or real library rows are included in benchmark output.

## Fixture Ratios

The synthetic fixture uses deterministic seed `31031` and fixture version `1`.

For a requested physical Track count `N`:

- artists: bounded at roughly `N / 50`, minimum 20, maximum 2000
- releases: roughly `N / 10`
- recordings: roughly `N * 0.75`
- editions: one per physical Track
- identities: one `MusicTrackIdentity` per physical Track
- technical profiles: one per physical Track
- source variants: repeated recordings across physical Tracks
- cross-release occurrences: deterministic every 37th Track
- recording types: `unknown`, `live`, `acoustic`, `remix`, `instrumental`, `radio_edit`
- participation: mostly `included`, with deterministic `library_only`, `archived`, and `blocked` rows
- preferences: deterministic automatic preferences plus some user overrides
- listener state: deterministic favorites, thumbs, qualified playback history
- playlists: bounded synthetic manual playlists with `PlaylistTrack` rows

Synthetic paths use relative strings such as `Music/Library/FLAC/...` and `Music/Library/MP3/...`. They are not real NAS paths.

## Metric Methodology

Each benchmark operation records:

- wall-time min, median, p95, max via `time.perf_counter()`
- SQL statement counts via SQLAlchemy `before_cursor_execute`
- peak Python memory via `tracemalloc`
- rows returned
- deterministic compact result checksum
- operation notes

The permanent smoke regression has no machine-specific timing threshold. It checks metric schema, deterministic checksums, temp-only artifacts, SQL counters, peak-memory presence, listener read-only behavior, scanner phase metric presence, and no real DB/media access.

## Commands Run

Smoke regression:

```text
cd personal-radio/backend
python scripts/check_prod3_1_scale_benchmark_harness.py
```

Extended 1K/10K benchmark:

```text
python scripts/benchmark_prod3_scale.py --sizes 1000,10000 --iterations 3 --warmups 1 --include-scanner --output tmp_tests/perf/prod3_baseline_1k_10k.json
```

50K listener-only attempt:

```text
python scripts/benchmark_prod3_scale.py --sizes 50000 --iterations 1 --warmups 0 --output tmp_tests/perf/prod3_baseline_50k_listener.json
```

## Baseline Results

1K fixture checksum: `533ae2e1b6bcd9aa`

| Operation | Median ms | SELECTs | Peak MiB |
| --- | ---: | ---: | ---: |
| scanner.incremental.50 | 2805.4 | 23 | 5.3 |
| scanner.startup_state | 644.1 | 1 | 2.2 |
| library.search.broad | 208.8 | 11 | 1.0 |
| library.tracks.deep | 107.5 | 8 | 0.6 |

10K fixture checksum: `29b1e964fb0d4ba3`

| Operation | Median ms | SELECTs | Peak MiB |
| --- | ---: | ---: | ---: |
| scanner.incremental.50 | 19973.8 | 23 | 40.7 |
| scanner.startup_state | 13254.8 | 1 | 23.3 |
| library.search.broad | 997.2 | 11 | 1.1 |
| library.tracks.deep | 530.9 | 8 | 0.6 |

50K listener-only fixture checksum: `aca25a563809eb0b`

| Operation | Median ms | SELECTs | Peak MiB |
| --- | ---: | ---: | ---: |
| library.search.broad | 2722.7 | 11 | 1.4 |
| library.tracks.first | 2322.5 | 8 | 1.4 |
| library.albums.first | 2206.8 | 2 | 0.3 |
| library.tracks.deep | 2203.0 | 8 | 0.7 |

100K was not run in this first baseline pass.

## Scaling Classification

Classification uses observed median wall time across measured sizes. Labels are empirical, not formal Big-O proof.

From the 1K/10K scanner-inclusive baseline:

- `scanner.startup_state`: `superlinear`
- `scanner.incremental.50`: `approximately_linear`
- listener summary, pagination, album/artist aggregation, search: mostly `approximately_linear`
- `library.recent_playback`: `bounded`

The 50K listener-only run confirms listener paths continue to scale materially with library size, with broad search and page projections in the 1.8-2.8 second range on this machine.

## Measured Hot Path

Top measured hot path: scanner incremental scan against a large existing index.

At 10K physical Tracks, `scanner.incremental.50` measured about 20 seconds median, and `scanner.startup_state` measured about 13.3 seconds median. This aligns with the known current behavior: full `Track` ORM load plus Python exact-path and legacy identity maps before processing a small incremental file set.

## Recommended Next Optimization

Recommended next task: benchmark-driven scanner startup/index-map optimization.

Do not optimize in BM-PROD3.1 itself. The next optimization should target replacing or narrowing the full `db.query(Track).all()` startup materialization and the full exact-path/legacy identity map construction, using this benchmark as the regression baseline.

## Validation

Targeted smoke:

```text
PASS: BM-PROD3.1 synthetic large-library benchmark harness
```

Permanent production gate result:

```text
python scripts/check_prod0_baseline.py
BM-PROD0 BASELINE GATE: PASS
Mandatory: 34 passed, 0 failed
Optional/integration: 4 skipped
```

## Deferred Work

- benchmark-driven scanner optimization
- benchmark-driven query/pagination optimization
- BM-PROD4 station generation/refill scale optimization
- explicit listener-selectable version controls only if later desired
- frontend curation/source/version controls
- release/edition-family refinement
- PostgreSQL and deployment hardening
- controlled real-media canary