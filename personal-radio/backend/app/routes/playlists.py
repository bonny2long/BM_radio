from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
from .serializers import track_item
router=APIRouter()
class PlaylistCreate(BaseModel):
    name:str
    description:str|None=None
class PlaylistPatch(BaseModel):
    name:str|None=None
    description:str|None=None
class PlaylistTrackCreate(BaseModel):
    track_id:int
class ReorderPayload(BaseModel):
    track_ids:list[int]
def summary(p:models.Playlist,db:Session):
    count=db.query(func.count(models.PlaylistTrack.id)).filter_by(playlist_id=p.id).scalar()
    return {'id':p.id,'name':p.name,'description':p.description,'kind':p.kind,'track_count':count or 0}
def detail(p:models.Playlist,db:Session):
    rows=db.query(models.PlaylistTrack).filter_by(playlist_id=p.id).order_by(models.PlaylistTrack.position,models.PlaylistTrack.id).all()
    return {**summary(p,db),'tracks':[track_item(r.track) for r in rows if r.track]}
def get_playlist_or_404(playlist_id:int,db:Session):
    p=db.get(models.Playlist,playlist_id)
    if not p:raise HTTPException(404,'Playlist not found')
    return p
@router.get('')
def get_playlists(db:Session=Depends(get_db)):
    return [summary(p,db) for p in db.query(models.Playlist).order_by(models.Playlist.created_at.desc(),models.Playlist.name).all()]
@router.post('')
def create_playlist(payload:PlaylistCreate,db:Session=Depends(get_db)):
    name=payload.name.strip()
    if not name:raise HTTPException(422,'Playlist name is required')
    p=models.Playlist(name=name,description=payload.description,kind='manual');db.add(p);db.commit();db.refresh(p);return summary(p,db)
@router.get('/{playlist_id}')
def get_playlist(playlist_id:int,db:Session=Depends(get_db)):
    return detail(get_playlist_or_404(playlist_id,db),db)
@router.patch('/{playlist_id}')
def patch_playlist(playlist_id:int,payload:PlaylistPatch,db:Session=Depends(get_db)):
    p=get_playlist_or_404(playlist_id,db)
    if payload.name is not None:
        name=payload.name.strip()
        if not name:raise HTTPException(422,'Playlist name is required')
        p.name=name
    if payload.description is not None:p.description=payload.description
    db.commit();return summary(p,db)
@router.delete('/{playlist_id}')
def delete_playlist(playlist_id:int,db:Session=Depends(get_db)):
    p=get_playlist_or_404(playlist_id,db);db.delete(p);db.commit();return {'deleted':True}
@router.post('/{playlist_id}/tracks')
def add_track(playlist_id:int,payload:PlaylistTrackCreate,db:Session=Depends(get_db)):
    p=get_playlist_or_404(playlist_id,db)
    if not db.get(models.Track,payload.track_id):raise HTTPException(404,'Track not found')
    existing=db.query(models.PlaylistTrack).filter_by(playlist_id=p.id,track_id=payload.track_id).first()
    if not existing:
        max_pos=db.query(func.max(models.PlaylistTrack.position)).filter_by(playlist_id=p.id).scalar() or 0
        db.add(models.PlaylistTrack(playlist_id=p.id,track_id=payload.track_id,position=max_pos+1));db.commit()
    return detail(p,db)
@router.delete('/{playlist_id}/tracks/{track_id}')
def remove_track(playlist_id:int,track_id:int,db:Session=Depends(get_db)):
    p=get_playlist_or_404(playlist_id,db)
    rows=db.query(models.PlaylistTrack).filter_by(playlist_id=p.id,track_id=track_id).all()
    for row in rows:db.delete(row)
    db.commit();return detail(p,db)
@router.patch('/{playlist_id}/tracks/reorder')
def reorder_tracks(playlist_id:int,payload:ReorderPayload,db:Session=Depends(get_db)):
    p=get_playlist_or_404(playlist_id,db);positions={tid:i+1 for i,tid in enumerate(payload.track_ids)}
    for row in db.query(models.PlaylistTrack).filter_by(playlist_id=p.id).all():
        if row.track_id in positions:row.position=positions[row.track_id]
    db.commit();return detail(p,db)
