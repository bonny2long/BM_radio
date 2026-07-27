# BM-PROD1.3D2 Active Queues, Stations, Playlists, and Playback

Owner: Bonny Makaniankhondo
Project: BM Radio Production Upgrade
Date: 2026-07-14
Scope: Active availability policy for queues, stations, playlists, smart collections, playback-event writes, and recent playback

## Baseline

| Item | Value |
| --- | --- |
| Starting commit | `82c61c234714bf4ad22c58151e6149662e7f20b6` |
| Starting worktree | BM-PROD1.3D1 already present in the branch state |
| Ending state | Pending working-tree changes |

Pre-change D2 gate output:

```text
python scripts/check_prod0_baseline.py
BM-PROD0 BASELINE GATE: PASS
Mandatory: 17 passed, 0 failed
Optional/integration: 4 skipped
```

The command printed the complete PASS summary but the shell call timed out immediately after output capture.

## Real Database Safety

No real scan, canary, or application data population was performed.

Read-only inspection of `personal-radio/backend/bm_radio.db` after validation:

```text
tracks: 0
audiobooks: 0
audiobook_chapters: 0
scan_runs: table missing
playback_events: 0
playlists: 0
playlist_tracks: 0
```

## Queue Policy

Album, artist, manual playlist, smart playlist, and station queues now select currently available Tracks only.

`queue_payloads.payload()` also defensively omits unavailable Tracks at the shared queue serialization boundary. Query-level filtering remains the primary protection.

## Manual Playlist Policy

Manual playlist membership remains durable user state.

Default playlist summary, detail, and queue output now represent active playable Tracks only. `PlaylistTrack` rows are not deleted when a linked Track becomes unavailable. When the same Track row becomes available again, the stored membership and position make it reappear automatically.

Adding a known unavailable Track to a playlist returns HTTP 409 with the shared Track unavailable message.

`create_from_track_list` validates known Track IDs before creating the Playlist row or membership rows, so an unavailable Track conflict leaves no partial playlist side effect. Unknown Track IDs retain the previous compatibility behavior and are skipped.

## Smart Playlist Policy

Favorites, Thumbs Up, Most Played, Recently Played, Recently Added, and Never Played now derive active IDs from available Tracks only.

Smart counts and smart queue IDs use the same active policy. Favorite, thumb, and playback history rows remain stored and become active again automatically when the referenced Track becomes available.

Smart queue loading now bulk-loads the selected active Track IDs instead of resolving each Track with one `db.get()` call per ID.

## Station Policy

Station listing counts now use available Tracks only for total, artist, album_artist, genre, genre-family, Favorites Radio, Recently Added, Deep Cuts, and saved user station counts.

Artist station counts use unique Track IDs across `artist` and `album_artist` so a Track is not double-counted when both fields match the same seed.

Station candidate pools now start from active Track queries before existing caps and scoring. This applies to generic, favorites, recently added, deep cuts, genre, song radio, artist radio, related artist expansion, and debug candidate pools.

Unavailable song-radio seeds return HTTP 409 for station queue and station debug. Saved Station rows and favorite state remain app-owned state and are not deleted when active candidates disappear.

Station scaling remains bounded by existing caps and Python-side scoring. Full large-library station optimization is deferred.

## Playback Policy

Generic playback-event writes now validate media before inserting history.

Music events require the Track to exist and be currently available. Known unavailable Tracks return HTTP 409 and do not create normal or automatic `qualified_play` rows.

Audiobook events require the Audiobook to exist and be currently available. If a chapter is supplied, the chapter must exist, belong to the Audiobook, and be currently available. Wrong ownership returns 422. Known unavailable Audiobooks or Chapters return 409.

Mixed music/audiobook event payloads are rejected with 422.

## Recent Playback Policy

Recent playback remains a replay/resume surface and now returns active available media only.

Historical PlaybackEvent rows are preserved. The route over-fetches a bounded recent window and skips unavailable rows so unavailable recent history does not consume the visible limit.

For available Audiobooks, recent playback does not expose an unavailable chapter as an active resume target. Stored progress remains unchanged.

## Files Changed

```text
personal-radio/backend/app/availability.py
personal-radio/backend/app/queue_payloads.py
personal-radio/backend/app/routes/queue.py
personal-radio/backend/app/routes/playlists.py
personal-radio/backend/app/routes/stations.py
personal-radio/backend/app/routes/playback.py
personal-radio/backend/app/station_engine.py
personal-radio/backend/scripts/check_prod1_3d2_active_playback_candidates.py
personal-radio/scripts/check_prod0_baseline.py
personal-radio/docs/production-upgrade/BM-PROD1.3D2_Active_Queues_Stations_Playlists_and_Playback.md
```

## Tests Run

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS | Pre-change D2 baseline output: 17 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python scripts/check_prod1_3d2_active_playback_candidates.py` | PASS | Covers Cases A-Z with temp SQLite DB and temp fixture only. |
| `cd backend; python scripts/check_prod1_3d1_core_availability_policy.py` | PASS | D1 policy preserved. |
| `cd backend; python scripts/check_prod1_3b_music_scan_reconciliation.py` | PASS | Music reconciliation preserved. |
| `cd backend; python scripts/check_prod1_3c1_audiobook_scan_progress_safety.py` | PASS | Audiobook C1 preserved. |
| `cd backend; python scripts/check_prod1_3c2_audiobook_reconciliation.py` | PASS | Audiobook C2 preserved. |
| `cd backend; python scripts/check_aa_manifest_audiobook_import.py` | PASS | AA audiobook import preserved. |
| `cd backend; python scripts/check_audiobook_multibook_ordering.py` | PASS | Multi-book ordering preserved. |
| `cd backend; python scripts/check_audiobook_progress_reset.py` | PASS | Explicit reset behavior preserved. |
| `cd backend; python scripts/check_prod1_3a_scan_run_foundation.py` | PASS | Scan-run foundation preserved. |
| `cd backend; python scripts/check_prod1_2b_runtime_safety.py` | PASS | Runtime safety preserved. |
| `cd backend; python scripts/check_prod1_2a_config_contract.py` | PASS | Config contract preserved. |
| `cd backend; python scripts/check_prod1_1_canonical_music_roots.py` | PASS | Canonical root policy preserved. |
| `cd backend; python -m compileall app scripts` | PASS | Backend app and scripts compiled. |
| `cd frontend; npm run build` | PASS | Run outside sandbox due known Windows Vite `spawn EPERM`. |
| `cd frontend; npm run lint` | PASS | 0 errors, 8 existing baseline warnings. |
| `python scripts/check_prod0_baseline.py` | PASS | Full post-change gate: 18 mandatory passed, 0 failed, 4 skipped. |
| `git diff --check` | PASS | No whitespace errors. |

## Explicit Non-Goals

BM-PROD1.3D2 does not add integrity unavailable issue categories, scan-run history API, integrity frontend redesign, or operator diagnostics. That remains BM-PROD1.3D3.

BM-PROD1.3D2 does not delete Track, Audiobook, AudiobookChapter, PlaylistTrack, TrackFavorite, TrackThumb, PlaybackEvent, Station, AudiobookProgress, or other durable user-state rows.

BM-PROD1.3D2 does not delete, move, rename, retag, or rewrite archive media files.

BM-PROD1.3D2 does not implement full station-engine or scanner performance optimization.

BM-PROD1.3D2 does not populate the real BM Radio database or start the controlled real-media canary.