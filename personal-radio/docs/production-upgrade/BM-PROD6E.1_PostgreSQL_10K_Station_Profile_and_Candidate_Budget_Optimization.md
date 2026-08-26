# BM-PROD6E.1 — PostgreSQL 10K Station Profile and Candidate-Budget Optimization

Date: 2026-08-22  
Starting commit: `74b1b707d6478fcfd4a7ab2b1a57bcad6457fb6c`  
Ending implementation commit: `0189dbaa8caf5f5a2a3ac6a140d19887b4dd507e`  
Report commit: `fa384a007cadd80d3195035e6d01f5b2bf29fdfb`
Final status: **PASS — PostgreSQL 16 production station thresholds met**

## Outcome

BM Radio now uses a bounded station candidate budget for normal listener queues instead of always hydrating up to 5,000 candidates. A 50-track request starts at 500 candidates, may expand to 750 for a library with at most 750 recordings, and retains 5,000 as the hard ceiling. Debug metrics expose the initial/final budget, recording-count hint, expansion count, and policy.

The station request path loads artist and album profiles only for normalized candidate-derived keys, in chunks of 500. The station path no longer performs unbounded artist/album profile-table loads. Full-table reads that remain in `radio_profiles.py` belong to explicit profile seeding/administration, not listener station generation.

The production acceptance source is a task-scoped PostgreSQL 16 container upgraded to Alembic head and populated with a deterministic 10,000-track fixture. All seven initial station families and all sixteen refill cases meet their individual latency thresholds.

## Accepted policy

```text
initial budget = max(500, requested_queue_size * 10)
small-library expansion = 750 when total recordings <= 750
absolute ceiling = 5000
normal 50-track request on 10K fixture = 500
policy name = queue_scaled_10x_floor_500_small_library_750
```

The 10K acceptance fixture reported `recording_count_hint=7500`, `initial_budget=500`, `final_budget=500`, and `expanded=false`.

## Acceptance environment

| Item | Result |
|---|---|
| Database | Disposable PostgreSQL 16 |
| Schema | Alembic head |
| Physical tracks / editions | 10,000 / 10,000 |
| Logical recordings | 7,500 |
| Releases / artists | 1,000 / 200 |
| Fixture seed / checksum | 41041 / `29b1e964fb0d4ba3` |
| Warmups / measured iterations | 2 / 10 |
| Fixture build time | 30,335.898 ms, excluded from latency |
| Task resource prefix | `bm-prod6e1-` |
| Protected active container | Present and explicitly rejected |
| Cleanup | PASS; no task container or volume remains |

## SQLite historical comparison

SQLite remains a regression signal, not the production acceptance database.

| Operation | Historical median | Post-change diagnostic |
|---|---:|---:|
| Song initial | 3,738.8 ms | 1,024.1 ms |
| Song Live initial | 3,642.4 ms | 798.4 ms |
| Artist initial | 3,415.6 ms | 869.5 ms |
| Genre initial | 3,382.5 ms | 690.7 ms |
| Favorites initial | 2,820.2 ms | 512.0 ms |
| Recently Added initial | 2,634.2 ms | 451.9 ms |
| Deep Cuts initial | 3,113.5 ms | 503.2 ms |
| Song refill range | 3,581.9–4,881.4 ms | 717.5–793.8 ms |
| Artist refill range | 4,656.2–4,757.8 ms | 758.3–927.1 ms |
| Genre refill range | 4,421.9–4,577.0 ms | 718.6–811.0 ms |
| Favorites refill range | 3,862.3–3,966.4 ms | 456.9–513.1 ms |

The post-change SQLite values are a bounded one-sample diagnostic with four chained refills, so they do not provide a meaningful p95. An attempted 2-warmup/10-iteration SQLite run exceeded a 20-minute safety limit and was stopped. This limitation does not affect PostgreSQL acceptance.

## Candidate-budget matrix

This is a one-sample-per-family diagnostic used to choose the production budget. Latency, SQL, hydration, and memory columns show the range across the seven initial station families.

| Budget | Latency range | SELECT range | SQL time range | Tracks hydrated | Peak memory | PROD6B quality |
|---:|---:|---:|---:|---:|---:|---|
| 500 | 385.7–797.8 ms | 16–43 | 220.9–483.1 ms | 500–501 | 2.21–2.93 MiB | PASS for selected production policy |
| 750 | 384.7–992.1 ms | 16–47 | 202.5–596.4 ms | 750–751 | 3.29–4.76 MiB | Diagnostic override only |
| 1,000 | 455.0–1,331.4 ms | 16–48 | 168.2–823.3 ms | 1,000–1,002 | 4.00–5.76 MiB | Diagnostic override only |
| 1,500 | 825.2–2,696.4 ms | 18–50 | 287.9–1,353.1 ms | 1,500–1,504 | 6.19–9.74 MiB | Diagnostic override only |
| 2,500 | 1,228.2–2,981.3 ms | 25–61 | 502.3–1,414.5 ms | 2,500–2,505 | 8.81–15.19 MiB | Diagnostic override only |
| 5,000 | 2,145.7–3,210.2 ms | 35–71 | 755.1–1,451.2 ms | 5,008–5,009 | 27.39–27.72 MiB | Superseded ceiling baseline |

The selected 500-candidate production policy received the complete deterministic PROD6B quality acceptance, including duplicates, downvotes, caps, relevance/diversity, genre coherence, system stations, feedback, recent suppression, version affinity, refill overlap/exhaustion, and preferred sources. Larger diagnostic overrides were not separately claimed as quality passes.

## PostgreSQL 10K pre-optimization ceiling baseline

The pre-policy comparison forces the former 5,000-candidate ceiling. It is a single measured diagnostic, so p50 and p95 are the same sample and are shown only as the optimization baseline.

| Initial family | p50 | p95 |
|---|---:|---:|
| Song | 3,010.9 ms | 3,010.9 ms |
| Song Live | 3,210.2 ms | 3,210.2 ms |
| Artist | 3,091.3 ms | 3,091.3 ms |
| Genre | 2,781.5 ms | 2,781.5 ms |
| Favorites | 2,154.0 ms | 2,154.0 ms |
| Recently Added | 2,206.8 ms | 2,206.8 ms |
| Deep Cuts | 2,145.7 ms | 2,145.7 ms |

## PostgreSQL 10K final initial results

Threshold: p50 <= 1,500 ms and p95 <= 2,500 ms for every family.

| Initial family | p50 | p95 | SELECT p50 | SQL p50 | Tracks / profile rows | Peak memory |
|---|---:|---:|---:|---:|---:|---:|
| Song | 861.5 ms | 1,018.9 ms | 46 | 453.8 ms | 501 / 502 | 2.97 MiB |
| Song Live | 903.5 ms | 1,037.4 ms | 46 | 500.6 ms | 500 / 501 | 2.11 MiB |
| Artist | 857.1 ms | 953.7 ms | 33 | 457.7 ms | 500 / 500 | 2.91 MiB |
| Genre | 750.0 ms | 988.2 ms | 40 | 424.6 ms | 500 / 500 | 2.81 MiB |
| Favorites | 627.0 ms | 664.0 ms | 36 | 312.5 ms | 500 / 500 | 2.62 MiB |
| Recently Added | 388.9 ms | 482.1 ms | 18 | 172.7 ms | 500 / 500 | 2.13 MiB |
| Deep Cuts | 651.2 ms | 785.6 ms | 36 | 315.4 ms | 500 / 500 | 2.77 MiB |

Result: **PASS for every initial family**.

## PostgreSQL 10K final refill results

Threshold: p50 <= 1,000 ms and p95 <= 2,000 ms for every family and exclusion size.

| Refill | Exclusions | p50 | p95 |
|---|---:|---:|---:|
| Song | 50 | 753.5 ms | 787.1 ms |
| Artist | 50 | 689.6 ms | 799.9 ms |
| Genre | 50 | 886.7 ms | 987.2 ms |
| Favorites | 50 | 623.3 ms | 694.0 ms |
| Song | 100 | 779.5 ms | 827.8 ms |
| Artist | 100 | 635.0 ms | 743.4 ms |
| Genre | 100 | 870.1 ms | 943.8 ms |
| Favorites | 100 | 520.2 ms | 652.5 ms |
| Song | 150 | 619.9 ms | 658.5 ms |
| Artist | 150 | 556.2 ms | 633.4 ms |
| Genre | 150 | 867.3 ms | 1,043.4 ms |
| Favorites | 150 | 535.0 ms | 729.5 ms |
| Song | 200 | 668.4 ms | 746.7 ms |
| Artist | 200 | 583.8 ms | 659.3 ms |
| Genre | 200 | 869.9 ms | 1,231.1 ms |
| Favorites | 200 | 551.0 ms | 611.5 ms |

Result: **PASS for all sixteen refill cases**, with zero duplicate or return failures.

## Phase timing

The profiler records request/context, eligibility, intent buckets, source resolution, track/recording hydration, profile cache, listener signals, version affinity, scoring, window assembly, and serialization. Timings below are the median p50 across all final operations; nested segments are not additive.

| Slowest phase | Median operation p50 | Worst operation p50 |
|---|---:|---:|
| Station total | 668.4 ms | 903.4 ms |
| Request context total | 558.1 ms | 783.2 ms |
| Context candidate work | 286.1 ms | 468.0 ms |
| Candidate projection | 286.1 ms | 468.0 ms |
| Feedback/recent/favorites/play-count signals | 198.3 ms | 243.6 ms |

The data confirms that candidate SQL/projection and listener-signal queries are material; Python scoring is lower at a 76.1 ms median p50 and was not micro-optimized blindly.

## SQL profiling and EXPLAIN

Final operations used 18–48 SELECTs, with SQL p50 ranging from 172.7 to 516.5 ms across the full initial/refill matrix. Slow normalized signatures are stored only in ignored raw evidence.

A focused disposable 10K diagnostic ran `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on the slowest SELECT from every initial family. Concise representative results:

| Family | Top node | Execution | Rows | Shared hit/read | Temp read/write |
|---|---|---:|---:|---:|---:|
| Song | Limit | 109.1 ms | 370 | 59,878 / 0 | 0 / 0 |
| Song Live | Limit | 46.3 ms | 366 | 59,848 / 0 | 0 / 0 |
| Artist | Seq Scan | 0.7 ms | 117 | 27 / 0 | 0 / 0 |
| Genre | Limit | 96.9 ms | 500 | 85,594 / 0 | 0 / 0 |
| Favorites | Limit | 73.8 ms | 500 | 60,409 / 0 | 0 / 0 |
| Recently Added | Limit | 82.4 ms | 500 | 60,409 / 0 | 0 / 0 |
| Deep Cuts | Aggregate | 4.8 ms | 38 | 68 / 0 | 0 / 0 |

No explain plan spilled to temporary blocks, and no credentials or full database URL were logged.

## Architecture and memory closure

| Requirement | Result |
|---|---|
| Candidate-scoped artist/album profile loading | YES |
| Full profile-table loads in station request path | NO |
| Candidate limit exposed | YES |
| Recording IDs selected exposed | YES |
| Track rows hydrated exposed | YES |
| Profile rows loaded exposed | YES |
| Effective sources and final pool exposed | YES |
| Expansion exposed | YES |
| 5,000 absolute ceiling retained | YES |
| Unbounded process-global cache added | NO |
| Candidate hydration before/after | 5,008–5,009 -> 500–501 |
| Peak memory before/after | 27.39–27.72 MiB -> 2.11–2.97 MiB |

## Quality and regression evidence

| Check | Result |
|---|---|
| Full deterministic PROD6B acceptance | PASS |
| Permanent PROD6B contract | PASS, 52 checks |
| PROD4.1 | PASS |
| PROD4.2A | PASS |
| PROD4.2B | PASS |
| PROD4.2C | PASS |
| PROD4.2C.1 | PASS |
| PROD4.2D | PASS |
| PROD4.2E | PASS |
| PROD1.5A / PROD1.5B | PASS / PASS |
| PROD6A contract | PASS, 40 checks |
| PROD6C contract | PASS, 41 checks |
| PROD6D contract | PASS, 30 checks |
| Changed Python files compile | PASS |
| Git diff check | PASS |

### PROD0 execution note

A complete PROD0 invocation reached 61 mandatory passes and one failure. The sole failure was a Windows/OneDrive cleanup lock in the PROD5.3B disposable migration fixture; no behavioral assertion failed. The affected PROD5.3A, PROD5.3A.1, and PROD5.3B checks were moved to system-temp fixtures and each repeated successfully twice, with the real database unchanged.

A final consolidated retry later stalled inside PROD4.2D and its wrapper timed out. That exact PROD4.2D gate had already passed independently and in the prior complete invocation. The timed-out test-only processes were identified and stopped. Therefore regression evidence is complete by composition, but this report does **not** claim a clean final single-invocation PROD0 summary.

PROD0 remains at 62 mandatory checks; it was not advanced to 63 because no permanent PROD6E contract was added in this task.

## Protected state and cleanup

| Protected item | Result |
|---|---|
| Active adopted PostgreSQL used | NO |
| SQLite fallback SHA-256 | unchanged: `e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619` |
| `backend/.env` SHA-256 | unchanged: `1d87e58b633f6dd2f34c9e6bc3c1fbde5b837529a0851e928e56d2ffa1526317` |
| Real media accessed | NO |
| Durable migration/adoption/backup/recovery evidence | unchanged |
| Task PostgreSQL containers/volumes | cleaned; zero `bm-prod6e1-*` remain |
| Abandoned SQLite system-temp fixtures | removed |
| Protected `bm-radio-postgres-dev` resources | explicitly rejected by harness |

Protected state: **PASS**.

## Raw performance artifact policy

Raw JSON remains local under ignored `backend/tmp_tests/perf/` and `tmp_tests/perf/` paths. The previously tracked `tmp_tests/perf/prod4_1_station_baseline.json` was removed from the Git index but preserved locally. `.gitignore` now prevents future generated performance JSON rewrites from entering source history. Concise durable evidence is kept in this report.

Key ignored evidence files:

```text
backend/tmp_tests/perf/prod6e1_postgres_budget_matrix_initial.json
backend/tmp_tests/perf/prod6e1_postgres_final_optimized_policy.json
backend/tmp_tests/perf/prod6e1_postgres_explain_diagnostic.json
backend/tmp_tests/perf/prod6e1_sqlite_post_diagnostic.json
```

## Stop condition

PostgreSQL 16 normal 10K station generation is below the required initial and refill thresholds for every measured family. BM-PROD6E.1 therefore stops with **PASS**.

The 60-minute soak was not started. PROD6F was not started.
