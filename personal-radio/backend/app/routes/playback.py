from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from .. import models
from ..availability import AUDIOBOOK_UNAVAILABLE_MESSAGE, CHAPTER_UNAVAILABLE_MESSAGE, TRACK_UNAVAILABLE_MESSAGE, is_audiobook_available, is_chapter_available, is_track_available
from ..db import get_db
from ..music_playback_policy import MusicPlaybackContext, project_recent_music_playback, recent_qualified_exists, validate_music_playback_context
from ..music_recording_feedback import current_feedback, is_favorite, resolve_track_feedback_context, set_feedback, set_favorite, toggle_favorite
from .serializers import audiobook_item

router = APIRouter()


class PlaybackEventCreate(BaseModel):
    event_type: str
    track_id: int | None = None
    audiobook_id: int | None = None
    audiobook_chapter_id: int | None = None
    station_id: int | None = None
    station_type: str | None = None
    station_name: str | None = None
    position_seconds: float | None = None
    completed_percent: float | None = None
    mode: str | None = None


class TrackThumbCreate(BaseModel):
    value: str
    station_id: int | None = None


class FavoritePayload(BaseModel):
    favorite: bool | None = None


class StationFavoritePayload(BaseModel):
    station_type: str
    seed_value: str | None = None
    station_name: str
    favorite: bool = True


def norm_event(v):
    return {'started': 'start', 'completed': 'finish', 'skipped': 'skip', 'seeked': 'seek', 'paused': 'pause'}.get(v, v)


def norm_thumb(v):
    return {'thumbs_up': 'up', 'thumbs_down': 'down', 'neutral': 'neutral'}.get(v, v)


def track_completion_percent(track: models.Track, position_seconds: float | None, completed_percent: float | None) -> float:
    if completed_percent is not None:
        return float(completed_percent)
    if track.duration_seconds and track.duration_seconds > 0 and position_seconds is not None:
        return (float(position_seconds) / float(track.duration_seconds)) * 100
    return 0.0


def should_qualify_track_listen(event_type: str, track: models.Track | None, payload: PlaybackEventCreate) -> bool:
    if not track:
        return False
    if event_type == 'finish':
        return True
    percent = track_completion_percent(track, payload.position_seconds, payload.completed_percent)
    return percent >= 50.0


def validate_playback_media(payload: PlaybackEventCreate, db: Session) -> MusicPlaybackContext | None:
    has_music = payload.track_id is not None
    has_book = payload.audiobook_id is not None or payload.audiobook_chapter_id is not None
    if has_music and has_book:
        raise HTTPException(422, 'Playback event cannot mix music and audiobook media')
    context = None
    if payload.track_id is not None:
        track = db.get(models.Track, payload.track_id)
        if not track:
            raise HTTPException(404, 'Track not found')
        if not is_track_available(track):
            raise HTTPException(409, TRACK_UNAVAILABLE_MESSAGE)
        context = validate_music_playback_context(db, track)
    if payload.audiobook_chapter_id is not None and payload.audiobook_id is None:
        raise HTTPException(422, 'Audiobook chapter requires audiobook_id')
    if payload.audiobook_id is not None:
        book = db.get(models.Audiobook, payload.audiobook_id)
        if not book:
            raise HTTPException(404, 'Audiobook not found')
        if not is_audiobook_available(book):
            raise HTTPException(409, AUDIOBOOK_UNAVAILABLE_MESSAGE)
        if payload.audiobook_chapter_id is not None:
            chapter = db.get(models.AudiobookChapter, payload.audiobook_chapter_id)
            if not chapter:
                raise HTTPException(404, 'Audiobook chapter not found')
            if chapter.audiobook_id != payload.audiobook_id:
                raise HTTPException(422, 'Chapter does not belong to audiobook')
            if not is_chapter_available(chapter):
                raise HTTPException(409, CHAPTER_UNAVAILABLE_MESSAGE)
    return context


def active_audiobook_progress(db: Session, book: models.Audiobook):
    progress_rows = db.query(models.AudiobookProgress).filter_by(audiobook_id=book.id).order_by(models.AudiobookProgress.updated_at.desc()).limit(10).all()
    for progress in progress_rows:
        if progress.chapter_id is None:
            return progress
        chapter = db.get(models.AudiobookChapter, progress.chapter_id)
        if chapter and chapter.audiobook_id == book.id and is_chapter_available(chapter):
            return progress
    return None


@router.post('/event')
def register_event(payload: PlaybackEventCreate, db: Session = Depends(get_db)):
    event_type = norm_event(payload.event_type)
    if event_type not in {'start', 'pause', 'resume', 'skip', 'finish', 'seek', 'progress', 'qualified_play'}:
        raise HTTPException(422, 'Invalid playback event')
    music_context = validate_playback_media(payload, db)
    recording_id = music_context.recording_id if music_context is not None else None
    track = music_context.track if music_context is not None else None
    event = models.PlaybackEvent(event_type=event_type, track_id=payload.track_id, recording_id=recording_id, audiobook_id=payload.audiobook_id, station_id=payload.station_id, position_seconds=payload.position_seconds)
    db.add(event)
    if (payload.mode == 'music' or payload.track_id) and should_qualify_track_listen(event_type, track, payload):
        if track and not recent_qualified_exists(db, track_id=track.id, recording_id=recording_id):
            db.add(models.PlaybackEvent(event_type='qualified_play', track_id=track.id, recording_id=recording_id, station_id=payload.station_id, position_seconds=payload.position_seconds))
    db.commit()
    db.refresh(event)
    return {'id': event.id, 'event_type': event.event_type}


@router.post('/events')
def register_event_alias(payload: PlaybackEventCreate, db: Session = Depends(get_db)):
    return register_event(payload, db)


def _recent_audiobook_items(db: Session, events: list[models.PlaybackEvent], limit: int) -> list[dict]:
    out = []
    seen = set()
    for event in events:
        if event.audiobook_id is None or event.audiobook_id in seen:
            continue
        book = db.get(models.Audiobook, event.audiobook_id)
        if not is_audiobook_available(book):
            continue
        seen.add(event.audiobook_id)
        item = audiobook_item(book)
        progress = active_audiobook_progress(db, book)
        out.append({'mode': 'audiobook', 'audiobook_id': book.id, 'chapter_id': progress.chapter_id if progress else None, 'position_seconds': progress.position_seconds if progress else 0, 'title': book.title, 'subtitle': book.author, 'cover_url': item['cover_url'], 'stream_url': None, 'last_event_at': str(event.created_at)})
        if len(out) >= limit:
            break
    return out


@router.get('/recent')
def recent_playback(limit: int = 5, db: Session = Depends(get_db)):
    visible_limit = max(1, min(limit, 25))
    candidate_limit = min(max(visible_limit * 20, 80), 500)
    rows = db.query(models.PlaybackEvent).filter(or_(and_(models.PlaybackEvent.track_id.isnot(None), models.PlaybackEvent.event_type == 'qualified_play'), and_(models.PlaybackEvent.audiobook_id.isnot(None), models.PlaybackEvent.event_type.in_(['start', 'pause', 'progress', 'seek'])))).order_by(models.PlaybackEvent.created_at.desc()).limit(candidate_limit).all()
    music_events = [row for row in rows if row.track_id is not None]
    audiobook_events = [row for row in rows if row.audiobook_id is not None]
    music_items = project_recent_music_playback(db, events=music_events, limit=visible_limit)
    audiobook_items = _recent_audiobook_items(db, audiobook_events, visible_limit)
    out = sorted([*music_items, *audiobook_items], key=lambda item: item.get('last_event_at') or '', reverse=True)[:visible_limit]
    return {'items': out}


@router.post('/tracks/{track_id}/thumb')
def track_thumb(track_id: int, payload: TrackThumbCreate, db: Session = Depends(get_db)):
    context = resolve_track_feedback_context(db, track_id)
    if context is None:
        raise HTTPException(404, 'Track not found')
    value = norm_thumb(payload.value)
    if value not in {'up', 'down', 'neutral'}:
        raise HTTPException(422, 'Thumb must be up/down/neutral')
    result = set_feedback(db, context, value, station_id=payload.station_id)
    db.commit()
    response = {'track_id': track_id, 'value': result}
    if context.recording_id is not None:
        response['recording_id'] = context.recording_id
    return response


@router.post('/tracks/{track_id}/feedback')
def track_feedback(track_id: int, payload: TrackThumbCreate, db: Session = Depends(get_db)):
    return track_thumb(track_id, payload, db)


@router.get('/tracks/{track_id}/feedback')
def get_track_feedback(track_id: int, db: Session = Depends(get_db)):
    context = resolve_track_feedback_context(db, track_id)
    if context is None:
        raise HTTPException(404, 'Track not found')
    response = {'track_id': track_id, 'value': current_feedback(db, context)}
    if context.recording_id is not None:
        response['recording_id'] = context.recording_id
    return response


@router.post('/tracks/{track_id}/favorite')
def track_favorite(track_id: int, payload: FavoritePayload | None = None, db: Session = Depends(get_db)):
    context = resolve_track_feedback_context(db, track_id)
    if context is None:
        raise HTTPException(404, 'Track not found')
    desired = toggle_favorite(db, context) if payload is None or payload.favorite is None else set_favorite(db, context, bool(payload.favorite))
    db.commit()
    response = {'track_id': track_id, 'favorite': desired}
    if context.recording_id is not None:
        response['recording_id'] = context.recording_id
    return response


@router.get('/tracks/{track_id}/favorite')
def get_track_favorite(track_id: int, db: Session = Depends(get_db)):
    context = resolve_track_feedback_context(db, track_id)
    if context is None:
        raise HTTPException(404, 'Track not found')
    response = {'track_id': track_id, 'favorite': is_favorite(db, context)}
    if context.recording_id is not None:
        response['recording_id'] = context.recording_id
    return response


@router.post('/stations/favorite')
def station_favorite(payload: StationFavoritePayload, db: Session = Depends(get_db)):
    station = db.query(models.Station).filter_by(type=payload.station_type, seed_value=payload.seed_value).first()
    if not station:
        station = models.Station(name=payload.station_name, type=payload.station_type, seed_value=payload.seed_value, favorite=payload.favorite)
        db.add(station)
    else:
        station.favorite = payload.favorite
        station.name = payload.station_name
    db.commit()
    return {'favorite': payload.favorite}


@router.get('/stations/favorites')
def station_favorites(db: Session = Depends(get_db)):
    return [{'name': s.name, 'type': s.type, 'seed_value': s.seed_value, 'favorite': s.favorite} for s in db.query(models.Station).filter_by(favorite=True).all()]
