from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from . import models
from .availability import LIBRARY_AVAILABLE
from .music_recording_participation import PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY
from .music_source_preference import resolve_effective_music_sources_read_only

SMART_VISIBLE_STATES = {PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY}
SMART_INCLUDED_ONLY = {PARTICIPATION_INCLUDED}
SMART_KEYS = {"favorites", "thumbs_up", "most_played", "recently_played", "recently_added", "never_played"}


@dataclass(frozen=True)
class TrackFeedbackContext:
    track: models.Track
    recording_id: int | None
    identity_backed: bool


def _unique_ints(values: Iterable[int | None]) -> list[int]:
    return list(dict.fromkeys(int(value) for value in values if value is not None))


def _track_recording_id(db: Session, track_id: int) -> int | None:
    return db.query(models.MusicTrackIdentity.recording_id).filter_by(track_id=track_id).scalar()


def resolve_track_feedback_context(db: Session, track_id: int) -> TrackFeedbackContext | None:
    track = db.get(models.Track, track_id)
    if track is None:
        return None
    recording_id = _track_recording_id(db, track_id)
    return TrackFeedbackContext(track=track, recording_id=recording_id, identity_backed=recording_id is not None)


def _track_ids_for_recording(db: Session, recording_id: int) -> list[int]:
    return [int(row[0]) for row in db.query(models.MusicTrackIdentity.track_id).filter_by(recording_id=recording_id).all()]


def _favorite_query_for_context(db: Session, context: TrackFeedbackContext):
    if context.recording_id is None:
        return db.query(models.TrackFavorite).filter(models.TrackFavorite.recording_id.is_(None), models.TrackFavorite.track_id == context.track.id)
    linked_track_ids = _track_ids_for_recording(db, context.recording_id)
    clauses = [models.TrackFavorite.recording_id == context.recording_id]
    if linked_track_ids:
        clauses.append(and_(models.TrackFavorite.recording_id.is_(None), models.TrackFavorite.track_id.in_(linked_track_ids)))
    return db.query(models.TrackFavorite).filter(or_(*clauses))


def is_favorite(db: Session, context: TrackFeedbackContext) -> bool:
    return _favorite_query_for_context(db, context).first() is not None


def set_favorite(db: Session, context: TrackFeedbackContext, desired: bool) -> bool:
    if desired:
        if not is_favorite(db, context):
            db.add(models.TrackFavorite(track_id=context.track.id, recording_id=context.recording_id))
        db.flush()
        return True
    _favorite_query_for_context(db, context).delete(synchronize_session="fetch")
    db.flush()
    return False


def toggle_favorite(db: Session, context: TrackFeedbackContext) -> bool:
    return set_favorite(db, context, not is_favorite(db, context))


def _thumb_query_for_context(db: Session, context: TrackFeedbackContext):
    if context.recording_id is None:
        return db.query(models.TrackThumb).filter(models.TrackThumb.recording_id.is_(None), models.TrackThumb.track_id == context.track.id)
    linked_track_ids = _track_ids_for_recording(db, context.recording_id)
    clauses = [models.TrackThumb.recording_id == context.recording_id]
    if linked_track_ids:
        clauses.append(and_(models.TrackThumb.recording_id.is_(None), models.TrackThumb.track_id.in_(linked_track_ids)))
    return db.query(models.TrackThumb).filter(or_(*clauses))


def _thumb_value(row: models.TrackThumb | None) -> str:
    if row is None or row.value is None:
        return "neutral"
    value = row.value.value if hasattr(row.value, "value") else str(row.value)
    return value or "neutral"


def current_feedback(db: Session, context: TrackFeedbackContext) -> str:
    row = _thumb_query_for_context(db, context).order_by(models.TrackThumb.created_at.desc(), models.TrackThumb.id.desc()).first()
    return _thumb_value(row)


def set_feedback(db: Session, context: TrackFeedbackContext, value: str, station_id: int | None = None) -> str:
    if value == "neutral":
        _thumb_query_for_context(db, context).delete(synchronize_session="fetch")
        db.flush()
        return "neutral"
    db.add(models.TrackThumb(track_id=context.track.id, recording_id=context.recording_id, station_id=station_id, value=models.ThumbValue(value)))
    db.flush()
    return value


def _participation_by_recording(db: Session, recording_ids: list[int]) -> dict[int, str]:
    if not recording_ids:
        return {}
    rows = db.query(models.MusicRecordingParticipation).filter(models.MusicRecordingParticipation.recording_id.in_(recording_ids)).all()
    return {row.recording_id: row.participation_state for row in rows}


def _project_recording_candidates(db: Session, recording_ids: list[int], *, allowed_states: set[str]) -> list[int]:
    ordered = _unique_ints(recording_ids)
    if not ordered:
        return []
    participation = _participation_by_recording(db, ordered)
    visible_ids = [recording_id for recording_id in ordered if participation.get(recording_id, PARTICIPATION_INCLUDED) in allowed_states]
    resolutions = resolve_effective_music_sources_read_only(db, recording_ids=visible_ids)
    return [int(resolutions[recording_id].track_id) for recording_id in visible_ids if recording_id in resolutions and resolutions[recording_id].track_id is not None]


def _legacy_available_track_ids(db: Session, track_ids: list[int], *, limit: int) -> list[int]:
    ids = _unique_ints(track_ids)
    if not ids:
        return []
    rows = (
        db.query(models.Track.id)
        .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.Track.id)
        .filter(models.Track.id.in_(ids), models.MusicTrackIdentity.id.is_(None), models.Track.library_availability == LIBRARY_AVAILABLE)
        .all()
    )
    available = {int(row[0]) for row in rows}
    return [track_id for track_id in ids if track_id in available][:limit]


def _candidate_limit(limit: int) -> int:
    return max(1, min(int(limit), 1000))


def _recording_ids_from_rows(rows) -> list[int]:
    return [int(row.recording_id) for row in rows if row.recording_id is not None]


def _favorite_recording_rows(db: Session, limit: int):
    rec_id = func.coalesce(models.TrackFavorite.recording_id, models.MusicTrackIdentity.recording_id).label("recording_id")
    ranked = (
        db.query(
            rec_id,
            func.max(models.TrackFavorite.created_at).label("latest_at"),
            func.max(models.TrackFavorite.id).label("latest_id"),
        )
        .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.TrackFavorite.track_id)
        .filter(rec_id.isnot(None))
        .group_by(rec_id)
        .order_by(func.max(models.TrackFavorite.created_at).desc(), func.max(models.TrackFavorite.id).desc())
        .limit(max(limit * 4, limit))
        .all()
    )
    return ranked


def _favorite_legacy_track_ids(db: Session, limit: int) -> list[int]:
    rows = (
        db.query(models.TrackFavorite.track_id)
        .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.TrackFavorite.track_id)
        .join(models.Track, models.Track.id == models.TrackFavorite.track_id)
        .filter(models.TrackFavorite.recording_id.is_(None), models.MusicTrackIdentity.id.is_(None), models.Track.library_availability == LIBRARY_AVAILABLE)
        .order_by(models.TrackFavorite.created_at.desc(), models.TrackFavorite.id.desc())
        .limit(limit)
        .all()
    )
    return _unique_ints([row[0] for row in rows])


def _latest_thumb_recording_rows(db: Session, limit: int):
    rec_id = func.coalesce(models.TrackThumb.recording_id, models.MusicTrackIdentity.recording_id).label("recording_id")
    row_number = func.row_number().over(
        partition_by=rec_id,
        order_by=(models.TrackThumb.created_at.desc(), models.TrackThumb.id.desc()),
    ).label("rn")
    subq = (
        db.query(rec_id, models.TrackThumb.value.label("value"), models.TrackThumb.created_at.label("created_at"), models.TrackThumb.id.label("id"), row_number)
        .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.TrackThumb.track_id)
        .filter(rec_id.isnot(None))
        .subquery()
    )
    return db.query(subq).filter(subq.c.rn == 1, subq.c.value == models.ThumbValue.up).order_by(subq.c.created_at.desc(), subq.c.id.desc()).limit(max(limit * 4, limit)).all()


def _thumbs_up_legacy_track_ids(db: Session, limit: int) -> list[int]:
    row_number = func.row_number().over(
        partition_by=models.TrackThumb.track_id,
        order_by=(models.TrackThumb.created_at.desc(), models.TrackThumb.id.desc()),
    ).label("rn")
    subq = (
        db.query(models.TrackThumb.track_id.label("track_id"), models.TrackThumb.value.label("value"), models.TrackThumb.created_at.label("created_at"), models.TrackThumb.id.label("id"), row_number)
        .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.TrackThumb.track_id)
        .join(models.Track, models.Track.id == models.TrackThumb.track_id)
        .filter(models.TrackThumb.recording_id.is_(None), models.MusicTrackIdentity.id.is_(None), models.Track.library_availability == LIBRARY_AVAILABLE)
        .subquery()
    )
    rows = db.query(subq).filter(subq.c.rn == 1, subq.c.value == models.ThumbValue.up).order_by(subq.c.created_at.desc(), subq.c.id.desc()).limit(limit).all()
    return _unique_ints([row.track_id for row in rows])


def _playback_recording_rows(db: Session, *, key: str, limit: int):
    rec_id = func.coalesce(models.PlaybackEvent.recording_id, models.MusicTrackIdentity.recording_id).label("recording_id")
    query = (
        db.query(
            rec_id,
            func.count(models.PlaybackEvent.id).label("plays"),
            func.max(models.PlaybackEvent.created_at).label("latest_at"),
        )
        .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.PlaybackEvent.track_id)
        .filter(models.PlaybackEvent.event_type == "qualified_play", rec_id.isnot(None))
        .group_by(rec_id)
    )
    if key == "most_played":
        query = query.order_by(func.count(models.PlaybackEvent.id).desc(), func.max(models.PlaybackEvent.created_at).desc(), rec_id.asc())
    else:
        query = query.order_by(func.max(models.PlaybackEvent.created_at).desc(), rec_id.asc())
    return query.limit(max(limit * 4, limit)).all()


def _playback_legacy_track_ids(db: Session, *, key: str, limit: int) -> list[int]:
    query = (
        db.query(models.PlaybackEvent.track_id, func.count(models.PlaybackEvent.id).label("plays"), func.max(models.PlaybackEvent.created_at).label("latest_at"))
        .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.PlaybackEvent.track_id)
        .join(models.Track, models.Track.id == models.PlaybackEvent.track_id)
        .filter(models.PlaybackEvent.event_type == "qualified_play", models.MusicTrackIdentity.id.is_(None), models.Track.library_availability == LIBRARY_AVAILABLE)
        .group_by(models.PlaybackEvent.track_id)
    )
    if key == "most_played":
        query = query.order_by(func.count(models.PlaybackEvent.id).desc(), func.max(models.PlaybackEvent.created_at).desc(), models.PlaybackEvent.track_id.asc())
    else:
        query = query.order_by(func.max(models.PlaybackEvent.created_at).desc(), models.PlaybackEvent.track_id.asc())
    return _unique_ints([row.track_id for row in query.limit(limit).all()])


def _recently_added_recording_rows(db: Session, limit: int):
    rows = (
        db.query(models.MusicTrackIdentity.recording_id.label("recording_id"), func.min(models.Track.created_at).label("first_seen"), func.min(models.Track.id).label("stable_id"))
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .filter(models.Track.library_availability == LIBRARY_AVAILABLE)
        .group_by(models.MusicTrackIdentity.recording_id)
        .order_by(func.min(models.Track.created_at).desc(), func.min(models.Track.id).desc())
        .limit(max(limit * 4, limit))
        .all()
    )
    return rows


def _recently_added_legacy_track_ids(db: Session, limit: int) -> list[int]:
    rows = (
        db.query(models.Track.id)
        .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.Track.id)
        .filter(models.MusicTrackIdentity.id.is_(None), models.Track.library_availability == LIBRARY_AVAILABLE)
        .order_by(models.Track.created_at.desc(), models.Track.last_indexed_at.desc(), models.Track.id.desc())
        .limit(limit)
        .all()
    )
    return _unique_ints([row[0] for row in rows])


def _never_played_recording_rows(db: Session, limit: int):
    played_subq = (
        db.query(func.coalesce(models.PlaybackEvent.recording_id, models.MusicTrackIdentity.recording_id).label("recording_id"))
        .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.PlaybackEvent.track_id)
        .filter(models.PlaybackEvent.event_type == "qualified_play", func.coalesce(models.PlaybackEvent.recording_id, models.MusicTrackIdentity.recording_id).isnot(None))
        .group_by(func.coalesce(models.PlaybackEvent.recording_id, models.MusicTrackIdentity.recording_id))
        .subquery()
    )
    rows = (
        db.query(models.MusicTrackIdentity.recording_id.label("recording_id"), func.min(models.Track.created_at).label("first_seen"), func.min(models.Track.id).label("stable_id"))
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .outerjoin(played_subq, played_subq.c.recording_id == models.MusicTrackIdentity.recording_id)
        .filter(models.Track.library_availability == LIBRARY_AVAILABLE, played_subq.c.recording_id.is_(None))
        .group_by(models.MusicTrackIdentity.recording_id)
        .order_by(func.min(models.Track.created_at).desc(), func.min(models.Track.id).desc())
        .limit(max(limit * 4, limit))
        .all()
    )
    return rows


def _never_played_legacy_track_ids(db: Session, limit: int) -> list[int]:
    rows = (
        db.query(models.Track.id)
        .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.Track.id)
        .outerjoin(models.PlaybackEvent, and_(models.PlaybackEvent.track_id == models.Track.id, models.PlaybackEvent.event_type == "qualified_play"))
        .filter(models.MusicTrackIdentity.id.is_(None), models.Track.library_availability == LIBRARY_AVAILABLE)
        .group_by(models.Track.id)
        .having(func.count(models.PlaybackEvent.id) == 0)
        .order_by(models.Track.created_at.desc(), models.Track.id.desc())
        .limit(limit)
        .all()
    )
    return _unique_ints([row[0] for row in rows])


def smart_music_candidate_track_ids(db: Session, *, key: str, limit: int) -> list[int]:
    bounded = _candidate_limit(limit)
    if key not in SMART_KEYS:
        return []
    allowed = SMART_INCLUDED_ONLY if key in {"recently_added", "never_played"} else SMART_VISIBLE_STATES
    legacy: list[int] = []
    recording_ids: list[int] = []
    if key == "favorites":
        recording_ids = _recording_ids_from_rows(_favorite_recording_rows(db, bounded))
        legacy = _favorite_legacy_track_ids(db, bounded)
    elif key == "thumbs_up":
        recording_ids = _recording_ids_from_rows(_latest_thumb_recording_rows(db, bounded))
        legacy = _thumbs_up_legacy_track_ids(db, bounded)
    elif key in {"most_played", "recently_played"}:
        recording_ids = _recording_ids_from_rows(_playback_recording_rows(db, key=key, limit=bounded))
        legacy = _playback_legacy_track_ids(db, key=key, limit=bounded)
    elif key == "recently_added":
        recording_ids = _recording_ids_from_rows(_recently_added_recording_rows(db, bounded))
        legacy = _recently_added_legacy_track_ids(db, bounded)
    elif key == "never_played":
        recording_ids = _recording_ids_from_rows(_never_played_recording_rows(db, bounded))
        legacy = _never_played_legacy_track_ids(db, bounded)
    projected = _project_recording_candidates(db, recording_ids, allowed_states=allowed)
    return (projected + legacy)[:bounded]


def smart_music_candidate_count(db: Session, *, key: str) -> int:
    if key not in SMART_KEYS:
        return 0
    if key == "favorites":
        rec_id = func.coalesce(models.TrackFavorite.recording_id, models.MusicTrackIdentity.recording_id)
        recording_count = db.query(func.count(func.distinct(rec_id))).outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.TrackFavorite.track_id).filter(rec_id.isnot(None)).scalar() or 0
        legacy_count = db.query(func.count(func.distinct(models.TrackFavorite.track_id))).outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.TrackFavorite.track_id).join(models.Track, models.Track.id == models.TrackFavorite.track_id).filter(models.TrackFavorite.recording_id.is_(None), models.MusicTrackIdentity.id.is_(None), models.Track.library_availability == LIBRARY_AVAILABLE).scalar() or 0
        return int(recording_count) + int(legacy_count)
    if key == "thumbs_up":
        rec_rows = _latest_thumb_recording_rows(db, 1000)
        legacy_rows = _thumbs_up_legacy_track_ids(db, 1000)
        return len(rec_rows) + len(legacy_rows)
    if key in {"most_played", "recently_played"}:
        rec_id = func.coalesce(models.PlaybackEvent.recording_id, models.MusicTrackIdentity.recording_id)
        recording_count = db.query(func.count(func.distinct(rec_id))).outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.PlaybackEvent.track_id).filter(models.PlaybackEvent.event_type == "qualified_play", rec_id.isnot(None)).scalar() or 0
        legacy_count = db.query(func.count(func.distinct(models.PlaybackEvent.track_id))).outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.PlaybackEvent.track_id).join(models.Track, models.Track.id == models.PlaybackEvent.track_id).filter(models.PlaybackEvent.event_type == "qualified_play", models.MusicTrackIdentity.id.is_(None), models.Track.library_availability == LIBRARY_AVAILABLE).scalar() or 0
        return int(recording_count) + int(legacy_count)
    if key == "recently_added":
        recording_count = db.query(func.count(func.distinct(models.MusicTrackIdentity.recording_id))).join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id).filter(models.Track.library_availability == LIBRARY_AVAILABLE).scalar() or 0
        legacy_count = db.query(func.count(models.Track.id)).outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.Track.id).filter(models.MusicTrackIdentity.id.is_(None), models.Track.library_availability == LIBRARY_AVAILABLE).scalar() or 0
        return int(recording_count) + int(legacy_count)
    if key == "never_played":
        return len(smart_music_candidate_track_ids(db, key=key, limit=1000))
    return 0