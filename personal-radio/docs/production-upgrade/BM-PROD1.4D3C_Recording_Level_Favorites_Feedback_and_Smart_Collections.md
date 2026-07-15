# BM-PROD1.4D3C - Recording-Level Favorites, Feedback, and Smart Collections

Starting commit: `06b9b743f5bc37238b1dca207d656ccf5c63b242`
Ending state: working tree implementation for BM-PROD1.4D3C; no commit created by Codex.

## Files Changed

- `backend/app/models.py`
- `backend/app/schema_maintenance.py`
- `backend/app/main.py`
- `backend/app/music_recording_feedback.py`
- `backend/app/routes/playback.py`
- `backend/app/routes/playlists.py`
- `backend/app/routes/queue.py`
- `backend/scripts/check_prod1_4d3b_playback_recording_identity.py`
- `backend/scripts/check_prod1_4d3c_recording_feedback_and_smart_collections.py`
- `scripts/check_prod0_baseline.py`
- `docs/production-upgrade/BM-PROD1.4D3C_Recording_Level_Favorites_Feedback_and_Smart_Collections.md`

## Implementation

D3C makes identity-backed favorites and thumbs/feedback apply to `MusicRecording` rather than one physical Track source. `TrackFavorite.track_id` and `TrackThumb.track_id` remain physical source/context evidence. New identity-backed favorite/thumb rows also store `recording_id`.

Existing SQLite databases are handled by `ensure_recording_feedback_columns(engine)`. The maintenance is SQLite-only, additive, idempotent, preserves existing rows, adds nullable `recording_id` columns to `track_favorites` and `track_thumbs`, and creates `ix_track_favorites_recording_id` and `ix_track_thumbs_recording_id`. No startup backfill is performed.

Legacy rows with `recording_id = null` remain supported through current `Track -> MusicTrackIdentity` resolution. Identity-less tracks keep exact physical Track fallback behavior.

Favorite state is effective at Recording level. Favoriting one physical source makes every source for that Recording read as favorite. Toggling or explicitly unfavoriting from another source clears explicit Recording rows and legacy null-recording rows that currently map to that Recording.

Feedback state is effective at Recording level. The latest feedback event across explicit Recording rows and legacy null-recording rows determines current `up` or `down` state. `neutral` clears the targeted Recording's feedback state. `station_id`, physical `track_id`, and event history are preserved on new feedback rows.

Changing preferred physical source does not change favorite or feedback state. Favorite/feedback writes do not mutate participation or source preference rows.

Smart music collections aggregate identity-backed media at `MusicRecording` level and return the current effective physical source. Favorites, thumbs-up, most-played, recently-played, recently-added, and never-played all collapse physical variants before queue projection.

Recently Added uses logical Recording first appearance, based on the earliest linked Track creation time, so adding a new physical source does not re-bump an old Recording. Never Played considers qualified playback of any physical source belonging to the Recording, including legacy null-recording playback events that currently map through Track identity.

Smart collection participation mapping is preserved:

- Favorites, thumbs-up, most-played, and recently-played allow included and library_only Recordings.
- Recently-added and never-played allow included Recordings only.
- Archived and blocked Recordings are excluded from active smart collections.

Smart count paths use count-specific SQL or bounded logical candidate paths instead of materializing 100,000 physical track rows. Smart candidate projection uses the existing batch read-only effective-source resolver rather than one resolver call per Recording.

D3C does not change station generation, station candidate weighting, or `Station.favorite` semantics.

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

The real BM Radio database remained empty.

## Validation

Targeted D3C regression covers fresh schema, existing SQLite migration, cross-source favorites, preference independence, toggle/unfavorite semantics, legacy favorite compatibility, identity-less favorite fallback, cross-source feedback, latest feedback ordering, neutral clear, station context preservation, identity-less feedback fallback, smart favorites/thumbs-up/history/discovery collections, current effective-source projection, participation filtering, no-source omission, logical smart counts, query/materialization guards, batch source resolution, route response compatibility, participation/source-preference independence, station boundary, and media mutation scope.

Additional validation run during completion:

- D3B playback safety and recording-aware history
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

- recording-first station engine
- station feedback consumption by Recording
- live/acoustic/remix station affinity
- frontend curation/source controls
- release/edition-family refinement
- scanner full-table startup-map scaling
- controlled real-media canary after station/preference integration