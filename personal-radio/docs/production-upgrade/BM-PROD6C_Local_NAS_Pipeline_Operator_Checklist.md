# BM-PROD6C Local NAS Pipeline Operator Checklist

This checklist is the live, cross-repository portion of BM-PROD6C. It uses a configurable `NAS_LOCAL_ROOT`; never put a personal absolute path or username in committed files. BM Radio remains PostgreSQL, Archive Assistant remains SQLite, and Intake Watcher and Cleaner remain lightweight filesystem/report applications.

## Safety boundary

- Use copied or generated, regenerable acceptance media only. Production/original media is prohibited.
- Keep immutable source copies in `$NAS_LOCAL_ROOT/_TEST_FIXTURES/prod6c_source` and working copies in `$NAS_LOCAL_ROOT/_INGEST/incoming`.
- Never reset Archive Assistant. Use its normal SQLite state and normal review/approval flow.
- Cleaner is report/dry-run only: deletion is prohibited, final-library media and quarantine must never be selected.
- BM Radio must use disposable PostgreSQL 16, run Alembic to head, and mount final Music, Audiobooks, and Books read-only. Never scan into the active PostgreSQL database. Movies and TV are excluded from BM Radio.
- If Intake Watcher or Archive Assistant needs a code change, stop and open a separately reviewed task for that repository.

## 1. Preflight and copied fixture

- Record branch, HEAD, and `git status --short` for BM Radio, Archive Assistant, Intake Watcher, and Cleaner.
- Set `NAS_LOCAL_ROOT` only in the operator shell.
- Verify `_INGEST`, `_QUARANTINE`, `_REPORTS`, `_STAGING`, `Audiobooks`, `Backups`, `Books`, `Documents`, `Movies`, `Music`, `Photos`, `Projects`, and `TV` exist below that root.
- Choose a bounded copied fixture: 8–30 music tracks across 2–4 artists/albums with one multi-track album, one multi-file audiobook, and one EPUB. A FLAC/MP3 logical pair and artwork are preferred.
- Inventory and hash every immutable source file before copying. Save privacy-safe evidence in `$NAS_LOCAL_ROOT/_REPORTS/prod6c`; paths in evidence must be relative to `$NAS_LOCAL_ROOT`.

## 2. Intake Watcher

- Copy working copies into `_INGEST/incoming`.
- Run Intake once using its existing test stability override. Confirm new/partial input is not promoted early.
- Wait for the same files to become stable, run again, and confirm they reach `_INGEST/ready`.
- Verify exact content hashes: Intake made no metadata edits, no final-library writes, and no deletion.
- Rerun Intake and verify it creates no duplicate promoted fixture.

## 3. Archive Assistant

- Start Archive Assistant with `DATA_ROOT=$NAS_LOCAL_ROOT`, `INGEST_ROOT=$NAS_LOCAL_ROOT/_INGEST/ready`, its normal SQLite database, and dev/reset tools disabled.
- Run the normal scan. Inspect every task batch and verify music, audiobook, and EPUB/book classification.
- Review metadata and destination previews. Confirm music targets Music, audiobook targets Audiobooks, and EPUB targets Books.
- Explicitly approve each task batch through the normal review/approval API or UI before executing the move.
- Execute only the approved task batch moves. Do not use a reset or destructive test-data mechanism.
- Account for every approved file in the final library and verify quarantine is unchanged/protected.
- Rescan/restart Archive Assistant and verify no duplicate final media is created. Record safe source remnants, if any; do not manually delete them.

## 4. Cleaner boundary

- Run Cleaner only with dry-run/report settings and deletion disabled.
- Verify no final Music, Audiobooks, or Books media is selected; verify quarantine is not selected; verify no deletion occurred.
- Cleaner may be recorded as deferred if unavailable, but any dangerous selection is a blocking failure.

## 5. Isolated BM Radio acceptance

- Run `python scripts/check_prod6c_library_source_ux_acceptance.py --preflight-only`.
- Run `python scripts/check_prod6c_library_source_ux_acceptance.py --bm-radio-automated`.
- The automation must create disposable PostgreSQL 16, run Alembic upgrade head, build production images, mount final media read-only, run the real music and audiobook scanners, and keep the frontend available for review.
- Verify artist/release/recording/track-occurrence identity, one logical listener song per recording, and no physical-source duplicate in library, albums, or search.
- For a FLAC/MP3 pair, verify two occurrences, one logical song, lossless automatic preference, manual override, and unset returning to automatic. For a single source, verify that source is selected.
- Verify favorite/unfavorite, thumbs up/down, refresh persistence, recording-level persistence across source change, thumbs-down station exclusion, and up/favorite scoring evidence.
- Verify playlist create, rename, add from library/search, reorder, play first/middle, remove, and delete. Intentional duplicate logical playlist entries remain allowed unless a separate product change revises that policy.
- Verify album, search, and playlist queues preserve logical identity while resolving the effective physical source; next/previous behavior must remain correct.
- Verify artwork in album/player through the same-origin route, or record `not_applicable` with a clean missing-art fallback.
- Rescan BM Radio and require identical logical and physical occurrence counts.

## 6. Human real-library review

- Run `python scripts/check_prod6c_library_source_ux_acceptance.py --manual-url` and open the printed loopback URL.
- The human operator checks organization, artist/album names, track order, search, absence of FLAC/MP3 duplicate songs, playlist usability, favorite/thumb controls, understandable preferred-source behavior, and real copied-track playback.
- Automation may not fabricate the human result. Record it with `--record-manual PASS --operator-note "..."` or `FAIL` and a real operator note.

## 7. Final equality and cleanup

- Re-hash immutable source fixtures and require exact equality with the before hashes.
- Require BM Radio active PostgreSQL, SQLite fallback, `backend/.env`, and transfer/adoption/backup/recovery evidence to equal their before snapshots.
- Run `python scripts/check_prod6c_library_source_ux_acceptance.py --cleanup`. Cleanup may remove only `bm-prod6c-*` containers/network/volume and task runtime credentials; it must not delete copied source or final library evidence.
- Run the permanent 6C contract, PROD6B contract, PROD6A contract, full PROD0, frontend build/lint, `git diff --check`, and `git status --short`.
- Stop at `BM-PROD6C LOCAL-LIBRARY-UX PASS`. Do not begin PROD6D, TrueNAS work, Cleaner deletion, real production import, or SQLite retirement.
