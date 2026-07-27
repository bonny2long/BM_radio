# BM-PROD1.4A1 - Music Identity Graph Foundation

Owner: Bonny Makaniankhondo
Date: 2026-07-14
Status: PASS

## Scope

BM-PROD1.4A1 adds an additive, first-class music identity graph for Release, Edition, Recording, and physical Track linkage. It does not change scanning, station generation, playback resolution, frontend behavior, or source preference selection.

## Starting Point

- Starting SHA: `dad12f9657a5c31d90ae0df4c56146d732fdf8d8`
- Ending state: working tree contains A1 implementation and regression checks.
- Real application database: `personal-radio/backend/bm_radio.db`
- Real DB population: not performed.
- Real DB read-only census: all existing media and user-state tables remained at 0 rows.

## Identity Graph Model

- `MusicRelease` is the logical release family. It uses a conservative identity key based on normalized album artist and full release title. Weak or generic metadata adds a deterministic source-scope disambiguator to avoid unsafe global grouping.
- `MusicEdition` is one concrete archived source/edition. It belongs to one `MusicRelease` and is keyed by release identity plus normalized source directory scope derived from Track path strings.
- `MusicRecording` is the song/performance identity future radio logic can select before resolving a physical source. It is keyed by normalized artist, normalized title, explicit recording type, and duration bucket, with extra disambiguation for weak metadata.
- `MusicTrackIdentity` links one physical `Track` to one `MusicEdition` and one `MusicRecording`. It does not duplicate `release_id`; the release relationship is through `MusicEdition.release_id`.
- `Track.id` and `Track.path` remain the durable physical-file identity.

## Semantics

- Release grouping is intentionally conservative. A1 does not strip Deluxe, Anniversary, Remaster, Japan, Live, or similar edition markers from release titles.
- Edition source scope is derived from `Track.relative_path` parent directory with fallback to `Track.path`, normalizing separators without resolving or touching the filesystem.
- Source format family is descriptive only: FLAC, MP3, M4A, AAC, OGG, OPUS, WAV, or UNKNOWN. A1 does not score quality.
- Recording type inference is explicit only: live, acoustic, remix, instrumental, and radio_edit. Absence of a marker remains `unknown`, not studio.
- Unknown/generic artist, album, or title values cannot collapse unrelated Tracks into one unsafe release or recording identity.
- Same recording occurrences across album, single, and edition contexts can share one `MusicRecording` when artist/title/type/duration evidence is compatible.
- Explicit live/acoustic/remix/instrumental/radio-edit versions remain separate recordings.

## Materialization Behavior

- `materialize_music_identity_for_track(db, track)` derives or reuses Release, Edition, and Recording rows, then creates or updates one current `MusicTrackIdentity` for the Track.
- `materialize_music_identity_graph(db, track_ids=None)` provides a bounded future backfill entry point.
- Materialization is idempotent. Re-running it does not duplicate releases, editions, recordings, or track links.
- Unavailable Tracks are materialized because availability is orthogonal to identity.
- Metadata rebinding updates the Track's current identity link while preserving the Track row and all user state.
- A1 does not prune now-orphaned identity nodes.
- A1 does not run automatically at startup or during scanner execution.

## Existing DB Compatibility

The graph is additive. `Base.metadata.create_all()` creates the new tables on an existing SQLite database without dropping or rebuilding current Track, playlist, favorite, thumb, playback, station, audiobook, or scan tables.

## Non-Goals Confirmed

- The real BM Radio database remained empty.
- A1 does not score quality.
- A1 does not select a preferred edition or Track.
- A1 does not change station logic.
- A1 does not change current scanner duplicate behavior.
- A1 does not change frontend UI.
- No archive media file was read, written, moved, renamed, retagged, or deleted by the identity materializer.

## Files Changed

- `personal-radio/backend/app/models.py`
- `personal-radio/backend/app/media_identity.py`
- `personal-radio/backend/app/music_identity_graph.py`
- `personal-radio/backend/scripts/check_prod1_4a1_music_identity_graph.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.4A1_Music_Identity_Graph_Foundation.md`

## Verification

- Targeted A1 regression: PASS
  - `cd personal-radio/backend; python scripts/check_prod1_4a1_music_identity_graph.py`
- D1 regression: PASS
  - `python scripts/check_prod1_3d1_core_availability_policy.py`
- D2 regression: PASS
  - `python scripts/check_prod1_3d2_active_playback_candidates.py`
- D3 regression: PASS
  - `python scripts/check_prod1_3d3_integrity_reporting.py`
- Music reconciliation regression: PASS
  - `python scripts/check_prod1_3b_music_scan_reconciliation.py`
- Audiobook C1 regression: PASS
  - `python scripts/check_prod1_3c1_audiobook_scan_progress_safety.py`
- Audiobook C2 regression: PASS
  - `python scripts/check_prod1_3c2_audiobook_reconciliation.py`
- Existing audiobook checks: PASS
  - `python scripts/check_aa_manifest_audiobook_import.py`
  - `python scripts/check_audiobook_multibook_ordering.py`
  - `python scripts/check_audiobook_progress_reset.py`
- Backend compile: PASS
  - `python -m compileall app scripts`
- Frontend build: PASS
  - `npm run build`
- Frontend lint: PASS, 0 errors, 8 existing warnings
  - `npm run lint`
- Full production gate: PASS, 21 mandatory passed, 0 failed, 4 skipped
  - `python scripts/check_prod0_baseline.py`
- Diff quality: PASS
  - `git diff --check`

## Deferred Work

- BM-PROD1.4A2 scanner integration and physical-source preservation.
- BM-PROD1.4B objective technical quality signal extraction.
- BM-PROD1.4C automatic preferred-source resolution and manual override foundation.
- BM-PROD1.4D library/UI/playback integration.
- BM-PROD1.5 recording-first station-engine review and live/acoustic/remix affinity.
- BM-PROD3/BM-PROD4 large-library and station performance.
- Controlled real-media canary after the preference pipeline is ready.