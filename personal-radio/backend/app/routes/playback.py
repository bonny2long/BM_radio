from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from .. import models
from ..availability import AUDIOBOOK_UNAVAILABLE_MESSAGE, CHAPTER_UNAVAILABLE_MESSAGE, TRACK_UNAVAILABLE_MESSAGE, is_audiobook_available, is_chapter_available, is_track_available
from ..db import get_db
from .serializers import track_item, audiobook_item

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


def recent_qualified_exists(db: Session, track_id: int, minutes: int = 30) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return (
        db.query(models.PlaybackEvent.id)
        .filter(
            models.PlaybackEvent.track_id == track_id,
            models.PlaybackEvent.event_type == 'qualified_play',
            models.PlaybackEvent.created_at >= cutoff,
        )
        .first()
        is not None
    )


def validate_playback_media(payload: PlaybackEventCreate, db: Session) -> models.Track | None:
    has_music = payload.track_id is not None
    has_book = payload.audiobook_id is not None or payload.audiobook_chapter_id is not None
    if has_music and has_book:
        raise HTTPException(422, 'Playback event cannot mix music and audiobook media')
    track = None
    if payload.track_id is not None:
        track = db.get(models.Track, payload.track_id)
        if not track:
            raise HTTPException(404, 'Track not found')
        if not is_track_available(track):
            raise HTTPException(409, TRACK_UNAVAILABLE_MESSAGE)
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
    return track


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
    track = validate_playback_media(payload, db)
    event = models.PlaybackEvent(event_type=event_type, track_id=payload.track_id, audiobook_id=payload.audiobook_id, station_id=payload.station_id, position_seconds=payload.position_seconds)
    db.add(event)
    if (payload.mode == 'music' or payload.track_id) and should_qualify_track_listen(event_type, track, payload):
        if track and not recent_qualified_exists(db, track.id):
            db.add(models.PlaybackEvent(event_type='qualified_play', track_id=track.id, station_id=payload.station_id, position_seconds=payload.position_seconds))
    db.commit()
    db.refresh(event)
    return {'id': event.id, 'event_type': event.event_type}


@router.post('/events')
def register_event_alias(payload: PlaybackEventCreate, db: Session = Depends(get_db)):
    return register_event(payload, db)


@router.get('/recent')
def recent_playback(limit: int = 5, db: Session = Depends(get_db)):
    visible_limit = max(1, min(limit, 25))
    rows = db.query(models.PlaybackEvent).filter(or_(and_(models.PlaybackEvent.track_id.isnot(None), models.PlaybackEvent.event_type == 'qualified_play'), and_(models.PlaybackEvent.audiobook_id.isnot(None), models.PlaybackEvent.event_type.in_(['start', 'pause', 'progress', 'seek'])))).order_by(models.PlaybackEvent.created_at.desc()).limit(min(max(visible_limit * 12, 40), 200)).all()
    out = []
    seen = set()
    for e in rows:
        key = ('track', e.track_id) if e.track_id else ('book', e.audiobook_id)
        if key in seen:
            continue
        if e.track_id:
            track = db.get(models.Track, e.track_id)
            if not is_track_available(track):
                continue
            seen.add(key)
            item = track_item(track)
            out.append({'mode': 'music', 'track_id': track.id, 'title': track.title, 'subtitle': ' - '.join([x for x in [track.artist, track.album] if x]), 'cover_url': item['cover_url'], 'stream_url': item['stream_url'], 'last_event_at': str(e.created_at)})
        elif e.audiobook_id:
            book = db.get(models.Audiobook, e.audiobook_id)
            if not is_audiobook_available(book):
                continue
            seen.add(key)
            item = audiobook_item(book)
            progress = active_audiobook_progress(db, book)
            out.append({'mode': 'audiobook', 'audiobook_id': book.id, 'chapter_id': progress.chapter_id if progress else None, 'position_seconds': progress.position_seconds if progress else 0, 'title': book.title, 'subtitle': book.author, 'cover_url': item['cover_url'], 'stream_url': None, 'last_event_at': str(e.created_at)})
        if len(out) >= visible_limit:
            break
    return {'items': out}


@router.post('/tracks/{track_id}/thumb')
def track_thumb(track_id: int, payload: TrackThumbCreate, db: Session = Depends(get_db)):
    if not db.get(models.Track, track_id):
        raise HTTPException(404, 'Track not found')
    value = norm_thumb(payload.value)
    if value == 'neutral':
        db.query(models.TrackThumb).filter_by(track_id=track_id).delete()
        db.commit()
        return {'track_id': track_id, 'value': 'neutral'}
    if value not in {'up', 'down'}:
        raise HTTPException(422, 'Thumb must be up/down/neutral')
    thumb = models.TrackThumb(track_id=track_id, station_id=payload.station_id, value=models.ThumbValue(value))
    db.add(thumb)
    db.commit()
    return {'track_id': track_id, 'value': value}


@router.post('/tracks/{track_id}/feedback')
def track_feedback(track_id: int, payload: TrackThumbCreate, db: Session = Depends(get_db)):
    return track_thumb(track_id, payload, db)


@router.get('/tracks/{track_id}/feedback')
def get_track_feedback(track_id: int, db: Session = Depends(get_db)):
    row = db.query(models.TrackThumb).filter_by(track_id=track_id).order_by(models.TrackThumb.created_at.desc()).first()
    return {'track_id': track_id, 'value': row.value.value if row else 'neutral'}


@router.post('/tracks/{track_id}/favorite')
def track_favorite(track_id: int, payload: FavoritePayload | None = None, db: Session = Depends(get_db)):
    if not db.get(models.Track, track_id):
        raise HTTPException(404, 'Track not found')
    favorite = db.query(models.TrackFavorite).filter_by(track_id=track_id).first()
    desired = (not bool(favorite)) if payload is None or payload.favorite is None else payload.favorite
    if desired and not favorite:
        db.add(models.TrackFavorite(track_id=track_id))
    if not desired and favorite:
        db.delete(favorite)
    db.commit()
    return {'track_id': track_id, 'favorite': desired}


@router.get('/tracks/{track_id}/favorite')
def get_track_favorite(track_id: int, db: Session = Depends(get_db)):
    return {'track_id': track_id, 'favorite': db.query(models.TrackFavorite).filter_by(track_id=track_id).first() is not None}


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