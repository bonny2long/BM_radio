# BM-PROD1.4D2.1 - Listener Projection Scale Stabilization

Starting commit: `9e0cb76e36b008ca5007c98e17da95a784acbda3`
Ending state: working tree implementation pending commit

## Summary

D2.1 preserves all D2 listener identity and participation semantics while fixing unbounded Python materialization in summary, artist, album, recent-album, artist-album, and global artist-search paths.

The real BM Radio database remained empty.

## Unbounded D2 Paths Found

The D2 implementation already paginated track/search listener occurrences at SQL occurrence-key level, but these aggregate paths still loaded too much into Python:

- `listener_summary()` loaded all occurrence keys.
- `listener_artists()` loaded all occurrence keys and paged afterward.
- `listener_albums()` serialized every visible occurrence before grouping releases.
- `listener_artist_albums()` loaded all albums and filtered afterward.
- `global_music_search()` loaded all artists and filtered afterward.

## SQL Aggregation

D2.1 adds focused SQL aggregate helpers in `listener_library.py`:

- visible occurrence subquery
- artist aggregate query
- release aggregate query
- release row serializer

`listener_summary()` now computes tracks, distinct artists, and distinct releases through SQL aggregation.

`listener_artists()` now groups by display artist in SQL and applies order, offset, and limit before loading rows.

Global artist search now passes the search term and limit into the SQL artist aggregate path.

## Release Aggregation

`listener_albums()` now groups by `MusicRelease` in SQL and computes:

- `release_id`
- `release_type`
- display title
- display artist
- year
- occurrence track count
- deterministic presentation Track ID for cover context
- recent ordering keys

Album page pagination applies at release level before rows are materialized.

Recent albums apply SQL ordering and limit before materialization.

Artist albums are filtered through the release aggregate query instead of loading the full album catalog.

## Representative Cover Context

Album cover URLs use a deterministic visible presentation Track ID from the release aggregate. No effective playback-source resolution is needed to build album summaries.

## Semantics Preserved

D2.1 preserves:

- `(MusicRelease.id, MusicRecording.id)` listener occurrence identity
- same Recording across releases as separate occurrences
- multiple physical sources in the same occurrence collapsed to one
- included and library_only visible
- archived and blocked hidden
- unavailable-only occurrences hidden
- read-only GET behavior
- response compatibility

D2.1 does not change queue, playlist, station, playback, media-streaming, scanner, or frontend behavior.

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Materialization Guards

The targeted regression monkeypatches unbounded materializers for summary, artist, album, recent-album, and artist-album paths. Static source checks also verify aggregate paths do not call unbounded `occurrence_keys(db)` or `serialize_occurrences()` patterns.

## Files Changed

- `personal-radio/backend/app/listener_library.py`
- `personal-radio/backend/scripts/check_prod1_4d2_1_listener_projection_scale.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.4D2.1_Listener_Projection_Scale_Stabilization.md`

## Validation

Targeted D2.1 regression:

```text
PASS: BM-PROD1.4D2.1 listener projection scale stabilization
```

Full gate result after D2.1:

```text
28 mandatory passed
0 failed
4 skipped
```