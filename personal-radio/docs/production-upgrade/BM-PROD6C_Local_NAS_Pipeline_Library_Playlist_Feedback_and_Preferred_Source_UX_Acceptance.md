# BM-PROD6C Local NAS Pipeline, Library, Playlist, Feedback, and Preferred-Source UX Acceptance

BM-PROD6C status: **LOCAL-LIBRARY-UX PASS**

Starting BM Radio SHA: `5e3b2be2e5163c37297881dd9d1fcd33d55bd129`

Implementation commit at human-review entry / ending HEAD at final validation: `84afc0699b8db89de49b65b3d5a95dfc9493eafc`. The final completion-result update to this report is the only post-commit evidence edit expected at handoff.

## PROD6B documentation correction

The PROD6B report now records implementation/accepted phase commit `5e3b2be2e5163c37297881dd9d1fcd33d55bd129` and no longer describes the accepted implementation as uncommitted. Its real-library subjective station review remains deferred.

## Cross-repository preflight

| Application | Branch | HEAD | Entry status |
|---|---|---|---|
| BM Radio | `main` | `5e3b2be2e5163c37297881dd9d1fcd33d55bd129` | clean |
| Archive Assistant | `master` | `e19dc4281a0c984a21daae41499be0d27eed40c4` | pre-existing `frontend/package-lock.json` modification; not touched by this task |
| Intake Watcher | `main` | `6d6434595489ca1a13924089d5db69dd4ba32088` | clean |
| Cleaner | `main` | `d0a9fc8467241c1891d8138355b52fc61a035f24` | clean |

No other repository will be patched by BM-PROD6C. If Intake Watcher or Archive Assistant requires a code change, this phase stops for a separately reviewed task.

## Architecture and local NAS root contract

BM Radio uses PostgreSQL. Archive Assistant remains SQLite. Intake Watcher and Cleaner retain lightweight filesystem/report state. `NAS_LOCAL_ROOT` is supplied at runtime; no personal absolute path or username is committed.

The acceptance root is task-scoped so unrelated real files already present in the normal shared intake/ready lanes cannot be promoted or scanned accidentally. Immutable copied/generated sources live below `$NAS_LOCAL_ROOT/_TEST_FIXTURES/prod6c_source`, working copies enter `$NAS_LOCAL_ROOT/_INGEST/incoming`, and privacy-safe evidence is written below `$NAS_LOCAL_ROOT/_REPORTS/prod6c`.

## Copied fixture and Intake Watcher

- Immutable source: 18 generated/regenerable files, stored outside the pipeline working lane. The canonical fixture-inventory JSON SHA-256 is `45685aa20feec40e0caa36e0e2476ec7752287d3af6ef3e88ec7c2b260c78591`; the inventory contains an individual SHA-256 and size for every file.
- Shape: 14 music occurrences / 10 logical songs, three artists, three albums, four FLAC+MP3 logical pairs, one live-titled track, three MP3 audiobook chapters, and one EPUB.
- First Intake run: six top-level inputs returned `first_seen`; none was promoted.
- Stable run using the existing two-second test override: six inputs / 18 files promoted to `_INGEST/ready`.
- Exact source/ready content hashes matched. Intake made no metadata edits, final-library writes, or deletions.
- Immediate Intake rerun: zero items; no duplicate promotion.

## Archive Assistant and Cleaner

- Archive Assistant remained on its normal SQLite state with `DATA_ROOT`/`INGEST_ROOT` pointed only at the task root and dev/reset tools disabled.
- Scan created six task batches: four music albums, one audiobook, and one book; there were no movie, TV, unknown, or unsupported batches.
- Music warnings were reviewed and explicitly accepted. All six batches were explicitly approved through the normal flow. The FLAC/MP3 pair triggered the intended duplicate review and was resolved as `keep_separate` because its FLAC and MP3 destination previews were distinct.
- Selected-move preflight: six ready, zero blocked, 18 source files. Execution: six batches moved, 18 files moved, zero failed moves/errors. Destinations were Music/Library/FLAC or MP3, Audiobooks/Library, and Books/EPUB. Six move manifests were written.
- Ready contained zero files after move; quarantine contained zero files and was never selected.
- AA rescan after move and again after restart created zero batches. The same six task batches remained singular and moved.
- Cleaner ran with `dry_run=true` and `destructive_actions_enabled=false`. It proposed only five `blocked_no_action` records for fresh empty ready folders under the 14-day age gate. No final media or quarantine was selected and no deletion occurred.

## BM Radio isolated acceptance

- Disposable PostgreSQL 16, Alembic head, private backend/database networking, loopback-only production frontend, and read-only Music/Audiobooks/Books mounts: PASS.
- Movies and TV were not mounted or scanned. The active 1,257-row PostgreSQL database was not used.
- The first live scan exposed a BM Radio interoperability defect: AA's explicit unknown-year text reached a fallback scanner path and was passed to an integer column. BM Radio now normalizes only plausible four-digit years and treats unknown/non-numeric values as missing. `check_aa_manifest_music_import.py` permanently covers the AA `Unknown Year` case.
- Real music scan: 14 tracks, 10 recordings, 14 identities/technical profiles, zero probe failures, and four FLAC/MP3 recording pairs preserved as physical sources.
- Real audiobook scan: one audiobook, three chapters, zero errors. EPUB remained mounted under Books but is not presented as audiobook media.
- Listener projection: 10 logical songs, three artists, three albums, zero listener/artist/album duplicates. Search, artist, album, album ordering, search-to-play, and audiobook entry playback passed.
- Preferred source: unique lossless FLAC was automatically chosen for the tested pair; manual MP3/FLAC override took effect; unset resumed automatic selection. One listener song represented two retained physical occurrences. Single-source behavior remains covered and prior synthetic source-policy regressions remain registered.
- Feedback: favorite/unfavorite and thumbs up/down passed; refresh persistence passed; feedback remained recording-level across a source switch; later thumbs-down removed Favorites-station eligibility. The observed up/favorite debug score delta was `+1.15`.
- Playlist: create, rename, add, order, play first, play middle, reorder, remove, and delete passed. Duplicate logical playlist entries remain intentionally allowed.
- Queue/source continuity: album, search, and playlist logical identities remained stable; source override did not corrupt the queue. Existing PROD6A next/previous contracts remain passing.
- Artwork: `not_applicable`. AA reported and moved no artwork from this bounded fixture, and BM Radio presented the clean missing-art fallback.
- BM Radio rescan: logical count 10, physical count 14, and audiobook count 1 remained equal.

## Human review, equality, and cleanup

- Human operator result: **PASS**, supplied after reviewing the retained production-style frontend and checklist. Automation did not fabricate the result.
- Immutable source hashes: exact before/after equality PASS.
- Final AA-cleaned media: exact hash/size/mtime equality before/after BM Radio PASS.
- Protected active PostgreSQL, SQLite fallback, `backend/.env`, and transfer/adoption/backup/recovery evidence: canonical before/after SHA-256 `5fcaf1261e0dd11e5f342a77ed7ea656334c2cef8c9b547cb8cabf6a3e3728a3`; equality PASS.
- Cleanup: zero remaining `bm-prod6c-*` containers, networks, or volumes; task runtime credentials removed. Privacy-safe task evidence remains under `$NAS_LOCAL_ROOT/_REPORTS/prod6c`.

## Final validation

- Python compile: PASS.
- PROD6C contract: PASS (41 checks), including prior-regression execution.
- PROD6B contract: PASS (52 checks).
- PROD6A contract: PASS (40 checks).
- The first full PROD0 run exposed the superseded PROD1.4D1 static boundary that prohibited every frontend recording-control reference. The permanent check now permits the PROD6C route literal only in `frontend/src/api.ts` and its advanced consumer only in `TrackActionSheet`, while continuing to prohibit broad listener participation controls.
- PROD0 final rerun: PASS — `61 passed / 0 failed / 4 skipped`.
- Frontend production build: PASS.
- Frontend lint: PASS — 0 errors, 8 existing warnings.
- `git diff --check`: PASS.
- Final working tree: only the post-`84afc0699b8db89de49b65b3d5a95dfc9493eafc` completion-report update and forward-compatible PROD1.4D1 static-boundary update remain for the next repository checkpoint; no generated build/runtime files are present.

TrueNAS work, Cleaner deletion, production/original media, active-database scanning, real production-library import, and SQLite retirement are prohibited.

**STOP: BM-PROD6C LOCAL-LIBRARY-UX PASS. Do not begin PROD6D, TrueNAS work, Cleaner deletion, real production import, or SQLite retirement.**
