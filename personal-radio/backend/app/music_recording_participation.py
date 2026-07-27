from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from . import models

PARTICIPATION_INCLUDED = "included"
PARTICIPATION_LIBRARY_ONLY = "library_only"
PARTICIPATION_ARCHIVED = "archived"
PARTICIPATION_BLOCKED = "blocked"
PARTICIPATION_STATES = frozenset({
    PARTICIPATION_INCLUDED,
    PARTICIPATION_LIBRARY_ONLY,
    PARTICIPATION_ARCHIVED,
    PARTICIPATION_BLOCKED,
})

STATE_SOURCE_USER = "user"
STATE_SOURCE_SYSTEM = "system"
STATE_SOURCES = frozenset({STATE_SOURCE_USER, STATE_SOURCE_SYSTEM})
MAX_REASON_CODE_LENGTH = 100


@dataclass(frozen=True)
class MusicRecordingParticipationState:
    recording_id: int
    participation_state: str
    state_source: str | None
    reason_code: str | None
    explicit: bool
    row_id: int | None = None


def normalize_reason_code(reason_code: str | None) -> str | None:
    if reason_code is None:
        return None
    value = reason_code.strip()
    if not value:
        return None
    if len(value) > MAX_REASON_CODE_LENGTH:
        raise ValueError("reason_code must be 100 characters or fewer")
    return value


def validate_participation_state(participation_state: str) -> str:
    value = str(participation_state or "").strip()
    if value not in PARTICIPATION_STATES:
        raise ValueError("invalid participation_state")
    return value


def validate_state_source(state_source: str) -> str:
    value = str(state_source or "").strip()
    if value not in STATE_SOURCES:
        raise ValueError("invalid state_source")
    return value


def get_music_recording_participation(
    db: Session,
    *,
    recording_id: int,
) -> MusicRecordingParticipationState:
    row = db.query(models.MusicRecordingParticipation).filter_by(recording_id=recording_id).one_or_none()
    if row is None:
        return MusicRecordingParticipationState(
            recording_id=recording_id,
            participation_state=PARTICIPATION_INCLUDED,
            state_source=None,
            reason_code=None,
            explicit=False,
        )
    return MusicRecordingParticipationState(
        recording_id=row.recording_id,
        participation_state=row.participation_state,
        state_source=row.state_source,
        reason_code=row.reason_code,
        explicit=True,
        row_id=row.id,
    )


def set_music_recording_participation(
    db: Session,
    *,
    recording_id: int,
    participation_state: str,
    reason_code: str | None = None,
    state_source: str = STATE_SOURCE_USER,
) -> models.MusicRecordingParticipation:
    state = validate_participation_state(participation_state)
    source = validate_state_source(state_source)
    reason = normalize_reason_code(reason_code)
    row = db.query(models.MusicRecordingParticipation).filter_by(recording_id=recording_id).one_or_none()
    if row is None:
        row = models.MusicRecordingParticipation(recording_id=recording_id)
        db.add(row)
    row.participation_state = state
    row.state_source = source
    row.reason_code = reason
    db.flush()
    return row


def clear_music_recording_participation(
    db: Session,
    *,
    recording_id: int,
) -> None:
    row = db.query(models.MusicRecordingParticipation).filter_by(recording_id=recording_id).one_or_none()
    if row is not None:
        db.delete(row)
        db.flush()
