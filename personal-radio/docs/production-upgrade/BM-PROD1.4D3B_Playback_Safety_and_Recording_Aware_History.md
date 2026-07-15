# BM-PROD1.4D3B - Playback Safety and Recording-Aware History

Starting commit: `f81fb2e39552ba5e4dc3320dc79cc1ec44810bce`
Ending state: working tree implementation for BM-PROD1.4D3B; no commit created by Codex.

## Files Changed

- `backend/app/models.py`
- `backend/app/schema_maintenance.py`
- `backend/app/main.py`
- `backend/app/music_playback_policy.py`
- `backend/app/routes/playback.py`
- `backend/app/routes/media.py`
- `backend/scripts/check_prod1_4d3b_playback_recording_identity.py`
- `scripts/check_prod0_baseline.py`
- `docs/production-upgrade/BM-PROD1.4D3B_Playback_Safety_and_Recording_Aware_History.md`

## Implementation

D3B adds nullable `PlaybackEvent.recording_id` so new identity-backed music playback events store both the actual physical `track_id` and the logical `MusicRecording` identity. Audiobook and identity-less legacy music events keep `recording_id = null`.

Existing SQLite databases are handled by `ensure_playback_identity_columns(engine)`. The maintenance is SQLite-only, additive, idempotent, preserves all existing `playback_events` rows, adds `playback_events.recording_id`, and creates `ix_playback_events_recording_id`. It is registered during startup after `Base.metadata.create_all()`.

`music_playback_policy.py` centralizes music playback identity derivation, participation-state checks, recording-aware qualified-listen dedupe, and recent music projection. Stream and event routes both use this helper so blocked playback policy has one owner.

D3B blocks audio streaming and music playback-event registration only for `participation_state = blocked`. Included and library_only recordings remain playable. Archived recordings remain directly addressable by physical track URL for future operator/archive inspection, while normal listener library and queue routes continue to hide them.

D3B does not redirect direct physical Track stream requests to the preferred source. Normal listener library and queue routes remain responsible for selecting the preferred source. Direct `/api/media/tracks/{track_id}/stream` serves the requested physical source when it is available, approved, supported, and not blocked by recording participation.

Qualified music listen suppression is Recording-aware for identity-backed media. Legacy null-recording qualified events can still suppress a new duplicate when their physical `track_id` belongs to the same MusicRecording. Identity-less tracks retain exact physical-track dedupe.

Recent music playback is Recording-aware. It dedupes by `MusicRecording`, hides archived and blocked recordings, keeps included and library_only visible, and replays through the current effective source while preserving `played_track_id` as historical source evidence. A historical unavailable source remains visible when the recording has another current source; recordings with no current available source are hidden. Ambiguous source cases use read-only deterministic fallback and do not persist a false winner during GET.

Recent audiobook behavior is preserved and does not receive music recording fields.

D3B does not migrate `TrackFavorite` or `TrackThumb` semantics. D3B does not change station generation.

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

The real BM Radio database remained empty.

## Validation

Targeted D3B regression covers fresh schema, existing SQLite additive migration, recording identity persistence, automatic qualified playback identity, recording-level qualified dedupe, legacy null-recording compatibility, identity-less fallback, blocked stream/event rejection, included/library_only/archived playback, direct alternate-source behavior, recent recording projection, current effective-source replay, user override, ambiguous read-only fallback, unavailable historical source fallback, no-source hiding, participation visibility, same-recording cross-release dedupe, live/studio separation, identity-less recent fallback, audiobook preservation, query bounding, read-only GET behavior, no favorite/thumb migration, no station changes, and no media mutation.

Additional validation run during completion:

- D3A listener queue and playlist source resolution
- D2.1 listener projection scale stabilization
- D2 listener library and search projection
- D1 recording control API
- C2 scanner preference reevaluation
- C1 preferred source policy
- B1 technical profile
- A2 scanner identity integration
- A1 music identity graph
- D1 availability policy
- D2 active playback candidates
- D3 integrity reporting
- music scan reconciliation
- audiobook scan progress and reconciliation regressions
- backend compileall
- frontend production build
- frontend lint
- full production gate
- `git diff --check`

## Deferred Work

- Recording-level favorite semantics
- Recording-level thumb/feedback semantics
- smart collection/history aggregation by Recording
- recording-first station engine
- live/acoustic/remix station affinity
- frontend curation/source controls
- release/edition-family refinement
- scanner full-table startup-map scaling
- controlled real-media canary after preference pipeline completion
