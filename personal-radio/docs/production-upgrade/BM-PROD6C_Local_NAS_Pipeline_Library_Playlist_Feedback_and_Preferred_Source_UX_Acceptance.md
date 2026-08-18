# BM-PROD6C Local NAS Pipeline, Library, Playlist, Feedback, and Preferred-Source UX Acceptance

BM-PROD6C status: **IN PROGRESS — LIVE PIPELINE AND HUMAN REVIEW PENDING**

Starting BM Radio SHA: `5e3b2be2e5163c37297881dd9d1fcd33d55bd129`

Ending SHA / working-tree state: pending completion review and phase commit.

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

## Live results

- Fixture counts and before hashes: pending.
- Intake unstable/stable promotion, no-edit/no-delete proof, and rerun: pending.
- Archive Assistant SQLite scan, review, explicit approval, destinations, move accounting, and rescan: pending.
- Cleaner dry-run/no-deletion boundary: pending.
- Isolated PostgreSQL 16, Alembic head, read-only final media, and real BM Radio scans: pending.
- Logical/physical identity and duplicate checks: pending.
- Preferred source, override/unset, and single-source fallback: pending.
- Library/search/audiobook UX: pending.
- Feedback persistence and radio causal bridge: pending.
- Playlist and queue/source continuity: pending.
- Artwork: pending or `not_applicable` after fixture inspection.
- Human real-library review: **NOT PROVIDED**. Automation cannot fabricate it.
- Final source hashes, protected active-state equality, and cleanup: pending.
- Contract/PROD0/build/lint/diff: pending.

TrueNAS work, Cleaner deletion, production/original media, active-database scanning, real production-library import, and SQLite retirement are prohibited.

This report may state **BM-PROD6C LOCAL-LIBRARY-UX PASS** only after the live pipeline, human review, final equality, cleanup, and `61 passed / 0 failed / 4 skipped` PROD0 result are all recorded.
