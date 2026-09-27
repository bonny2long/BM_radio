# BM Radio

Private radio, music player, and audiobook bookshelf built from the NAS's final Music and Audiobooks libraries. It reads media read-only and never moves, renames, retags, or deletes anything.

```text
Intake Watcher -> Archive Assistant -> final libraries -> BM Radio (listen)
                                      -> Cleaner (leftovers)
```

## Where it lives

| What | Local | NAS (planned) |
|---|---|---|
| Code | `C:\Dev\NAS\BM_radio\personal-radio` | container images |
| Music | `C:\NAS-Local\nas-data\Music` (read-only) | `/mnt/rust-pool/Music`, read-only mount |
| Audiobooks | `C:\NAS-Local\nas-data\Audiobooks\Library` (read-only) | `/mnt/rust-pool/Audiobooks/Library`, read-only |
| Database | PostgreSQL 16 in Docker, `127.0.0.1:55432`, container `bm-radio-postgres-dev` | PostgreSQL on the fast NVMe pool |
| Cache | `C:\NAS-Local\App-State\BM-Radio\cache` | fast NVMe pool |
| Backend API | http://127.0.0.1:8094 | private LAN or Tailscale only |
| App | http://127.0.0.1:5174 | private LAN or Tailscale only |

## Start

1. Start Docker Desktop, then the database:

```powershell
docker start bm-radio-postgres-dev
```

2. Backend:

```powershell
Set-Location C:\Dev\NAS\BM_radio\personal-radio\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env        # set the real database password
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8094
```

3. Frontend:

```powershell
Set-Location C:\Dev\NAS\BM_radio\personal-radio\frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 5174
```

4. Open http://127.0.0.1:5174. On the home page, **Rescan** under Your Library picks up music and audiobooks that Archive Assistant has moved.

For phones on your home Wi-Fi, `scripts\start_local_lan_demo.ps1` starts the database, backend and frontend together. Use `-Stop` to stop them.

Database migrations use Alembic. To build an empty database at the current schema:

```powershell
$env:BM_RADIO_DB_URL = "<value from backend/.env>"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## Audiobooks

- Chapters play in path order inside the book, compared number-aware per folder, so `Dune Disc 2` comes before `Dune Disc 10` and each disc's tracks stay together. Books with every file in one folder play in file-name order.
- Books with disc or part sub-folders show collapsible **disc sections** on the book page. The disc you are listening to opens automatically. Single-folder books show a plain chapter list.
- Progress is saved per chapter and survives rescans.

## Checks

```powershell
Set-Location C:\Dev\NAS\BM_radio\personal-radio\backend
.\.venv\Scripts\python.exe ..\scripts\check_prod0_baseline.py
```

The PROD0 gate currently gives 63 passed, 0 failed, 4 skipped. `scripts\check_audiobook_multibook_ordering.py` covers chapter order, including multi-disc books.

## Docs

| Doc | Purpose |
|---|---|
| `docs/production-upgrade/` | The current engineering record, one document per production phase (PROD0 to PROD6F) |
| `docs/production-upgrade/BM-PROD6F_Whole_NAS_Handoff_and_Source_of_Truth_Delta.md` | Whole-NAS handoff and source of truth |
| `docs/local-recovery-storage.md` | Current local layout, database, and backups |
| `docs/source-of-truth.md` | BM Radio's role in the NAS |
| `docs/blueprint.md` | Product definition and design direction |
| `docs/runbook.md`, `docs/handoff.md`, `docs/index.md` | Historical June 2026 notes |

## Rules

- Read final libraries only. Never scan `_INGEST`, `_STAGING` or `_QUARANTINE`.
- No file moves, deletes, renames, or tag writes.
- Movies and TV belong to Jellyfin; photos belong to Immich.
- Keep the database and dashboards private. No public port forwarding.
