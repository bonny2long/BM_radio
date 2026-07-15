from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from . import models
from .availability import LIBRARY_AVAILABLE, TRACK_UNAVAILABLE_MESSAGE, is_track_available
from .music_recording_participation import PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY
from .music_source_preference import resolve_effective_music_sources_read_only

AUTOMATIC_PARTICIPATION_STATES = {PARTICIPATION_INCLUDED}
SEED_PARTICIPATION_STATES = {PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY}
MAX_STATION_CANDIDATE_POOL = 5000


def _has_table(db: Session, table_name: str) -> bool:
    return sqlalchemy_inspect(db.get_bind()).has_table(table_name)


def _has_column(db: Session, table_name: str, column_name: str) -> bool:
    if not _has_table(db, table_name):
        return False
    return any(column["name"] == column_name for column in sqlalchemy_inspect(db.get_bind()).get_columns(table_name))


@dataclass(frozen=True)
class StationRecordingCandidate:
    recording_id: int | None
    candidate_key: tuple[str, int]
    profile_track: models.Track
    effective_track: models.Track
    participation_state: str
    recording_type: str | None
    version_hint: str | None
    source_resolution: str | None
    source_confidence: str | None
    source_reason_code: str | None


def unique_ints(values: Iterable[int | None]) -> list[int]:
    return list(dict.fromkeys(int(value) for value in values if value is not None))


def _track_rows_by_id(db: Session, track_ids: Iterable[int | None]) -> dict[int, models.Track]:
    ids = unique_ints(track_ids)
    if not ids:
        return {}
    return {row.id: row for row in db.query(models.Track).filter(models.Track.id.in_(ids)).all()}


def _participation_by_recording_id(db: Session, recording_ids: list[int]) -> dict[int, str]:
    if not recording_ids:
        return {}
    rows = db.query(models.MusicRecordingParticipation).filter(models.MusicRecordingParticipation.recording_id.in_(recording_ids)).all()
    return {row.recording_id: row.participation_state for row in rows}


def _recording_rows_by_id(db: Session, recording_ids: list[int]) -> dict[int, models.MusicRecording]:
    if not recording_ids:
        return {}
    return {row.id: row for row in db.query(models.MusicRecording).filter(models.MusicRecording.id.in_(recording_ids)).all()}


def _deterministic_profile_track_ids(db: Session, recording_ids: list[int]) -> dict[int, int]:
    if not recording_ids:
        return {}
    row_number = func.row_number().over(
        partition_by=models.MusicTrackIdentity.recording_id,
        order_by=(models.Track.created_at.asc(), models.Track.relative_path.asc(), models.Track.id.asc()),
    ).label("rn")
    subq = (
        db.query(
            models.MusicTrackIdentity.recording_id.label("recording_id"),
            models.Track.id.label("track_id"),
            row_number,
        )
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .filter(models.MusicTrackIdentity.recording_id.in_(recording_ids), models.Track.library_availability == LIBRARY_AVAILABLE)
        .subquery()
    )
    return {int(row.recording_id): int(row.track_id) for row in db.query(subq).filter(subq.c.rn == 1).all()}


def _attach_candidate_metadata(track: models.Track, candidate: StationRecordingCandidate) -> models.Track:
    for attr in ("_station_version_affinity_mode", "_station_version_affinity_tier", "_station_version_affinity_score"):
        if hasattr(track, attr):
            delattr(track, attr)
    setattr(track, "_station_candidate", candidate)
    setattr(track, "_station_recording_id", candidate.recording_id)
    setattr(track, "_station_effective_track_id", candidate.effective_track.id)
    setattr(track, "_station_profile_track_id", candidate.profile_track.id)
    setattr(track, "_station_participation_state", candidate.participation_state)
    setattr(track, "_station_recording_type", candidate.recording_type)
    setattr(track, "_station_version_hint", candidate.version_hint)
    setattr(track, "_station_source_resolution", candidate.source_resolution)
    setattr(track, "_station_source_confidence", candidate.source_confidence)
    setattr(track, "_station_source_reason_code", candidate.source_reason_code)
    return track


def station_candidate_for_track(track: models.Track) -> StationRecordingCandidate | None:
    return getattr(track, "_station_candidate", None)


def station_identity_key_for_track(track: models.Track | None) -> tuple[str, int] | None:
    if track is None:
        return None
    candidate = station_candidate_for_track(track)
    if candidate is not None:
        return candidate.candidate_key
    return ("track", int(track.id))


def station_identity_keys_for_track_ids(db: Session, track_ids: Iterable[int | None]) -> set[tuple[str, int]]:
    ids = unique_ints(track_ids)
    if not ids:
        return set()
    if not _has_table(db, "music_track_identities"):
        return {("track", track_id) for track_id in ids}
    rows = db.query(models.MusicTrackIdentity.track_id, models.MusicTrackIdentity.recording_id).filter(models.MusicTrackIdentity.track_id.in_(ids)).all()
    by_track = {int(track_id): int(recording_id) for track_id, recording_id in rows}
    out: set[tuple[str, int]] = set()
    for track_id in ids:
        recording_id = by_track.get(track_id)
        out.add(("recording", recording_id) if recording_id is not None else ("track", track_id))
    return out


def seed_recording_id_for_track(db: Session, track_id: int | None) -> int | None:
    if track_id is None:
        return None
    if not _has_table(db, "music_track_identities"):
        return None
    return db.query(models.MusicTrackIdentity.recording_id).filter_by(track_id=track_id).scalar()


def validate_song_seed_track(db: Session, track: models.Track) -> tuple[int | None, str | None]:
    if not is_track_available(track):
        raise HTTPException(409, TRACK_UNAVAILABLE_MESSAGE)
    if not _has_table(db, "music_track_identities") or not _has_table(db, "music_recording_participation"):
        return None, None
    row = (
        db.query(models.MusicTrackIdentity.recording_id, models.MusicRecordingParticipation.participation_state)
        .outerjoin(models.MusicRecordingParticipation, models.MusicRecordingParticipation.recording_id == models.MusicTrackIdentity.recording_id)
        .filter(models.MusicTrackIdentity.track_id == track.id)
        .one_or_none()
    )
    if row is None:
        return None, None
    state = row.participation_state or PARTICIPATION_INCLUDED
    if state not in SEED_PARTICIPATION_STATES:
        raise HTTPException(409, "Recording is not eligible as a station seed")
    return int(row.recording_id), state


def load_station_recording_candidates(
    db: Session,
    *,
    limit: int = MAX_STATION_CANDIDATE_POOL,
    exclude_keys: set[tuple[str, int]] | None = None,
) -> list[StationRecordingCandidate]:
    bounded = max(1, min(int(limit), MAX_STATION_CANDIDATE_POOL))
    exclude = exclude_keys or set()
    if not _has_table(db, "music_track_identities"):
        return _legacy_track_candidates(db, limit=bounded, exclude=exclude)
    recording_rows = (
        db.query(models.MusicTrackIdentity.recording_id, func.min(models.Track.created_at).label("first_seen"), func.min(models.Track.id).label("stable_id"))
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .filter(models.Track.library_availability == LIBRARY_AVAILABLE)
        .group_by(models.MusicTrackIdentity.recording_id)
        .order_by(func.min(models.Track.created_at).desc(), func.min(models.Track.id).asc())
        .limit(bounded * 3)
        .all()
    )
    recording_ids = unique_ints([row.recording_id for row in recording_rows])
    participation = _participation_by_recording_id(db, recording_ids)
    recording_ids = [recording_id for recording_id in recording_ids if participation.get(recording_id, PARTICIPATION_INCLUDED) in AUTOMATIC_PARTICIPATION_STATES and ("recording", recording_id) not in exclude]
    resolutions = resolve_effective_music_sources_read_only(db, recording_ids=recording_ids)
    profile_ids = _deterministic_profile_track_ids(db, recording_ids)
    tracks_by_id = _track_rows_by_id(db, [resolution.track_id for resolution in resolutions.values()] + list(profile_ids.values()))
    recordings = _recording_rows_by_id(db, recording_ids)

    candidates: list[StationRecordingCandidate] = []
    for recording_id in recording_ids:
        resolution = resolutions.get(recording_id)
        if resolution is None or resolution.track_id is None:
            continue
        effective_track = tracks_by_id.get(int(resolution.track_id))
        profile_track = tracks_by_id.get(profile_ids.get(recording_id) or int(resolution.track_id))
        recording = recordings.get(recording_id)
        if effective_track is None or profile_track is None:
            continue
        candidate = StationRecordingCandidate(
            recording_id=recording_id,
            candidate_key=("recording", recording_id),
            profile_track=profile_track,
            effective_track=effective_track,
            participation_state=participation.get(recording_id, PARTICIPATION_INCLUDED),
            recording_type=recording.recording_type if recording is not None else None,
            version_hint=recording.version_hint if recording is not None else None,
            source_resolution=resolution.source,
            source_confidence=resolution.confidence,
            source_reason_code=resolution.reason_code,
        )
        candidates.append(candidate)
        if len(candidates) >= bounded:
            break

    candidates.extend(_legacy_track_candidates(db, limit=max(0, bounded - len(candidates)), exclude=exclude))
    return candidates[:bounded]


def _legacy_track_candidates(db: Session, *, limit: int, exclude: set[tuple[str, int]]) -> list[StationRecordingCandidate]:
    if limit <= 0:
        return []
    query = db.query(models.Track)
    if _has_table(db, "music_track_identities"):
        query = query.outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.Track.id).filter(models.MusicTrackIdentity.id.is_(None))
    legacy_tracks = (
        query
        .filter(models.Track.library_availability == LIBRARY_AVAILABLE)
        .order_by(models.Track.created_at.desc(), models.Track.id.asc())
        .limit(limit)
        .all()
    )
    candidates: list[StationRecordingCandidate] = []
    for track in legacy_tracks:
        key = ("track", int(track.id))
        if key in exclude:
            continue
        candidates.append(StationRecordingCandidate(
            recording_id=None,
            candidate_key=key,
            profile_track=track,
            effective_track=track,
            participation_state=PARTICIPATION_INCLUDED,
            recording_type=None,
            version_hint=None,
            source_resolution="legacy_track",
            source_confidence=None,
            source_reason_code=None,
        ))
        if len(candidates) >= limit:
            break
    return candidates


def station_tracks_from_candidates(candidates: list[StationRecordingCandidate]) -> list[models.Track]:
    return [_attach_candidate_metadata(candidate.effective_track, candidate) for candidate in candidates]


def load_station_candidate_tracks(
    db: Session,
    *,
    limit: int = MAX_STATION_CANDIDATE_POOL,
    exclude_track_ids: Iterable[int | None] | None = None,
    seed_track_id: int | None = None,
) -> list[models.Track]:
    exclude_keys = station_identity_keys_for_track_ids(db, exclude_track_ids or [])
    if seed_track_id is not None:
        seed_recording_id = seed_recording_id_for_track(db, seed_track_id)
        exclude_keys.add(("recording", seed_recording_id) if seed_recording_id is not None else ("track", int(seed_track_id)))
    return station_tracks_from_candidates(load_station_recording_candidates(db, limit=limit, exclude_keys=exclude_keys))


def current_feedback_by_station_track(db: Session, tracks: list[models.Track]) -> dict[int, str]:
    recording_ids = unique_ints([getattr(track, "_station_recording_id", None) for track in tracks])
    result: dict[int, str] = {}
    can_join_identity = _has_table(db, "music_track_identities")
    has_thumb_recording_id = _has_column(db, "track_thumbs", "recording_id")
    if recording_ids and can_join_identity and has_thumb_recording_id:
        rec_id = func.coalesce(models.TrackThumb.recording_id, models.MusicTrackIdentity.recording_id).label("recording_id")
        row_number = func.row_number().over(partition_by=rec_id, order_by=(models.TrackThumb.created_at.desc(), models.TrackThumb.id.desc())).label("rn")
        subq = (
            db.query(rec_id, models.TrackThumb.value.label("value"), row_number)
            .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.TrackThumb.track_id)
            .filter(rec_id.in_(recording_ids))
            .subquery()
        )
        value_by_recording = {int(row.recording_id): (row.value.value if hasattr(row.value, "value") else str(row.value)) for row in db.query(subq).filter(subq.c.rn == 1).all()}
        for track in tracks:
            recording_id = getattr(track, "_station_recording_id", None)
            if recording_id in value_by_recording:
                result[track.id] = value_by_recording[recording_id]
    legacy_ids = [track.id for track in tracks if getattr(track, "_station_recording_id", None) is None]
    if legacy_ids:
        query = db.query(models.TrackThumb).filter(models.TrackThumb.track_id.in_(legacy_ids))
        if has_thumb_recording_id:
            query = query.filter(models.TrackThumb.recording_id.is_(None))
        rows = query.order_by(models.TrackThumb.created_at.asc(), models.TrackThumb.id.asc()).all()
        for row in rows:
            result[row.track_id] = row.value.value if hasattr(row.value, "value") else str(row.value)
    return result


def favorite_ids_by_station_track(db: Session, tracks: list[models.Track]) -> set[int]:
    recording_ids = unique_ints([getattr(track, "_station_recording_id", None) for track in tracks])
    favorite_recordings: set[int] = set()
    can_join_identity = _has_table(db, "music_track_identities")
    has_favorite_recording_id = _has_column(db, "track_favorites", "recording_id")
    if recording_ids and can_join_identity and has_favorite_recording_id:
        rec_id = func.coalesce(models.TrackFavorite.recording_id, models.MusicTrackIdentity.recording_id)
        rows = (
            db.query(rec_id.label("recording_id"))
            .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.TrackFavorite.track_id)
            .filter(rec_id.in_(recording_ids))
            .group_by(rec_id)
            .all()
        )
        favorite_recordings = {int(row.recording_id) for row in rows}
    legacy_ids = [track.id for track in tracks if getattr(track, "_station_recording_id", None) is None]
    favorite_legacy = set()
    if legacy_ids:
        query = db.query(models.TrackFavorite.track_id).filter(models.TrackFavorite.track_id.in_(legacy_ids))
        if has_favorite_recording_id:
            query = query.filter(models.TrackFavorite.recording_id.is_(None))
        favorite_legacy = {int(row[0]) for row in query.all()}
    return {track.id for track in tracks if getattr(track, "_station_recording_id", None) in favorite_recordings or track.id in favorite_legacy}


def play_counts_by_station_track(db: Session, tracks: list[models.Track]) -> dict[int, int]:
    recording_ids = unique_ints([getattr(track, "_station_recording_id", None) for track in tracks])
    result: dict[int, int] = {}
    can_join_identity = _has_table(db, "music_track_identities")
    has_event_recording_id = _has_column(db, "playback_events", "recording_id")
    if recording_ids and can_join_identity and has_event_recording_id:
        rec_id = func.coalesce(models.PlaybackEvent.recording_id, models.MusicTrackIdentity.recording_id)
        rows = (
            db.query(rec_id.label("recording_id"), func.count(models.PlaybackEvent.id).label("plays"))
            .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.PlaybackEvent.track_id)
            .filter(models.PlaybackEvent.event_type == "qualified_play", rec_id.in_(recording_ids))
            .group_by(rec_id)
            .all()
        )
        plays_by_recording = {int(row.recording_id): int(row.plays or 0) for row in rows}
        for track in tracks:
            recording_id = getattr(track, "_station_recording_id", None)
            if recording_id in plays_by_recording:
                result[track.id] = plays_by_recording[recording_id]
    legacy_ids = [track.id for track in tracks if getattr(track, "_station_recording_id", None) is None]
    if legacy_ids:
        rows = db.query(models.PlaybackEvent.track_id, func.count(models.PlaybackEvent.id)).filter(models.PlaybackEvent.event_type == "qualified_play", models.PlaybackEvent.track_id.in_(legacy_ids)).group_by(models.PlaybackEvent.track_id).all()
        result.update({int(track_id): int(count or 0) for track_id, count in rows})
    return result


def recent_ids_by_station_track(db: Session, tracks: list[models.Track], limit: int = 80) -> set[int]:
    recording_ids = unique_ints([getattr(track, "_station_recording_id", None) for track in tracks])
    recent_recordings: set[int] = set()
    can_join_identity = _has_table(db, "music_track_identities")
    has_event_recording_id = _has_column(db, "playback_events", "recording_id")
    if recording_ids and can_join_identity and has_event_recording_id:
        rec_id = func.coalesce(models.PlaybackEvent.recording_id, models.MusicTrackIdentity.recording_id)
        rows = (
            db.query(rec_id.label("recording_id"))
            .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.PlaybackEvent.track_id)
            .filter(models.PlaybackEvent.event_type == "qualified_play", rec_id.in_(recording_ids))
            .order_by(models.PlaybackEvent.created_at.desc())
            .limit(limit)
            .all()
        )
        recent_recordings = {int(row.recording_id) for row in rows if row.recording_id is not None}
    legacy_ids = [track.id for track in tracks if getattr(track, "_station_recording_id", None) is None]
    recent_legacy: set[int] = set()
    if legacy_ids:
        rows = db.query(models.PlaybackEvent.track_id).filter(models.PlaybackEvent.event_type == "qualified_play", models.PlaybackEvent.track_id.in_(legacy_ids)).order_by(models.PlaybackEvent.created_at.desc()).limit(limit).all()
        recent_legacy = {int(row[0]) for row in rows if row[0] is not None}
    return {track.id for track in tracks if getattr(track, "_station_recording_id", None) in recent_recordings or track.id in recent_legacy}


def logical_station_count(db: Session, *, station_type: str, seed_value: str | None = None) -> int:
    tracks = load_station_candidate_tracks(db, limit=MAX_STATION_CANDIDATE_POOL)
    if station_type == "favorites":
        fb = current_feedback_by_station_track(db, tracks)
        favs = favorite_ids_by_station_track(db, tracks)
        return len([track for track in tracks if track.id in favs or fb.get(track.id) == "up"])
    if station_type == "recently_added":
        return len(tracks)
    if station_type == "deep_cuts":
        counts = play_counts_by_station_track(db, tracks)
        return len([track for track in tracks if counts.get(track.id, 0) <= 1])
    if station_type == "artist" and seed_value:
        token = str(seed_value).strip().lower()
        return len([track for track in tracks if (track.artist or "").strip().lower() == token or (track.album_artist or "").strip().lower() == token])
    if station_type == "genre" and seed_value:
        target = str(seed_value or "").strip().lower()
        return len([track for track in tracks if target and target in (track.genre or "").strip().lower()])
    return 0