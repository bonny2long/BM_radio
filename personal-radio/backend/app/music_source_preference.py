from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

from . import models
from .scan_runs import LIBRARY_AVAILABLE

PREFERENCE_POLICY_VERSION = 1
PREFERENCE_BATCH_CHUNK_SIZE = 500

DECISION_PREFERRED = "preferred"
DECISION_AMBIGUOUS = "ambiguous"
DECISION_NO_ELIGIBLE_SOURCE = "no_eligible_source"

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_NONE = "none"

REASON_SINGLE_AVAILABLE_SOURCE = "single_available_source"
REASON_UNIQUE_LOSSLESS_SOURCE = "unique_lossless_source"
REASON_UNIQUE_HEALTHY_PROBE = "unique_healthy_probe"
REASON_HIGHER_BITRATE_SAME_LOSSY_CODEC = "higher_bitrate_same_lossy_codec"
REASON_MULTIPLE_LOSSLESS_AMBIGUOUS = "multiple_lossless_sources_ambiguous"
REASON_MIXED_LOSSY_CODECS_AMBIGUOUS = "mixed_lossy_codecs_ambiguous"
REASON_MULTIPLE_EQUIVALENT_AMBIGUOUS = "multiple_equivalent_sources_ambiguous"
REASON_INSUFFICIENT_TECHNICAL_EVIDENCE = "insufficient_technical_evidence"
REASON_NO_AVAILABLE_SOURCE = "no_available_source"
REASON_USER_OVERRIDE = "user_override"
REASON_USER_OVERRIDE_UNAVAILABLE_FALLBACK = "user_override_unavailable_fallback"
REASON_AUTOMATIC_PREFERENCE = "automatic_preference"
REASON_DETERMINISTIC_FALLBACK = "deterministic_fallback"

SOURCE_USER_OVERRIDE = "user_override"
SOURCE_AUTOMATIC_PREFERENCE = "automatic_preference"
SOURCE_DETERMINISTIC_FALLBACK = "deterministic_fallback"
SOURCE_NO_SOURCE = "no_source"

LOSSY_CODECS = {"mp3", "aac", "vorbis", "opus"}


@dataclass(frozen=True)
class Candidate:
    recording_id: int
    track_id: int
    path: str
    library_availability: str | None
    probe_status: str | None
    codec: str | None
    is_lossless: bool | None
    bitrate_bps: int | None

    @property
    def available(self) -> bool:
        return self.library_availability == LIBRARY_AVAILABLE

    @property
    def known_lossy(self) -> bool:
        return self.is_lossless is False and (self.codec or "").lower() in LOSSY_CODECS


@dataclass(frozen=True)
class PreferenceDecision:
    decision_state: str
    auto_preferred_track_id: int | None
    confidence: str
    reason_code: str
    candidate_count: int
    eligible_candidate_count: int


@dataclass(frozen=True)
class MusicSourceResolution:
    recording_id: int
    track_id: int | None
    source: str
    decision_state: str
    confidence: str
    reason_code: str
    user_override_track_id: int | None
    auto_preferred_track_id: int | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def chunked(values: Iterable[int], size: int = PREFERENCE_BATCH_CHUNK_SIZE):
    chunk = []
    for value in values:
        chunk.append(int(value))
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def unique_ints(values: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(int(value) for value in values))


def deterministic_fallback(candidates: list[Candidate]) -> Candidate | None:
    available = [candidate for candidate in candidates if candidate.available]
    if not available:
        return None
    return sorted(available, key=lambda candidate: (candidate.track_id, (candidate.path or "").lower()))[0]


def evaluate_candidates(candidates: list[Candidate]) -> PreferenceDecision:
    unique_by_track = {candidate.track_id: candidate for candidate in candidates}
    all_candidates = list(unique_by_track.values())
    eligible = [candidate for candidate in all_candidates if candidate.available]
    candidate_count = len(all_candidates)
    eligible_count = len(eligible)

    if eligible_count == 0:
        return PreferenceDecision(DECISION_NO_ELIGIBLE_SOURCE, None, CONFIDENCE_NONE, REASON_NO_AVAILABLE_SOURCE, candidate_count, eligible_count)
    if eligible_count == 1:
        return PreferenceDecision(DECISION_PREFERRED, eligible[0].track_id, CONFIDENCE_HIGH, REASON_SINGLE_AVAILABLE_SOURCE, candidate_count, eligible_count)

    known_lossless = [candidate for candidate in eligible if candidate.is_lossless is True]
    if len(known_lossless) == 1:
        return PreferenceDecision(DECISION_PREFERRED, known_lossless[0].track_id, CONFIDENCE_HIGH, REASON_UNIQUE_LOSSLESS_SOURCE, candidate_count, eligible_count)
    if len(known_lossless) > 1:
        return PreferenceDecision(DECISION_AMBIGUOUS, None, CONFIDENCE_NONE, REASON_MULTIPLE_LOSSLESS_AMBIGUOUS, candidate_count, eligible_count)

    healthy = [candidate for candidate in eligible if candidate.probe_status == "ok"]
    if len(healthy) == 1:
        return PreferenceDecision(DECISION_PREFERRED, healthy[0].track_id, CONFIDENCE_MEDIUM, REASON_UNIQUE_HEALTHY_PROBE, candidate_count, eligible_count)

    if all(candidate.known_lossy for candidate in eligible):
        codecs = {(candidate.codec or "").lower() for candidate in eligible}
        if len(codecs) == 1:
            known_bitrate = [candidate for candidate in eligible if candidate.bitrate_bps is not None]
            if len(known_bitrate) >= 2:
                highest = max(candidate.bitrate_bps or 0 for candidate in known_bitrate)
                winners = [candidate for candidate in known_bitrate if candidate.bitrate_bps == highest]
                if len(winners) == 1:
                    return PreferenceDecision(DECISION_PREFERRED, winners[0].track_id, CONFIDENCE_MEDIUM, REASON_HIGHER_BITRATE_SAME_LOSSY_CODEC, candidate_count, eligible_count)
        elif len(codecs) > 1:
            return PreferenceDecision(DECISION_AMBIGUOUS, None, CONFIDENCE_NONE, REASON_MIXED_LOSSY_CODECS_AMBIGUOUS, candidate_count, eligible_count)

    if any(candidate.probe_status in {None, "partial", "failed"} or candidate.is_lossless is None for candidate in eligible):
        return PreferenceDecision(DECISION_AMBIGUOUS, None, CONFIDENCE_NONE, REASON_INSUFFICIENT_TECHNICAL_EVIDENCE, candidate_count, eligible_count)
    return PreferenceDecision(DECISION_AMBIGUOUS, None, CONFIDENCE_NONE, REASON_MULTIPLE_EQUIVALENT_AMBIGUOUS, candidate_count, eligible_count)


def music_recording_ids_for_track_ids(
    db: Session,
    *,
    track_ids: list[int],
) -> set[int]:
    ids = unique_ints(track_ids)
    if not ids:
        return set()
    recording_ids: set[int] = set()
    for chunk in chunked(ids):
        rows = (
            db.query(models.MusicTrackIdentity.recording_id)
            .filter(models.MusicTrackIdentity.track_id.in_(chunk))
            .all()
        )
        recording_ids.update(row[0] for row in rows if row[0] is not None)
    return recording_ids

def _target_recording_ids(db: Session, recording_ids: list[int] | None) -> list[int]:
    if recording_ids is not None:
        return unique_ints(recording_ids)
    return [row[0] for row in db.query(models.MusicRecording.id).order_by(models.MusicRecording.id.asc()).all()]


def _load_candidates(db: Session, recording_ids: list[int]) -> dict[int, list[Candidate]]:
    candidates = {recording_id: [] for recording_id in recording_ids}
    for chunk in chunked(recording_ids):
        rows = (
            db.query(
                models.MusicTrackIdentity.recording_id,
                models.Track.id,
                models.Track.path,
                models.Track.library_availability,
                models.MusicTechnicalProfile.probe_status,
                models.MusicTechnicalProfile.codec,
                models.MusicTechnicalProfile.is_lossless,
                models.MusicTechnicalProfile.bitrate_bps,
            )
            .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
            .outerjoin(models.MusicTechnicalProfile, models.MusicTechnicalProfile.track_id == models.Track.id)
            .filter(models.MusicTrackIdentity.recording_id.in_(chunk))
            .all()
        )
        for row in rows:
            candidates.setdefault(row.recording_id, []).append(Candidate(
                recording_id=row.recording_id,
                track_id=row.id,
                path=row.path or "",
                library_availability=row.library_availability,
                probe_status=row.probe_status,
                codec=row.codec,
                is_lossless=row.is_lossless,
                bitrate_bps=row.bitrate_bps,
            ))
    return candidates


def _load_preferences(db: Session, recording_ids: list[int]) -> dict[int, models.MusicRecordingPreference]:
    preferences = {}
    for chunk in chunked(recording_ids):
        for row in db.query(models.MusicRecordingPreference).filter(models.MusicRecordingPreference.recording_id.in_(chunk)).all():
            preferences[row.recording_id] = row
    return preferences


def _apply_decision(row: models.MusicRecordingPreference, decision: PreferenceDecision) -> None:
    row.auto_preferred_track_id = decision.auto_preferred_track_id
    row.decision_state = decision.decision_state
    row.confidence = decision.confidence
    row.reason_code = decision.reason_code
    row.policy_version = PREFERENCE_POLICY_VERSION
    row.candidate_count = decision.candidate_count
    row.eligible_candidate_count = decision.eligible_candidate_count
    row.evaluated_at = utc_now()


def evaluate_music_recording_preferences(
    db: Session,
    *,
    recording_ids: list[int] | None = None,
) -> dict[str, int]:
    ids = _target_recording_ids(db, recording_ids)
    candidates_by_recording = _load_candidates(db, ids)
    preferences = _load_preferences(db, ids)
    created = 0
    for recording_id in ids:
        row = preferences.get(recording_id)
        if row is None:
            row = models.MusicRecordingPreference(recording_id=recording_id)
            db.add(row)
            preferences[recording_id] = row
            created += 1
        decision = evaluate_candidates(candidates_by_recording.get(recording_id, []))
        _apply_decision(row, decision)
    db.flush()
    return {"recordings_seen": len(ids), "preferences_created": created, "preferences_updated": len(ids) - created}


def evaluate_music_recording_preference(
    db: Session,
    *,
    recording_id: int,
) -> models.MusicRecordingPreference:
    evaluate_music_recording_preferences(db, recording_ids=[recording_id])
    return db.query(models.MusicRecordingPreference).filter_by(recording_id=recording_id).one()


def _track_linked_to_recording(db: Session, *, recording_id: int, track_id: int) -> bool:
    return db.query(models.MusicTrackIdentity.id).filter_by(recording_id=recording_id, track_id=track_id).first() is not None


def set_music_recording_user_preference(
    db: Session,
    *,
    recording_id: int,
    track_id: int | None,
) -> models.MusicRecordingPreference:
    row = db.query(models.MusicRecordingPreference).filter_by(recording_id=recording_id).one_or_none()
    if row is None:
        row = evaluate_music_recording_preference(db, recording_id=recording_id)
    if track_id is not None and not _track_linked_to_recording(db, recording_id=recording_id, track_id=track_id):
        raise ValueError("track is not linked to the requested MusicRecording")
    row.user_preferred_track_id = track_id
    db.flush()
    return row


def _available_linked_track_ids(candidates: list[Candidate]) -> set[int]:
    return {candidate.track_id for candidate in candidates if candidate.available}




def _resolution_from_preference_and_candidates(
    *,
    recording_id: int,
    preference: models.MusicRecordingPreference | None,
    candidates: list[Candidate],
) -> MusicSourceResolution:
    decision = evaluate_candidates(candidates) if preference is None else PreferenceDecision(
        preference.decision_state,
        preference.auto_preferred_track_id,
        preference.confidence,
        preference.reason_code,
        preference.candidate_count,
        preference.eligible_candidate_count,
    )
    user_preferred_track_id = preference.user_preferred_track_id if preference is not None else None
    auto_preferred_track_id = decision.auto_preferred_track_id
    available_track_ids = _available_linked_track_ids(candidates)
    linked_track_ids = {candidate.track_id for candidate in candidates}

    user_override_unavailable = False
    if user_preferred_track_id is not None:
        if user_preferred_track_id in available_track_ids:
            return MusicSourceResolution(recording_id, user_preferred_track_id, SOURCE_USER_OVERRIDE, decision.decision_state, CONFIDENCE_HIGH, REASON_USER_OVERRIDE, user_preferred_track_id, auto_preferred_track_id)
        if user_preferred_track_id in linked_track_ids:
            user_override_unavailable = True

    if auto_preferred_track_id is not None and auto_preferred_track_id in available_track_ids:
        reason = REASON_USER_OVERRIDE_UNAVAILABLE_FALLBACK if user_override_unavailable else REASON_AUTOMATIC_PREFERENCE
        return MusicSourceResolution(recording_id, auto_preferred_track_id, SOURCE_AUTOMATIC_PREFERENCE, decision.decision_state, decision.confidence, reason, user_preferred_track_id, auto_preferred_track_id)

    fallback = deterministic_fallback(candidates)
    if fallback is not None:
        reason = REASON_USER_OVERRIDE_UNAVAILABLE_FALLBACK if user_override_unavailable else REASON_DETERMINISTIC_FALLBACK
        return MusicSourceResolution(recording_id, fallback.track_id, SOURCE_DETERMINISTIC_FALLBACK, decision.decision_state, CONFIDENCE_LOW, reason, user_preferred_track_id, auto_preferred_track_id)

    return MusicSourceResolution(recording_id, None, SOURCE_NO_SOURCE, decision.decision_state, CONFIDENCE_NONE, REASON_NO_AVAILABLE_SOURCE, user_preferred_track_id, auto_preferred_track_id)


def resolve_effective_music_sources_read_only(
    db: Session,
    *,
    recording_ids: list[int],
) -> dict[int, MusicSourceResolution]:
    ids = unique_ints(recording_ids)
    if not ids:
        return {}
    candidates_by_recording = _load_candidates(db, ids)
    preferences = _load_preferences(db, ids)
    return {
        recording_id: _resolution_from_preference_and_candidates(
            recording_id=recording_id,
            preference=preferences.get(recording_id),
            candidates=candidates_by_recording.get(recording_id, []),
        )
        for recording_id in ids
    }
def resolve_effective_music_source(
    db: Session,
    *,
    recording_id: int,
) -> MusicSourceResolution:
    preference = db.query(models.MusicRecordingPreference).filter_by(recording_id=recording_id).one_or_none()
    if preference is None:
        preference = evaluate_music_recording_preference(db, recording_id=recording_id)
    candidates = _load_candidates(db, [recording_id]).get(recording_id, [])
    available_track_ids = _available_linked_track_ids(candidates)

    user_override_unavailable = False
    if preference.user_preferred_track_id is not None:
        if preference.user_preferred_track_id in available_track_ids:
            return MusicSourceResolution(recording_id, preference.user_preferred_track_id, SOURCE_USER_OVERRIDE, preference.decision_state, CONFIDENCE_HIGH, REASON_USER_OVERRIDE, preference.user_preferred_track_id, preference.auto_preferred_track_id)
        if _track_linked_to_recording(db, recording_id=recording_id, track_id=preference.user_preferred_track_id):
            user_override_unavailable = True

    if preference.auto_preferred_track_id is not None and preference.auto_preferred_track_id in available_track_ids:
        reason = REASON_USER_OVERRIDE_UNAVAILABLE_FALLBACK if user_override_unavailable else REASON_AUTOMATIC_PREFERENCE
        return MusicSourceResolution(recording_id, preference.auto_preferred_track_id, SOURCE_AUTOMATIC_PREFERENCE, preference.decision_state, preference.confidence, reason, preference.user_preferred_track_id, preference.auto_preferred_track_id)

    fallback = deterministic_fallback(candidates)
    if fallback is not None:
        reason = REASON_USER_OVERRIDE_UNAVAILABLE_FALLBACK if user_override_unavailable else REASON_DETERMINISTIC_FALLBACK
        return MusicSourceResolution(recording_id, fallback.track_id, SOURCE_DETERMINISTIC_FALLBACK, preference.decision_state, CONFIDENCE_LOW, reason, preference.user_preferred_track_id, preference.auto_preferred_track_id)

    return MusicSourceResolution(recording_id, None, SOURCE_NO_SOURCE, preference.decision_state, CONFIDENCE_NONE, REASON_NO_AVAILABLE_SOURCE, preference.user_preferred_track_id, preference.auto_preferred_track_id)