# BM-PROD6F — Final Local Production Acceptance and Whole-System Handoff

Owner: Bonny Makaniankhondo

Date: 2026-08-26

Phase boundary: final local-software acceptance before future NAS hardware deployment

Status: FINAL-LOCAL-ACCEPTANCE PASS

## Decision

The four local NAS applications, the copied `nas-data` tree, persistent PostgreSQL, Archive Assistant SQLite state, and a copied-real-media canary passed the automated, recovery, desktop-listener, and private-LAN phone checks described below.

Do not begin TrueNAS deployment, public exposure, or Cleaner destructive-mode work from this report.

Durable whole-NAS companion: [`BM-PROD6F_Whole_NAS_Handoff_and_Source_of_Truth_Delta.md`](./BM-PROD6F_Whole_NAS_Handoff_and_Source_of_Truth_Delta.md). This Git-tracked copy is authoritative over the convenience copy stored directly under `C:\Dev\NAS`.

## Canonical local source of truth

- Active development root: `C:\Dev\NAS`
- Active NAS-style data root: `C:\NAS-Local\nas-data`
- BM Radio repository: `C:\Dev\NAS\BM_radio`
- Archive Assistant repository: `C:\Dev\NAS\archive_assistant`
- Intake Watcher repository: `C:\Dev\NAS\intake-watcher`
- Cleaner repository: `C:\Dev\NAS\cleaner`
- Old OneDrive and Documents/GitHub copies: **FROZEN BACKUP — NOT ACTIVE DEVELOPMENT**

Original relocation proof: 930 files, 12,145,578,589 bytes, zero SHA-256 differences.

## Accepted repository baselines

| Application | Branch | Accepted code SHA | Final code state before handoff docs |
| --- | --- | --- | --- |
| BM Radio | `main` | `fb32bf397b86e7b3f8bc87d197f0cc9db0689497` | unchanged |
| Archive Assistant | `master` | `d785d8657bfabb96f1a83d0089d24d4e01ee5328` | unchanged |
| Intake Watcher | `main` | `6d6434595489ca1a13924089d5db69dd4ba32088` | unchanged |
| Cleaner | `main` | `d0a9fc8467241c1891d8138355b52fc61a035f24` | unchanged |

The documentation-only BM Radio ending SHA is recorded in the shared whole-NAS handoff and operator completion output after push; a tracked file cannot safely contain the SHA of the commit that contains itself.

## Final architecture

- BM Radio uses persistent local PostgreSQL 16 and consumes final `Music` and `Audiobooks` content.
- Archive Assistant uses SQLite and owns media review, approval, final movement, and move manifests.
- Intake Watcher uses lightweight filesystem/report state and promotes stable copies from `incoming` to `ready`.
- Cleaner uses lightweight report/evidence state. It remains dry-run/report-only and is the only future production deletion authority.
- Photos are reserved for the future Immich path and remain outside Archive Assistant/BM Radio.
- Movies and TV are reserved for a future Jellyfin consumer.
- PostgreSQL is loopback-only; the manual frontend was exposed only on the private LAN through the Vite development proxy.

Pipeline proved:

`copied real media -> _INGEST/incoming -> Intake Watcher -> _INGEST/ready -> Archive Assistant -> Music/Library/FLAC -> BM Radio -> Cleaner report-only`

## Configuration record without secrets

- `NAS_LOCAL_ROOT=C:\NAS-Local\nas-data`
- BM Radio DB backend: PostgreSQL, database `bm_radio`, loopback port 55432
- BM Radio music root: `C:\NAS-Local\nas-data\Music`
- BM Radio audiobook root: `C:\NAS-Local\nas-data\Audiobooks\Library`
- BM Radio books root: `C:\NAS-Local\nas-data\Books`
- Archive Assistant DB: `C:\Dev\NAS\archive_assistant\backend\archive_assistant.db`
- Archive Assistant ingest root: `C:\NAS-Local\nas-data\_INGEST\ready`
- Intake incoming: `C:\NAS-Local\nas-data\_INGEST\incoming`
- Intake ready: `C:\NAS-Local\nas-data\_INGEST\ready`
- Cleaner report root: `C:\NAS-Local\nas-data\_REPORTS\cleaner`
- Desktop frontend URL used: `http://127.0.0.1:5173`
- Private-LAN frontend URL form used: `http://<private-LAN-IPv4>:5173`
- Backend local URL: `http://127.0.0.1:8094`
- Runtime safety: public access false; file mutation false; delete false; tag writes false; ingest scanning false

No password, database URL, token, or API secret is recorded here.

## Backup evidence

### BM Radio PostgreSQL

Accepted pre-change logical backup:

- File: `C:\NAS-Local\Backups\BM-PROD6F\BM-Radio\PostgreSQL\bm_radio.postgres.logical.20260826T173149Z.4cd56b.dump`
- Created UTC: `2026-08-26T17:31:51Z`
- Size: 124,671 bytes
- SHA-256: `d30aeba117e9c168cebec2573ef05e72223a6a91f49701a10eb8d9469d1ac57d`
- Manifest SHA-256: `92eaa8794cec6b0b3bbc824801582f93307446768687bb02492b075fdb6b41e1`
- PostgreSQL: 16.15
- Database: `bm_radio`
- Migration: `0001_current_schema_baseline`
- Custom archive inspection, schema, foreign keys, and Alembic drift: PASS

Canonical post-path-repair checkpoint:

- File: `bm_radio.prod6f.canonical.20260826T232858Z.dump`
- Size: 134,548 bytes
- SHA-256: `b352aa2448462e2e334cfca13663494e2d4f7957895d649fdaf29ed2316ad67d`
- Manifest SHA-256: `4ba73e9aef926a483e483af56c7badb9b56574adf893bfbd747a8bba46dcd460`
- Counts: 255 tracks, 241 logical recordings, 1 audiobook
- Canonical root: `C:\NAS-Local\nas-data`; old-root references: 0; archive inspection: PASS

A diagnostic dump of the rejected duplicate-path scan state was retained as recovery evidence and was never adopted as active state.

### Archive Assistant SQLite

- Source: `C:\Dev\NAS\archive_assistant\backend\archive_assistant.db`
- Backup: `C:\NAS-Local\Backups\BM-PROD6F\Archive-Assistant\SQLite\archive_assistant.prod6f.20260826T173357Z.db`
- Size: 9,580,544 bytes
- Backup SHA-256: `0b88b8f517e0bb7837612cfaf3f798b703156811ba903e06e62428519719bf34`
- Source/backup logical hash at creation: `8cc936db6529d073d88c968799c994c2338b198cd82d2c1a444d7e2dffb33cbd`
- Integrity and quick check: `ok`
- Protected pre-canary batch count: 69

## Regression results

### BM Radio

- PROD6E contract: PASS
- PROD6D contract: PASS
- PROD6C contract: PASS
- PROD6B contract: PASS
- PROD6A contract: PASS
- Entry PROD0: 63 passed, 0 failed, 4 skipped
- Frontend `npm audit`: 0 vulnerabilities
- Frontend build: PASS
- Frontend lint: PASS with eight existing non-blocking React hook/Fast Refresh warnings
- Final PROD0: 63 passed, 0 failed, 4 skipped — PASS

### Archive Assistant

- Core V1: PASS
- QA1 all-media acceptance: PASS
- Frontend `npm audit`: 0 vulnerabilities
- Frontend build: PASS
- SQLite integrity: `ok`
- Final no-change scan: 70 -> 70 batches, created 0, skipped duplicate 1
- Old active-root references: 0
- Dependency remediation retained: PostCSS 8.5.26 and nanoid 3.3.18

### Intake Watcher

- Full documented unittest suite: 14/14 PASS
- Canonical server/config smoke: PASS
- Empty-incoming restart: incoming 0 -> 0, ready 9 -> 9, unexpected promotions 0
- Destructive actions: false

### Cleaner

- Configured pytest suite: 9/9 PASS
- Production report-only run: PASS
- Candidates: 12 total; 9 too new/blocked; 3 quarantine/protected
- Eligible actions: 0
- Dangerous actions: 0
- Deletion performed: NO

## Copied-real-media canary

Canary: a copied real 2026 FLAC deluxe album supplied by the owner. The original Downloads copy remained untouched.

### Intake

- Source inventory: 20 FLAC files plus `cover.jpg`, 21 files, 296,387,533 bytes
- Extended-path SHA-256 copy verification: 21 files, 0 mismatches
- First watcher pass: `first_seen`, not promoted
- Second pass after the bounded stability interval: `promoted_to_ready`
- Promoted once; no partial promotion; no collision; ready hashes matched

### Archive Assistant

- Exactly one new batch: batch 70
- Classification: `music_album`
- Reviewed metadata: Kanye West — Bully (Deluxe) — 2026 — Hip-Hop — FLAC
- Files: 20 tracks plus artwork
- Destination: `Music\Library\FLAC\Kanye West\2026 - Bully (Deluxe)`
- Selected-move preflight: ready 1, blocked 0, warnings 0
- Move: 21/21 completed; 0 failures; JSON and Markdown manifests created
- Source-to-final SHA-256 comparison: 0 mismatches
- Unrelated original batches changed: 0

Archive Assistant left an empty source-directory shell in `ready`. It contains zero files and zero child directories. Cleaner sees only that shell as fresh and assigns `blocked_no_action`; the final library media is outside Cleaner candidate lanes.

### BM Radio

- First canonical rescan: 275 scanned, 20 added, 255 updated, 0 unavailable, 0 errors
- Second canonical rescan: 275 scanned, 0 added, 275 updated, 0 unavailable, 0 errors
- Final identity counts: 275 physical tracks, 261 logical recordings, 1 audiobook
- Canary: 20 tracks, 20 distinct paths, one artist projection, one album projection
- Listener search: one `Bully (Deluxe)` album with 20 tracks
- Preferred-source evaluation completed for all 261 recordings
- Old/noncanonical track paths: 0
- HTTP Range playback: `206 Partial Content`, 1,024 requested bytes, `audio/flac`

### Cleaner after canary

- Final media selected: NO
- Quarantine eligible for action: NO
- Empty fresh source shell: protected by 14-day age gate
- Dangerous actions: 0
- Deletion: NO

## Manual listener and phone acceptance

Owner response: **PASS**.

Desktop testing used Chrome; the VS Code embedded browser is explicitly excluded because it previously failed audiobook media playback while Chrome passed. The physical phone browser family was not separately named by the owner.

The owner accepted the requested checks for:

- copied real music search, album playback, transitions, pause/resume, next/previous, and queue
- Artist Radio, Song Radio, Genre Radio, Favorites, Recently Added, Deep Cuts, and live/version-focused context
- seed relevance, artist/album diversity, genre coherence, duplicate avoidance, preferred-source behavior, transition quality, and refill behavior
- audiobook open/resume/seek/speed and return to music
- private-LAN phone browse/search/playback/control flow

No repeatable material recommendation defect was reported. No algorithm tuning was opened.

## Recovery and state preservation

Final controlled PostgreSQL restart after manual acceptance preserved exactly:

- tracks: 275 -> 275
- logical recordings: 261 -> 261
- audiobooks: 1 -> 1
- canary tracks: 20 -> 20
- playback events: 51 -> 51
- favorites, playlists, audiobook progress, and saved stations: 0 -> 0 (no durable rows remained from the manual session)
- PostgreSQL health: healthy; Alembic revision: `0001_current_schema_baseline`

Archive Assistant restart preserved 70 batches, 46 moved batches, batch 70 state `moved`, 21 completed canary moves, SQLite integrity `ok`, and zero old-root references.

Intake Watcher restart with auto-run and empty incoming produced zero unexpected promotion reports and no count drift.

Cleaner repeated the same 12-candidate report-only plan with zero eligible or dangerous actions.

Expected canary deltas are therefore explained: Archive Assistant 69 -> 70 batches; BM Radio 255 -> 275 physical tracks and 241 -> 261 logical recordings; audiobook count remained 1.

## Startup order

1. Start Docker Desktop and confirm `bm-radio-postgres-dev` is healthy.
2. Start BM Radio backend with protected PostgreSQL configuration and canonical media roots.
3. Start the BM Radio frontend.
4. Start Archive Assistant only when review/move work is needed.
5. Start Intake Watcher only when intake monitoring is needed.
6. Run Cleaner only in report-only mode during this local phase.

Never copy `.venv`, `node_modules`, a live SQLite file, or PostgreSQL volume files between active locations. Recreate dependencies from lock/dependency files and use logical database backups.

## Recovery ownership

- BM Radio database: recover from a verified custom-format logical PostgreSQL backup; never copy raw volume files.
- Archive Assistant: stop its process, take/restore a SQLite backup with integrity verification, then confirm batch counts and canonical paths.
- Git: fresh clone from the four remotes and verify exact branch/SHA before environment recreation.
- NAS-local media: preserve `C:\NAS-Local\nas-data` independently; verify counts, bytes, and SHA-256 after any relocation.
- Credentials: recreate from protected local environment/configuration; never commit them.

## Deferred production work

- TrueNAS SCALE and hardware-specific mounts
- private remote access/Tailscale as a separately approved task
- Jellyfin and Immich production integration
- Cleaner production deletion enablement
- hardware monitoring and UPS integration
- final hardware backup topology

## Final boundary

This phase authorizes no TrueNAS deployment, public port forwarding, raw PostgreSQL-volume copying, media deletion, quarantine deletion, or Cleaner destructive behavior.

Final decision: **BM-PROD6F FINAL-LOCAL-ACCEPTANCE PASS**.
