# Bonny NAS System Master Runbook v12

**Local Workflow Edition**

| | |
|---|---|
| Owner | Bonny Makaniankhondo |
| Updated | 2026-09-27 |
| Project | Personal NAS: Intake Watcher, Archive Assistant, Cleaner, BM Radio |
| Status | Full local workflow re-proven from a clean slate. Hardware and TrueNAS deployment still deferred. |
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

## 2. Current Status (2026-09-27)

| Area | State | Next |
|---|---|---|
| Hardware | Build plan locked, not purchased | Buy and assemble when ready |
| Local data | Fresh start on 2026-09-26; 7 releases re-ingested | Keep using copies from Restock |
| Intake Watcher | 14 tests pass | Decide whether non-media folders should be promoted for quarantine |
| Archive Assistant | Core V1 suite 24 checks pass; quarantine lifecycle; multi-disc grouping | Scheduled scan; pending-batch API for Cleaner |
| Cleaner | 18 tests pass; report-only; 30-day age gate; reviewed empty-folder removal behind four gates | Evidence linking, SQLite ledger, 14-day trash hold |
| BM Radio | PROD0 63 passed, 0 failed, 4 skipped; PostgreSQL 16 | Multi-disc audiobook order and disc sections done |
| Photos | Outside Archive Assistant and BM Radio | Future Immich |
| Movies and TV reader | Archive Assistant prepares folders | Future Jellyfin |
| Remote access | Local only | Future Tailscale |

## 3. Repository State

All four repositories were merged to their default branch on 2026-09-27 through pull requests, then documentation pull requests. Verify with `git log -1` before starting services.

| App | Repository | Default branch | Feature merge |
|---|---|---|---|
| Archive Assistant | bonny2long/archive_assistant | `master` | PR #2, merge `14a847f` |
| Cleaner | bonny2long/cleaner | `main` | PR #1, merge `92c1640` |
| BM Radio | bonny2long/BM_radio | `main` | PR #1, merge `926d2ee` |
| Intake Watcher | bonny2long/intake-watcher | `main` | PR #1, merge `dc94de2` |

Documentation-only pull requests titled "docs: bring documentation up to date" follow each feature merge.

## 4. Non-Negotiable Rules

1. No automatic deletion by Intake Watcher, Archive Assistant, BM Radio, Jellyfin, Immich, or any reader.
2. Only Cleaner may ever delete, and today it may only remove reviewed **empty folders**, only with all four production gates on.
3. Cleaner never deletes a file. File, junk, and quarantine cleanup stay disabled until the evidence, ledger, and 14-day trash hold exist.
4. No overwrite of existing final destinations.
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
| Cleaner | Which leftovers are safe to clean? | Its reports; reviewed empty-folder removal only when gated on | Delete files, touch quarantine or libraries |
| BM Radio | How do I listen? | Its PostgreSQL database and cache | Touch any media file |

## 10. Intake Watcher

- Watches `_INGEST/incoming` every `POLL_SECONDS` (300) and promotes items unchanged for `STABILITY_SECONDS` (1200, 20 minutes). Use 60 and 30 for quick local tests.
- Never overwrites: a name collision in `ready` is flagged and left in place.
- A folder with no supported media file stays in `incoming` as **Blocked** (`blocked_no_media_files`). Open decision: promote such folders so Archive Assistant can quarantine them.
- Dashboard: http://127.0.0.1:8091. Tests: 14.

## 11. Archive Assistant

- SQLite by design, with no Alembic migrations. Tables are created at startup.
- Scans only when you click **Scan ingest**. Multi-release downloads become a parent batch; approve its groups in the Review Workspace, then create child batches.
- **Multi-disc grouping:** names ending in a disc marker (`Dune Disc 1`, `Album (Disc 2)`, or `The Wall (1)` with an agreeing disc tag and CD folder) group as one release. Audiobooks without disc tags use disc folder numbers. One stray title or author tag does not split a book when a clear majority agrees.
- Music with repeated track numbers and no disc tags is flagged `disc_number_missing`.
- Folder-name noise (uploader handles, bitrate numbers, emoji, remaster years, Windows " - Copy") no longer leaks into suggestions.
- **Quarantine:** unknown or unsupported items can be quarantined, restored to review, discarded with a reason (nothing deleted), or have a discard undone. Each decision writes a disposition record to `_REPORTS/archive-assistant/dispositions`.
- **Recovery** returns unknown items to quarantine review and refuses moved or quarantined batches.
- `scripts/repair_foreign_root_batches.py` hides rows left by test runs against another data root, with a verified backup first.
- Dashboard: http://127.0.0.1:5173, API http://127.0.0.1:8001. Core V1 suite: 24 checks.

## 12. Cleaner

Timing model (agreed 2026-09-26):

| Step | Value | Status |
|---|---|---|
| Automatic plan | Weekly (`CHECK_INTERVAL_SECONDS=604800`, when `AUTO_RUN=true`) | Built |
| Age gate | 30 days untouched (`MIN_AGE_DAYS=30`) | Built |
| Trash hold | Cleaned items wait 14 days before purge | **Planned** |

Classifications: `safe_empty_folder`, `known_harmless_trash`, `uncertain_leftover`, `quarantine_hold`, `do_not_touch`, `blocked_too_new`, `blocked_by_missing_evidence`, `blocked_by_destination_missing`.

The only enabled action is **reviewed empty-folder removal**. It needs `CLEANER_MODE=production`, `DRY_RUN=false`, `DESTRUCTIVE_ACTIONS_ENABLED=true`, and `ALLOW_EMPTY_FOLDER_REMOVAL=true`. At execution time the folder must also:

- appear in a plan reviewed less than 24 hours ago;
- still be classified safe in a fresh plan;
- sit inside `ready`, `failed`, or `_STAGING`, and not be a lane root;
- not be quarantine, leftover-review, a link, or a junction;
- contain no files anywhere in its tree.

Removal is bottom-up `rmdir` only, and every run writes an execution report.

Next priorities, in order:

1. Read every move manifest per source folder, plus Archive Assistant disposition records.
2. Ask Archive Assistant whether any batch from a folder is still pending.
3. Add a Cleaner SQLite ledger for first-seen dates, plan identity, and actions.
4. Build the 14-day trash hold, then known-junk cleanup and approved quarantine discards.

Dashboard: http://127.0.0.1:8092. Tests: 18. The local `.env` is report-only.

## 13. BM Radio

- PostgreSQL 16 in Docker (`bm-radio-postgres-dev`, loopback `127.0.0.1:55432`), Alembic revision `0001_current_schema_baseline`.
- Reads Music and Audiobooks read-only. **Rescan** on the home page picks up new moves.
- **Audiobooks:** chapters play in path order compared number-aware per folder, so Disc 2 comes before Disc 10. Books with sub-folders show collapsible disc sections that open on the disc you are listening to.
- Current library (2026-09-27): 119 tracks, 119 recordings, 1 audiobook with 396 chapters.
- App http://127.0.0.1:5174, API http://127.0.0.1:8094. PROD0: 63 passed, 0 failed, 4 skipped.
- Phones on home Wi-Fi: `scripts\start_local_lan_demo.ps1`.

## 14. Fresh-Start Acceptance (2026-09-26 to 27)

- Every library file was restored to its original download folder using Archive Assistant's move manifests, then moved to `C:\NAS-Local\Restock`. 769 files (about 12.4GB) were verified by SHA-256, with none missing.
- `nas-data`, the Archive Assistant database, the BM Radio database (dropped, then Alembic to head), all reports, and the caches were cleared. Pre-wipe backups were taken and verified.
- Downloads were re-ingested through Intake Watcher, then Archive Assistant, then the final libraries, then BM Radio. Six albums and one 17-disc audiobook moved. Multi-disc releases landed as single releases, and Dune plays in the correct disc and track order.
- Test data found missing in the source: Dune has no Disc 14.

## 15. Backup and Recovery

- **BM Radio:** logical `pg_dump -Fc` dumps only, never raw volume files. Record size, SHA-256, and Alembic revision.
- **Archive Assistant:** use the SQLite backup API, check `pragma integrity_check`, and record the batch count and SHA-256.
- **Code:** fresh clones from the four GitHub repositories; verify branch and commit.
- **Media:** verify with file counts, bytes, and SHA-256. The master test set is `C:\NAS-Local\Restock`.

## 16. Security

- PostgreSQL loopback or internal only. Dashboards private. No public port forwarding.
- BM Radio media mounts read-only. Cleaner writes only its reports until a removal action is deliberately enabled.
- Future TrueNAS identities: least privilege per service, as in section 9.

## 17. Deferred Work

TrueNAS installation and hardware acceptance; production pools and mounts; Tailscale; Jellyfin and Immich; Cleaner file and quarantine cleanup; monitoring and UPS integration; off-site backup; Bay 4 expansion; optional 10GbE.

## 18. Documentation Policy

- One current whole-system runbook (this one). Older runbooks are kept as history.
- Each repository's README and `docs/` describe that app as it is now. Dated handoff and audit documents carry a "Historical" banner.
- A tracked copy of this runbook is in `BM_radio/personal-radio/docs/production-upgrade/`, next to the PROD6F whole-NAS handoff.

## 19. Starting Commands

```powershell
docker start bm-radio-postgres-dev
# BM Radio
Set-Location C:\Dev\NAS\BM_radio\personal-radio\backend;  .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8094
Set-Location C:\Dev\NAS\BM_radio\personal-radio\frontend; npm.cmd run dev -- --host 127.0.0.1 --port 5174
# Archive Assistant
Set-Location C:\Dev\NAS\archive_assistant\backend;  .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
Set-Location C:\Dev\NAS\archive_assistant\frontend; npm.cmd run dev -- --host 127.0.0.1 --port 5173
# Intake Watcher
Set-Location C:\Dev\NAS\intake-watcher; .\.venv\Scripts\python.exe -m intake_watcher.server --host 127.0.0.1 --port 8091
# Cleaner (report-only)
Set-Location C:\Dev\NAS\cleaner; .\.venv\Scripts\python.exe -m cleaner.server --host 127.0.0.1 --port 8092
```

`Documents\GitHub\START_ALL_3_NAS_APPS.txt` has the same commands with notes.

## 20. System Model

```text
Intake Watcher      watches uploads, waits for stability, promotes to ready
Archive Assistant   scans ready on request, groups releases, you review and approve,
                    moves to final libraries, writes manifests and disposition records
Cleaner             reads move evidence, reports leftovers after 30 days,
                    removes reviewed empty folders only when gated on
BM Radio            reads Music and Audiobooks read-only, PostgreSQL, radio and bookshelf
Jellyfin (future)   Movies and TV
Immich (future)     Photos
```

## Appendix: Baselines

| App | Baseline |
|---|---|
| Intake Watcher | 14 tests pass |
| Archive Assistant | Core V1 suite 24 checks pass; SQLite integrity ok |
| Cleaner | 18 tests pass; report-only |
| BM Radio | PROD0 63 passed, 0 failed, 4 skipped |
