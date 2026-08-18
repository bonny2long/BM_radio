# BM-PROD6C.1 Real Copied Media Revalidation and Fixture Policy Hardening

BM-PROD6C.1 status: **REAL-COPIED-MEDIA PASS**

Correction starting BM Radio SHA: `9b8cc2cf48a619422b3d25983bc61267149fdaa5`

Ending working-tree state: 12 reviewed BM Radio files modified on the starting SHA; no runtime or build artifact is present. The exact diff is held uncommitted for review before PROD6D.

## Corrected media policy

The earlier PROD6C fixture-policy result is superseded by this correction. Live pipeline, scanner, player, and listener acceptance now blocks unless an external `$PROD6C_COPIED_MEDIA_SOURCE` is present with this exact classification:

- `copied_test_media=true`
- `generated_by_acceptance_script=false`
- `original_only_copy=false`

No personal source path is committed. Acceptance code cannot create audio or random media-shaped bytes. The permanent AA music/audiobook regressions use virtual scanner inputs and synthetic database-only fixtures; they do not write fake media files. Missing real copied media is a blocking result.

## Copied source and cross-application pipeline

- Copied source: 26 hash-inventoried files outside the task pipeline root, including 8 valid FLAC tracks from two albums, one valid M4B audiobook, and one valid EPUB. Mutagen validated all nine audio files; the shortest duration was 161.39 seconds.
- Original-to-copied-source SHA-256 equality: PASS for every file.
- Intake initial run: four drops were held as `first_seen` and none was promoted early.
- Intake stable run: four drops / 26 files promoted to ready. Source/ready hashes matched, there were no failures, and the immediate rerun returned zero items.
- Archive Assistant normal SQLite state was retained; reset/dev tools remained disabled. Its checksum ledger correctly refused duplicate batches for the two already-AA-processed albums and EPUB. Their copied AA-final trees were reused under the runbook's real-evidence reuse rule; duplicate working copies were preserved in `leftover-review`.
- A copied final-library M4B directory initially classified as unknown because it contained nested prior-AA metadata. The stale task row was rejected, the metadata was preserved in `leftover-review`, and the unchanged M4B bytes were rerun through Intake as a supported top-level file.
- Archive Assistant batch 69 classified as `audiobook`, received explicit metadata review/unknown-year and narrator acceptance, was explicitly approved, and moved one M4B with zero failed moves.
- Ready was empty after the move/reuse accounting. Archive Assistant rescans before and after restart returned zero created and zero skipped; quarantine remained empty.
- No Intake Watcher, Archive Assistant, or Cleaner source code changed.
- Cleaner ran with `dry_run=true` and `destructive_actions_enabled=false`. All five fresh leftovers were blocked by the 14-day gate; final media and quarantine were not selected and nothing was deleted.

## Isolated BM Radio acceptance

- Disposable PostgreSQL 16, Alembic head, private backend/database networking, loopback-only production frontend, and read-only Music/Audiobooks/Books mounts: PASS.
- Movies and TV were excluded. The active PostgreSQL database and SQLite fallback were not used or changed.
- Music scanner: 8 tracks, 7 logical recordings, 2 albums, 1 artist, 8 successful technical probes, no probe failures.
- One album exposed one logical song backed by two identical physical occurrences; the other exposed six tracks. Listener, artist, and album duplicate counts were zero.
- Audiobook scanner: one valid M4B audiobook and one playable chapter entry, with no scan errors.
- Search, album queues, playlist create/rename/order/play/reorder/remove/delete, favorite/unfavorite, thumbs up/down, refresh persistence, feedback-to-station scoring, preferred-source override/unset, queue/source continuity, artwork, and rescans: PASS.
- Source hash/size/mtime equality and final-media hash/size/mtime equality before/after BM Radio: PASS.
- Exact classification in live evidence: `copied_test_media=true`, `generated_by_acceptance_script=false`, `original_only_copy=false`.

## Manual findings and corrections during review

Human result: **PASS**, recorded at `2026-08-18T02:48:03Z`. Automation did not fabricate the result.

The operator observed one artist, two albums, one logical song in one album, and six tracks in the other. Audible music transitions took approximately 5–8 seconds. The audiobook initially appeared broken but audible sound began after approximately 3 minutes. These are report-only observations; no additional playback behavior change was requested.

The manual browser console exposed a blocked Google Fonts request: the page imported a remote stylesheet while the production CSP correctly allowed styles only from self. The remote import was removed, the existing system-font stack was retained, and the production container contract now prohibits remote CSS font imports. The strict CSP was not weakened.

Repeated M4B byte-range requests also exposed database-pool exhaustion: file responses retained request-scoped database sessions while large streams remained open. All five media routes now use function-scoped database dependencies, closing the session before the file response is sent. A permanent live proof holds 18 unconsumed range streams open—more than the 15-connection pool limit—while requiring the library API to remain healthy. The corrected stack passed with `database_pool_exhausted=false`.

After both corrections, frontend build and lint passed, served CSS contained no remote font reference, the CSP remained self-only, the 18-stream live proof passed, and the backend/frontend containers remained healthy. The operator's PASS remained authoritative; no further manual behavior change was requested.

## Cleanup and equality

- Copied source equality: PASS.
- Final media equality: PASS.
- Protected active PostgreSQL, SQLite fallback, environment, and durable evidence equality: PASS; canonical SHA-256 before/after `5fcaf1261e0dd11e5f342a77ed7ea656334c2cef8c9b547cb8cabf6a3e3728a3`.
- Cleanup: zero remaining `bm-prod6c-*` containers, networks, or volumes; runtime credentials removed.
- TrueNAS work, Cleaner deletion, original-only import, active-database scanning, and SQLite retirement were not performed.

## Final validation

- Python compile/compileall: PASS.
- AA music and audiobook manifest regressions: PASS without media-file writes.
- PROD5.6B integrated production stack contract: PASS (34 checks).
- PROD6A listener playback contract: PASS (40 checks).
- PROD6B station quality contract: PASS (52 checks).
- PROD6C copied-real-media/source UX contract: PASS (41 checks), including prior-regression execution.
- PROD0: PASS — `61 passed / 0 failed / 4 skipped`.
- Frontend production build: PASS.
- Frontend lint: PASS — 0 errors, 8 existing warnings.
- `git diff --check`: PASS.
- Final policy/privacy audit: PASS; no personal path committed, no remote font import, and applicable live/AA scripts contain no fake-media creation pattern.
- Working tree contains only the reviewed PROD6C.1 BM Radio code, contract, checklist, and report changes; no runtime/build artifacts.

**STOP: BM-PROD6C.1 REAL-COPIED-MEDIA PASS. Do not begin PROD6D.**
