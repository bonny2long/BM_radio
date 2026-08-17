# BM-PROD6B Radio Station Behavior and Recommendation Quality Acceptance

BM-PROD6B status: **RADIO-QUALITY PASS**

Starting SHA: `387033a7cfad43ce42c9f8ba7fc0372c7b471b30`

Ending SHA / working-tree state: HEAD remains `387033a7cfad43ce42c9f8ba7fc0372c7b471b30`; the intentional PROD6B implementation and evidence changes listed by final `git status --short` remain uncommitted for exact review.

## PROD6A final-commit documentation correction

The PROD6A report now records core implementation commit `cd8add5c3de868f0872ed9786c3520a1243eedd5` and final accepted phase commit `387033a7cfad43ce42c9f8ba7fc0372c7b471b30`. Stale uncommitted-state wording was removed.

## Fixture

- Logical recordings: 200
- Physical tracks: 201
- Artists: 25
- Releases: 50
- Genre families: 5 (`hip-hop`, `electronic`, `rock`, `r&b`, `jazz`)
- Version types: studio, standard, live, acoustic, remix, instrumental
- Feedback/history signals: favorite, thumbs-up, later thumbs-down precedence, and 0–5 qualified plays
- Source: disposable synthetic SQLite database; no real media files are opened

## Objective quality result

- Universal quality: zero logical duplicates, zero physical duplicates, zero thumbs-down selections. Artist/release consecutive caps and rolling last-9 caps pass across normal 25-track windows.
- Artist Radio: 25-track windows, five artists, seed artist present, seed share at most 28%, compatible share 100%, no unrelated exploration.
- Song Radio: seed logical recording excluded, five artists, seed artist share at most 24%, same-family share 100% with exploration disabled.
- Genre Radio: five artists, same-family share 100%, single-artist share at most 24%.
- Favorites: only favorite or thumbs-up logical recordings; later thumbs-down wins.
- Recently Added: controlled newest-first order, thumbs-down removed, requested limit honored.
- Deep Cuts: first-20 unplayed/low-play share 100% (required >=70%).
- Feedback adaptation: a candidate appears before and disappears after a later downvote across Artist, Song, Genre, and Favorites stations. Comparable fixed-seed debug scores change by `+0.50` for thumbs-up, `+0.30` for favorite, and `-1.00` for recent play.
- Refill: initial window plus three refills have zero logical/physical overlap; terminal refill is empty and exhausted.
- Physical-source variant: MP3 and FLAC resolve to one logical row; lossless track 201 is preferred; excluding either physical source excludes the logical recording.
- Version behavior: live 60%, acoustic 60%, remix 60%, instrumental 60% primary-plus-adjacent share; balanced specialized share 24% (required <=25%). Sparse fallback warnings remain covered by `backend/scripts/check_prod1_5b_station_version_affinity.py`.
- Frontend refill: threshold, append-once, response deduplication, stable current item, station metadata, bounded 200-item exclusions, exhaustion, and finite album/playlist behavior pass.
- Station UI: Favorites 6, Recently Added 197, Deep Cuts 67; counts reflect playable logical membership after thumbs-down exclusion, and each system station is playable.

## Manual station report

Result: **ALGORITHMIC PASS — REAL-LIBRARY SUBJECTIVE REVIEW DEFERRED TO PROD6F**

Operator result: NOT PROVIDED. Automation did not fabricate a listening result. See `BM-PROD6B_Station_Review.md`.

## Performance and regression gates

PROD4 station gates to execute:

- `check_prod4_1_station_scale_benchmark.py`
- `check_prod4_2a_scoped_station_profiles.py`
- `check_prod4_2b_station_candidate_projection_scope.py`
- `check_prod4_2c_station_intent_candidate_coverage.py`
- `check_prod4_2c_1_station_refill_closure.py`
- `check_prod4_2d_unified_intent_projection.py`
- `check_prod4_2e_benchmark_selected_projection_policy.py`

The 1000-track smoke remains mandatory through the PROD4 gate. The final 10k benchmark procedure is:

`python scripts/benchmark_prod4_station_scale.py --sizes 10000 --iterations 1 --warmups 0 --refill-count 4`

Results: all seven PROD4 gates PASS, including the mandatory 1000-track smoke. The separate 10k benchmark completed in 189.6 seconds. Initial 50-track windows measured 4165.4–5824.1 ms with 49–64 SELECTs and 24.7–25.7 MiB peak memory. Four-refill chains all returned 50 tracks; refill timing measured 3240.0–6799.7 ms with bounded 53–65 SELECTs. Candidate/source resolution remained scoped and the benchmark wrote only ignored disposable evidence under `backend/tmp_tests/perf`.

## Protected state

- active PostgreSQL: not opened or mutated; `active_postgresql_used=false`; no Docker resources created
- SQLite: `backend/bm_radio.db` SHA-256 remained `e7edbf59d2f447193175e764e83b7ecb6375d77792399ae578f1cea1076d4619`
- .env/evidence: `.env` SHA-256 remained `1d87e58b633f6dd2f34c9e6bc3c1fbde5b837529a0851e928e56d2ffa1526317`; durable evidence was not mutated by acceptance
- Real media accessed: NO
- TrueNAS work: prohibited

Cleanup: disposable fixture database removed by temporary-directory cleanup; no Docker resources created.

## Final gates

- 6B contract: PASS (52 checks)
- 6A contract: PASS (40 checks)
- 5.6B contract: PASS (34 checks)
- PROD0: PASS — `60 passed / 0 failed / 4 skipped`
- Backend compile: PASS
- Frontend build: PASS
- Frontend lint: PASS — 0 errors, 8 existing warnings
- `git diff --check`: PASS
- Final git status: intentional PROD6B files and compatibility/documentation updates remain uncommitted for exact review; no unexpected generated files are present

Next action: review the exact PROD6B diff and create the phase commit if accepted. Then, only after explicit approval, proceed to BM-PROD6C Library, Playlist, Feedback, and Preferred-Source UX Acceptance.

**STOP: BM-PROD6B RADIO-QUALITY PASS. No PROD6C, audiobook, TrueNAS, real-library import, or SQLite-retirement work was started.**
