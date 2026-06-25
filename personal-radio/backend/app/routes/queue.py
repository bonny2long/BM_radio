import random
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
from .serializers import track_item
router = APIRouter()
class StationQueueRequest(BaseModel):
 type:str
 seed_value:str|None=None
 limit:int=50
 shuffle:bool=True
class AlbumQueueRequest(BaseModel):
 artist:str
 album:str
 limit:int=500
class ArtistQueueRequest(BaseModel):
 artist:str
 limit:int=50
def latest_feedback(db:Session)->dict[int,str]:
 rows=db.query(models.TrackThumb).order_by(models.TrackThumb.created_at.asc()).all();return {r.track_id:r.value.value for r in rows}
def play_counts(db:Session)->dict[int,int]:
 rows=db.query(models.PlaybackEvent.track_id,func.count(models.PlaybackEvent.id)).filter(models.PlaybackEvent.track_id.isnot(None)).group_by(models.PlaybackEvent.track_id).all();return {tid:c for tid,c in rows}
def score_tracks(db:Session,tracks:list[models.Track],station_type:str)->list[models.Track]:
 fb=latest_feedback(db);counts=play_counts(db);scored=[]
 for t in tracks:
  rating=fb.get(t.id);score=random.random()
  score-=min(counts.get(t.id,0),20)*0.08
  if rating=='up':score+=0.35
  if rating=='down':score-=5.0
  if station_type=='deep_cuts':score-=counts.get(t.id,0)*0.2
  scored.append((score,t))
 scored.sort(key=lambda x:x[0],reverse=True);return [t for _,t in scored]
def no_repeats(tracks:list[models.Track],limit:int,artist_loose:bool=False)->list[models.Track]:
 out=[];used=set();last_album=None;artist_run={}
 for t in tracks:
  if t.id in used:continue
  if last_album and t.album==last_album and len(out)+1<limit:
   continue
  if not artist_loose and artist_run.get(t.artist,0)>=2 and len(out)+1<limit:
   continue
  out.append(t);used.add(t.id);last_album=t.album;artist_run={t.artist:artist_run.get(t.artist,0)+1}
  if len(out)>=limit:break
 if len(out)<limit:
  for t in tracks:
   if t.id not in used:
    out.append(t);used.add(t.id)
    if len(out)>=limit:break
 return out
def payload(tracks):return {'queue':[track_item(t) for t in tracks]}
@router.post('/station')
def station_queue(req:StationQueueRequest,db:Session=Depends(get_db)):
 limit=min(max(req.limit,1),100);q=db.query(models.Track)
 if req.type=='favorites':
  tracks=[f.track for f in db.query(models.TrackFavorite).order_by(models.TrackFavorite.created_at.desc()).limit(limit*4).all() if f.track]
 elif req.type=='recently_added':
  tracks=q.order_by(models.Track.created_at.desc()).limit(limit*5).all();random.shuffle(tracks)
 elif req.type=='deep_cuts':
  tracks=q.outerjoin(models.PlaybackEvent,models.PlaybackEvent.track_id==models.Track.id).group_by(models.Track.id).order_by(func.count(models.PlaybackEvent.id),func.random()).limit(limit*6).all()
 elif req.type=='genre':
  tracks=q.filter(models.Track.genre==req.seed_value).limit(limit*6).all();random.shuffle(tracks)
 elif req.type=='artist':
  tracks=q.filter(or_(models.Track.artist==req.seed_value,models.Track.album_artist==req.seed_value)).limit(limit*6).all();random.shuffle(tracks)
 else:return {'queue':[]}
 tracks=score_tracks(db,tracks,req.type)
 return payload(no_repeats(tracks,limit,artist_loose=req.type=='artist'))
@router.post('/album')
def album_queue(req:AlbumQueueRequest,db:Session=Depends(get_db)):
 return payload(db.query(models.Track).filter_by(artist=req.artist,album=req.album).order_by(models.Track.relative_path,models.Track.title).limit(min(req.limit,500)).all())
@router.post('/artist')
def artist_queue(req:ArtistQueueRequest,db:Session=Depends(get_db)):
 tracks=db.query(models.Track).filter(or_(models.Track.artist==req.artist,models.Track.album_artist==req.artist)).limit(min(req.limit*6,500)).all();random.shuffle(tracks);return payload(no_repeats(score_tracks(db,tracks,'artist'),min(req.limit,100),artist_loose=True))
@router.get('/current')
def get_current_queue():return {'queue':[]}