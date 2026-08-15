# Local Recovery Storage

Updated: 2026-08-15

This computer is the temporary primary development location until the TrueNAS
system is ready. The layout follows the v10 recovery runbook while keeping the
shared archive outside every individual app repository and keeping personal
media and application state out of Git.

## Current local roots

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\
  NAS\
    nas-data\                     shared data root for all four NAS apps
  BM_radio\
    personal-radio\               BM Radio source
    local-state\bm-radio\        BM Radio-owned mutable state
    recovery-docs\               private recovery material
```

The authoritative shared development data root is:

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data
```

BM Radio is configured by `backend/.env`. Media roots point into that shared
`nas-data` tree.
The recovery SQLite database remains at `backend\bm_radio.db` because the
checked-out regression and migration gates explicitly protect and inspect that
development path. It is ignored by Git. Caches and backup staging live under
`local-state\bm-radio`.

The earlier `BM_radio\nas-data` tree is empty and is no longer configured as an
application data source. It may remain temporarily as an ignored recovery
artifact; do not put media there.

## Shared app handoff

```text
copied/test upload
  -> nas-data\_INGEST\incoming
  -> Intake Watcher waits for stability
  -> nas-data\_INGEST\ready
  -> Archive Assistant reviews and organizes approved media
  -> nas-data\Music | Movies | TV | Books | Audiobooks
  -> BM Radio reads final Music/Audiobooks/Books only

Cleaner reads evidence and reports in dry-run mode; it does not participate in
the forward handoff and must not delete anything during recovery.
```

Use these paths when the other repositories are recovered:

| App | Local configuration |
| --- | --- |
| Intake Watcher | `DATA_ROOT=C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data` |
| Archive Assistant | `DATA_ROOT=...\NAS\nas-data`; `INGEST_ROOT=...\NAS\nas-data\_INGEST\ready` |
| Cleaner | `DATA_ROOT=...\NAS\nas-data`; keep `DRY_RUN=true` and destructive actions disabled |
| BM Radio | Music, Audiobooks, and Books roots under `...\NAS\nas-data`; never point it at `_INGEST` |

## Safety rules

- Put only copied/test media in this tree until the recovery gate is green.
- BM Radio reads final `Music`, `Audiobooks`, and optional `Books` libraries.
- BM Radio must never scan `_INGEST`, `_STAGING`, or `_QUARANTINE`.
- Keep file mutation, deletion, tag writing, and ingest scanning disabled.
- Do not commit `backend/.env`, `nas-data`, `local-state`, or `recovery-docs`.

## Future TrueNAS mapping

| Local path | Future NAS role |
| --- | --- |
| `NAS\nas-data\Music` | `/mnt/rust-pool/Music` (read-only to BM Radio) |
| `NAS\nas-data\Audiobooks\Library` | `/mnt/rust-pool/Audiobooks/Library` (read-only) |
| `NAS\nas-data\Books` | `/mnt/rust-pool/Books` (read-only) |
| `backend\bm_radio.db` (local recovery only) | migrate deliberately to PostgreSQL state on fast-pool |
| `local-state\bm-radio\cache` | `/mnt/fast-pool/apps/bm-radio/cache` |
| `local-state\bm-radio\backups` | database backup staging on fast-pool plus independent backup |

When the NAS is ready, change only the environment paths and database URL after
the documented migration, backup, restore, and readiness gates pass. Do not
move the source repository into the media tree.
