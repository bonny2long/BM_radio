from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models
from .availability import is_track_available
from .music_recording_participation import (
    PARTICIPATION_ARCHIVED,
    PARTICIPATION_BLOCKED,
    PARTICIPATION_INCLUDED,
    PARTICIPATION_LIBRARY_ONLY,
)
from .music_source_preference import resolve_effective_music_sources_read_only
from .routes.serializers import track_item

BLOCKED_RECORDING_PLAYBACK_MESSAGE = "Recording is blocked from playback"
RECENT_MUSIC_VISIBLE_STATES = {PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY}
RECENT_CANDIDATE_SCAN_LIMIT = 500


@dataclass(frozen=True)
class MusicPlaybackContext:
    track: models.Track
    recording_id: int | None
    participation_state: str | None
    identity_backed: bool


def _unique_ints(values: Iterable[int | None]) -> list[int]:
    return list(dict.fromkeys(int(value) for value in values if value is not None))


def _track_rows_by_ids(db: Session, track_ids: Iterable[int | None]) -> dict[int, models.Track]:
    ids = _unique_ints(track_ids)
    if not ids:
        return {}
    return {row.id: row for row in db.query(models.Track).filter(models.Track.id.in_(ids)).all()}


def _identity_rows_by_track_id(db: Session, track_ids: Iterable[int | None]) -> dict[int, models.MusicTrackIdentity]:
    ids = _unique_ints(track_ids)
    if not ids:
        return {}
    return {row.track_id: row for row in db.query(models.MusicTrackIdentity).filter(models.MusicTrackIdentity.track_id.in_(ids)).all()}


def _participation_by_recording_id(db: Session, recording_ids: Iterable[int | None]) -> dict[int, str]:
    ids = _unique_ints(recording_ids)
    if not ids:
        return {}
    rows = db.query(models.MusicRecordingParticipation).filter(models.MusicRecordingParticipation.recording_id.in_(ids)).all()
    return {row.recording_id: row.participation_state for row in rows}


def _recording_rows_by_id(db: Session, recording_ids: Iterable[int | None]) -> dict[int, models.MusicRecording]:
    ids = _unique_ints(recording_ids)
    if not ids:
        return {}
    return {row.id: row for row in db.query(models.MusicRecording).filter(models.MusicRecording.id.in_(ids)).all()}


def _track_ids_for_recording(db: Session, recording_id: int) -> list[int]:
    return [
        int(row[0])
        for row in db.query(models.MusicTrackIdentity.track_id)
        .filter(models.MusicTrackIdentity.recording_id == recording_id)
        .all()
    ]


def resolve_music_playback_context(db: Session, track: models.Track) -> MusicPlaybackContext:
    identity = db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).one_or_none()
    if identity is None:
        return MusicPlaybackContext(track=track, recording_id=None, participation_state=None, identity_backed=False)
    participation = db.query(models.MusicRecordingParticipation).filter_by(recording_id=identity.recording_id).one_or_none()
    state = participation.participation_state if participation is not None else PARTICIPATION_INCLUDED
    return MusicPlaybackContext(track=track, recording_id=identity.recording_id, participation_state=state, identity_backed=True)


def validate_music_playback_context(db: Session, track: models.Track) -> MusicPlaybackContext:
    context = resolve_music_playback_context(db, track)
    if context.participation_state == PARTICIPATION_BLOCKED:
        raise HTTPException(409, BLOCKED_RECORDING_PLAYBACK_MESSAGE)
    return context


def recent_qualified_exists(
    db: Session,
    *,
    track_id: int,
    recording_id: int | None,
    minutes: int = 30,
) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    query = db.query(models.PlaybackEvent.id).filter(
        models.PlaybackEvent.event_type == "qualified_play",
        models.PlaybackEvent.created_at >= cutoff,
    )
    if recording_id is not None:
        linked_track_ids = _track_ids_for_recording(db, recording_id)
        clauses = [models.PlaybackEvent.recording_id == recording_id]
        if linked_track_ids:
            clauses.append(
                (models.PlaybackEvent.recording_id.is_(None))
                & (models.PlaybackEvent.track_id.in_(linked_track_ids))
            )
        return query.filter(clauses[0] if len(clauses) == 1 else clauses[0] | clauses[1]).first() is not None
    return query.filter(models.PlaybackEvent.track_id == track_id).first() is not None


def _event_recording_id(event: models.PlaybackEvent, identities: dict[int, models.MusicTrackIdentity]) -> int | None:
    if event.recording_id is not None:
        return int(event.recording_id)
    if event.track_id is None:
        return None
    identity = identities.get(int(event.track_id))
    return int(identity.recording_id) if identity is not None else None


def project_recent_music_playback(
    db: Session,
    *,
    events: list[models.PlaybackEvent],
    limit: int,
) -> list[dict]:
    visible_limit = max(1, min(int(limit), 25))
    candidates = events[:RECENT_CANDIDATE_SCAN_LIMIT]
    track_ids = [event.track_id for event in candidates if event.track_id is not None]
    tracks = _track_rows_by_ids(db, track_ids)
    identities = _identity_rows_by_track_id(db, track_ids)

    selected: list[tuple[models.PlaybackEvent, tuple[str, int], int | None]] = []
    seen: set[tuple[str, int]] = set()
    for event in candidates:
        if event.track_id is None:
            continue
        recording_id = _event_recording_id(event, identities)
        key = ("recording", recording_id) if recording_id is not None else ("track", int(event.track_id))
        if key in seen:
            continue
        seen.add(key)
        selected.append((event, key, recording_id))

    recording_ids = [recording_id for _, _, recording_id in selected if recording_id is not None]
    participation = _participation_by_recording_id(db, recording_ids)
    recordings = _recording_rows_by_id(db, recording_ids)
    resolutions = resolve_effective_music_sources_read_only(db, recording_ids=recording_ids)
    effective_tracks = _track_rows_by_ids(db, [resolution.track_id for resolution in resolutions.values() if resolution.track_id is not None])

    out: list[dict] = []
    for event, _, recording_id in selected:
        if event.track_id is None:
            continue
        played_track = tracks.get(int(event.track_id))
        if played_track is None:
            continue
        if recording_id is None:
            if not is_track_available(played_track):
                continue
            item = track_item(played_track)
            out.append({
                "mode": "music",
                "recording_id": None,
                "track_id": played_track.id,
                "played_track_id": played_track.id,
                "effective_track_id": played_track.id,
                "title": played_track.title,
                "subtitle": " - ".join([x for x in [played_track.artist, played_track.album] if x]),
                "cover_url": item["cover_url"],
                "stream_url": item["stream_url"],
                "source_resolution": None,
                "source_confidence": None,
                "source_reason_code": None,
                "participation_state": None,
                "last_event_at": str(event.created_at),
            })
        else:
            state = participation.get(recording_id, PARTICIPATION_INCLUDED)
            if state not in RECENT_MUSIC_VISIBLE_STATES:
                continue
            resolution = resolutions.get(recording_id)
            if resolution is None or resolution.track_id is None:
                continue
            effective_track = effective_tracks.get(int(resolution.track_id))
            if effective_track is None:
                continue
            recording = recordings.get(recording_id)
            item = track_item(effective_track)
            title = (recording.title if recording is not None else None) or played_track.title or effective_track.title
            artist = (recording.artist if recording is not None else None) or played_track.artist or effective_track.artist
            album = played_track.album or effective_track.album
            out.append({
                "mode": "music",
                "recording_id": recording_id,
                "track_id": effective_track.id,
                "played_track_id": played_track.id,
                "effective_track_id": effective_track.id,
                "title": title,
                "subtitle": " - ".join([x for x in [artist, album] if x]),
                "cover_url": item["cover_url"],
                "stream_url": item["stream_url"],
                "source_resolution": resolution.source,
                "source_confidence": resolution.confidence,
                "source_reason_code": resolution.reason_code,
                "participation_state": state,
                "last_event_at": str(event.created_at),
            })
        if len(out) >= visible_limit:
            break
    return out
