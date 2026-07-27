# BM Radio Documents Index

Owner: Bonny Makaniankhondo  
Project: NAS System / BM Radio  
Updated: 2026-06-24  
Status: Documentation checkpoint after BM Radio scaffold, shared `nas-data` connection, scanner, playback, and first UI polish passes.

## Purpose

This index records the current BM Radio document pack and where each file should be used.

BM Radio is the fourth custom NAS app. It is separate from Intake Watcher, Archive Assistant, and Cleaner. The first three systems are the back-office media pipeline. BM Radio is the private listening app that reads the final approved Music and Audiobooks libraries.

## Current document pack

| File | Purpose |
|---|---|
| `blueprint.md` | Product definition, design direction, screens, V1/V2 feature map, and experience rules. |
| `runbook.md` | Architecture, local setup, paths, environment variables, API routes, scanner/playback behavior, and safety rules. |
| `source-of-truth.md` | Source-of-truth addendum for how BM Radio fits into the full NAS system. |
| `handoff.md` | Current codebase status, what works, remaining issues, and next coding priorities. |

## Recommended storage location

Copy these files into the BM Radio project:

```text
personal-radio/docs/
```

Suggested final layout:

```text
personal-radio/
  docs/
    index.md
    blueprint.md
    runbook.md
    source-of-truth.md
    handoff.md
```

## Current one-line status

BM Radio can see the shared NAS-style `nas-data` library, scan music and audiobooks, generate stations, stream audio, and show an early premium phone-first UI. The next phase should focus on final UI polish, artwork consistency, station tuning, library browsing, and audiobook bookshelf behavior.
