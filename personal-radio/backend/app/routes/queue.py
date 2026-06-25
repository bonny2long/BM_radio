import random,re
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
 shuffle:bool=False
class ArtistQueueRequest(BaseModel):
 artist:str
 limit:int=50
 shuffle:bool=False
ARTIST_GENRE_FALLBACKS={
 'Kanye West':'Hip-Hop',
 'Kendrick Lamar':'Hip-Hop',
 'Lil Wayne':'Hip-Hop',
 'The Weeknd':'R&B',
}
GENRE_ALIASES={
 'hip hop':'hip-hop','hip-hop':'hip-hop','hiphop':'hip-hop','rap':'hip-hop',
 'r&b':'r&b','rnb':'r&b','rhythm and blues':'r&b',
}
def norm_genre(value:str|None)->str:
 v=(value or '').strip().lower().replace('/',' ').replace('_',' ')
 v=' '.join(v.split())
 return GENRE_ALIASES.get(v,v)
def display_genre(value:str|None)->str:
 v=norm_genre(value)
 return {'hip-hop':'Hip-Hop','r&b':'R&B'}.get(v,(value or '').strip())
def track_genre(track:models.Track)->str:
 return norm_genre(track.genre or ARTIST_GENRE_FALLBACKS.get(track.artist) or ARTIST_GENRE_FALLBACKS.get(track.album_artist))
def latest_feedback(db:Session)->dict[int,str]:
 rows=db.query(models.TrackThumb).order_by(models.TrackThumb.created_at.asc()).all();return {r.track_id:r.value.value for r in rows}
def play_counts(db:Session)->dict[int,int]:
 rows=db.query(models.PlaybackEvent.track_id,func.count(models.PlaybackEvent.id)).filter(models.PlaybackEvent.track_id.isnot(None)).group_by(models.PlaybackEvent.track_id).all();return {tid:c for tid,c in rows}
def recent_ids(db:Session,limit:int=80)->set[int]:
 rows=db.query(models.PlaybackEvent.track_id).filter(models.PlaybackEvent.track_id.isnot(None)).order_by(models.PlaybackEvent.created_at.desc()).limit(limit).all();return {r[0] for r in rows if r[0]}
def favorite_ids(db:Session)->set[int]:
 return {r[0] for r in db.query(models.TrackFavorite.track_id).all()}
def album_counts(tracks:list[models.Track])->dict[tuple[str,str],int]:
 counts={}
 for t in tracks:
  key=(t.artist or '',t.album or '');counts[key]=counts.get(key,0)+1
 return counts
def track_number_guess(track:models.Track)->int|None:
 text=' '.join([track.relative_path or '',track.title or ''])
 m=re.search(r'(?:^|[\\/\s._-])(?:disc\s*\d+[\\/\s._-]*)?(\d{1,2})(?:[\s._-]+|$)',text,re.I)
 if m:
  n=int(m.group(1))
  if 1<=n<=40:return n
 return None
def score_tracks(db:Session,tracks:list[models.Track],station_type:str)->list[models.Track]:
 fb=latest_feedback(db);counts=play_counts(db);recent=recent_ids(db);favs=favorite_ids(db);albums=album_counts(tracks);scored=[]
 for t in tracks:
  rating=fb.get(t.id);plays=counts.get(t.id,0);num=track_number_guess(t);album_total=albums.get((t.artist or '',t.album or ''),0);score=random.random()
  score-=min(plays,20)*0.08
  if rating=='up':score+=0.35
  if rating=='down':score-=5.0
  if t.id in recent:score-=0.45
  if station_type=='deep_cuts':
   if plays==0:score+=1.0
   else:score+=max(0,.5-(plays*.12))
   if num and num>=4:score+=0.45
   if album_total>=6:score+=0.25
   if num in (1,2):score-=0.45
   if t.id in favs:score-=0.35
  if station_type=='favorites' and rating=='up':score+=0.25
  scored.append((score,t))
 scored.sort(key=lambda x:x[0],reverse=True);return [t for _,t in scored]
def no_repeats(tracks:list[models.Track],limit:int,artist_loose:bool=False)->list[models.Track]:
 out=[];used=set();last_album=None;artist_run={}
 for t in tracks:
  if t.id in used:continue
  if last_album and t.album==last_album and len(out)+1<limit:continue
  if not artist_loose and artist_run.get(t.artist,0)>=2 and len(out)+1<limit:continue
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
 limit=min(max(req.limit,1),100);q=db.query(models.Track);fb=latest_feedback(db);down={tid for tid,value in fb.items() if value=='down'}
 if req.type=='favorites':
  fav_tracks=[f.track for f in db.query(models.TrackFavorite).order_by(models.TrackFavorite.created_at.desc()).limit(limit*6).all() if f.track]
  up_ids=[tid for tid,value in fb.items() if value=='up']
  up_tracks=db.query(models.Track).filter(models.Track.id.in_(up_ids)).all() if up_ids else []
  tracks=[t for t in fav_tracks+up_tracks if t.id not in down]
 elif req.type=='recently_added':
  tracks=q.order_by(models.Track.created_at.desc(),models.Track.last_indexed_at.desc()).limit(limit*5).all();random.shuffle(tracks);tracks=[t for t in tracks if t.id not in down]
 elif req.type=='deep_cuts':
  tracks=q.outerjoin(models.PlaybackEvent,models.PlaybackEvent.track_id==models.Track.id).group_by(models.Track.id).order_by(func.count(models.PlaybackEvent.id),func.random()).limit(limit*10).all();tracks=[t for t in tracks if t.id not in down]
 elif req.type=='genre':
  target=norm_genre(req.seed_value);tracks=[t for t in q.limit(5000).all() if t.id not in down and track_genre(t)==target];random.shuffle(tracks)
 elif req.type=='artist':
  tracks=q.filter(or_(models.Track.artist==req.seed_value,models.Track.album_artist==req.seed_value)).limit(limit*8).all();random.shuffle(tracks);tracks=[t for t in tracks if t.id not in down]
 else:return {'queue':[]}
 tracks=score_tracks(db,tracks,req.type)
 return payload(no_repeats(tracks,limit,artist_loose=req.type=='artist'))
@router.post('/album')
def album_queue(req:AlbumQueueRequest,db:Session=Depends(get_db)):
 tracks=db.query(models.Track).filter_by(artist=req.artist,album=req.album).order_by(models.Track.relative_path,models.Track.title).limit(min(req.limit,500)).all()
 if req.shuffle:random.shuffle(tracks)
 return payload(tracks)
@router.post('/artist')
def artist_queue(req:ArtistQueueRequest,db:Session=Depends(get_db)):
 tracks=db.query(models.Track).filter(or_(models.Track.artist==req.artist,models.Track.album_artist==req.artist)).limit(min(req.limit*8,500)).all();random.shuffle(tracks)
 if not req.shuffle:tracks=score_tracks(db,tracks,'artist')
 return payload(no_repeats(tracks,min(req.limit,100),artist_loose=True))
@router.get('/current')
def get_current_queue():return {'queue':[]}
