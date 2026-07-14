# BM-PROD0 Baseline and Regression Gate

Owner: Bonny Makaniankhondo
Project: BM Radio Production Upgrade
Date: 2026-07-14
Scope: Baseline freeze only. No production behavior change.

## Baseline Snapshot

| Item | Value |
| --- | --- |
| Branch | `main` |
| Starting commit SHA | `dbad0670508e799f960ce868993f6f23f4a78d68` |
| Starting commit | `dbad067 (HEAD -> main, origin/main, origin/HEAD) docs: remove obsolete architecture diagram documentation` |
| Worktree before BM-PROD0 changes | Clean |
| Python | `Python 3.14.3` |
| Node | `v22.19.0` |
| npm | `11.12.1` |

Required pre-change commands were run before adding this report and `scripts/check_prod0_baseline.py`.

## Backend Versions

From `personal-radio/backend`:

| Dependency | Version |
| --- | --- |
| SQLAlchemy | `2.0.49` |
| FastAPI | `0.135.3` |
| Pydantic | `2.12.5` |

Current backend is FastAPI plus SQLAlchemy. The local backend convention remains port `8094`.

## Frontend Summary

From `personal-radio/frontend`, `npm ls --depth=0` reported:

| Package | Version |
| --- | --- |
| `@types/node` | `24.13.2` |
| `@types/react` | `19.2.17` |
| `@types/react-dom` | `19.2.3` |
| `@vitejs/plugin-react` | `6.0.3` |
| `oxlint` | `1.71.0` |
| `react` | `19.2.7` |
| `react-dom` | `19.2.7` |
| `typescript` | `6.0.3` |
| `vite` | `8.1.0` |

Current frontend is React plus Vite plus TypeScript. The local frontend convention remains port `5174`.

## Database Baseline

Current default database setting is `DATABASE_URL = sqlite:///./bm_radio.db` in `backend/app/config.py`. When run from `personal-radio/backend`, this resolves to `personal-radio/backend/bm_radio.db`.

Observed assumptions:

- SQLite is the current local development default.
- PostgreSQL is documented as the future production target.
- `app/main.py` creates missing SQLAlchemy tables on startup.
- `schema_maintenance.py` contains narrow additive SQLite column maintenance for manifest ingestion fields.
- `perf.py` creates additional indexes at startup through `ensure_performance_indexes()`.
- `seed_default_radio_profiles()` runs on app startup and may add default radio-profile rows.
- The BM-PROD0 regression gate does not require or mutate Bonny's personal populated database.

## Scanner and Index Baseline

Observed music scanner root behavior in `backend/app/scanner/music_scanner.py`:

```text
settings.MUSIC_MP3_ROOT
settings.MUSIC_FLAC_ROOT
settings.MUSIC_DISCOGRAPHIES_ROOT
```

The scanner uses existing roots from that list and currently includes legacy `Music/Discographies` behavior. BM-PROD0 records this only; BM-PROD1.1 will make canonical final-library roots explicit.

The music index is currently track-centric. The `Track` model includes metadata and Archive Assistant provenance fields such as `metadata_source`, `source_manifest_path`, `source_manifest_version`, `source_metadata_version`, `track_number`, `disc_number`, and `primary_genre`.

## Archive Assistant Manifest Support

Existing manifest import support is present in:

- `backend/app/scanner/archive_assistant_manifest.py`
- `backend/app/scanner/music_scanner.py`
- `backend/app/scanner/audiobook_scanner.py`
- `backend/scripts/check_aa_manifest_music_import.py`
- `backend/scripts/check_aa_manifest_audiobook_import.py`

The deterministic manifest checks pass using in-memory SQLite databases and controlled fixture folders under `backend/tmp_tests`.

## Performance Instrumentation

Existing performance instrumentation is present in `backend/app/perf.py`:

- request timing middleware in development;
- SQL query counting headers;
- `perf_segment()` logging;
- startup index creation through `ensure_performance_indexes()`.

Known future performance concern: some station and library paths still load bounded collections into Python, for example station count/profile paths that query up to 5,000 tracks. BM-PROD0 records this only.

## Current Production Concerns Carried Forward

| Future phase | Concern |
| --- | --- |
| BM-PROD1.1 | Canonical music roots must become `Music/Library/FLAC` and `Music/Library/MP3`; legacy `Music/Discographies` scanning must become explicit compatibility behavior and be disabled by default for production. |
| BM-PROD1.2 | Configuration needs a unified `BM_RADIO_*` contract, production-safe CORS, API-doc controls, safe path validation, and private defaults. |
| BM-PROD1.3 | Scanning needs scan-run or scan-generation reconciliation so unavailable indexed paths can be marked without deleting archive media. |
| BM-PROD1.4 / BM-PROD2 | The index must distinguish file, release, recording/work, and display identity; artist-centric release grouping belongs in BM Radio, not in physical NAS layout. |
| BM-PROD3 | Large-library scanner and query performance need benchmark-backed optimization. |
| BM-PROD4 | Station generation and refill need to avoid expensive full-library Python work as the library grows. |
| BM-PROD5 | PostgreSQL migration, deterministic migrations, backup/restore proof, TrueNAS hardening, read-only media mounts, and production security remain future work. |

## Existing Check Classification

| Script | Classification | Reason |
| --- | --- | --- |
| `check_aa_manifest_audiobook_import.py` | DETERMINISTIC | Uses controlled temp fixture files and an in-memory SQLite DB. |
| `check_aa_manifest_music_import.py` | DETERMINISTIC | Uses controlled temp fixture files and an in-memory SQLite DB. |
| `check_audiobook_multibook_ordering.py` | DETERMINISTIC | Pure ordering checks against fixture path names. |
| `check_audiobook_progress_reset.py` | DETERMINISTIC | Uses an in-memory SQLite DB and constructed rows. |
| `check_bm_radio_safe_roots.py` | DETERMINISTIC | Uses controlled temp fixture files under `backend/tmp_tests`. |
| `check_frontend_mojibake.py` | DETERMINISTIC | Scans repository frontend text files only. |
| `check_imported_metadata_mojibake.py` | LOCAL_DATABASE_INTEGRATION | Uses `SessionLocal` and scans the active configured BM Radio database. A clean checkout may have no populated DB. |
| `check_station_genre_families_m5_1.py` | PERSONAL_LIBRARY_INTEGRATION | Depends on populated track/profile state and named artists/genres from the local library. |
| `check_station_logic_m5.py` | PERSONAL_LIBRARY_INTEGRATION | Depends on populated track/profile state including OutKast seed data. |
| `check_station_logic_m5_2.py` | PERSONAL_LIBRARY_INTEGRATION | Depends on populated track/profile state including Electronic and Hip-Hop artists. |

No current checks are classified as `FIXTURE_REQUIRED` or `OBSOLETE_OR_SUPERSEDED` in BM-PROD0.

## Regression Commands

Unified BM-PROD0 gate from `personal-radio/`:

```bash
python scripts/check_prod0_baseline.py
```

Deterministic commands included in the gate:

```bash
cd personal-radio/backend
python -m compileall app scripts
python scripts/check_aa_manifest_music_import.py
python scripts/check_aa_manifest_audiobook_import.py
python scripts/check_audiobook_multibook_ordering.py
python scripts/check_audiobook_progress_reset.py
python scripts/check_bm_radio_safe_roots.py
python scripts/check_frontend_mojibake.py

cd ../frontend
npm run build
npm run lint
```

Environment-dependent checks are reported by the gate as skipped:

```text
check_imported_metadata_mojibake.py
check_station_genre_families_m5_1.py
check_station_logic_m5.py
check_station_logic_m5_2.py
```

## Results Recorded During BM-PROD0

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS | Unified gate: 9 mandatory passed, 0 failed, 4 integration checks skipped. |
| `python -m compileall app scripts` | PASS | Backend app and scripts compiled. |
| `python scripts/check_aa_manifest_music_import.py` | PASS | `ok: AA music manifest import` |
| `python scripts/check_aa_manifest_audiobook_import.py` | PASS | `ok: AA audiobook manifest import` |
| `python scripts/check_audiobook_multibook_ordering.py` | PASS | `Audiobook multi-book ordering checks passed.` |
| `python scripts/check_audiobook_progress_reset.py` | PASS | `ok: audiobook progress reset` |
| `python scripts/check_bm_radio_safe_roots.py` | PASS | `ok: BM Radio safe roots` |
| `python scripts/check_frontend_mojibake.py` | PASS | `ok: no frontend mojibake tokens` |
| `npm run build` | PASS | TypeScript and Vite production build completed. |
| `npm run lint` | PASS | 0 errors, 8 warnings. |
| `check_imported_metadata_mojibake.py` | SKIP | Active local database integration check. |
| `check_station_genre_families_m5_1.py` | SKIP | Personal populated library/profile integration check. |
| `check_station_logic_m5.py` | SKIP | Personal populated library/profile integration check. |
| `check_station_logic_m5_2.py` | SKIP | Personal populated library/profile integration check. |

Codex environment note: the sandboxed Python child process hit a Windows `spawn EPERM` inside Vite config loading. The same unified runner passed when rerun outside that sandbox restriction, and direct `npm run build` also passed.

Frontend lint warning summary:

- 6 React hook dependency warnings.
- 2 React fast-refresh `only-export-components` warnings.
- 0 lint errors.

## Clean Checkout Limitations

The following checks cannot be mandatory for a clean checkout because they use the active configured database or assume Bonny's populated local library/profile state:

- `check_imported_metadata_mojibake.py`
- `check_station_genre_families_m5_1.py`
- `check_station_logic_m5.py`
- `check_station_logic_m5_2.py`

They are preserved as integration checks to run manually when the expected local database/library state exists.

## BM-PROD0 Behavior Statement

BM-PROD0 intentionally made no production behavior change. Runtime application code, scanner behavior, station logic, schema design, configuration behavior, and frontend behavior were not changed.
