# BM-PROD1.4D3A - Listener Queue and Playlist Source Resolution

Starting commit: `2a49deff60b86314a25ed430ccc6cf2d25554c96`
Ending state: working tree implementation pending commit

## Summary

D3A makes finite non-station music queues use listener occurrences and current effective physical sources.

The real BM Radio database remained empty.

## Queue Occurrence Identity

Finite album, artist, manual playlist, and smart playlist queue items now project through:

```text
MusicRelease.id + MusicRecording.id
```

The physical source that plays remains the effective Track from `MusicRecordingPreference` resolution.

Same physical-source variants within one Release+Recording collapse in active playlist detail/queue. The same MusicRecording in different MusicRelease contexts may remain separately represented.

## Participation Rules

- Explicit album queue: `included`, `library_only`
- Explicit artist play: `included`, `library_only`
- Shuffle artist: `included` only
- Manual playlist detail/queue: `included`, `library_only`
- Smart user-state/history queues (`favorites`, `thumbs_up`, `most_played`, `recently_played`): `included`, `library_only`
- Smart discovery queues (`recently_added`, `never_played`): `included` only

Archived and blocked Recordings are hidden from active finite queue and playlist projection.

## Album Queue Contract

`POST /api/queue/album` accepts optional `release_id`. When present, `release_id` is authoritative. Legacy `artist` + `album` compatibility remains and follows the existing deterministic single-release selection behavior rather than merging multiple same-title releases.

## Playlist Anchor Semantics

Manual `PlaylistTrack.track_id` remains the durable membership anchor and is not rewritten when source preference changes.

At read/queue time, stored physical anchors are mapped to Release+Recording occurrences and current effective physical sources. This means playlist detail and playlist queue can play a preferred FLAC source while the membership row still stores an older MP3 anchor.

Add/remove/reorder now resolve physical Track IDs to occurrence identity when available:

- Adding a second physical source for the same Release+Recording is deduped.
- Removing by current effective Track removes the stored occurrence anchor.
- Reordering by effective Track IDs maps back to stored occurrence anchors.
- Hidden archived/blocked membership rows remain stored and are placed after visible rows when reorder input omits them.

## Smart Playlists

Smart playlist queue generation keeps existing physical candidate sources, then projects those candidate Track IDs through listener occurrence/effective-source rules. Active smart-playlist queue code no longer depends on `release_preferences.choose_preferred_tracks()`.

## Boundaries

D3A does not change station generation, playback-event identity, media-stream enforcement, scanner behavior, or frontend behavior.

Known temporary boundary:

```text
finite queues now project preferred effective sources
but direct low-level physical Track URLs/events are not yet participation-enforced
```

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/listener_queue.py`
- `personal-radio/backend/app/queue_contracts.py`
- `personal-radio/backend/app/routes/queue.py`
- `personal-radio/backend/app/routes/playlists.py`
- `personal-radio/backend/scripts/check_prod1_4d3a_listener_queue_and_playlist_projection.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.4D3A_Listener_Queue_and_Playlist_Source_Resolution.md`

## Validation

Targeted D3A regression:

```text
PASS: BM-PROD1.4D3A listener queue and playlist source resolution
```

Full gate result after D3A:

```text
29 mandatory passed
0 failed
4 skipped
```