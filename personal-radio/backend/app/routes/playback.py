from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
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
    return {'started':'start','completed':'finish','skipped':'skip','seeked':'seek','paused':'pause'}.get(v,v)
def norm_thumb(v):
    return {'thumbs_up':'up','thumbs_down':'down','neutral':'neutral'}.get(v,v)
@router.post('/event')
def register_event(payload: PlaybackEventCreate, db: Session = Depends(get_db)):
    event_type=norm_event(payload.event_type)
    if event_type not in {'start','pause','resume','skip','finish','seek','progress'}: raise HTTPException(422, 'Invalid playback event')
    event=models.PlaybackEvent(event_type=event_type,track_id=payload.track_id,audiobook_id=payload.audiobook_id,station_id=payload.station_id,position_seconds=payload.position_seconds)
    db.add(event); db.commit(); db.refresh(event); return {'id': event.id, 'event_type': event.event_type}
@router.post('/events')
def register_event_alias(payload: PlaybackEventCreate, db: Session = Depends(get_db)): return register_event(payload,db)
@router.post('/tracks/{track_id}/thumb')
def track_thumb(track_id: int, payload: TrackThumbCreate, db: Session = Depends(get_db)):
    if not db.get(models.Track, track_id): raise HTTPException(404, 'Track not found')
    value=norm_thumb(payload.value)
    if value=='neutral':
        db.query(models.TrackThumb).filter_by(track_id=track_id).delete(); db.commit(); return {'track_id': track_id, 'value': 'neutral'}
    if value not in {'up','down'}: raise HTTPException(422, 'Thumb must be up/down/neutral')
    thumb = models.TrackThumb(track_id=track_id, station_id=payload.station_id, value=models.ThumbValue(value)); db.add(thumb); db.commit(); return {'track_id': track_id, 'value': value}
@router.post('/tracks/{track_id}/feedback')
def track_feedback(track_id:int,payload:TrackThumbCreate,db:Session=Depends(get_db)): return track_thumb(track_id,payload,db)
@router.get('/tracks/{track_id}/feedback')
def get_track_feedback(track_id:int,db:Session=Depends(get_db)):
    row=db.query(models.TrackThumb).filter_by(track_id=track_id).order_by(models.TrackThumb.created_at.desc()).first(); return {'track_id':track_id,'value':row.value.value if row else 'neutral'}
@router.post('/tracks/{track_id}/favorite')
def track_favorite(track_id: int, payload:FavoritePayload|None=None, db: Session = Depends(get_db)):
    if not db.get(models.Track, track_id): raise HTTPException(404, 'Track not found')
    favorite = db.query(models.TrackFavorite).filter_by(track_id=track_id).first(); desired = (not bool(favorite)) if payload is None or payload.favorite is None else payload.favorite
    if desired and not favorite: db.add(models.TrackFavorite(track_id=track_id))
    if not desired and favorite: db.delete(favorite)
    db.commit(); return {'track_id': track_id, 'favorite': desired}
@router.get('/tracks/{track_id}/favorite')
def get_track_favorite(track_id:int,db:Session=Depends(get_db)):
    return {'track_id':track_id,'favorite':db.query(models.TrackFavorite).filter_by(track_id=track_id).first() is not None}
@router.post('/stations/favorite')
def station_favorite(payload:StationFavoritePayload,db:Session=Depends(get_db)):
    station=db.query(models.Station).filter_by(type=payload.station_type,seed_value=payload.seed_value).first()
    if not station:
        station=models.Station(name=payload.station_name,type=payload.station_type,seed_value=payload.seed_value,favorite=payload.favorite);db.add(station)
    else:
        station.favorite=payload.favorite;station.name=payload.station_name
    db.commit();return {'favorite':payload.favorite}
@router.get('/stations/favorites')
def station_favorites(db:Session=Depends(get_db)):
    return [{'name':s.name,'type':s.type,'seed_value':s.seed_value,'favorite':s.favorite} for s in db.query(models.Station).filter_by(favorite=True).all()]