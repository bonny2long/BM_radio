from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
from .serializers import track_item
router = APIRouter()
class StationQueueRequest(BaseModel):
    type: str
    seed_value: str | None = None
    limit: int = 50
class AlbumQueueRequest(BaseModel):
    artist: str
    album: str
    limit: int = 50
class ArtistQueueRequest(BaseModel):
    artist: str
    limit: int = 50
def result(query, limit):
    tracks = query.limit(min(max(limit, 1), 500)).all()
    return {'queue': [track_item(track) for track in tracks]}
@router.post('/station')
def station_queue(payload: StationQueueRequest, db: Session = Depends(get_db)):
    q = db.query(models.Track)
    if payload.type == 'favorites': q = q.join(models.TrackFavorite).order_by(models.TrackFavorite.created_at.desc())
    elif payload.type == 'recently_added': q = q.order_by(models.Track.created_at.desc())
    elif payload.type == 'deep_cuts': q = q.outerjoin(models.PlaybackEvent, models.PlaybackEvent.track_id == models.Track.id).group_by(models.Track.id).order_by(func.count(models.PlaybackEvent.id))
    elif payload.type == 'genre': q = q.filter(models.Track.genre == payload.seed_value).order_by(models.Track.artist, models.Track.album, models.Track.title)
    elif payload.type == 'artist': q = q.filter((models.Track.artist == payload.seed_value) | (models.Track.album_artist == payload.seed_value)).order_by(models.Track.album, models.Track.title)
    else: return {'queue': []}
    return result(q, payload.limit)
@router.post('/album')
def album_queue(payload: AlbumQueueRequest, db: Session = Depends(get_db)): return result(db.query(models.Track).filter_by(artist=payload.artist, album=payload.album).order_by(models.Track.title), payload.limit)
@router.post('/artist')
def artist_queue(payload: ArtistQueueRequest, db: Session = Depends(get_db)): return result(db.query(models.Track).filter((models.Track.artist == payload.artist) | (models.Track.album_artist == payload.artist)).order_by(models.Track.album, models.Track.title), payload.limit)
@router.get('/current')
def get_current_queue(): return {'queue': []}