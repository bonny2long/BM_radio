from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
from ..scanner.audiobook_scanner import scan_audiobooks as run_audiobook_scan
from .serializers import chapter_item
router = APIRouter()
def as_detail(book):
    progress = sorted(book.progress, key=lambda p: p.updated_at or 0, reverse=True)
    latest = progress[0] if progress else None
    return {'id':book.id,'title':book.title,'author':book.author,'narrator':book.narrator,'status':book.status,'favorite':book.favorite,'duration_seconds':book.duration_seconds,'latest_progress':None if not latest else {'chapter_id':latest.chapter_id,'position_seconds':latest.position_seconds,'progress_percent':latest.progress_percent},'chapters':[chapter_item(c) for c in sorted(book.chapters,key=lambda c:c.sort_order)]}
@router.get('/')
def get_audiobooks(db: Session=Depends(get_db)):
    return [{'id':b.id,'title':b.title,'author':b.author,'status':b.status,'favorite':b.favorite,'duration_seconds':b.duration_seconds} for b in db.query(models.Audiobook).order_by(models.Audiobook.title)]
@router.get('/summary')
def get_summary(db: Session=Depends(get_db)):
    books=db.query(models.Audiobook).all(); return {'available':sum(b.status=='available' for b in books),'not_started':sum(b.status=='available' for b in books),'in_progress':sum(b.status=='in_progress' for b in books),'finished':sum(b.status=='finished' for b in books),'favorites':sum(b.favorite for b in books),'total_listening_seconds':db.query(func.coalesce(func.sum(models.AudiobookProgress.position_seconds),0)).scalar()}
@router.get('/{audiobook_id}')
def get_audiobook(audiobook_id:int,db:Session=Depends(get_db)):
    book=db.get(models.Audiobook,audiobook_id)
    if not book: raise HTTPException(404,'Audiobook not found')
    return as_detail(book)
@router.post('/scan')
def scan_audiobooks(db:Session=Depends(get_db)): return run_audiobook_scan(db)
class ProgressUpdate(BaseModel):
    position_seconds:float=0
    progress_percent:float=0
    chapter_id:int|None=None
@router.post('/{audiobook_id}/progress')
def update_progress(audiobook_id:int,payload:ProgressUpdate,db:Session=Depends(get_db)):
    book=db.get(models.Audiobook,audiobook_id)
    if not book: raise HTTPException(404,'Audiobook not found')
    if payload.chapter_id and not db.query(models.AudiobookChapter).filter_by(id=payload.chapter_id,audiobook_id=audiobook_id).first(): raise HTTPException(422,'Chapter does not belong to audiobook')
    status='finished' if payload.progress_percent>=99 else 'in_progress'; book.status=status; db.add(models.AudiobookProgress(audiobook_id=audiobook_id,chapter_id=payload.chapter_id,position_seconds=payload.position_seconds,progress_percent=payload.progress_percent,status=status));db.commit();return {'status':'ok','book_status':status}
@router.post('/{audiobook_id}/favorite')
def favorite_audiobook(audiobook_id:int,db:Session=Depends(get_db)):
    book=db.get(models.Audiobook,audiobook_id)
    if not book: raise HTTPException(404,'Audiobook not found')
    book.favorite=not book.favorite;db.commit();return {'favorite':book.favorite}
@router.post('/{audiobook_id}/finished')
def finish_audiobook(audiobook_id:int,db:Session=Depends(get_db)):
    book=db.get(models.Audiobook,audiobook_id)
    if not book: raise HTTPException(404,'Audiobook not found')
    book.status='finished';db.commit();return {'book_status':book.status}
@router.post('/{audiobook_id}/not-started')
def reset_audiobook(audiobook_id:int,db:Session=Depends(get_db)):
    book=db.get(models.Audiobook,audiobook_id)
    if not book: raise HTTPException(404,'Audiobook not found')
    book.status='available';db.commit();return {'book_status':book.status}

