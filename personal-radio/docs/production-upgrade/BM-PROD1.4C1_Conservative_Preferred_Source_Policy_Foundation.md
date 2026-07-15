# BM-PROD1.4C1 - Conservative Preferred-Source Policy Foundation

Owner: Bonny Makaniankhondo
Date: 2026-07-14
Status: PASS

## Scope

BM-PROD1.4C1 adds a conservative recording-level preferred-source policy foundation. It persists automatic source decisions and future manual override state, and it provides an effective-source resolver for later integration. It does not change scanner, playback, queue, station, library, search, frontend, or public API behavior.

## Starting Point

- Starting SHA: `84a3983b9bcd28a7a8de9fd99e5b9ae812036658`
- Ending state: working tree contains C1 implementation and regression checks.
- Real application database: `personal-radio/backend/bm_radio.db`
- Real DB population: not performed.
- Real DB read-only census: all existing media and user-state tables remained at 0 rows.

## MusicRecordingPreference Schema

C1 adds `MusicRecordingPreference` / `music_recording_preferences` as one durable decision row per `MusicRecording`.

Stored fields include:

- `recording_id`
- `auto_preferred_track_id`
- `user_preferred_track_id`
- `decision_state`
- `confidence`
- `reason_code`
- `policy_version`
- `candidate_count`
- `eligible_candidate_count`
- `evaluated_at`, `created_at`, `updated_at`

Required uniqueness and indexes are present for `recording_id`, automatic/user preferred Track IDs, and `decision_state`.

## Decision Contract

Decision states:

- `preferred`
- `ambiguous`
- `no_eligible_source`

Confidence values:

- `high`
- `medium`
- `low`
- `none`

Policy version:

- `policy_version = 1`

Reason codes are bounded stable strings such as `single_available_source`, `unique_lossless_source`, `multiple_lossless_sources_ambiguous`, `higher_bitrate_same_lossy_codec`, `mixed_lossy_codecs_ambiguous`, and `no_available_source`.

## Automatic Rule Order

The evaluator applies policy version 1 in this conservative order:

1. No available candidates: `no_eligible_source`.
2. One available candidate: high-confidence preference.
3. One known lossless source against lossy/unknown alternatives: high-confidence preference.
4. Multiple known lossless sources: ambiguous.
5. One healthy probe against partial/failed alternatives: medium-confidence preference.
6. Same lossy codec with a unique highest bitrate: medium-confidence preference.
7. Mixed lossy codecs: ambiguous.
8. Remaining multi-source cases: ambiguous.

## Explicit Non-Ranking Rules

C1 does not use higher lossless sample rate, bit depth, bitrate, file size, ReplayGain, remaster naming, anniversary naming, or vinyl/CD naming as automatic proof of a better master.

Multiple available lossless sources remain ambiguous in policy version 1 unless future stronger evidence is added.

C1 may automatically prefer a unique known lossless source over lossy/unknown alternatives.

## Resolver And Overrides

`set_music_recording_user_preference()` stores or clears future manual override state. A non-null override Track must be linked to the same `MusicRecording`. The override may reference an unavailable historical Track and is not erased when unavailable.

`resolve_effective_music_source()` applies:

1. valid available user override
2. valid available automatic preference
3. deterministic available fallback
4. no source

Deterministic fallback is stable and does not get persisted as an automatic preference. Stale automatic preferences and unavailable overrides are not returned for active source resolution.

## Batch Strategy

`evaluate_music_recording_preferences()` loads target recordings, candidates, technical profiles, and existing preferences in chunked grouped queries. It avoids per-recording/per-track SELECT loops and uses a chunk size of `500`.

Evaluation is idempotent: unchanged inputs preserve the same preference row, decision, auto Track, reason code, and candidate counts. Only timestamps may refresh.

## Non-Goals Confirmed

The real BM Radio database remained empty.

C1 stores future manual override state and resolves it safely, but exposes no public override API or UI yet. C1 does not change station, queue, playback, search, library, scanner, or frontend behavior.

No archive media file was read, written, moved, renamed, retagged, transcoded, or deleted by the preference service.

## Files Changed

- `personal-radio/backend/app/models.py`
- `personal-radio/backend/app/music_source_preference.py`
- `personal-radio/backend/scripts/check_prod1_4c1_preferred_source_policy.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.4C1_Conservative_Preferred_Source_Policy_Foundation.md`

## Verification

- Targeted C1 regression: PASS
  - `cd personal-radio/backend; python scripts/check_prod1_4c1_preferred_source_policy.py`
- B1 regression: PASS
  - `python scripts/check_prod1_4b1_music_technical_profile.py`
- A2 regression: PASS
  - `python scripts/check_prod1_4a2_scanner_identity_integration.py`
- A1 regression: PASS
  - `python scripts/check_prod1_4a1_music_identity_graph.py`
- D1 regression: PASS
  - `python scripts/check_prod1_3d1_core_availability_policy.py`
- D2 regression: PASS
  - `python scripts/check_prod1_3d2_active_playback_candidates.py`
- D3 regression: PASS
  - `python scripts/check_prod1_3d3_integrity_reporting.py`
- Music reconciliation regression: PASS
  - `python scripts/check_prod1_3b_music_scan_reconciliation.py`
- Audiobook regressions: PASS
  - `python scripts/check_prod1_3c1_audiobook_scan_progress_safety.py`
  - `python scripts/check_prod1_3c2_audiobook_reconciliation.py`
  - `python scripts/check_aa_manifest_audiobook_import.py`
  - `python scripts/check_audiobook_multibook_ordering.py`
  - `python scripts/check_audiobook_progress_reset.py`
- Backend compile: PASS
  - `python -m compileall app scripts`
- Frontend build: PASS
  - `npm run build`
- Frontend lint: PASS, 0 errors, 8 existing warnings
  - `npm run lint`
- Full production gate: PASS, 24 mandatory passed, 0 failed, 4 skipped
  - `python scripts/check_prod0_baseline.py`
- Diff quality: PASS
  - `git diff --check`

## Deferred Work

- Scanner-driven affected-recording preference re-evaluation.
- Public manual override API and operator controls.
- Participation states such as included/library_only/archived/blocked.
- Active library/queue/playback preferred-source integration.
- Recording-first station engine.
- Live/acoustic/remix station affinity.
- Release/edition-family refinement where stronger evidence exists.
- Large-library scanner and station performance.
- Controlled real-media canary after preference pipeline completion.