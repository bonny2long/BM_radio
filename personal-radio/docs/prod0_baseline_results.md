# BM-PROD0 Baseline Test Results

**Date**: 2026-08-15  
**Script**: `personal-radio/scripts/check_prod0_baseline.py`  
**Execution Environment**: Windows, Backend Virtual Environment (`personal-radio/backend/.venv`)  
**Overall Result**: **PASS (50 Passed, 0 Failed, 4 Skipped)**

---

## Executive Summary

| Category | Count | Status |
| :--- | :--- | :--- |
| **Mandatory Checks Passed** | **50** | `PASS` |
| **Mandatory Checks Failed** | **0** | `PASS` |
| **Optional / Integration Checks** | **4** | `SKIP` |
| **Total Evaluated** | **54** | |

---

## Resolution Notes
* **Issue**: In environments lacking an uncommitted historical backup archive in `backend/.local_backups/`, `check_prod5_3c_1_controlled_empty_local_rebuild.py` failed with an assertion error.
* **Fix**: Made `check_prod5_3c_1_controlled_empty_local_rebuild.py` self-contained and portable by allowing it to synthesize a disposable legacy incompatible fixture when an existing local backup is absent, avoiding reliance on machine-local uncommitted files.
* **Verification**: All 50 mandatory baseline tests and 30 internal rebuild checks pass cleanly.

---

## Detailed Results Breakdown

### Mandatory Checks (50/50 Passed)

| # | Check Name | Target / Subsystem | Status | Notes |
| :- | :--- | :--- | :-: | :--- |
| 1 | `python compileall` | Backend `app`, `scripts` | `PASS` | Clean syntax compilation |
| 2 | `AA music manifest import` | Backend `scripts/check_aa_manifest_music_import.py` | `PASS` | Manifest parsing & mapping |
| 3 | `canonical music scan roots` | Backend `scripts/check_prod1_1_canonical_music_roots.py` | `PASS` | Root configuration & validation |
| 4 | `production config contract` | Backend `scripts/check_prod1_2a_config_contract.py` | `PASS` | Environment and configuration contracts |
| 5 | `runtime API safety` | Backend `scripts/check_prod1_2b_runtime_safety.py` | `PASS` | API endpoint safety & rate/error boundaries |
| 6 | `scan-run foundation` | Backend `scripts/check_prod1_3a_scan_run_foundation.py` | `PASS` | Scan run lifecycle & persistence |
| 7 | `music scan reconciliation` | Backend `scripts/check_prod1_3b_music_scan_reconciliation.py` | `PASS` | File discovery and reconciliation |
| 8 | `audiobook scan progress safety` | Backend `scripts/check_prod1_3c1_audiobook_scan_progress_safety.py` | `PASS` | Progress preservation during rescans |
| 9 | `audiobook availability reconciliation` | Backend `scripts/check_prod1_3c2_audiobook_reconciliation.py` | `PASS` | Availability tracking across scans |
| 10 | `core active-library availability policy` | Backend `scripts/check_prod1_3d1_core_availability_policy.py` | `PASS` | Library availability invariant policy |
| 11 | `active queues stations playlists playback policy` | Backend `scripts/check_prod1_3d2_active_playback_candidates.py` | `PASS` | Playback candidate resolution rules |
| 12 | `integrity reporting and scan history` | Backend `scripts/check_prod1_3d3_integrity_reporting.py` | `PASS` | Integrity report persistence |
| 13 | `integrity UI contract` | Frontend `scripts/check_prod1_3d3_integrity_ui.mjs` | `PASS` | Integrity UI data model contract |
| 14 | `music identity graph foundation` | Backend `scripts/check_prod1_4a1_music_identity_graph.py` | `PASS` | Canonical artist/release/recording keys |
| 15 | `scanner identity integration and physical-source preservation` | Backend `scripts/check_prod1_4a2_scanner_identity_integration.py` | `PASS` | Multi-source graph integration |
| 16 | `objective music technical profile foundation` | Backend `scripts/check_prod1_4b1_music_technical_profile.py` | `PASS` | Bitrate, format, resolution profile |
| 17 | `conservative preferred-source policy foundation` | Backend `scripts/check_prod1_4c1_preferred_source_policy.py` | `PASS` | Lossless vs lossy ranking rules |
| 18 | `scanner-driven preference re-evaluation` | Backend `scripts/check_prod1_4c2_scanner_preference_reevaluation.py` | `PASS` | Incremental preference updating |
| 19 | `recording curation and preference control API` | Backend `scripts/check_prod1_4d1_recording_control_api.py` | `PASS` | Explicit user pinning & overrides |
| 20 | `listener library and search projection` | Backend `scripts/check_prod1_4d2_listener_library_projection.py` | `PASS` | Canonical search & listing views |
| 21 | `listener projection scale stabilization` | Backend `scripts/check_prod1_4d2_1_listener_projection_scale.py` | `PASS` | Query plan & pagination stability |
| 22 | `listener queue and playlist source resolution` | Backend `scripts/check_prod1_4d3a_listener_queue_and_playlist_projection.py` | `PASS` | On-demand file path resolution |
| 23 | `playback safety and recording-aware history` | Backend `scripts/check_prod1_4d3b_playback_recording_identity.py` | `PASS` | Playback history recording identity |
| 24 | `recording-level favorites feedback and smart collections` | Backend `scripts/check_prod1_4d3c_recording_feedback_and_smart_collections.py` | `PASS` | Feedback propagation to collections |
| 25 | `recording-first station candidate foundation` | Backend `scripts/check_prod1_5a_recording_first_station_candidates.py` | `PASS` | Candidate generator graph traversal |
| 26 | `seed version affinity and adaptive fallback` | Backend `scripts/check_prod1_5b_station_version_affinity.py` | `PASS` | Seed matching & fallback policies |
| 27 | `synthetic large-library benchmark harness` | Backend `scripts/check_prod3_1_scale_benchmark_harness.py` | `PASS` | Scale benchmark simulation |
| 28 | `scanner candidate-scoped index optimization` | Backend `scripts/check_prod3_2_scanner_index_optimization.py` | `PASS` | Candidate query indexing |
| 29 | `scanner diagnostic pair canonicalization` | Backend `scripts/check_prod3_2_1_scanner_diagnostic_pair_canonicalization.py` | `PASS` | Diagnostic pair index verification |
| 30 | `listener occurrence query optimization` | Backend `scripts/check_prod3_3_listener_occurrence_query_optimization.py` | `PASS` | Occurrence query optimization |
| 31 | `station generation and refill scale benchmark baseline` | Backend `scripts/check_prod4_1_station_scale_benchmark.py` | `PASS` | Generation latency benchmark |
| 32 | `candidate-scoped station profiles and request context` | Backend `scripts/check_prod4_2a_scoped_station_profiles.py` | `PASS` | Request-scoped radio profiles |
| 33 | `final-set station candidate projection and source-resolution scope` | Backend `scripts/check_prod4_2b_station_candidate_projection_scope.py` | `PASS` | Resolution scoping |
| 34 | `station intent-aware large-library candidate coverage` | Backend `scripts/check_prod4_2c_station_intent_candidate_coverage.py` | `PASS` | Intent candidate coverage |
| 35 | `station refill closure and PROD4 gate` | Backend `scripts/check_prod4_2c_1_station_refill_closure.py` | `PASS` | Refill loop completion |
| 36 | `unified station intent candidate projection` | Backend `scripts/check_prod4_2d_unified_intent_projection.py` | `PASS` | Intent candidate projection |
| 37 | `benchmark-selected station projection policy` | Backend `scripts/check_prod4_2e_benchmark_selected_projection_policy.py` | `PASS` | Selected projection policy |
| 38 | `Alembic migration framework and current-schema baseline` | Backend `scripts/check_prod5_3a_migration_framework.py` | `PASS` | Migration runner & baseline revision |
| 39 | `Alembic schema parity hardening` | Backend `scripts/check_prod5_3a_1_schema_parity_hardening.py` | `PASS` | SQLAlchemy vs Alembic schema parity |
| 40 | `migration-authoritative startup readiness` | Backend `scripts/check_prod5_3b_migration_authoritative_startup.py` | `PASS` | Fast startup readiness classification |
| 41 | `controlled empty local SQLite rebuild` | Backend `scripts/check_prod5_3c_1_controlled_empty_local_rebuild.py` | `PASS` | 30 rebuild and compatibility checks passed |
| 42 | `PostgreSQL dialect foundation and offline migration proof` | Backend `scripts/check_prod5_4a_postgresql_dialect_foundation.py` | `PASS` | Offline PostgreSQL migration SQL gen |
| 43 | `disposable PostgreSQL integration safety contract` | Backend `scripts/check_prod5_4b_postgresql_integration_contract.py` | `PASS` | Disposable DB execution contract |
| 44 | `AA audiobook manifest import` | Backend `scripts/check_aa_manifest_audiobook_import.py` | `PASS` | Audiobook manifest parsing & mapping |
| 45 | `audiobook multi-book ordering` | Backend `scripts/check_audiobook_multibook_ordering.py` | `PASS` | Multi-disc & multi-book track order |
| 46 | `audiobook progress reset` | Backend `scripts/check_audiobook_progress_reset.py` | `PASS` | Position and completion reset flows |
| 47 | `safe media roots` | Backend `scripts/check_bm_radio_safe_roots.py` | `PASS` | Media folder boundary containment |
| 48 | `frontend mojibake` | Backend `scripts/check_frontend_mojibake.py` | `PASS` | Text encoding & unicode integrity |
| 49 | `frontend production build` | Frontend `npm run build` | `PASS` | Vite + TypeScript production bundle |
| 50 | `frontend lint` | Frontend `npm run lint` | `PASS` | 0 errors, 0 warnings |

---

### Skipped Checks (Optional / Integration)

| Check Name | Status | Reason |
| :--- | :-: | :--- |
| `imported metadata mojibake` | `SKIP` | Requires initialized or populated local BM Radio database |
| `station genre families M5.1` | `SKIP` | Depends on populated library/profile fixture state |
| `station logic M5` | `SKIP` | Depends on populated library/profile fixture state |
| `station logic M5.2` | `SKIP` | Depends on populated library/profile fixture state |
