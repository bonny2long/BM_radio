# Local Storage and Recovery

Updated: 2026-09-27 (runbook v12)

This computer is the primary development location until the TrueNAS system is built. Code, media and application state live in separate roots, and none of the media or state is in Git.

## Current local roots

```text
C:\Dev\NAS\                       active code (one Git repo per app)
  intake-watcher\
  archive_assistant\
  cleaner\
  BM_radio\personal-radio\

C:\NAS-Local\
  nas-data\                       shared data root for all four apps
  App-State\BM-Radio\cache\       BM Radio cache and artwork cache
  Restock\                        master copies of the test downloads
  Backups\                        verified backups (database dumps, repair reports)
```

Old copies under `C:\Users\...\Documents\GitHub` are frozen backups. Do not run, edit or test them.

## BM Radio state

| State | Where | Backup |
|---|---|---|
| Database | PostgreSQL 16, Docker container `bm-radio-postgres-dev`, volume `bm-radio-postgres-dev-data`, `127.0.0.1:55432` | `pg_dump -Fc` logical dump, never raw volume files |
| Cache | `C:\NAS-Local\App-State\BM-Radio\cache` | Rebuildable, not backed up |
| Settings | `backend\.env` (ignored by Git) | Keep a private copy |

Take a verified logical backup:

```powershell
docker exec bm-radio-postgres-dev pg_dump -U bm_radio_app -d bm_radio -Fc -f /tmp/bm_radio.dump
docker cp bm-radio-postgres-dev:/tmp/bm_radio.dump C:\NAS-Local\Backups\<date>\bm_radio.dump
docker exec bm-radio-postgres-dev pg_restore --list /tmp/bm_radio.dump
docker exec bm-radio-postgres-dev rm /tmp/bm_radio.dump
```

Record the file size, SHA-256, and the Alembic revision (`select version_num from alembic_version`).

## Shared app handoff

```text
copied download
  -> nas-data\_INGEST\incoming
  -> Intake Watcher waits for stability
  -> nas-data\_INGEST\ready
  -> Archive Assistant reviews and moves approved media
  -> nas-data\Music | Movies | TV | Books | Audiobooks
  -> BM Radio reads Music and Audiobooks (Rescan on the home page)

Cleaner reports leftovers in ready after 30 days; it never touches final libraries.
```

| App | Local configuration |
| --- | --- |
| Intake Watcher | `DATA_ROOT=C:/NAS-Local/nas-data` |
| Archive Assistant | `DATA_ROOT=C:/NAS-Local/nas-data`, `INGEST_ROOT=C:/NAS-Local/nas-data/_INGEST/ready` |
| Cleaner | `DATA_ROOT=C:/NAS-Local/nas-data`, report-only by default |
| BM Radio | Music and Audiobooks roots under `C:/NAS-Local/nas-data`; never `_INGEST` |

## Safety rules

- Only copied test media lives in `nas-data`. Master copies are in `C:\NAS-Local\Restock`.
- BM Radio reads final `Music`, `Audiobooks`, and optional `Books` only.
- Keep file mutation, deletion, tag writing, and ingest scanning disabled.
- Never commit `backend/.env`, databases, caches, media, or backups.

## TrueNAS mapping (planned)

| Local | NAS |
| --- | --- |
| `nas-data\Music` | `/mnt/rust-pool/Music`, read-only to BM Radio |
| `nas-data\Audiobooks\Library` | `/mnt/rust-pool/Audiobooks/Library`, read-only |
| `nas-data\Books` | `/mnt/rust-pool/Books`, read-only |
| PostgreSQL volume | `/mnt/fast-pool/apps/postgresql` |
| `App-State\BM-Radio\cache` | `/mnt/fast-pool/apps/bm-radio/cache` |
| `Backups` | fast-pool backup staging plus an independent off-site copy |

Move to the NAS by restoring a verified logical dump and changing only environment paths and the database URL, after the backup, restore and readiness gates pass.
