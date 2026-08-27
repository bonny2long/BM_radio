# BM-PROD6F Whole-NAS Handoff and Source-of-Truth Delta

Owner: Bonny Makaniankhondo

Date: 2026-08-26

Status: FINAL-LOCAL-ACCEPTANCE PASS

## Durability note

This is the Git-tracked durable copy of the whole-NAS handoff. The convenience copy at `C:\Dev\NAS\BM-PROD6F_Whole_NAS_Handoff_and_Source_of_Truth_Delta.md` is not the only copy or recovery authority.

The BM Radio SHA recorded below is the pushed PROD6F acceptance-report commit. The later documentation-only commit that adds this durable copy is intentionally obtained from repository `HEAD`, because a tracked document cannot contain the SHA of the commit that contains itself.

## Current source of truth

- Active development: `C:\Dev\NAS`
- Active local data: `C:\NAS-Local\nas-data`
- Old OneDrive/Documents copies: **FROZEN BACKUP - NOT ACTIVE DEVELOPMENT**
- Original relocation: 930 files, 12,145,578,589 bytes, zero SHA-256 differences

## Accepted application state

- BM Radio: `main`; accepted code SHA `fb32bf397b86e7b3f8bc87d197f0cc9db0689497`; pushed PROD6F acceptance-report SHA `5e6f9b32bd6eb4be2fe7436a53683951a32832df`; PostgreSQL 16; PROD6A-6E contracts PASS; final PROD0 63 passed, 0 failed, 4 skipped
- Archive Assistant: `master` at `d785d8657bfabb96f1a83d0089d24d4e01ee5328`; SQLite; 70 retained batches; Core V1 and QA1 PASS; audit 0; PostCSS 8.5.26; nanoid 3.3.18
- Intake Watcher: `main` at `6d6434595489ca1a13924089d5db69dd4ba32088`; 14/14 PASS; empty-incoming restart produced 0 promotions
- Cleaner: `main` at `d0a9fc8467241c1891d8138355b52fc61a035f24`; 9/9 PASS; report-only; 0 dangerous actions; deletion NO

Accepted ending application/report SHAs:

- BM Radio acceptance report: `5e6f9b32bd6eb4be2fe7436a53683951a32832df`
- Archive Assistant: `d785d8657bfabb96f1a83d0089d24d4e01ee5328`
- Intake Watcher: `6d6434595489ca1a13924089d5db69dd4ba32088`
- Cleaner: `d0a9fc8467241c1891d8138355b52fc61a035f24`

## Local acceptance delta

- One copied real FLAC album completed Intake -> Archive Assistant -> final Music library -> BM Radio.
- Source/final content comparison: 21 files, zero SHA-256 mismatches.
- Archive Assistant created only batch 70 and moved 21/21 files with both move manifests.
- BM Radio added the album once: 275 physical tracks, 261 logical recordings, 1 audiobook; second scan added 0.
- Search/library projection and HTTP Range playback passed.
- Owner desktop listener and private-LAN physical phone acceptance: PASS.
- Final restart retained 275/261/1, 20 canary tracks, and 51 playback events.
- Cleaner protected the empty fresh ready-shell and never selected final library media for action.

## Architecture boundary

- BM Radio -> PostgreSQL -> Music/Audiobooks
- Archive Assistant -> SQLite -> review/move/manifests
- Intake Watcher -> filesystem/report state -> incoming/ready promotion
- Cleaner -> report/evidence state -> future deletion authority, currently disabled
- Photos -> future Immich path outside Archive Assistant/BM Radio
- Movies/TV -> future Jellyfin consumer

## Startup order

1. Docker/PostgreSQL
2. BM Radio backend and frontend
3. Archive Assistant as needed
4. Intake Watcher as needed
5. Cleaner report-only as needed

## Backup and recovery

- BM Radio: verified custom-format PostgreSQL logical backups under `C:\NAS-Local\Backups\BM-PROD6F\BM-Radio\PostgreSQL`; never copy raw volume files.
- Archive Assistant: verified SQLite backup under `C:\NAS-Local\Backups\BM-PROD6F\Archive-Assistant\SQLite`.
- Git: recover with fresh clones from the four remotes and verify branch/SHA.
- Media: preserve and re-verify `C:\NAS-Local\nas-data` using counts, bytes, and SHA-256.

## Deferred work

TrueNAS SCALE, hardware mounts, Tailscale/private remote access, Jellyfin/Immich production integration, Cleaner deletion enablement, monitoring/UPS, and final hardware backup topology remain explicitly deferred.

Do not start TrueNAS or destructive Cleaner work from this handoff.

Final decision: **BM-PROD6F FINAL-LOCAL-ACCEPTANCE PASS**.
