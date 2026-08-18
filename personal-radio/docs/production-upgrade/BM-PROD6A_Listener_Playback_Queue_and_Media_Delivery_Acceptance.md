# BM-PROD6A Listener Playback, Queue, and Media Delivery Acceptance

Status: **LISTENER-PLAYBACK PASS — MEDIA POLICY CORRECTED BY PROD6C.1**

## Phase identity

- Starting SHA: `100d81e730ad24b58ec294a73e3bec061024cb0d`.
- Core implementation commit: `cd8add5c3de868f0872ed9786c3520a1243eedd5`.
- Final accepted phase commit: `387033a7cfad43ce42c9f8ba7fc0372c7b471b30`.
- The earlier live fixture evidence is superseded by the real-copied-media revalidation in BM-PROD6C.1.

## Corrected media boundary

All future PROD6A live acceptance requires `$PROD6C_COPIED_MEDIA_SOURCE` and the exact classification `copied_test_media=true`, `generated_by_acceptance_script=false`, and `original_only_copy=false`. If real copied media is unavailable, the harness blocks. It cannot create audio files.

The copied source and task copy are protected by exact SHA-256, size, and mtime snapshots before and after acceptance. Music, Audiobooks, and Books remain read-only inside the production backend container. The active PostgreSQL target, SQLite fallback, environment, and durable evidence remain protected.

## Playback architecture and acceptance

- `PlaybackContext.tsx` owns one `HTMLAudioElement`, one item reference, and one logical current item.
- Native play/pause events drive state. Pause/resume does not create a duplicate start.
- Seek and volume do not mutate the queue.
- Natural end advances exactly once; Next advances exactly once; Previous selects the prior queue item.
- A failed file produces a controlled message and no automatic retry or queue loop.
- Recording-first projections preserve logical queue identity across library, search, album, playlist, and effective-source resolution.
- Full streaming, byte ranges, invalid ranges, missing/restored files, and path-disclosure protection remain covered.
- Media routes close database sessions before file streaming begins. PROD6C.1 permanently proves more than the database pool limit of open range streams cannot exhaust the API.
- Playlist create/order/reorder/remove/delete and playback history identity remain covered.
- Refresh intentionally clears the in-memory listener session.

## Human result and correction linkage

The original PROD6A human listener result was PASS. BM-PROD6C.1 repeated real copied-track and audiobook playback through the production stack and received a new explicit human PASS. Its report records the observed music-transition and audiobook-start latency without requesting another behavior change.

Station recommendation quality is deferred to BM-PROD6B. TrueNAS work: prohibited and not performed.

## Permanent validation

- BM-PROD6A contract remains 40 checks.
- Player-state regression remains 13 checks.
- BM-PROD5.6B production-container contract now prohibits blocked remote CSS font imports.
- BM-PROD6C contract retains the copied-real-media and open-stream session-release guards without increasing the PROD0 check count.

**STOP: LISTENER-PLAYBACK PASS.**
