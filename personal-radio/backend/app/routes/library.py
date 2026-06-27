from pathlib import Path
from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from .. import models
from ..config import settings
from ..db import get_db
from ..perf import perf_segment
from ..scanner.music_scanner import scan_music
from .serializers import track_item
router = APIRouter()
def track_query(db,artist=None,album=None,q=None,sort='artist_album_track'):
 query=db.query(models.Track)
 if artist: query=query.filter(or_(models.Track.artist==artist,models.Track.album_artist==artist))
 if album: query=query.filter(models.Track.album==album)
 if q:
  term=f'%{q.strip()}%';query=query.filter(or_(models.Track.title.ilike(term),models.Track.artist.ilike(term),models.Track.album.ilike(term),models.Track.album_artist.ilike(term),models.Track.genre.ilike(term),models.Track.relative_path.ilike(term)))
 if sort=='title': query=query.order_by(models.Track.title)
 elif sort=='album': query=query.order_by(models.Track.album,models.Track.relative_path,models.Track.title)
 elif sort=='created_desc': query=query.order_by(models.Track.created_at.desc())
 else: query=query.order_by(models.Track.artist,models.Track.album,models.Track.relative_path,models.Track.title)
 return query
def page(query,limit,offset):
 limit=min(max(limit,1),200);offset=max(offset,0);total=query.order_by(None).count();items=query.offset(offset).limit(limit).all();return {'items':[track_item(t) for t in items],'total':total,'limit':limit,'offset':offset,'has_more':offset+len(items)<total}
@router.get('/summary')
async def get_summary(db: Session = Depends(get_db)):
 return {'tracks': db.query(func.count(models.Track.id)).scalar(), 'artists': db.query(func.count(func.distinct(models.Track.artist))).scalar(), 'albums': db.query(func.count(func.distinct(models.Track.album))).scalar()}
@router.get('/paths')
async def get_paths():
 paths={'nas_data_root':settings.NAS_DATA_ROOT,'music_root':settings.MUSIC_ROOT,'music_library_root':settings.MUSIC_LIBRARY_ROOT,'music_mp3_root':settings.MUSIC_MP3_ROOT,'music_flac_root':settings.MUSIC_FLAC_ROOT,'music_discographies_root':settings.MUSIC_DISCOGRAPHIES_ROOT,'audiobooks_root':settings.AUDIOBOOKS_ROOT};response=dict(paths);response.update({f'{key}_exists':Path(value).is_dir() for key,value in paths.items()});response['safety']={'public_access':settings.PUBLIC_ACCESS,'allow_file_mutation':settings.ALLOW_FILE_MUTATION,'allow_delete':settings.ALLOW_DELETE,'allow_tag_writes':settings.ALLOW_TAG_WRITES,'scan_ingest_folders':settings.SCAN_INGEST_FOLDERS};return response
@router.get('/tracks')
async def get_tracks(limit:int=100,offset:int=0,artist:str|None=None,album:str|None=None,q:str|None=None,sort:str='artist_album_track',db:Session=Depends(get_db)):
 return [track_item(t) for t in track_query(db,artist,album,q,sort).offset(offset).limit(min(limit,500)).all()]
@router.get('/tracks-page')
def get_tracks_page(limit:int=100,offset:int=0,artist:str|None=None,album:str|None=None,q:str|None=None,sort:str='artist_album_track',db:Session=Depends(get_db)):
 return page(track_query(db,artist,album,q,sort),limit,offset)
@router.get('/artists')
async def get_artists(db:Session=Depends(get_db)):
 rows=db.query(models.Track.artist,func.count(models.Track.id),func.count(func.distinct(models.Track.album))).group_by(models.Track.artist).order_by(models.Track.artist).all();return [{'name':n,'track_count':c,'album_count':a} for n,c,a in rows if n]
@router.get('/artists-page')
def get_artists_page(limit:int=50,offset:int=0,db:Session=Depends(get_db)):
 limit=min(max(limit,1),200);offset=max(offset,0);query=db.query(models.Track.artist,func.count(models.Track.id),func.count(func.distinct(models.Track.album))).group_by(models.Track.artist).order_by(models.Track.artist);rows=query.offset(offset).limit(limit).all();return {'items':[{'name':n,'track_count':c,'album_count':a} for n,c,a in rows if n],'limit':limit,'offset':offset}
@router.get('/artists/{artist}/detail')
def artist_detail(artist:str,db:Session=Depends(get_db)):
 base=track_query(db,artist=artist);total=base.order_by(None).count();albums=[]
 for album,year,count in db.query(models.Track.album,func.min(models.Track.year),func.count(models.Track.id)).filter(or_(models.Track.artist==artist,models.Track.album_artist==artist)).group_by(models.Track.album).order_by(func.min(models.Track.year),models.Track.album).all():albums.append({'title':album,'artist':artist,'year':year,'track_count':count})
 preview=track_query(db,artist=artist).limit(50).all();return {'name':artist,'track_count':total,'album_count':len(albums),'albums':albums,'tracks':[track_item(t) for t in preview]}
@router.get('/artists/{artist}/tracks')
def artist_tracks(artist:str,limit:int=50,offset:int=0,db:Session=Depends(get_db)):
 return page(track_query(db,artist=artist),limit,offset)
@router.get('/artists/{artist}/albums')
def artist_albums(artist:str,db:Session=Depends(get_db)):
 return [{'title':album,'artist':artist,'year':year,'track_count':count} for album,year,count in db.query(models.Track.album,func.min(models.Track.year),func.count(models.Track.id)).filter(or_(models.Track.artist==artist,models.Track.album_artist==artist)).group_by(models.Track.album).order_by(func.min(models.Track.year),models.Track.album).all()]

def album_rows(db: Session, limit: int | None = None, offset: int = 0, segment_prefix: str = 'library.albums'):
 query=db.query(models.Track.album,models.Track.artist,func.min(models.Track.year),func.count(models.Track.id)).group_by(models.Track.album,models.Track.artist).order_by(func.max(models.Track.created_at).desc(),models.Track.artist,models.Track.album)
 if offset: query=query.offset(max(offset,0))
 if limit is not None: query=query.limit(min(max(limit,1),200))
 with perf_segment(f'{segment_prefix}.sql'):
  rows=query.all()
 with perf_segment(f'{segment_prefix}.serialize'):
  return [{'title':album,'artist':artist,'year':year,'track_count':count,'cover_url':f'/api/media/albums/cover?artist={artist}&album={album}'} for album,artist,year,count in rows]

@router.get('/albums')
async def get_albums(db:Session=Depends(get_db)):
 return album_rows(db)
@router.get('/albums-page')
def get_albums_page(limit:int=50,offset:int=0,db:Session=Depends(get_db)):
 return {'items':album_rows(db,limit,offset),'limit':min(max(limit,1),200),'offset':max(offset,0)}
@router.get('/recent-albums')
def get_recent_albums(limit:int=8,db:Session=Depends(get_db)):
 return album_rows(db,limit,0,'library.recent_albums')
@router.get('/search')
async def search(q:str,db:Session=Depends(get_db)):
 term=f'%{q.strip()}%';return [track_item(track) for track in db.query(models.Track).filter(or_(models.Track.title.ilike(term),models.Track.artist.ilike(term),models.Track.album.ilike(term),models.Track.album_artist.ilike(term),models.Track.genre.ilike(term),models.Track.relative_path.ilike(term),models.Track.library_area.ilike(term))).limit(300).all()]
@router.post('/scan/music')
async def scan_music_route(db:Session=Depends(get_db)):return scan_music(db)
@router.get('/album-tracks')
def playback_album_tracks(artist:str,album:str,db:Session=Depends(get_db)):
 return [track_item(track) for track in db.query(models.Track).filter_by(artist=artist,album=album).order_by(models.Track.relative_path,models.Track.title).limit(500)]