# BM-PROD1.5A - Recording-First Station Candidate Foundation

Owner: Bonny Makaniankhondo
Date: 2026-07-15
Starting commit: fd2e0eeee2cd07844f8e3c5270c9b621f6be1072
Ending state: working tree implementation for BM-PROD1.5A

## Summary

BM-PROD1.5A changes station candidate identity from physical `Track` to `MusicRecording` for identity-backed media. The station engine now selects the logical recording candidate first, and the playable physical source is supplied through the current source-preference resolver for that recording.

The real BM Radio database remained empty. Validation used temporary SQLite databases and synthetic identity/source/listener-state fixtures. No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/station_candidates.py`
- `personal-radio/backend/app/station_engine.py`
- `personal-radio/backend/app/queue_payloads.py`
- `personal-radio/backend/app/routes/stations.py`
- `personal-radio/backend/scripts/check_prod1_5a_recording_first_station_candidates.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.5A_Recording_First_Station_Candidate_Foundation.md`

## Candidate Identity

Old station behavior treated physical tracks as station candidates. This meant FLAC, MP3, and alternate physical copies could each occupy candidate slots and bias station frequency.

New station behavior uses `MusicRecording.id` as the station candidate identity for identity-backed media. Multiple physical source variants do not create multiple station candidates or consume multiple station candidate-cap slots. The same `MusicRecording` across different releases is one radio candidate.

Identity-less legacy tracks still remain available as exact physical fallback candidates when no `MusicTrackIdentity` row exists.

## Candidate Projection Contract

`StationRecordingCandidate` distinguishes:

- logical candidate identity: `recording_id` and `candidate_key`
- metadata/profile proxy: `profile_track`
- playable source: `effective_track`
- participation: `participation_state`
- version metadata: `recording_type`, `version_hint`
- source resolution: `source_resolution`, `source_confidence`, `source_reason_code`

Station payloads and debug rows expose recording/source fields while keeping compatible `track_id` behavior. For identity-backed rows, `track_id` is the effective playable track.

## Participation Rules

Automatic radio includes only `participation_state = included`. This applies to Song, Artist, Genre, Favorites, Recently Added, Deep Cuts, refill, listing counts, and debug candidate pools.

`library_only` remains manually playable but is excluded from automatic radio candidates. A `library_only` song may be an explicit Song Radio seed. `archived` and `blocked` recordings are rejected as Song Radio seeds with a stable client error.

Seed and current queue exclusions map physical `exclude_track_ids` to recording identity. If MP3 is queued or used as a seed, the FLAC copy of the same recording cannot reappear as a separate candidate.

## Listener Signals

Recording-level favorite, feedback, qualified-play count, and recent history are the station listener signals. Legacy null-recording feedback and playback events remain compatible by resolving `track_id` to the current recording identity where possible; identity-less fallback remains exact-track based.

Favorites Radio now uses effective recording favorites and current recording thumbs-up state. Recently Added uses the logical first appearance of a recording, so adding a newer source copy does not re-bump an old recording. Deep Cuts uses qualified recording play counts instead of physical all-event counts.

## Source Resolution

Physical source preference is resolved only after a `MusicRecording` is selected as the station candidate. The station engine no longer uses legacy `release_preferences.choose_preferred_tracks()` as source-selection authority, and it does not call `quality_rank()` or `rank_recording_variant()` for active station generation.

User override and automatic source preference can change the returned physical track without multiplying or changing the logical station candidate.

## Profile Proxy and Version Boundary

Current radio profile and genre scoring still use a deterministic `Track` profile proxy. Candidate identity remains the recording. Different source tracks do not become separate candidates because they carry different profile rows.

Distinct live/acoustic/remix/instrumental/radio-edit `MusicRecording` identities remain separate candidates. BM-PROD1.5A does not globally collapse distinct recordings by normalized title.

BM-PROD1.5A does not yet implement explicit live/acoustic/remix affinity ratios. That policy is deferred to BM-PROD1.5B.

## Station Counts and Debug

Station listing counts for Favorites, Recently Added, Deep Cuts, Artist, and Genre are based on automatic-radio-eligible logical recording candidates. Physical duplicates and excluded participation states do not inflate counts.

Station debug selected/rejected rows include `recording_id`, `recording_type`, `version_hint`, `effective_track_id`, `profile_track_id`, `participation_state`, `source_resolution`, `source_confidence`, and `source_reason_code`.

## Query and Read-Only Boundary

Candidate and signal loading are batched for recording candidates, participation, favorite/feedback state, qualified play counts, recent identities, and effective sources. The 1.5A regression includes a 100-recording/multi-source bounded-query assertion.

Normal station generation is read-only. It does not write `MusicRecordingPreference`, `MusicRecordingParticipation`, `TrackFavorite`, `TrackThumb`, or `PlaybackEvent`.

## Validation

Targeted regression:

```text
cd personal-radio/backend
python scripts/check_prod1_5a_recording_first_station_candidates.py
PASS: BM-PROD1.5A recording-first station candidate foundation
```

Dependency regressions run and passed:

```text
check_prod1_4d3c_recording_feedback_and_smart_collections.py
check_prod1_4d3b_playback_recording_identity.py
check_prod1_4d3a_listener_queue_and_playlist_projection.py
check_prod1_4d2_1_listener_projection_scale.py
check_prod1_4d2_listener_library_projection.py
check_prod1_4d1_recording_control_api.py
check_prod1_4c2_scanner_preference_reevaluation.py
check_prod1_4c1_preferred_source_policy.py
check_prod1_4b1_music_technical_profile.py
check_prod1_4a2_scanner_identity_integration.py
check_prod1_4a1_music_identity_graph.py
check_prod1_3d1_core_availability_policy.py
check_prod1_3d2_active_playback_candidates.py
check_prod1_3d3_integrity_reporting.py
check_prod1_3b_music_scan_reconciliation.py
check_prod1_3c1_audiobook_scan_progress_safety.py
check_prod1_3c2_audiobook_reconciliation.py
```

Existing personal-library station scripts were run separately. `check_station_logic_m5.py` and `check_station_logic_m5_2.py` reached the local application database but the local database schema is stale (`tracks.library_availability` is missing). `check_station_genre_families_m5_1.py` requires the missing optional `httpx` package. These scripts are not the synthetic production gate checks and did not populate the real database.

The permanent production gate is updated to include:

```text
backend/scripts/check_prod1_5a_recording_first_station_candidates.py
```

Full production gate result:

```text
python scripts/check_prod0_baseline.py
BM-PROD0 BASELINE GATE: PASS
Mandatory: 32 passed, 0 failed
Optional/integration: 4 skipped
```

## Deferred Work

- BM-PROD1.5B explicit live/acoustic/remix/instrumental affinity
- station seed/version-character controls
- frontend curation/source controls
- release/edition-family refinement
- scanner full-table startup-map scaling
- larger-library station retrieval/performance profiling
- controlled real-media canary after station identity and affinity work