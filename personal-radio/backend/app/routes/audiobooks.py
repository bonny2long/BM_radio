from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
from ..scanner.audiobook_scanner import scan_audiobooks as run_audiobook_scan

router = APIRouter()

@router.get("/")
async def get_audiobooks(db: Session = Depends(get_db)):
    return db.query(models.Audiobook).order_by(models.Audiobook.title).all()

@router.get("/summary")
async def get_summary(db: Session = Depends(get_db)):
    books = db.query(models.Audiobook).all()
    return {"available": sum(book.status == "available" for book in books), "not_started": sum(book.status == "available" for book in books), "in_progress": sum(book.status == "in_progress" for book in books), "finished": sum(book.status == "finished" for book in books), "favorites": sum(book.favorite for book in books), "total_listening_seconds": db.query(func.coalesce(func.sum(models.AudiobookProgress.position_seconds), 0)).scalar()}

@router.get("/{audiobook_id}")
async def get_audiobook(audiobook_id: int, db: Session = Depends(get_db)):
    book = db.get(models.Audiobook, audiobook_id)
    if not book: raise HTTPException(404, "Audiobook not found")
    return {"id": book.id, "title": book.title, "author": book.author, "narrator": book.narrator, "status": book.status, "favorite": book.favorite, "duration_seconds": book.duration_seconds, "chapters": sorted(book.chapters, key=lambda item: item.sort_order)}

@router.post("/scan")
async def scan_audiobooks(db: Session = Depends(get_db)):
    return run_audiobook_scan(db)

class ProgressUpdate(BaseModel):
    position_seconds: float = 0
    progress_percent: float = 0
    chapter_id: int | None = None

@router.post("/{audiobook_id}/progress")
async def update_progress(audiobook_id: int, payload: ProgressUpdate, db: Session = Depends(get_db)):
    book = db.get(models.Audiobook, audiobook_id)
    if not book: raise HTTPException(404, "Audiobook not found")
    status = "finished" if payload.progress_percent >= 100 else "in_progress"
    book.status = status
    db.add(models.AudiobookProgress(audiobook_id=audiobook_id, chapter_id=payload.chapter_id, position_seconds=payload.position_seconds, progress_percent=payload.progress_percent, status=status)); db.commit()
    return {"status": "ok", "audiobook_id": audiobook_id, "book_status": status}

@router.post("/{audiobook_id}/favorite")
async def favorite_audiobook(audiobook_id: int, db: Session = Depends(get_db)):
    book = db.get(models.Audiobook, audiobook_id)
    if not book: raise HTTPException(404, "Audiobook not found")
    book.favorite = not book.favorite; db.commit(); return {"status": "ok", "favorite": book.favorite}

@router.post("/{audiobook_id}/finished")
async def finish_audiobook(audiobook_id: int, db: Session = Depends(get_db)):
    book = db.get(models.Audiobook, audiobook_id)
    if not book: raise HTTPException(404, "Audiobook not found")
    book.status = "finished"; db.commit(); return {"status": "ok", "book_status": book.status}
