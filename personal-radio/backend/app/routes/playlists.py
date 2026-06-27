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
class TrackListPlaylistCreate(BaseModel):
    name:str
    description:str|None=None
    track_ids:list[int]

def latest_thumb_values(db:Session):
    rows=db.query(models.TrackThumb).order_by(models.TrackThumb.created_at.asc()).all()
    return {r.track_id:r.value.value for r in rows}
def smart_track_ids(db:Session,key:str,limit:int=500):
    limit=max(1,min(limit,1000))
    if key=='favorites':
        return [r[0] for r in db.query(models.TrackFavorite.track_id).order_by(models.TrackFavorite.created_at.desc()).limit(limit).all()]
    if key=='thumbs_up':
        latest=latest_thumb_values(db);return [tid for tid,value in latest.items() if value=='up'][:limit]
    if key=='most_played':
        rows=db.query(models.PlaybackEvent.track_id,func.count(models.PlaybackEvent.id).label('plays')).filter(models.PlaybackEvent.track_id.isnot(None),models.PlaybackEvent.event_type=='qualified_play').group_by(models.PlaybackEvent.track_id).order_by(func.count(models.PlaybackEvent.id).desc()).limit(limit).all();return [r[0] for r in rows]
    if key=='recently_played':
        rows=db.query(models.PlaybackEvent.track_id).filter(models.PlaybackEvent.track_id.isnot(None),models.PlaybackEvent.event_type=='qualified_play').order_by(models.PlaybackEvent.created_at.desc()).limit(limit*4).all();out=[];seen=set()
        for (tid,) in rows:
            if tid and tid not in seen:
                seen.add(tid);out.append(tid)
            if len(out)>=limit:break
        return out
    if key=='recently_added':
        return [r[0] for r in db.query(models.Track.id).order_by(models.Track.created_at.desc(),models.Track.last_indexed_at.desc()).limit(limit).all()]
    if key=='never_played':
        rows=db.query(models.Track.id).outerjoin(models.PlaybackEvent,(models.PlaybackEvent.track_id==models.Track.id) & (models.PlaybackEvent.event_type=='qualified_play')).group_by(models.Track.id).having(func.count(models.PlaybackEvent.id)==0).order_by(models.Track.created_at.desc()).limit(limit).all();return [r[0] for r in rows]
    return []
def smart_count(db:Session,key:str):
    if key=='favorites':
        return db.query(func.count(func.distinct(models.TrackFavorite.track_id))).scalar() or 0
    if key=='thumbs_up':
        return sum(1 for value in latest_thumb_values(db).values() if value=='up')
    if key=='most_played':
        return db.query(func.count(func.distinct(models.PlaybackEvent.track_id))).filter(models.PlaybackEvent.track_id.isnot(None),models.PlaybackEvent.event_type=='qualified_play').scalar() or 0
    if key=='recently_played':
        return db.query(func.count(func.distinct(models.PlaybackEvent.track_id))).filter(models.PlaybackEvent.track_id.isnot(None),models.PlaybackEvent.event_type=='qualified_play').scalar() or 0
    if key=='recently_added':
        return db.query(func.count(models.Track.id)).scalar() or 0
    if key=='never_played':
        return db.query(func.count(models.Track.id)).outerjoin(models.PlaybackEvent,(models.PlaybackEvent.track_id==models.Track.id) & (models.PlaybackEvent.event_type=='qualified_play')).group_by(models.Track.id).having(func.count(models.PlaybackEvent.id)==0).count()
    return 0

def smart_summary(db:Session,key:str,name:str,description:str):
    return {'id':key,'name':name,'kind':'smart','track_count':smart_count(db,key),'description':description}
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
@router.get('/smart')
def get_smart_playlists(db:Session=Depends(get_db)):
    return [
        smart_summary(db,'favorites','Favorites','Hearted tracks'),
        smart_summary(db,'most_played','Most Played','Tracks you play the most'),
        smart_summary(db,'recently_played','Recently Played','Latest unique tracks from your listening history'),
        smart_summary(db,'recently_added','Recently Added','Newest tracks in your library'),
        smart_summary(db,'never_played','Never Played','Tracks with no playback history'),
        smart_summary(db,'thumbs_up','Thumbs Up','Tracks you rated thumbs up'),
    ]
@router.post('')
def create_playlist(payload:PlaylistCreate,db:Session=Depends(get_db)):
    name=payload.name.strip()
    if not name:raise HTTPException(422,'Playlist name is required')
    p=models.Playlist(name=name,description=payload.description,kind='manual');db.add(p);db.commit();db.refresh(p);return summary(p,db)
@router.post('/from-track-list')
def create_from_track_list(payload:TrackListPlaylistCreate,db:Session=Depends(get_db)):
    name=payload.name.strip()
    if not name:raise HTTPException(422,'Playlist name is required')
    p=models.Playlist(name=name,description=payload.description,kind='manual');db.add(p);db.flush()
    seen=set();position=1
    for track_id in payload.track_ids:
        if track_id in seen:continue
        if db.get(models.Track,track_id):
            db.add(models.PlaylistTrack(playlist_id=p.id,track_id=track_id,position=position));seen.add(track_id);position+=1
    db.commit();db.refresh(p);return detail(p,db)
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
