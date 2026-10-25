# Bonny NAS System Master Runbook v12

**Local Workflow Edition**

| | |
|---|---|
| Owner | Bonny Makaniankhondo |
| Updated | 2026-10-25 |
| Project | Personal NAS: Intake Watcher, Archive Assistant, Cleaner, BM Radio |
| Status | Full local workflow re-proven from a clean slate; October safety and recovery hardening merged. Hardware and TrueNAS deployment still deferred. |
| Supersedes | v11 Post-PROD6F Cleaner Focus Edition (2026-08-26), kept as history |

## Authority

For implementation detail, the order of precedence is:

1. The newest task-specific document in the relevant repository.
2. The repository code and tests on `main` (`master` for Archive Assistant).
3. This v12 runbook.
4. v11 and older runbooks, as history.

Do not weaken a permanent architecture rule just because an older document differs.

## 0. Read This First

- Active code: `C:\Dev\NAS` (one Git repository per app).
- Active data: `C:\NAS-Local\nas-data`.
- Master copies of the test downloads: `C:\NAS-Local\Restock`. Copy from here into `_INGEST\incoming`; never move.
- Restock holds 769 unique files (about 12.4GB) plus 3 intentional `- Copy` duplicates (Mac Miller Discography, Dune Chronicles (Dune 7), Golden Son). They are byte-identical to their originals (SHA-256, checked 2026-10-25) and are kept to exercise duplicate review. Folder total: 986 files (about 18.9GB). Local test data only; the NAS starts empty.
- The old copies under `Documents\GitHub` are **frozen backups**. Do not run, edit, or test them. `timeledger` in that folder is unrelated to the NAS.
- On 2026-09-26 the whole local system was wiped and restarted from empty databases, then fed the same media again through the full workflow. Backups from before the wipe are in `C:\NAS-Local\Backups\20260926T231453Z-pre-fresh-start`.
- TrueNAS deployment is still deferred. Local acceptance is not permission to start destructive Cleaner work or hardware deployment.

## 1. Mission

The NAS is long-term personal infrastructure: controlled intake of non-photo media, organized long-term storage, private listening through BM Radio, Movies and TV through Jellyfin, and photos through Immich. Access is private LAN plus Tailscale or VPN later, with off-site backup at the parents' house later.

```text
Archive preserves.
Readers consume.
Cleaner may eventually remove only proven-safe leftovers.
No reader application owns the archive.
```

## 2. Current Status (2026-10-25)

| Area | State | Next |
|---|---|---|
| Hardware | Build plan locked, not purchased | Buy and assemble when ready |
| Local data | Fresh start on 2026-09-26; 7 releases re-ingested | Keep using copies from Restock |
| Intake Watcher | 51 tests; origin guard; damaged-state recovery; one-pass fingerprints | Decide whether non-media folders should be promoted for quarantine |
| Archive Assistant | Core V1 suite 24 checks plus targeted safe-default, origin, and duplicate-guard checks; quarantine lifecycle; multi-disc grouping | Scheduled scan; pending-batch API for Cleaner |
| Cleaner | 126 tests; report-only by default; 30-day age gate; reviewed empty-folder removal; recoverable 14-day trash hold (off by default) | Pending-batch API integration, SQLite ledger |
| BM Radio | PROD0 63 passed, 0 failed, 4 skipped; PostgreSQL 16; removed-path reconciliation | Keep final library mounts read-only |
| Photos | Outside Archive Assistant and BM Radio | Future Immich |
| Movies and TV reader | Archive Assistant prepares folders | Future Jellyfin |
| Remote access | Local only | Future Tailscale |

## 3. Repository State

On 2026-10-25 all four active repositories were clean and matched their remote default branch. These are the heads inspected for this revision; still run `git status --short --branch` and `git log -1` before starting work.

| App / repository | Branch and verified HEAD | October change |
|---|---|---|
| Archive Assistant — bonny2long/archive_assistant | `master` at `41aa8a1` (PR #6) | Content duplicate guard and serialized moves; origin guard; safe dev defaults |
| Cleaner — bonny2long/cleaner | `main` at `779aed6` (PR #8) | Recoverable trash hold after leftover classification, evidence-scan, origin, and rip-sidecar work |
| BM Radio — bonny2long/BM_radio | `main` at `7cd22a0` | Runbook/start documentation; includes PR #5 removed-path reconciliation and PR #3 origin guard |
| Intake Watcher — bonny2long/intake-watcher | `main` at `7b24d65` (PR #4) | Damaged-state recovery and cheaper fingerprints; includes PR #3 origin guard |

## 4. Non-Negotiable Rules

1. No automatic deletion by Intake Watcher, Archive Assistant, BM Radio, Jellyfin, Immich, or any reader.
2. Only Cleaner may ever delete. It removes reviewed **empty folders** with all four production gates on, and it deletes files only by purging an expired item from its trash hold, which needs its own `ALLOW_TRASH_PURGE` switch and an explicit list from you.
3. Cleaner never deletes a file directly. Duplicates, ticked strays, approved quarantine discards, and known junk are first **moved** into a recoverable `_TRASH` hold (off by default), and stay there for `TRASH_HOLD_DAYS` (14) before they can be purged.
4. No overwrite of existing final destinations, and no duplicates: Archive Assistant never moves a media file whose exact content (SHA-256) is already in the library or in an earlier batch, whatever its name or metadata. Moves run one at a time.
5. No final Archive Assistant move without human approval.
6. No hidden Archive Assistant rescans from review actions. Scans happen when you click Scan ingest.
7. Weak metadata is not trash. It goes to review.
8. Discarding a quarantined item in Archive Assistant deletes nothing. It records a decision for Cleaner.
9. Archive Assistant handles all non-photo intake. Photos belong to Immich.
10. BM Radio reads final libraries only, read-only, and never scans `_INGEST`, `_STAGING`, or `_QUARANTINE`.
11. BM Radio does not own Movies or TV. Jellyfin does.
12. Development reset tools never run against real NAS media.
13. Never commit secrets, `.env` files, databases, caches, media, or backups.
14. RAID-Z1 is fault tolerance, not backup.
15. No public port forwarding. Use LAN, Tailscale, or VPN.
16. Before repairing state, back it up and record exactly what changed.

## 5. Local Layout

```text
C:\Dev\NAS\
  intake-watcher\
  archive_assistant\          backend\archive_assistant.db (SQLite)
  cleaner\
  BM_radio\personal-radio\

C:\NAS-Local\
  nas-data\                   shared data root (section 6)
  App-State\BM-Radio\cache\   BM Radio cache
  App-State\run-logs\         logs and PIDs when apps run in the background
  Restock\                    master copies of the test downloads
  Backups\                    verified backups and repair reports

Docker volume bm-radio-postgres-dev-data   BM Radio PostgreSQL 16
```

Each app reads its paths from its own git-ignored `.env`. Each repository ships a `.env.example` with the local values.

## 6. Folder Contract

```text
nas-data\
  _INGEST\incoming\            Intake Watcher watches
  _INGEST\intake-processing\   Intake Watcher promotion lane
  _INGEST\ready\               Archive Assistant scans
  _INGEST\failed\
  _INGEST\leftover-review\
  _STAGING\
  _QUARANTINE\unknown-type\ | unsupported-file\ | music\discography-excluded\
  _TRASH\                       Cleaner recoverable hold, off by default
  _REPORTS\intake-watcher\ | archive-assistant\ | cleaner\ | move-logs\
  Music\Library\FLAC\ | MP3\    Metadata\  Playlists\  Discographies\
  Movies\Library\  TV\Library\  Books\EPUB\ | PDF\  Audiobooks\Library\
  Photos\  Documents\  Projects\  Backups\
```

Final layouts:

```text
Music/Library/FLAC/<Artist>/<Year - Album>/
Music/Library/MP3/<Artist>/<Year - Album>/
Audiobooks/Library/<Author>/<Year - Title>/     disc folders kept inside
Books/EPUB/<Author>/<Year - Title>/
Books/PDF/<Author>/<Year - Title>/
Movies/Library/<Year - Title>/
TV/Library/<Show>/Season NN/   and   TV/Library/<Show>/Specials/   (OAD, OVA, SP)
```

A discography download is a source container. Each album becomes its own batch and moves into `Music/Library`.

## 7. Production Hardware (locked plan, not purchased)

| Component | Plan | Role |
|---|---|---|
| Chassis | UGREEN NASync DXP4800 Pro | NAS platform |
| Memory | 64GB DDR5 | Containers, databases, cache |
| HDDs | 3 x Seagate IronWolf Pro 14TB CMR | rust-pool, RAID-Z1, about 28TB usable |
| NVMe | 2 x Samsung 9100 Pro 2TB | fast-pool mirror, about 2TB |
| Boot | 128GB internal SSD | TrueNAS only |
| UPS | CyberPower CP1500PFCLCD | Graceful shutdown |
| Network | Cat6A, existing NETGEAR C7000v2 | First deployment LAN |
| Cooling | Arctic P14 Pro | Chassis fan upgrade |
| Bay 4 | Empty | Later expansion |

Re-verify the current stable TrueNAS Community Edition release on installation day.

## 8. TrueNAS Pools (planned)

- **rust-pool:** ingest lanes, final libraries, reports, photos, documents, backups, future camera footage.
- **fast-pool:** application state, BM Radio PostgreSQL, Archive Assistant SQLite, container volumes, caches, database backup staging.

```text
/mnt/fast-pool/apps/{intake-watcher,archive-assistant,cleaner,bm-radio,postgresql,backups,service-config,scripts}
/mnt/rust-pool/   mounted into containers as /app/data
```

Keep SQLite files on a local dataset, never on an SMB or NFS share. Take a ZFS snapshot before any first production cleanup run.

## 9. Ownership and Write Boundaries

| Service | Answers | May write | Must not |
|---|---|---|---|
| Intake Watcher | Is the upload finished? | incoming, processing, ready, failed; its reports | Classify, write libraries, delete |
| Archive Assistant | What is it, where does it go? | Its database; ready, quarantine, staging; approved final folders; manifests, disposition records | Delete, watch active downloads, handle photos |
| Cleaner | Which leftovers are safe to clean? | Its reports; reviewed empty-folder removal; gated moves into `_TRASH`; verified purge of explicitly selected expired holds | Write final libraries, touch active intake, or directly delete source files |
| BM Radio | How do I listen? | Its PostgreSQL database and cache | Touch any media file |

## 10. Intake Watcher

- Watches `_INGEST/incoming` every `POLL_SECONDS` (300) and promotes items unchanged for `STABILITY_SECONDS` (1200, 20 minutes). Use 60 and 30 for quick local tests.
- Never overwrites: a name collision in `ready` is flagged and left in place.
- A folder with no supported media file stays in `incoming` as **Blocked** (`blocked_no_media_files`). Open decision: promote such folders so Archive Assistant can quarantine them.
- A damaged state file is renamed with a `.corrupt-<UTC time>` suffix, logged, and rebuilt from empty state; waiting items safely restart their stability window. Folder fingerprints now use one walk, and the dashboard reuses the inspection result.
- Dashboard: http://127.0.0.1:8091. Tests: 51.

## 11. Archive Assistant

- SQLite by design, with no Alembic migrations. Tables are created at startup.
- Scans only when you click **Scan ingest**. Multi-release downloads become a parent batch; approve its groups in the Review Workspace, then create child batches.
- **Multi-disc grouping:** names ending in a disc marker (`Dune Disc 1`, `Album (Disc 2)`, or `The Wall (1)` with an agreeing disc tag and CD folder) group as one release. Audiobooks without disc tags use disc folder numbers. One stray title or author tag does not split a book when a clear majority agrees.
- Music with repeated track numbers and no disc tags is flagged `disc_number_missing`.
- Folder-name noise (uploader handles, bitrate numbers, emoji, remaster years, Windows " - Copy") no longer leaks into suggestions.
- **Quarantine:** unknown or unsupported items can be quarantined, restored to review, discarded with a reason (nothing deleted), or have a discard undone. Each decision writes a disposition record to `_REPORTS/archive-assistant/dispositions`.
- **Recovery** returns unknown items to quarantine review and refuses moved or quarantined batches.
- **Unknown years:** a known year names the folder `<Year - Title>`. If the year is unknown, the reviewer either enters one or presses **Accept Unknown Year**, and the folder becomes `Unknown Year - <Title>` (for example `Audiobooks/Library/Frank Herbert/Unknown Year - Dune`). A missing year is a warning, not a block; the one exception is a movie inside a collection, which needs a year or an explicit accept. This is a locked Core V1 rule.
- `DEBUG` and `DEV_TOOLS_ENABLED` default to `false`; local development must explicitly enable both before dev-reset tools exist.
- `scripts/repair_foreign_root_batches.py` hides rows left by test runs against another data root, with a verified backup first.
- Dashboard: http://127.0.0.1:5173, API http://127.0.0.1:8001. Core V1 suite: 24 checks; run the targeted safe-default, origin, and content-duplicate checks when changing those areas.

## 12. Cleaner

Timing model (agreed 2026-09-26):

| Step | Value | Status |
|---|---|---|
| Automatic plan | Weekly (`CHECK_INTERVAL_SECONDS=604800`, when `AUTO_RUN=true`) | Built |
| Age gate | 30 days untouched (`MIN_AGE_DAYS=30`) | Built |
| Trash hold | Cleaned items wait 14 days before purge (`TRASH_HOLD_DAYS`) | Built, off by default |

Classifications: `safe_empty_folder`, `known_harmless_trash`, `uncertain_leftover`, `quarantine_hold`, `do_not_touch`, `blocked_too_new`, `blocked_by_missing_evidence`, `blocked_by_destination_missing`.

CD-rip leftovers (`.log`, `.cue`, `.accurip`, `.m3u`, `DR<n>.txt`, `auCDtect.txt`) that remain after a verified move are labeled `known_harmless_trash`. Archive Assistant does not move them into the library, so Cleaner owns them; they move to the trash hold only when `ALLOW_TRASH_HOLD` and `ALLOW_KNOWN_TRASH_DELETE` are on; otherwise they stay report-only.

Cleaner also recognises three more kinds of leftover. They are report-only unless the trash hold is on, and even then they are only moved aside, never deleted:

- **Verified duplicates:** a folder Archive Assistant has no record of (for example a `- Copy` folder) whose media files are all byte-for-byte copies (SHA-256) of files already in a final library.
- **Quarantine discards:** quarantined items whose newest Archive Assistant decision is `discard_approved` and whose files still match what was recorded. Undecided quarantine items are never picked up. Moving a discard also needs `ALLOW_QUARANTINE_DISCARD`.
- **Unrecorded leftovers:** anything else with no record. Listed for a decision, never picked up automatically, because it may be a download not yet scanned; it moves to the trash hold only when you tick it on the dashboard.

**Reviewed empty-folder removal** needs `CLEANER_MODE=production`, `DRY_RUN=false`, `DESTRUCTIVE_ACTIONS_ENABLED=true`, and `ALLOW_EMPTY_FOLDER_REMOVAL=true`. At execution time the folder must also:

- appear in a plan reviewed less than 24 hours ago;
- still be classified safe in a fresh plan;
- sit inside `ready`, `failed`, or `_STAGING`, and not be a lane root;
- not be quarantine, leftover-review, a link, or a junction;
- contain no files anywhere in its tree.

Removal is bottom-up `rmdir` only, and every run writes an execution report.

**The trash hold** (`ALLOW_TRASH_HOLD`, plus the production gates) renames an item into `_TRASH/<run>/<original path>` on the same disk, with a manifest recording the reason, evidence, file inventory, and `purge_after`. Items are re-verified at move time (same category in a plan under 24 hours old, duplicates re-proved by content, folder unchanged, correct lane, no links). **Restore** is always available and never overwrites. **Purge** (`ALLOW_TRASH_PURGE`) deletes only items you explicitly list whose hold has expired and whose files still match the recorded inventory. Cleanup actions are serialized. The dashboard has a Trash Hold panel; the CLI has `trash-move`, `trash-list`, `restore`, and `purge`.

Next priorities, in order:

1. Read every move manifest per source folder, plus Archive Assistant disposition records.
2. Ask Archive Assistant whether any batch from a folder is still pending.
3. Add a Cleaner SQLite ledger for first-seen dates, plan identity, and actions.
Dashboard: http://127.0.0.1:8092. Tests: 126. The local `.env` is report-only; the trash hold is off.

## 13. BM Radio

- PostgreSQL 16 in Docker (`bm-radio-postgres-dev`, loopback `127.0.0.1:55432`), Alembic revision `0001_current_schema_baseline`.
- Reads Music and Audiobooks read-only. **Rescan** on the home page picks up new moves.
- **Audiobooks:** chapters play in path order compared number-aware per folder, so Disc 2 comes before Disc 10. Books with sub-folders show collapsible disc sections that open on the disc you are listening to.
- **Reconciliation:** a successful rescan marks tracks, books, and chapters that disappeared from the configured library roots as unavailable while preserving database history and user state; restored paths become available again. Missing roots and failed scans fail closed instead of hiding the library.
- Accepted library snapshot (2026-09-27): 119 tracks, 119 recordings, 1 audiobook with 396 chapters.
- App http://127.0.0.1:5174, API http://127.0.0.1:8094. PROD0: 63 passed, 0 failed, 4 skipped.
- Phones on home Wi-Fi: `scripts\start_local_lan_demo.ps1`.

## 14. Fresh-Start Acceptance (2026-09-26 to 27)

- Every library file was restored to its original download folder using Archive Assistant's move manifests, then moved to `C:\NAS-Local\Restock`. 769 files (about 12.4GB, unique content; see section 0 for the 3 duplicate fixtures) were verified by SHA-256, with none missing.
- `nas-data`, the Archive Assistant database, the BM Radio database (dropped, then Alembic to head), all reports, and the caches were cleared. Pre-wipe backups were taken and verified.
- Downloads were re-ingested through Intake Watcher, then Archive Assistant, then the final libraries, then BM Radio. Six albums and one 17-disc audiobook moved. Multi-disc releases landed as single releases, and Dune plays in the correct disc and track order.
- Test data found missing in the source: Dune has no Disc 14.

## 15. Backup and Recovery

- **BM Radio:** logical `pg_dump -Fc` dumps only, never raw volume files. Record size, SHA-256, and Alembic revision.
- **Archive Assistant:** use the SQLite backup API, check `pragma integrity_check`, and record the batch count and SHA-256. Its duplicate guard learns prior library content from batches and move records, so if the library survives but this database is lost, restore the database before accepting new intake.
- **Code:** fresh clones from the four GitHub repositories; verify branch and commit.
- **Media:** verify with file counts, bytes, and SHA-256. The master test set is `C:\NAS-Local\Restock`.

## 16. Security

- PostgreSQL loopback or internal only. Dashboards private. No public port forwarding.
- **Origin check:** every app refuses a changing request (POST, PUT, PATCH, DELETE) whose `Origin` header is not allowed, so a web page on another site cannot drive an app through your browser. Loopback addresses are always allowed. To use an app from a LAN or Tailscale address, list that exact address in `ALLOWED_ORIGINS` (Intake Watcher, Archive Assistant, Cleaner) or `BM_RADIO_CORS_ORIGINS` (BM Radio). Requests with no `Origin` header (curl, scripts) and all reads are unaffected.
- BM Radio media mounts read-only. Cleaner writes only its reports until a removal action is deliberately enabled.
- Future TrueNAS identities: least privilege per service, as in section 9.

## 17. Deferred Work

TrueNAS installation and hardware acceptance; production pools and mounts; Tailscale; Jellyfin and Immich; Cleaner pending-batch integration and SQLite ledger; monitoring and UPS integration; off-site backup; Bay 4 expansion; optional 10GbE.

## 18. Documentation Policy

- One current whole-system runbook (this one). Older runbooks are kept as history.
- Each repository's README and `docs/` describe that app as it is now. Dated handoff and audit documents carry a "Historical" banner.
- A tracked copy of this runbook is in `BM_radio/personal-radio/docs/production-upgrade/`, next to the PROD6F whole-NAS handoff.

## 19. Starting Commands

Start in this order, one terminal per line, and keep each window open. Nothing starts on its own after a reboot.

```powershell
# 0. Start Docker Desktop first, then BM Radio PostgreSQL. Wait for "healthy".
docker start bm-radio-postgres-dev
docker inspect bm-radio-postgres-dev --format '{{.State.Health.Status}}'
# 1-2. BM Radio
Set-Location C:\Dev\NAS\BM_radio\personal-radio\backend;  .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8094
Set-Location C:\Dev\NAS\BM_radio\personal-radio\frontend; npm.cmd run dev -- --host 127.0.0.1 --port 5174
# 3-4. Archive Assistant
Set-Location C:\Dev\NAS\archive_assistant\backend;  .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
Set-Location C:\Dev\NAS\archive_assistant\frontend; npm.cmd run dev -- --host 127.0.0.1 --port 5173
# 5. Intake Watcher
Set-Location C:\Dev\NAS\intake-watcher; .\.venv\Scripts\python.exe -m intake_watcher.server --host 127.0.0.1 --port 8091
# 6. Cleaner (report-only unless you enable the trash hold, as needed)
Set-Location C:\Dev\NAS\cleaner; .\.venv\Scripts\python.exe -m cleaner.server --host 127.0.0.1 --port 8092
```

| App | Open | Health |
|---|---|---|
| BM Radio | http://127.0.0.1:5174 | http://127.0.0.1:8094/api/health |
| Archive Assistant | http://127.0.0.1:5173 | http://127.0.0.1:8001/api/health |
| Intake Watcher | http://127.0.0.1:8091 | http://127.0.0.1:8091/api/health |
| Cleaner | http://127.0.0.1:8092 | http://127.0.0.1:8092/api/health |

To stop, press Ctrl+C in each window, and never close one during an Archive Assistant move. `docker stop bm-radio-postgres-dev` is optional. The test baselines are in the Appendix.

`Documents\GitHub\START_ALL_3_NAS_APPS.txt` has the same commands with notes, test commands, and first-time setup.

## 20. System Model

```text
Intake Watcher      watches uploads, waits for stability, promotes to ready
Archive Assistant   scans ready on request, groups releases, you review and approve,
                    moves to final libraries, writes manifests and disposition records
Cleaner             reads move evidence, reports leftovers after 30 days,
                    removes reviewed empty folders when gated on, can move reviewed items
                    into a recoverable hold, and purges only expired verified selections
BM Radio            reads Music and Audiobooks read-only, PostgreSQL, radio and bookshelf
Jellyfin (future)   Movies and TV
Immich (future)     Photos
```

## Appendix: Baselines

| App | Baseline |
|---|---|
| Intake Watcher | 51 tests pass |
| Archive Assistant | Core V1 suite 24 checks; targeted safe-default, origin, and duplicate-guard checks; SQLite integrity ok |
| Cleaner | 126 tests pass; report-only and trash hold off by default |
| BM Radio | PROD0 63 passed, 0 failed, 4 skipped |
