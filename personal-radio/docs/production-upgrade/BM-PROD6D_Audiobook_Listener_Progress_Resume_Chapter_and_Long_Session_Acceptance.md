# BM-PROD6D — Audiobook Listener, Progress, Resume, Chapter, and Long-Session Acceptance

Date: 2026-08-18  
Starting commit: `b6d9a1b97c88e35f8774730ffcab2dafb4ce0428`  
Ending implementation commit: pending — the validated correction is in the working tree atop `09702e6ab69ce93ef42ce9e47bed8f29f50e4376`, but the repository metadata write was blocked by the approval service usage limit.

## Entry correction

The PROD6C.2 report now records the accepted implementation commit `b6d9a1b97c88e35f8774730ffcab2dafb4ce0428`. It documents the final bounded open-ended audiobook policy as a 4 MiB initial `bytes=0-` response and 64 KiB later open-ended responses; 256 KiB is labeled only as a superseded experiment.

## Starting capability audit

| Area | Entry classification | Finding |
|---|---|---|
| Audiobook and physical-part identity | Implemented | Existing `Audiobook` and `AudiobookChapter` scanner identities were reused. |
| Progress model | Partial | `AudiobookProgress` existed, but each checkpoint inserted another row and late arrival was not ordered. |
| Detail/resume API | Implemented | Detail returned physical parts and latest valid progress. |
| Browser resume/checkpoints | Partial | Resume and 15-second/pause/end saves existed; part changes and seek completion needed explicit saves. |
| Seek controls | Implemented | Audiobook-only -15/+30 and timeline seek existed. |
| Playback rate | Missing | No audiobook rate state or listener control existed. |
| Completion/replay | Partial | Natural end could mark completion, but the explicit completion row and replay UX were inconsistent. |
| Media delivery | Implemented/locked | Accepted internal Nginx, read-only media, 4 MiB/64 KiB range, and function-scoped DB-session behavior were preserved. |

No duplicate progress subsystem was added.

## Implemented contract

Progress is one authoritative row per audiobook, tied to the current physical `chapter_id`. It stores position seconds, overall percentage, completion state, and the ordered checkpoint in the existing `updated_at` column. No schema migration was added, so the accepted active PostgreSQL and protected SQLite fallback remain compatible and unchanged.

The API updates that row in place under a row lock and collapses any legacy duplicates to the newest row. A checkpoint with an older or equal `checkpointed_at` returns `stale` and cannot move the listener backward. The frontend checkpoints at a bounded 15-second cadence and on pause, seek completion, natural end, and physical-part change; it does not write on every `timeupdate`.

The listener exposes audiobook-only 0.75x, 1x, 1.25x, 1.5x, 1.75x, and 2x speeds. Loading music explicitly restores 1x. Rate changes update the existing audio element and do not reload the source. -15, +30, and timeline seeking remain audiobook-friendly and accessible.

The required mode sequence is `audiobook -> music -> audiobook`; the checkpoint cadence and music-rate reset protect both domains during that transition.

Finished books show Replay and start from the first physical part without automatically deleting their checkpoint/history. An explicit Reset remains available.

## Acceptance environment and media

Live acceptance is restricted to copied real media:

```text
copied_test_media=true
generated_by_acceptance_script=false
original_only_copy=false
```

The harness uses disposable PostgreSQL 16, Alembic head, the real scanner, loopback-only frontend, private backend/database, and read-only Music/Audiobooks/Books mounts. It does no TrueNAS work, generates no media, and snapshots copied source, final media, active PostgreSQL, SQLite fallback, `.env`, and durable evidence.

## Automated and human results

Automated PostgreSQL/real-media result: PASS on isolated PostgreSQL 16 at the accepted Alembic head, including the final schema-preserving rerun.
Scanner identity/rescan duplicates: PASS — 1 audiobook, 1 physical M4B part, 0 rescan duplicates.  
Refresh/new session/frontend/backend/PostgreSQL restart resume: PASS.  
Failure recovery: PASS — database outage returned controlled 500, absent stream returned controlled 404, and progress remained intact through recovery.  
Long-session writes/duplicate rows/out-of-order safety: PASS — 41 bounded checkpoints simulated 7,380 seconds, exactly 1 progress row remained, and the late checkpoint was rejected.  
Completion/replay: PASS — explicit/natural-compatible completion stored `finished`, history remained until explicit Reset, and Replay returned to `in_progress`.  
Physical chapter/part navigation: `not_applicable_single_physical_m4b`; no fake physical parts were created.  
PROD6C.2 latency and DB pool: PASS — final M4B initial 3,043.2 ms, metadata 3,022.7 ms, resume 25.9 ms, seek 25.8 ms, music cold 937.3 ms, music transition p95 777.8 ms, and 18 open streams without pool exhaustion.
Copied-source equality, final-media equality, and protected-state equality: PASS.  
Mobile/accessibility and operator listener review: PASS — the operator tested playback, pause/resume, seeks, every requested speed, refresh/Continue, audiobook/music switching, keyboard controls, and mobile layout; all worked. Automation did not fabricate this result.
Cleanup: PASS — copied source, final media, and protected state remained exactly equal; zero task containers, networks, or volumes remain.

## Final validation

Python compileall: PASS.
Permanent PROD6D contract: PASS, 30 checks.
Prior PROD6C/PROD6B/PROD6A contracts: PASS.
Full PROD0: PASS, 62 passed / 0 failed / 4 skipped.
Frontend production build: PASS.
Frontend lint: PASS with 0 errors and 8 existing warnings.
Git diff check: PASS.
Media/protected-state equality and task-resource cleanup: PASS.
Human listener/mobile acceptance: PASS.
Final commit/status: BLOCKED only on repository metadata write approval; do not label the phase final until the correction commit is created and its SHA is inserted above.
