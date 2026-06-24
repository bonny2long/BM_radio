from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from .. import models
from ..config import settings
from ..db import get_db
from ..scanner.path_safety import is_approved_path
router = APIRouter()
MEDIA_TYPES = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".m4b": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg", ".opus": "audio/opus", ".wav": "audio/wav"}
def media_response(path_value: str, roots: list[Path]):
    path = Path(path_value)
    if not path.is_file(): raise HTTPException(404, "Media file not found")
    suffix = path.suffix.lower()
    if suffix not in MEDIA_TYPES: raise HTTPException(415, "Unsupported media type")
    if not is_approved_path(path, roots): raise HTTPException(403, "Media path is outside the final library")
    return FileResponse(path, media_type=MEDIA_TYPES[suffix], filename=path.name)
@router.get("/tracks/{track_id}/stream")
def stream_track(track_id: int, db: Session = Depends(get_db)):
    track = db.get(models.Track, track_id)
    if not track: raise HTTPException(404, "Track not found")
    return media_response(track.path, [Path(settings.MUSIC_LIBRARY_ROOT), Path(settings.MUSIC_DISCOGRAPHIES_ROOT)])
@router.get("/audiobooks/{audiobook_id}/chapters/{chapter_id}/stream")
def stream_audiobook_chapter(audiobook_id: int, chapter_id: int, db: Session = Depends(get_db)):
    chapter = db.get(models.AudiobookChapter, chapter_id)
    if not chapter or chapter.audiobook_id != audiobook_id: raise HTTPException(404, "Audiobook chapter not found")
    return media_response(chapter.path, [Path(settings.AUDIOBOOKS_ROOT)])