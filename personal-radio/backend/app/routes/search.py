from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from .. import models
from ..availability import available_audiobook_filter, available_chapter_filter
from ..db import get_db
from ..listener_library import global_music_search
from .serializers import audiobook_item

router = APIRouter()


@router.get('/search')
def global_search(q: str, db: Session = Depends(get_db)):
    term = f'%{q.strip()}%'
    music = global_music_search(db, q=q)
    books = [
        audiobook_item(b)
        for b in db.query(models.Audiobook)
        .outerjoin(models.AudiobookChapter, and_(models.AudiobookChapter.audiobook_id == models.Audiobook.id, available_chapter_filter()))
        .filter(available_audiobook_filter())
        .filter(or_(models.Audiobook.title.ilike(term), models.Audiobook.author.ilike(term), models.Audiobook.series.ilike(term), models.AudiobookChapter.title.ilike(term)))
        .group_by(models.Audiobook.id)
        .limit(20)
        .all()
    ]
    return {**music, 'audiobooks': books}