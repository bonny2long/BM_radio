# BM-PROD1.4D1 - Recording Curation and Preference Control API

Starting commit: `957c6c311470cabe9515753697f295b24b740e5d`
Ending state: working tree implementation pending commit

## Summary

BM-PROD1.4D1 adds a backend-only control plane for recording curation. It introduces `MusicRecordingParticipation` as a sparse one-to-one policy row for `MusicRecording` and exposes private inspection/control endpoints at `/api/music/recordings`.

The real BM Radio database remained empty.

D1 adds a backend control plane only. No participation state is enforced by normal library/search/queue/playback/station/media routes yet.

## Participation Model

`music_recording_participation` stores explicit listener participation policy:

- `recording_id` is unique and indexed.
- `participation_state` is indexed.
- `state_source` is indexed.
- `reason_code` is nullable and bounded to 100 characters.

No row means `participation_state = included` with `explicit = false`.

Allowed participation states:

- `included`: normal listener experience default.
- `library_only`: visible/manual-listening policy for future enforcement, excluded from automatic radio later.
- `archived`: preserved/indexed, hidden from normal listener surfaces later.
- `blocked`: preserved/indexed, excluded from active playback later.

Allowed state sources:

- `user`: used by D1 write endpoints.
- `system`: reserved for future integrity/review automation.

Participation applies to MusicRecording listener policy. Physical-source preference remains a separate `MusicRecordingPreference` concern. A lower-quality alternate physical source is not automatically archived merely because another Track is preferred.

## Service Contract

`backend/app/music_recording_participation.py` provides:

- `get_music_recording_participation()` with sparse default semantics.
- `set_music_recording_participation()` with state/source validation and bounded reason codes.
- `clear_music_recording_participation()` deleting only the explicit policy row.

Clearing explicit state returns the Recording to implicit `included` and does not delete Recording, Track, identity, profile, preference, user history, playlist, or playback rows.

## Control API

Registered under `/api/music/recordings`:

- `GET /{recording_id}/control`
- `PUT /{recording_id}/preferred-track`
- `DELETE /{recording_id}/preferred-track`
- `PUT /{recording_id}/participation`
- `DELETE /{recording_id}/participation`

The control detail response includes:

- recording identity
- effective participation state
- stored preference row
- effective source resolution
- all physical source candidates

Candidate evidence includes Track metadata, relative path only, identity IDs, release context, edition/source context, technical profile fields including ReplayGain values, and auto/user/effective preference flags.

Absolute host filesystem paths are not serialized.

Candidate order is deterministic: effective source, user-preferred source, automatic-preferred source, available sources, then Track ID ascending.

Manual preferred-source writes call the existing `set_music_recording_user_preference()` authority. D1 does not duplicate or replace the C1 preference algorithm and does not use the legacy extension-based `release_preferences.py` heuristic as authority.

## Error Behavior

- Unknown Recording: `404`
- Unknown Track for preferred-track write: `404`
- Track linked to another Recording: `409`
- Invalid participation state: `422`

Unavailable linked Tracks may be stored as user overrides. The effective resolver falls back while unavailable and returns to the user override when it is available again.

## Query Efficiency

The control detail endpoint loads candidate evidence with a focused joined query instead of per-candidate identity/edition/release/profile lookups. The D1 regression exercises 100 candidates and asserts bounded SELECT growth.

## Scanner Boundary

Scanner-driven C2 preference re-evaluation remains unchanged. Normal scans do not create participation rows and do not reset user participation. The sparse default remains `included`.

## Reader Enforcement Boundary

D1 does not modify normal reader behavior:

- library
- search
- queue
- playlists
- stations
- playback
- media streaming
- frontend

A blocked Recording may still be reachable through legacy Track-centric media routes until the later active reader/playback enforcement task.

## Media Mutation Boundary

No archive media file was written, moved, renamed, retagged, transcoded, or deleted.

## Files Changed

- `personal-radio/backend/app/models.py`
- `personal-radio/backend/app/music_recording_participation.py`
- `personal-radio/backend/app/routes/music_recordings.py`
- `personal-radio/backend/app/main.py`
- `personal-radio/backend/scripts/check_prod1_4d1_recording_control_api.py`
- `personal-radio/scripts/check_prod0_baseline.py`
- `personal-radio/docs/production-upgrade/BM-PROD1.4D1_Recording_Curation_and_Preference_Control_API.md`

## Validation

Targeted D1 regression:

```text
PASS: BM-PROD1.4D1 recording curation and preference control API
```

Full gate result after D1:

```text
26 mandatory passed
0 failed
4 skipped
```