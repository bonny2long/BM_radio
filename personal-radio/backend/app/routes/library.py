from pathlib import Path
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models
from ..config import settings
from ..db import get_db
from ..scanner.music_scanner import scan_music

router = APIRouter()

@router.get("/summary")
async def get_summary(db: Session = Depends(get_db)):
    return {"tracks": db.query(func.count(models.Track.id)).scalar(), "artists": db.query(func.count(func.distinct(models.Track.artist))).scalar(), "albums": db.query(func.count(func.distinct(models.Track.album))).scalar()}

@router.get("/paths")
async def get_paths():
    paths = {"nas_data_root": settings.NAS_DATA_ROOT, "music_root": settings.MUSIC_ROOT, "music_library_root": settings.MUSIC_LIBRARY_ROOT, "music_mp3_root": settings.MUSIC_MP3_ROOT, "music_flac_root": settings.MUSIC_FLAC_ROOT, "music_discographies_root": settings.MUSIC_DISCOGRAPHIES_ROOT, "audiobooks_root": settings.AUDIOBOOKS_ROOT}
    response = dict(paths)
    response.update({f"{key}_exists": Path(value).is_dir() for key, value in paths.items()})
    response["safety"] = {"public_access": settings.PUBLIC_ACCESS, "allow_file_mutation": settings.ALLOW_FILE_MUTATION, "allow_delete": settings.ALLOW_DELETE, "allow_tag_writes": settings.ALLOW_TAG_WRITES, "scan_ingest_folders": settings.SCAN_INGEST_FOLDERS}
    return response

@router.get("/tracks")
async def get_tracks(limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    return db.query(models.Track).order_by(models.Track.artist, models.Track.album, models.Track.title).offset(offset).limit(min(limit, 500)).all()

@router.get("/artists")
async def get_artists(db: Session = Depends(get_db)):
    return [{"name": name, "track_count": count} for name, count in db.query(models.Track.artist, func.count(models.Track.id)).group_by(models.Track.artist).order_by(models.Track.artist).all()]

@router.get("/albums")
async def get_albums(db: Session = Depends(get_db)):
    return [{"title": album, "artist": artist, "track_count": count} for album, artist, count in db.query(models.Track.album, models.Track.artist, func.count(models.Track.id)).group_by(models.Track.album, models.Track.artist).order_by(models.Track.artist, models.Track.album).all()]

@router.get("/search")
async def search(q: str, db: Session = Depends(get_db)):
    term = f"%{q.strip()}%"
    return db.query(models.Track).filter((models.Track.title.ilike(term)) | (models.Track.artist.ilike(term)) | (models.Track.album.ilike(term))).limit(100).all()

@router.post("/scan/music")
async def scan_music_route(db: Session = Depends(get_db)):
    return scan_music(db)

from .serializers import track_item
@router.get('/album-tracks')
def playback_album_tracks(artist: str, album: str, db: Session = Depends(get_db)):
    return [track_item(track) for track in db.query(models.Track).filter_by(artist=artist, album=album).order_by(models.Track.title).limit(500)]
