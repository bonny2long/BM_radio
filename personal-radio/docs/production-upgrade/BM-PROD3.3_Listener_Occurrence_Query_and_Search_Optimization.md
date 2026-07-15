# BM-PROD3.3 Listener Occurrence Query and Search Optimization

Date: 2026-07-15
Starting commit: f56dbf267d3fa1821c57c672e393338f126bf2c7
Ending state: working tree after BM-PROD3.3 implementation

## Scope

BM-PROD3.3 preserves `MusicRelease + MusicRecording` listener occurrence identity while replacing the full physical-Track `row_number()` window projection used as the main occurrence collapse for listener page/search/aggregate queries.

The real BM Radio database remained empty. No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

No listener identity, source-preference, participation, queue, playback, feedback, station, version-affinity, scanner, or frontend behavior changed.

## Files Changed

- `backend/app/listener_library.py`
- `backend/scripts/check_prod3_3_listener_occurrence_query_optimization.py`
- `scripts/check_prod0_baseline.py`
- `docs/production-upgrade/BM-PROD3.3_Listener_Occurrence_Query_and_Search_Optimization.md`

## Old Projection

The prior identity-backed listener path built one physical Track row projection with:

```text
row_number() over (
  partition by release_id, recording_id
  order by presentation Track fields
)
```

Then normal pages, counts, search, summary, artist aggregates, and album aggregates consumed that physical-row window projection. `listener_tracks_page()` also always ran a separate occurrence count query plus a separate page query.

## New Projection

The optimized path uses `_grouped_occurrence_query()` to group available, visible physical sources into logical occurrence keys first:

```text
MusicEdition.release_id + MusicTrackIdentity.recording_id
```

Filtering, grouping, ordering, and paging happen at logical occurrence level. `occurrence_page()` returns page keys and total with `COUNT(*) OVER ()` over grouped occurrence rows. A fallback count is used only for beyond-end offsets.

Presentation Track selection is bounded to requested occurrence keys through `presentation_tracks_for_occurrences()`. Exact Release/Recording pair filters use OR-of-pairs chunks, avoiding release/recording cross-product leaks. Selection order remains:

```text
available first
known disc before null
known track before null
relative_path
Track.id
```

Serialization and read-only effective-source resolution remain unchanged and bounded to the page/search occurrence set.

## Search And Aggregates

Search still covers the existing fields:

- `MusicRecording.title`
- `MusicRecording.artist`
- `MusicRelease.title`
- `MusicRelease.album_artist`
- `Track.genre`
- `Track.primary_genre`
- `Track.relative_path`
- `Track.title`
- `Track.artist`
- `Track.album`
- `Track.album_artist`

Matching physical variants are deduped by grouped occurrence identity. Summary, artist, album, recent album, album-track, and global-search helpers consume the grouped logical occurrence projection and preserve existing response shapes.

## Index Decision

No schema or index changes were added. The grouped projection and bounded presentation selection produced meaningful same-machine benchmark improvement without adding speculative indexes.

## Benchmark Results

Committed BM-PROD3.1 50K baseline:

| Operation | Median ms |
| --- | ---: |
| library.search.broad | 2,722.7 |
| library.tracks.first | 2,322.5 |
| library.albums.first | 2,206.8 |
| library.tracks.deep | 2,203.0 |

Same-machine BM-PROD3.2 benchmark JSON retained from the prior task:

| Operation | Median ms | SELECTs | Peak MiB | Checksum |
| --- | ---: | ---: | ---: | --- |
| library.tracks.first | 1,485.703 | 8 | 1.416 | `281b8bc0baab49fa` |
| library.tracks.deep | 1,246.665 | 8 | 0.721 | `7249d78df8c5bffa` |
| library.albums.first | 869.211 | 2 | 0.262 | `e0de4fddc547995f` |
| library.search.broad | 2,192.531 | 11 | 1.374 | `03983a7358ad8793` |

BM-PROD3.3 50K result:

| Operation | Median ms | SELECTs | Peak MiB | Checksum |
| --- | ---: | ---: | ---: | --- |
| library.tracks.first | 786.345 | 7 | 0.557 | `281b8bc0baab49fa` |
| library.tracks.deep | 848.785 | 7 | 0.567 | `7249d78df8c5bffa` |
| library.albums.first | 654.607 | 2 | 0.148 | `e0de4fddc547995f` |
| library.search.broad | 1,949.312 | 12 | 1.064 | `03983a7358ad8793` |

BM-PROD3.3 1K and 10K result highlights:

| Size | Operation | Median ms | SELECTs | Peak MiB |
| --- | --- | ---: | ---: | ---: |
| 1K | library.tracks.first | 59.753 | 7 | 0.593 |
| 1K | library.albums.first | 22.733 | 2 | 0.159 |
| 1K | library.search.broad | 189.517 | 12 | 1.037 |
| 10K | library.tracks.first | 187.946 | 7 | 0.557 |
| 10K | library.albums.first | 139.909 | 2 | 0.143 |
| 10K | library.search.broad | 506.861 | 12 | 1.070 |

100K listener-only attempt completed:

| Operation | Median ms | SELECTs | Peak MiB |
| --- | ---: | ---: | ---: |
| library.tracks.first | 1,550.002 | 7 | 1.523 |
| library.tracks.deep | 1,708.409 | 7 | 0.608 |
| library.albums.first | 1,292.286 | 2 | 0.270 |
| library.search.broad | 4,280.298 | 12 | 1.925 |

Benchmark outputs:

- `backend/tmp_tests/perf/prod3_3_listener_1k_10k_50k.json`
- `backend/tmp_tests/perf/prod3_3_listener_100k.json`

## Remaining Hot Path

The remaining 50K/100K listener cost is the grouped occurrence scan and substring search over Track-backed fields. Deep offset remains offset-based by design for this task. Full-text search and cursor/keyset pagination remain deferred until later measurement justifies them.

## Validation

Passed:

- `python scripts/check_prod3_3_listener_occurrence_query_optimization.py`
- `python scripts/check_prod1_4d2_listener_library_projection.py`
- `python scripts/check_prod1_4d2_1_listener_projection_scale.py`
- `python scripts/check_prod3_1_scale_benchmark_harness.py`
- `python -m compileall app`

Final validation passed:

- `python scripts/check_prod0_baseline.py` - 37 mandatory passed, 0 failed, 4 skipped
- `python -m compileall app scripts`
- `frontend npm run build`
- `frontend npm run lint` - 0 errors, 8 existing warnings
- `git diff --check`