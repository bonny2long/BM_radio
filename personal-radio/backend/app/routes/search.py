from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
from .serializers import track_item, audiobook_item
router=APIRouter()
@router.get('/search')
def global_search(q:str,db:Session=Depends(get_db)):
 term=f'%{q.strip()}%'
 artists=[{'name':n,'track_count':c} for n,c in db.query(models.Track.artist,func.count(models.Track.id)).filter(models.Track.artist.ilike(term)).group_by(models.Track.artist).limit(20).all() if n]
 albums=[{'title':a,'artist':ar,'track_count':c} for a,ar,c in db.query(models.Track.album,models.Track.artist,func.count(models.Track.id)).filter(or_(models.Track.album.ilike(term),models.Track.artist.ilike(term),models.Track.genre.ilike(term))).group_by(models.Track.album,models.Track.artist).limit(30).all()]
 tracks=[track_item(t) for t in db.query(models.Track).filter(or_(models.Track.title.ilike(term),models.Track.artist.ilike(term),models.Track.album.ilike(term),models.Track.album_artist.ilike(term),models.Track.genre.ilike(term),models.Track.relative_path.ilike(term))).limit(80).all()]
 books=[audiobook_item(b) for b in db.query(models.Audiobook).outerjoin(models.AudiobookChapter).filter(or_(models.Audiobook.title.ilike(term),models.Audiobook.author.ilike(term),models.Audiobook.series.ilike(term),models.AudiobookChapter.title.ilike(term))).group_by(models.Audiobook.id).limit(20).all()]
 stations=[]
 for a in artists[:5]:stations.append({'name':a['name']+' Radio','type':'artist','seed_value':a['name'],'track_count':a['track_count']})
 return {'artists':artists,'albums':albums,'tracks':tracks,'stations':stations,'audiobooks':books}