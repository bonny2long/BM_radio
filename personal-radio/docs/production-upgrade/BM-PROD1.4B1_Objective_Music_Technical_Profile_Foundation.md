# BM-PROD1.4B1 - Objective Music Technical Profile Foundation

Owner: Bonny Makaniankhondo
Date: 2026-07-14
Status: PASS

## Scope

BM-PROD1.4B1 adds objective per-file music technical profiles. It records evidence about each physical Track source, but it does not score, rank, or select a preferred source.

## Starting Point

- Starting SHA: `4a6df75b478058bdf3aeec293c4e5ad24ea99291`
- Ending state: working tree contains B1 implementation and regression checks.
- Real application database: `personal-radio/backend/bm_radio.db`
- Real DB population: not performed.
- Real DB read-only census: all existing media and user-state tables remained at 0 rows.

## Technical Profile Schema

B1 adds `MusicTechnicalProfile` / `music_technical_profiles` as a one-to-one profile for a physical `Track` row.

Stored fields include:

- probe status, source, and version
- codec and container
- nullable lossless classification
- sample rate, bit depth, bitrate, channel count
- file size
- ReplayGain gain and peak values
- bounded probe error code
- probed/created/updated timestamps

Required indexes and constraints are present for `track_id`, `probe_status`, `codec`, and `is_lossless`. `track_id` is unique.

## Probe Status

- `ok`: codec/container are known and at least one meaningful stream property is available.
- `partial`: the media opened but important properties are missing or ambiguous.
- `failed`: the probe could not parse/open the supported media file or a deterministic probe exception occurred.

A failed technical probe does not delete, suppress, or mark unavailable a valid physical source.

## Normalization

- Codec and container are stored separately.
- FLAC is `container=flac`, `codec=flac`, lossless true.
- MP3 is `container=mp3`, `codec=mp3`, lossless false.
- WAV/PCM is `container=wav`, `codec=pcm`, lossless true.
- M4A/MP4 distinguishes AAC from ALAC when evidence exists.
- Ambiguous M4A remains `codec=unknown`, `is_lossless=null`, and `probe_status=partial`.
- Lossless state is conservative and nullable.
- Invalid, zero, or negative numeric stream values are stored as null.

## ReplayGain And File Size

ReplayGain parsing accepts common numeric values such as `-7.23 dB`, `+1.50 dB`, and peak values like `0.987654`. Malformed values become null and do not fail the scan.

File size is recorded with a read-only stat. Stat failure produces null and does not fail the scan.

## Scanner Integration

The scanner reuses the existing Mutagen open in `read_metadata(path)` and attaches a `technical` payload from the same media object. It does not open every file a second time solely for B1.

Successful music scans now run:

1. Scan approved media files.
2. Create/update/mark observed `Track` rows.
3. Batch upsert `MusicTechnicalProfile` rows.
4. Batch materialize the music identity graph.
5. Reconcile unseen Tracks unavailable.
6. Complete the `ScanRun` as succeeded.

A technical-profile database persistence failure fails the `ScanRun` and prevents unseen reconciliation. A per-file probe status of `failed` is persisted as profile state and does not fail the scan by itself.

Scanner result counters added:

- `technical_profiles_updated`
- `technical_probe_ok`
- `technical_probe_partial`
- `technical_probe_failed`

## Batch Upsert

`upsert_music_technical_profiles()` performs chunked lookup by Track IDs and updates or creates one profile row per Track. Rescans update the same profile row. The batch chunk size is `500`, and regression coverage verifies profile SELECT behavior is batched rather than one SELECT per Track.

## Lifecycle

- New Track: profile created.
- Identical rescan: same Track ID and same profile ID, values refreshed.
- Track unavailable: Track, profile, and identity graph rows remain.
- Track returns: same Track/profile/identity IDs are reused when identity is unchanged.
- User state including favorites, thumbs, playlist membership, and playback events is preserved.

## Non-Goals Confirmed

The real BM Radio database remained empty.

B1 records objective technical evidence only. B1 does not claim that higher sample rate means a better master. B1 does not choose a preferred Track or Edition. B1 does not change station, queue, playback, or library behavior. Technical probe failure does not delete or suppress a valid indexed physical source.

No archive media file was written, moved, renamed, retagged, normalized, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/models.py`
- `personal-radio/backend/app/music_technical_profile.py`
- `personal-radio/backend/app/scanner/music_scanner.py`
- `personal-radio/backend/scripts/check_prod1_4b1_music_technical_profile.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.4B1_Objective_Music_Technical_Profile_Foundation.md`

## Verification

- Targeted B1 regression: PASS
  - `cd personal-radio/backend; python scripts/check_prod1_4b1_music_technical_profile.py`
- A1 regression: PASS
  - `python scripts/check_prod1_4a1_music_identity_graph.py`
- A2 regression: PASS
  - `python scripts/check_prod1_4a2_scanner_identity_integration.py`
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
- Full production gate: PASS, 23 mandatory passed, 0 failed, 4 skipped
  - `python scripts/check_prod0_baseline.py`
- Diff quality: PASS
  - `git diff --check`

## Deferred Work

- Release/edition evidence refinement where required.
- Automatic preferred-source policy and deterministic resolver.
- Manual preference override foundation.
- Active library/playback/UI preference integration.
- Recording-first station engine and live/acoustic/remix affinity.
- Large-library scanner/station performance.
- Controlled real-media canary after preference pipeline completion.