# BM-PROD1.2A Production Configuration Core

Owner: Bonny Makaniankhondo
Project: BM Radio Production Upgrade
Date: 2026-07-14
Scope: Canonical application configuration, media-root contract, compatibility aliases, and app-owned storage paths

## Baseline

| Item | Value |
| --- | --- |
| Starting commit | `82b7a9a5afac7de5f51da4918446af605bc1b35f` |
| Starting worktree | Clean |
| Ending state | Pending working-tree changes |

Pre-change gate result:

```text
python scripts/check_prod0_baseline.py
PASS when rerun outside the Windows sandbox Vite spawn restriction
10 mandatory passed, 0 failed, 4 integration checks skipped
```

## Canonical Environment Names

BM-PROD1.2A implements these canonical production-facing names:

```text
BM_RADIO_DB_URL
BM_RADIO_MUSIC_ROOT
BM_RADIO_AUDIOBOOK_ROOT
BM_RADIO_BOOK_ROOT
BM_RADIO_CACHE_ROOT
BM_RADIO_ARTWORK_CACHE_ROOT
BM_RADIO_API_HOST
BM_RADIO_API_PORT
BM_RADIO_CORS_ORIGINS
BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN
```

`BM_RADIO_CORS_ORIGINS` is parsed and validated as configuration only. It is not wired into FastAPI middleware in BM-PROD1.2A.

## Canonical `.env` Location

The backend-owned config file is:

```text
personal-radio/backend/.env
```

`Settings` resolves this path relative to `backend/app/config.py`, not the shell working directory. Real process environment variables still override `.env` values. Tests can instantiate `Settings(_env_file=None)` to avoid loading a developer `.env`.

The root-level `personal-radio/.env.example` is now only a pointer to `backend/.env.example`, preventing two competing configuration examples.

## Precedence Rules

Configuration precedence is:

```text
1. New BM_RADIO_* environment value
2. Supported legacy environment value when the new value is absent
3. Safe application default
```

New canonical values win over conflicting legacy values. In particular, an explicit `BM_RADIO_MUSIC_ROOT` causes derived music child paths to be based on that root rather than legacy leaf overrides.

## Legacy Compatibility Retained

Supported temporary legacy environment aliases:

```text
DATABASE_URL -> BM_RADIO_DB_URL
MUSIC_ROOT -> BM_RADIO_MUSIC_ROOT
AUDIOBOOKS_ROOT -> BM_RADIO_AUDIOBOOK_ROOT
BACKEND_HOST -> BM_RADIO_API_HOST
BACKEND_PORT -> BM_RADIO_API_PORT
```

Legacy Python attribute names such as `MUSIC_FLAC_ROOT`, `MUSIC_MP3_ROOT`, `MUSIC_DISCOGRAPHIES_ROOT`, `AUDIOBOOKS_ROOT`, `DATABASE_URL`, `BACKEND_HOST`, and `BACKEND_PORT` remain resolved compatibility fields for current runtime code and tests.

## Music Configuration

`BM_RADIO_MUSIC_ROOT` is the canonical music base.

Derived paths:

```text
<Music Root>/Library
<Music Root>/Library/FLAC
<Music Root>/Library/MP3
<Music Root>/Discographies
<Music Root>/Playlists
<Music Root>/Metadata
```

BM-PROD1.1 behavior is preserved:

```text
default scan roots: FLAC + MP3
legacy Discographies scan: explicit opt-in only
```

## Audiobook Configuration

Audiobooks remain a first-class BM Radio media domain.

`BM_RADIO_AUDIOBOOK_ROOT` is independent from `BM_RADIO_MUSIC_ROOT`. Audiobook scanning, audiobook manifest import, multi-book ordering, and audiobook progress regressions remain in the production gate and pass.

## Book Configuration

`BM_RADIO_BOOK_ROOT` is configuration-only in BM-PROD1.2A.

BM-PROD1.2A does not add book scanning, book indexing, book routes, or book UI.

## Cache and Artwork Cache Safety

App-owned writable storage roots:

```text
BM_RADIO_CACHE_ROOT
BM_RADIO_ARTWORK_CACHE_ROOT
```

Validation rejects cache and artwork cache roots that resolve inside:

```text
BM_RADIO_MUSIC_ROOT
BM_RADIO_AUDIOBOOK_ROOT
BM_RADIO_BOOK_ROOT
```

Artwork cache under cache root is allowed.

Media roots are rejected when any path component is exactly:

```text
_INGEST
_STAGING
_QUARANTINE
```

## Files Changed

```text
personal-radio/backend/app/config.py
personal-radio/backend/app/db.py
personal-radio/backend/app/routes/library.py
personal-radio/backend/.env.example
personal-radio/.env.example
personal-radio/README.md
personal-radio/backend/scripts/check_prod1_2a_config_contract.py
personal-radio/scripts/check_prod0_baseline.py
personal-radio/docs/production-upgrade/BM-PROD1.2A_Production_Configuration_Core.md
```

## Tests Run

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS before implementation | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 10 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python scripts/check_prod1_2a_config_contract.py` | PASS | Proves canonical names, audiobook independence, derived music roots, legacy aliases, precedence, CORS parsing, cache safety, forbidden lanes, and `.env` isolation. |
| `cd backend; python scripts/check_prod1_1_canonical_music_roots.py` | PASS | BM-PROD1.1 behavior preserved. |
| `cd backend; python scripts/check_aa_manifest_audiobook_import.py` | PASS | Audiobook manifest import preserved. |
| `cd backend; python scripts/check_audiobook_multibook_ordering.py` | PASS | Audiobook ordering preserved. |
| `cd backend; python scripts/check_audiobook_progress_reset.py` | PASS | Audiobook progress behavior preserved. |
| `python scripts/check_prod0_baseline.py` | PASS | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 11 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python -m compileall app scripts` | PASS | Backend app and scripts compiled. |
| `cd frontend; npm run build` | PASS | TypeScript and Vite production build completed. |
| `cd frontend; npm run lint` | PASS | 0 errors, 8 existing baseline warnings. |
| `git diff --check` | PASS | No whitespace errors. |

## Explicit Non-Goals

BM-PROD1.2A does not implement CORS middleware hardening.

BM-PROD1.2A does not implement API docs disablement.

BM-PROD1.2A does not migrate the database to PostgreSQL.

BM-PROD1.2A does not add book scanning.

BM-PROD1.2A does not change database schema, add migrations, implement scan-run reconciliation, optimize stations, or mutate media files.
