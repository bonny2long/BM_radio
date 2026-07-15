# BM-PROD1.5B - Seed Version Affinity and Adaptive Fallback

Owner: Bonny Makaniankhondo
Date: 2026-07-15
Starting commit: 08c5fad81f133e8c7eb8c6839125c93ef714c518
Ending state: working tree implementation for BM-PROD1.5B

## Summary

BM-PROD1.5B adds seed-derived version-character affinity to Song Radio. The policy applies only when Song Radio has an identity-backed seed whose `MusicRecording.recording_type` is `live`, `acoustic`, `remix`, or `instrumental`.

The real BM Radio database remained empty. Validation used temporary SQLite databases and synthetic `MusicRecording` / `Track` graphs. No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/station_version_affinity.py`
- `personal-radio/backend/app/station_engine.py`
- `personal-radio/backend/app/station_intelligence.py`
- `personal-radio/backend/app/station_candidates.py`
- `personal-radio/backend/app/queue_payloads.py`
- `personal-radio/backend/scripts/check_prod1_5a_recording_first_station_candidates.py`
- `personal-radio/backend/scripts/check_prod1_5b_station_version_affinity.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.5B_Seed_Version_Affinity_and_Adaptive_Fallback.md`

## Seed-Derived Mapping

BM-PROD1.5B derives Song Radio version affinity only from first-class `MusicRecording.recording_type`:

- `live` -> live affinity
- `acoustic` -> acoustic affinity
- `remix` -> remix affinity
- `instrumental` -> instrumental affinity
- `unknown`, `radio_edit`, null, and identity-less seeds -> balanced

The station layer does not infer live/acoustic/remix/instrumental character from title, filename, album title, or path strings.

## Compatibility Matrix

Focused affinity classifies identity-backed candidates into `primary`, `adjacent`, `neutral`, and `other`; identity-less fallback tracks are `legacy_unknown`.

- Live: primary `live`; adjacent `acoustic`; neutral `unknown`, `radio_edit`, `studio`, `standard`; other `remix`, `instrumental`
- Acoustic: primary `acoustic`; adjacent `live`; neutral ordinary/unknown/radio edit; other `remix`, `instrumental`
- Remix: primary `remix`; neutral ordinary/unknown/radio edit; other `live`, `acoustic`, `instrumental`
- Instrumental: primary `instrumental`; adjacent `acoustic`; neutral ordinary/unknown/radio edit; other `live`, `remix`
- Balanced: no focused tier receives a score preference

## Score Constants

Version affinity is bounded and explainable:

- `version_affinity_primary`: `+1.2`
- `version_affinity_adjacent`: `+0.55`
- `version_affinity_neutral`: `0.0`
- `version_affinity_other`: `-0.2`
- `version_affinity_legacy`: `0.0`

These values are smaller than the existing profile/genre overlap signals and far weaker than hard exclusions such as thumbs-down. Existing Song Radio musical relevance, feedback, participation, recent-history, seed/current-queue exclusion, coherence, and spacing rules remain authoritative.

## Adaptive Fill

Focused affinity is soft and adaptive rather than a rigid output ratio. Song Radio still builds a Recording-first candidate pool, applies normal coherence and feedback rules, scores musical relevance, adds the bounded affinity part, and then interleaves candidates within the existing musical tiers using soft character targets.

A focused station prefers matching Recording character but may use adjacent and neutral fallback material when the library is small. No-primary and fallback-heavy states are debug warnings, not errors.

## Source Separation

Version affinity ranks logical `MusicRecording` candidates. Physical source preference remains a separate step after Recording selection. A higher-resolution standard Recording is not a file-quality replacement for a selected live/acoustic/remix/instrumental Recording. A user source override changes the returned physical file without changing the Recording's affinity tier.

## Debug Contract

Song Radio debug output now includes a top-level `version_affinity` summary with:

- `mode`
- `source`
- `seed_recording_id`
- `seed_recording_type`
- `candidate_distribution`
- `selected_distribution`
- `fallback_used`

Song debug selected/rejected rows include `version_affinity_mode`, `version_affinity_tier`, and a version-affinity score part. Warnings are bounded to sparse/no-primary/fallback-heavy states.

Normal and debug Song Radio paths use the same affinity derivation, tier classification, and adaptive ordering helpers.

## Scope Boundaries

BM-PROD1.5B does not add public version-mode request fields, Station schema columns, or frontend controls. Non-Song station types retain BM-PROD1.5A balanced Recording-first behavior.

The shared station-window title key now uses `recording:<id>` for identity-backed station candidates so distinct live/acoustic/remix/instrumental recordings are not collapsed by normalized-title similarity.

## Query and Read-Only Boundary

Candidate objects already carry `recording_type` and `version_hint`, so affinity scoring does not query `MusicRecording` once per candidate. The targeted regression includes a 100+ Recording bounded-query guard.

Station generation remains read-only. It does not write preference, participation, feedback, or playback-history tables.

## Validation

Targeted regressions passed:

```text
cd personal-radio/backend
python scripts/check_prod1_5b_station_version_affinity.py
PASS: BM-PROD1.5B seed version affinity and adaptive fallback

python scripts/check_prod1_5a_recording_first_station_candidates.py
PASS: BM-PROD1.5A recording-first station candidate foundation
```

Permanent gate wiring now includes:

```text
backend/scripts/check_prod1_5b_station_version_affinity.py
```

Full production gate result:

```text
python scripts/check_prod0_baseline.py
BM-PROD0 BASELINE GATE: PASS
Mandatory: 33 passed, 0 failed
Optional/integration: 4 skipped
```

Optional personal-library station scripts remain optional/integration checks because they require populated local library/profile state, fresh local DB schema, or optional `httpx`. BM-PROD1.5B did not populate or upgrade the local personal library to force those scripts to pass.

## Deferred Work

- explicit listener-selectable version mode controls
- saved station version-affinity persistence if later required
- frontend curation/source/version controls
- release/edition-family refinement
- scanner full-table startup-map scaling
- larger-library station retrieval/performance profiling
- controlled real-media canary after radio identity/affinity validation