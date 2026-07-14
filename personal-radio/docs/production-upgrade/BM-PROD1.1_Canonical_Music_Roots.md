# BM-PROD1.1 Canonical Music Roots

Owner: Bonny Makaniankhondo
Project: BM Radio Production Upgrade
Date: 2026-07-14
Scope: Canonical music scan-root selection only

## Baseline

| Item | Value |
| --- | --- |
| Starting commit | `2e0e58a7125f4a5b9939e9c9382053b0bc5ceb22` |
| Starting worktree | Clean |
| Ending state | Pending working-tree changes |

Pre-change gate result:

```text
python scripts/check_prod0_baseline.py
PASS when rerun outside the Windows sandbox Vite spawn restriction
9 mandatory passed, 0 failed, 4 integration checks skipped
```

## Root Policy

BM Radio music scanning now uses one centralized policy helper:

```text
configured_music_scan_roots()
```

Default configured roots, in deterministic order:

```text
MUSIC_FLAC_ROOT
MUSIC_MP3_ROOT
```

Compatibility behavior:

```text
BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN=false
  -> scan only MUSIC_FLAC_ROOT and MUSIC_MP3_ROOT

BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN=true
  -> scan MUSIC_FLAC_ROOT, MUSIC_MP3_ROOT, and MUSIC_DISCOGRAPHIES_ROOT
```

The helper de-duplicates configured roots before existence checks. Missing canonical roots are reported as skipped by `scan_music()` and do not trigger a broader fallback to `MUSIC_ROOT`, `MUSIC_LIBRARY_ROOT`, or `NAS_DATA_ROOT`.

## Compatibility Flag

| Setting | Default | Purpose |
| --- | --- | --- |
| `BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN` | `false` | Temporary explicit opt-in for legacy `Music/Discographies` scanning. |

The setting is visible in `backend/.env.example` and does not rename the rest of the configuration contract. The full `BM_RADIO_*` migration remains BM-PROD1.2.

## Scanner Result Observability

`scan_music()` now reports:

```text
legacy_discography_scan_enabled
```

When legacy mode is disabled, `MUSIC_DISCOGRAPHIES_ROOT` is not part of the configured scan roots and does not appear as scanned or skipped merely because the directory exists.

## Files Changed

```text
personal-radio/backend/app/config.py
personal-radio/backend/app/scanner/music_scanner.py
personal-radio/backend/.env.example
personal-radio/backend/scripts/check_prod1_1_canonical_music_roots.py
personal-radio/scripts/check_prod0_baseline.py
personal-radio/docs/production-upgrade/BM-PROD1.1_Canonical_Music_Roots.md
```

## Tests Run

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS before implementation | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 9 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python scripts/check_prod1_1_canonical_music_roots.py` | PASS | Proves default canonical policy, explicit legacy opt-in, no broad fallback, de-duplication, and scanner result policy. |

Post-change validation:

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 10 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python scripts/check_prod1_1_canonical_music_roots.py` | PASS | Targeted BM-PROD1.1 regression passed. |
| `cd backend; python -m compileall app scripts` | PASS | Backend app and scripts compiled. |
| `cd frontend; npm run build` | PASS | TypeScript and Vite production build completed. |
| `cd frontend; npm run lint` | PASS | 0 errors, 8 existing baseline warnings. |

## Explicit Statements

Music/Library/FLAC and Music/Library/MP3 are canonical.

Music/Discographies is optional legacy compatibility input only.

Legacy scanning is disabled by default.

Existing previously indexed legacy rows are not reconciled in BM-PROD1.1.

## Known Non-Goals

BM-PROD1.1 does not implement:

- BM-PROD1.2 production configuration contract;
- BM-PROD1.3 scan-run reconciliation;
- database row deletion, stale marking, or unavailable-path handling;
- artist, release, recording/work identity migration;
- station generation optimization;
- frontend visual or playback changes;
- PostgreSQL, Docker, or TrueNAS deployment changes.

## Media Safety

No media files are moved, deleted, renamed, retagged, or modified. BM Radio remains a read-only consumer of final library files and Archive Assistant metadata/manifests.
