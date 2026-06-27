from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
from ..scanner.audiobook_scanner import load_audiobook_sidecar, scan_audiobooks as run_audiobook_scan
from .serializers import chapter_item, audiobook_item
router = APIRouter()
def contained_books(book):
    try:return load_audiobook_sidecar(Path(book.path)).get('contained_books') or []
    except Exception:return []
def progress_payload(book,progress):
    if not progress:return None
    chapters=sorted(book.chapters,key=lambda c:c.sort_order);total=sum((c.duration_seconds or 0) for c in chapters);before=0;current=None
    for c in chapters:
        if c.id==progress.chapter_id:current=c;break
        before+=c.duration_seconds or 0
    position=max(0,float(progress.position_seconds or 0));chapter_duration=float(current.duration_seconds or 0) if current else 0
    chapter_pct=(position/chapter_duration*100) if chapter_duration else float(progress.progress_percent or 0)
    overall=((before+position)/total*100) if total else chapter_pct
    return {'chapter_id':progress.chapter_id,'position_seconds':position,'chapter_progress_percent':min(100,max(0,chapter_pct)),'overall_progress_percent':min(100,max(0,overall)),'progress_percent':min(100,max(0,overall)),'updated_at':str(progress.updated_at)}
def as_detail(book):
    progress = sorted(book.progress, key=lambda p: p.updated_at or 0, reverse=True);latest = progress[0] if progress else None
    return {**audiobook_item(book),'contained_books':contained_books(book),'latest_progress':progress_payload(book,latest),'chapters':[chapter_item(c) for c in sorted(book.chapters,key=lambda c:c.sort_order)]}
@router.get('/')
def get_audiobooks(db: Session=Depends(get_db)): return [audiobook_item(b) for b in db.query(models.Audiobook).order_by(models.Audiobook.title)]
@router.get('/summary')
def get_summary(db: Session=Depends(get_db)):
    books=db.query(models.Audiobook).all(); return {'available':len(books),'not_started':sum(b.status=='available' for b in books),'in_progress':sum(b.status=='in_progress' for b in books),'finished':sum(b.status=='finished' for b in books),'favorites':sum(b.favorite for b in books),'total_listening_seconds':db.query(func.coalesce(func.sum(models.AudiobookProgress.position_seconds),0)).scalar()}
@router.get('/recent-or-progress')
def recent_or_progress(limit:int=3,db:Session=Depends(get_db)):
    limit=min(max(limit,1),20)
    books=db.query(models.Audiobook).filter(models.Audiobook.status=='in_progress').order_by(models.Audiobook.updated_at.desc(),models.Audiobook.title).limit(limit).all()
    if len(books)<limit:
        seen={b.id for b in books}
        more=db.query(models.Audiobook).order_by(models.Audiobook.created_at.desc(),models.Audiobook.title).limit(limit*2).all()
        books.extend([b for b in more if b.id not in seen][:limit-len(books)])
    return [audiobook_item(b) for b in books]

@router.get('/{audiobook_id}')
def get_audiobook(audiobook_id:int,db:Session=Depends(get_db)):
    book=db.get(models.Audiobook,audiobook_id)
    if not book: raise HTTPException(404,'Audiobook not found')
    return as_detail(book)
@router.post('/scan')
def scan_audiobooks(db:Session=Depends(get_db)): return run_audiobook_scan(db)
class ProgressUpdate(BaseModel):
    position_seconds:float=0;progress_percent:float=0;chapter_id:int|None=None
@router.post('/{audiobook_id}/progress')
def update_progress(audiobook_id:int,payload:ProgressUpdate,db:Session=Depends(get_db)):
    book=db.get(models.Audiobook,audiobook_id)
    if not book: raise HTTPException(404,'Audiobook not found')
    chapter=None
    if payload.chapter_id:
        chapter=db.query(models.AudiobookChapter).filter_by(id=payload.chapter_id,audiobook_id=audiobook_id).first()
        if not chapter: raise HTTPException(422,'Chapter does not belong to audiobook')
    chapters=sorted(book.chapters,key=lambda c:c.sort_order);total=sum((c.duration_seconds or 0) for c in chapters);before=0
    for c in chapters:
        if c.id==payload.chapter_id:break
        before+=c.duration_seconds or 0
    overall=((before+max(0,payload.position_seconds))/total*100) if total else max(0,payload.progress_percent)
    status='available' if overall<=0 else 'finished' if overall>=99 else 'in_progress'; book.status=status
    db.add(models.AudiobookProgress(audiobook_id=audiobook_id,chapter_id=payload.chapter_id,position_seconds=payload.position_seconds,progress_percent=overall,status=status));db.commit();return {'status':'ok','book_status':status,'overall_progress_percent':overall}
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
