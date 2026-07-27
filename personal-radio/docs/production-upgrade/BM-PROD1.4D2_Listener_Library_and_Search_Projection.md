# BM-PROD1.4D2 - Listener Library and Search Projection

Starting commit: `2009e263a5601d90980fe1c98190b3a74e41ce61`
Ending state: working tree implementation pending commit

## Summary

D2 changes normal music library/search presentation from physical Track rows to visible MusicRelease+MusicRecording occurrences.

The real BM Radio database remained empty.

D2 preserves the same MusicRecording across different MusicRelease contexts. D2 collapses multiple physical sources and Editions only within the same Release+Recording listener occurrence.

## Listener Occurrence Identity

The listener-facing unit is:

```text
(MusicRelease.id, MusicRecording.id)
```

This keeps an album occurrence and single occurrence visible separately even when they share the same `MusicRecording`. It also keeps distinct live/acoustic/remix Recording identities separate.

## Participation Visibility

Normal library/search visibility now uses sparse `MusicRecordingParticipation` state:

- `included`: visible
- `library_only`: visible
- `archived`: hidden
- `blocked`: hidden
- no row: visible as implicit `included`

Reads do not materialize participation rows.

## Active Occurrence Eligibility

A Release+Recording occurrence is visible only when at least one Track in that same release occurrence is currently available. A source available in another release for the same Recording does not keep an unavailable release occurrence visible.

## Presentation Context And Effective Source

Projected items preserve release context for display:

- title/artist/album/year/track number/disc number/genre from the presentation occurrence
- cover URL from `presentation_track_id`

Projected items use the effective physical source for playback compatibility:

- `id = effective_track_id`
- `stream_url = /api/media/tracks/{effective_track_id}/stream`
- file/source availability fields from the effective Track

The response adds:

- `recording_id`
- `release_id`
- `edition_id`
- `presentation_track_id`
- `effective_track_id`
- `participation_state`
- `source_resolution`
- `source_confidence`
- `source_reason_code`

Existing Track response fields remain present.

## Read-Only Batch Source Resolver

`resolve_effective_music_sources_read_only()` batches candidate, technical-profile, and preference loading for many Recordings. It reuses the C1 policy in memory for missing preference rows and does not insert or update preference rows during normal GET library/search reads.

D2 does not use the legacy extension-based `release_preferences.py` heuristic as authority.

## Route Semantics

Updated normal music projection routes:

- `/api/library/summary`
- `/api/library/tracks`
- `/api/library/tracks-page`
- `/api/library/artists`
- `/api/library/artists-page`
- `/api/library/artists/{artist}/detail`
- `/api/library/artists/{artist}/tracks`
- `/api/library/artists/{artist}/albums`
- `/api/library/albums`
- `/api/library/albums-page`
- `/api/library/recent-albums`
- `/api/library/search`
- `/api/library/album-tracks`
- `/api/search` music sections

Audiobook search behavior is preserved.

## Album Track Migration Path

`/api/library/album-tracks` now accepts authoritative `release_id`:

```text
/api/library/album-tracks?release_id=123
```

The legacy `artist` + `album` path remains for frontend compatibility. When strings match multiple visible MusicRelease rows, D2 selects one deterministic recent release rather than silently merging multiple release identities.

## Query And Pagination Strategy

D2 uses a windowed occurrence-key query for `(release_id, recording_id)` projection, then batch-loads presentation context and batch-resolves effective physical sources. Pagination and `/tracks-page total` operate on listener occurrences rather than physical Track rows.

Regression coverage includes bounded SELECT behavior for 100 listener occurrences and 100 search results.

## Temporary Boundary

D2 does not yet change queue, playlist, station, playback-event, media-stream enforcement, scanner behavior, or frontend behavior.

The known temporary mismatch is:

```text
library/search may display one curated occurrence
album/artist/station queue generation may still use legacy Track-centric logic
```

This is reserved for the next dedicated queue/playback integration task.

## Media Mutation Boundary

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/listener_library.py`
- `personal-radio/backend/app/music_source_preference.py`
- `personal-radio/backend/app/routes/library.py`
- `personal-radio/backend/app/routes/search.py`
- `personal-radio/backend/scripts/check_prod1_4d2_listener_library_projection.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.4D2_Listener_Library_and_Search_Projection.md`

## Validation

Targeted D2 regression:

```text
PASS: BM-PROD1.4D2 listener library and search projection
```

Full gate result after D2:

```text
27 mandatory passed
0 failed
4 skipped
```