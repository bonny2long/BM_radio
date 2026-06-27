from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
from ..perf import perf_segment
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
    with perf_segment('audiobooks.summary.sql'):
        total, not_started, in_progress, finished, favorites = db.query(
            func.count(models.Audiobook.id),
            func.coalesce(func.sum(case((models.Audiobook.status == 'available', 1), else_=0)), 0),
            func.coalesce(func.sum(case((models.Audiobook.status == 'in_progress', 1), else_=0)), 0),
            func.coalesce(func.sum(case((models.Audiobook.status == 'finished', 1), else_=0)), 0),
            func.coalesce(func.sum(case((models.Audiobook.favorite.is_(True), 1), else_=0)), 0),
        ).one()
        total_seconds = db.query(func.coalesce(func.sum(models.AudiobookProgress.position_seconds),0)).scalar() or 0
    with perf_segment('audiobooks.summary.serialize'):
        return {'available':total,'not_started':not_started,'in_progress':in_progress,'finished':finished,'favorites':favorites,'total_listening_seconds':total_seconds}
@router.get('/recent-or-progress')
def recent_or_progress(limit:int=3,db:Session=Depends(get_db)):
    limit=min(max(limit,1),20)
    with perf_segment('audiobooks.recent_progress.sql'):
        books=(
            db.query(models.Audiobook)
            .outerjoin(models.AudiobookProgress, models.AudiobookProgress.audiobook_id == models.Audiobook.id)
            .group_by(models.Audiobook.id)
            .order_by(func.max(models.AudiobookProgress.updated_at).desc().nullslast(), models.Audiobook.updated_at.desc(), models.Audiobook.created_at.desc(), models.Audiobook.title)
            .limit(limit)
            .all()
        )
    with perf_segment('audiobooks.recent_progress.serialize'):
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
