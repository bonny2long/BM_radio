# BM-PROD6A — Listener Playback, Queue, and Media Delivery Acceptance

Date: 2026-08-17  
Owner: Bonny Makaniankhondo  
Status: **LISTENER-PLAYBACK PASS**

## Phase identity

- Starting SHA: `100d81e730ad24b58ec294a73e3bec061024cb0d`.
- Ending SHA / implementation commit: `cd8add5c3de868f0872ed9786c3520a1243eedd5` (`feat: implement playback state management and queueing infrastructure for personal radio system`).
- Final evidence state: the completion-result update, 5.6B contract count compatibility correction, and restart-resilient manual-URL discovery remain as intentional uncommitted changes for exact review.
- BM-PROD5.6B documentation correction: PASS; its completion report records accepted implementation commit `100d81e730ad24b58ec294a73e3bec061024cb0d` while preserving all integrated-stack evidence.

## Media safety and fixture

- Classification: 12 script-generated, regenerable development WAV files; 3 artists; 3 releases; one four-track album per artist.
- Archive-only, original, real NAS, and production media: not accessed.
- Mount policy: read-only inside the production backend container.
- Artwork: `not_applicable`; the generated fixture intentionally contains none, and missing artwork does not block playback.
- Alternate-source case: `not_applicable`; no logical recording has multiple physical sources in this bounded fixture.
- Before/after SHA-256, size, and mtime evidence: exact equality after automated acceptance and again immediately before cleanup.

| Fixture path | SHA-256 | Bytes |
| --- | --- | ---: |
| Artist One / First Signals / 01 | `7b274b61f19a52b89e6272b1ce320f60a6e834f054291c8da89626ca920fe573` | 352,844 |
| Artist One / First Signals / 02 | `1716b6021c893441b667bf1c4b3d59dfcfedba327df1082cb658cfdf1a15e2fc` | 352,844 |
| Artist One / First Signals / 03 | `670c58f179b8c4f5b3aec8da1c1d3ffeff38a676b05daf0d3e713d62948a1e0a` | 352,844 |
| Artist One / First Signals / 04 | `8a72a93749861d9ffc9f6cd92cb930a0084af05bece81643ccc0845e8c3bc199` | 352,844 |
| Artist Two / Second Signals / 01 | `83382e646d67464e531ac36731fc8eb0efc2796469853696b21b220b2a0bd8e5` | 352,844 |
| Artist Two / Second Signals / 02 | `4f92e08a6a213e8c80796725219d9184d6611a1df22b31d176b707f68441f5f7` | 352,844 |
| Artist Two / Second Signals / 03 | `e4037c52f1cacd80aae00d0d5c62a44d77252ce1d80e46fd09b0fe6d9de6998f` | 352,844 |
| Artist Two / Second Signals / 04 | `43f9978223eb89cdca89ab34c89c39fa567ee657311912c127eacc0d146af1df` | 352,844 |
| Artist Three / Third Signals / 01 | `7cc5a9472bda3d0162dd57f6e15fcf19058438b133274fa639e0ac20cd2cb555` | 352,844 |
| Artist Three / Third Signals / 02 | `e8286e1a00e970e12e62df9d1c3a29c378d0ee1af14b0e6671e17956e250e59f` | 352,844 |
| Artist Three / Third Signals / 03 | `220198bc7192e60bfb0979710aa2f641baa138aa9cd41291aa604fcd433130e7` | 352,844 |
| Artist Three / Third Signals / 04 | `d15464853ccee43a1050aaff71826c7cbc7b99d4e32054b593f7f4c431f98574` | 352,844 |

## Playback architecture audit

- Player state and audio lifecycle: `frontend/src/state/PlaybackContext.tsx` owns one `HTMLAudioElement`, one `itemRef`, queue/index refs, listener state, and source context; this enforces one logical current item.
- Play/pause: native audio `play`/`pause` events update state. A history `start` is now emitted only after a real `play` event; later plays of the same loaded identity are `resume`, preventing rerender and pause/resume duplicate starts.
- Seek/volume: seek changes `currentTime` and emits `seek`; the new bounded volume control changes only `HTMLAudioElement.volume` and stores the preference, without mutating the queue.
- End/error: an identity guard permits one natural-end advance per loaded item. A load failure displays an understandable alert and never retries or advances automatically.
- Next/previous: pure bounds-checked queue-index transitions; Previous means the prior queue item, not “restart current after N seconds.”
- Queue: recording-first backend projections remain authoritative, preserving logical queue identity. The frontend holds one logical listener occurrence per projected item and supports next, previous, remove, clear-up-next, and reorder.
- Refresh semantics: queue, current item, position, and playing/paused state are in-memory and reset to an empty stopped state on full refresh. That current privacy/simple-session behavior is documented rather than adding unrequested persistence.
- Backend streaming: `backend/app/routes/media.py` validates availability, blocked-recording policy, approved roots, and supported types, then uses Starlette `FileResponse` for full and HTTP byte-range delivery.
- History: `backend/app/routes/playback.py` records physical `track_id` plus logical `recording_id`; qualified-play deduplication remains backend-controlled.
- Effective source: backend listener projections resolve the accepted physical source for the logical occurrence when a queue/search/album/playlist projection is requested.

## Automated acceptance

- Disposable PostgreSQL 16 / Alembic head / real scanner: PASS; 12 tracks, 3 artists, and 3 albums ingested. The active 1,257-row target was not used.
- Full stream: PASS, 200 with `audio/wav`, exact content length/bytes, and `Accept-Ranges: bytes`.
- Initial and mid-file byte ranges: PASS, 206 with exact `Content-Range` and byte slices.
- Invalid/out-of-range request: PASS, controlled 416.
- Missing copied file: PASS, controlled non-500 without a source path; the file was restored and immediately streamed again. The frontend shows one understandable alert and has no automatic retry/advance loop.
- Artwork: `not_applicable`; missing artwork did not block any flow.
- Player/queue invariants: PASS, 13 executable checks.
- Search-to-play: PASS; selected search result resolved to a ranged media response.
- Album-to-play: PASS; `Acceptance Tone 1` through `Acceptance Tone 4` projected once each in order and the first track streamed.
- Temporary playlist: PASS for create, stored order, first/middle playability, next-order projection, persisted reverse reorder, remove, and final delete.
- Playback history: PASS; exactly one `start`, followed by pause/resume/seek/finish and one qualified play. Every music event retained physical `track_id` and logical `recording_id`.
- Effective-source selection: `not_applicable`; the bounded fixture has no alternate physical sources. Existing recording-first source resolution remains covered by prior contracts.
- Queue controls: PASS for current/next/previous/progression in executable regressions; remove, clear-up-next, and reorder are implemented with immutable queue helpers.
- Frontend restart: PASS; app and subsequent playback recovered.
- Backend restart: PASS; frontend stayed available, the outage returned a prompt controlled proxy failure, health recovered, and playback resumed. This acceptance found and fixed the missing short Nginx backend-connect timeout.
- PostgreSQL restart: PASS; readiness and playback recovered without any schema repair.

## Manual listener acceptance

- Result: **PASS**.
- Operator: Bonny Makaniankhondo.
- Recorded: `2026-08-17T17:21:48Z`.
- Evidence origin: explicit user confirmation after completing the displayed checklist; automated code did not fabricate the result.
- Confirmed scope: audible correct-song playback, pause, resume, forward/backward seek, volume, one natural-end advance, Next, Previous, narrow-mobile player/queue/search/album usability, and basic keyboard/accessibility behavior.
- The computer restarted before confirmation, stopping both task containers and the protected active PostgreSQL container. The exact task stack was recovered in database/backend/frontend order and received a new loopback port. The protected PostgreSQL container was later restarted with its existing configuration and named volume; final equality proved no protected-state change.

## Protected state and cleanup

- Active 1,257-row PostgreSQL: exact protected-state equality after automated acceptance and before cleanup.
- SQLite fallback: exact protected-state equality after automated acceptance and before cleanup.
- Active `.env` and durable evidence: exact protected-state equality after automated acceptance and before cleanup.
- Protected-state canonical SHA-256 before and after: `5fcaf1261e0dd11e5f342a77ed7ea656334c2cef8c9b547cb8cabf6a3e3728a3`.
- Remaining `bm-prod6a-*` containers: none.
- Remaining `bm-prod6a-*` networks: none.
- Remaining `bm-prod6a-*` volumes: none.
- Generated test media, task credentials, cache, and local state: removed.
- TrueNAS work: prohibited and not performed.
- Station recommendation quality is deferred to BM-PROD6B.

## Validation

- Python compile: PASS.
- BM-PROD6A contract: PASS, 40 checks, including the prior 5.6B regression.
- BM-PROD5.6B contract: PASS, 34 checks.
- PROD0: PASS — 59 passed / 0 failed / 4 skipped.
- Frontend build: PASS.
- Frontend lint: PASS with no errors and the existing warning set.
- `git diff --check`: PASS.
- Final Git status: only this completion-result update, the 5.6B contract compatibility correction, and the restart-resilient manual-URL discovery change remain uncommitted for exact review; all other PROD6A implementation files are committed at `cd8add5c3de868f0872ed9786c3520a1243eedd5`.

**STOP: BM-PROD6A LISTENER-PLAYBACK PASS. Station recommendation quality remains deferred to BM-PROD6B; no station changes or TrueNAS work were performed.**
