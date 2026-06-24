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
    station_id: int | None = None
    position_seconds: float | None = None
class TrackThumbCreate(BaseModel):
    value: str
    station_id: int | None = None
@router.post('/event')
def register_event(payload: PlaybackEventCreate, db: Session = Depends(get_db)):
    if payload.event_type not in {'start','pause','resume','skip','finish','seek','progress'}: raise HTTPException(422, 'Invalid playback event')
    event = models.PlaybackEvent(**payload.model_dump()); db.add(event); db.commit(); db.refresh(event)
    return {'id': event.id, 'event_type': event.event_type}
@router.post('/tracks/{track_id}/thumb')
def track_thumb(track_id: int, payload: TrackThumbCreate, db: Session = Depends(get_db)):
    if not db.get(models.Track, track_id): raise HTTPException(404, 'Track not found')
    if payload.value not in {'up','down'}: raise HTTPException(422, 'Thumb must be up or down')
    thumb = models.TrackThumb(track_id=track_id, station_id=payload.station_id, value=models.ThumbValue(payload.value)); db.add(thumb); db.commit()
    return {'track_id': track_id, 'value': payload.value}
@router.post('/tracks/{track_id}/favorite')
def track_favorite(track_id: int, db: Session = Depends(get_db)):
    if not db.get(models.Track, track_id): raise HTTPException(404, 'Track not found')
    favorite = db.query(models.TrackFavorite).filter_by(track_id=track_id).first()
    if favorite: db.delete(favorite); state = False
    else: db.add(models.TrackFavorite(track_id=track_id)); state = True
    db.commit(); return {'track_id': track_id, 'favorite': state}