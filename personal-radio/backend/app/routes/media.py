from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from .. import models
from ..availability import active_tracks, is_audiobook_available, is_chapter_available, is_track_available
from ..config import settings
from ..db import get_db
from ..perf import perf_segment
from ..scanner.path_safety import is_approved_path

router = APIRouter()
MEDIA_TYPES = {'.mp3': 'audio/mpeg', '.flac': 'audio/flac', '.m4a': 'audio/mp4', '.m4b': 'audio/mp4', '.aac': 'audio/aac', '.ogg': 'audio/ogg', '.opus': 'audio/opus', '.wav': 'audio/wav'}
IMAGE_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
CACHE_HEADERS = {'Cache-Control': 'public, max-age=86400'}
COVER_NAMES = ('cover.jpg', 'cover.jpeg', 'cover.png', 'cover.webp', 'folder.jpg', 'folder.jpeg', 'folder.png', 'folder.webp', 'front.jpg', 'front.jpeg', 'front.png', 'front.webp', 'album.jpg', 'album.jpeg', 'album.png', 'album.webp', 'artwork.jpg', 'artwork.jpeg', 'artwork.png', 'artwork.webp')
TRACK_UNAVAILABLE_MESSAGE = 'Track is unavailable in the current library'
AUDIOBOOK_UNAVAILABLE_MESSAGE = 'Audiobook is unavailable in the current library'
CHAPTER_UNAVAILABLE_MESSAGE = 'Audiobook chapter is unavailable in the current library'


def music_media_roots() -> list[Path]:
    roots = [Path(settings.MUSIC_LIBRARY_ROOT)]
    if settings.BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN:
        roots.append(Path(settings.MUSIC_DISCOGRAPHIES_ROOT))
    return roots


def safe_file(path_value: str, roots: list[Path], types: dict[str, str]):
    path = Path(path_value)
    suffix = path.suffix.lower()
    if not path.is_file():
        raise HTTPException(404, 'File not found')
    if suffix not in types:
        raise HTTPException(415, 'Unsupported file type')
    if not is_approved_path(path, roots):
        raise HTTPException(403, 'Path is outside the final library')
    return FileResponse(path, media_type=types[suffix], filename=path.name, headers=CACHE_HEADERS if types is IMAGE_TYPES else None)


def find_cover(start: Path, roots: list[Path]) -> Path | None:
    for directory in (start, *start.parents):
        if not is_approved_path(directory, roots):
            break
        for name in COVER_NAMES:
            candidate = directory / name
            if candidate.is_file() and is_approved_path(candidate, roots):
                return candidate
        for folder in ('Artwork', 'artwork', 'Covers', 'covers', 'metadata'):
            art_dir = directory / folder
            if not art_dir.is_dir():
                continue
            for name in COVER_NAMES:
                candidate = art_dir / name
                if candidate.is_file() and is_approved_path(candidate, roots):
                    return candidate
            for candidate in art_dir.iterdir():
                if candidate.is_file() and candidate.suffix.lower() in IMAGE_TYPES and candidate.stem.lower().startswith(('cover', 'folder', 'front', 'artwork')) and is_approved_path(candidate, roots):
                    return candidate
    return None


@router.get('/tracks/{track_id}/stream')
def stream_track(track_id: int, db: Session = Depends(get_db)):
    track = db.get(models.Track, track_id)
    if not track:
        raise HTTPException(404, 'Track not found')
    if not is_track_available(track):
        raise HTTPException(409, TRACK_UNAVAILABLE_MESSAGE)
    return safe_file(track.path, music_media_roots(), MEDIA_TYPES)


@router.get('/tracks/{track_id}/cover')
def track_cover(track_id: int, db: Session = Depends(get_db)):
    track = db.get(models.Track, track_id)
    if not track:
        raise HTTPException(404, 'Track not found')
    if not is_track_available(track):
        raise HTTPException(409, TRACK_UNAVAILABLE_MESSAGE)
    roots = music_media_roots()
    if track.cover_path:
        with perf_segment('media.track_cover.use_stored_path'):
            try:
                return safe_file(track.cover_path, roots, IMAGE_TYPES)
            except HTTPException:
                pass
    with perf_segment('media.track_cover.folder_walk'):
        cover = find_cover(Path(track.path).parent, roots)
    if not cover:
        raise HTTPException(404, 'Cover not found')
    return safe_file(str(cover), roots, IMAGE_TYPES)


@router.get('/albums/cover')
def album_cover(artist: str, album: str, db: Session = Depends(get_db)):
    tracks = active_tracks(db).filter_by(artist=artist, album=album).all()
    if not tracks:
        raise HTTPException(404, 'Album not found')
    roots = music_media_roots()
    for track in tracks:
        if track.cover_path:
            with perf_segment('media.album_cover.use_stored_path'):
                try:
                    return safe_file(track.cover_path, roots, IMAGE_TYPES)
                except HTTPException:
                    pass
    for track in tracks:
        with perf_segment('media.album_cover.folder_walk'):
            cover = find_cover(Path(track.path).parent, roots)
        if cover:
            return safe_file(str(cover), roots, IMAGE_TYPES)
    raise HTTPException(404, 'Cover not found')


@router.get('/audiobooks/{audiobook_id}/chapters/{chapter_id}/stream')
def stream_audiobook_chapter(audiobook_id: int, chapter_id: int, db: Session = Depends(get_db)):
    book = db.get(models.Audiobook, audiobook_id)
    if not book:
        raise HTTPException(404, 'Audiobook not found')
    chapter = db.get(models.AudiobookChapter, chapter_id)
    if not chapter or chapter.audiobook_id != audiobook_id:
        raise HTTPException(404, 'Audiobook chapter not found')
    if not is_audiobook_available(book):
        raise HTTPException(409, AUDIOBOOK_UNAVAILABLE_MESSAGE)
    if not is_chapter_available(chapter):
        raise HTTPException(409, CHAPTER_UNAVAILABLE_MESSAGE)
    return safe_file(chapter.path, [Path(settings.AUDIOBOOKS_ROOT)], MEDIA_TYPES)


@router.get('/audiobooks/{audiobook_id}/cover')
def audiobook_cover(audiobook_id: int, db: Session = Depends(get_db)):
    book = db.get(models.Audiobook, audiobook_id)
    if not book:
        raise HTTPException(404, 'Audiobook not found')
    if not is_audiobook_available(book):
        raise HTTPException(409, AUDIOBOOK_UNAVAILABLE_MESSAGE)
    roots = [Path(settings.AUDIOBOOKS_ROOT)]
    cover = find_cover(Path(book.path), roots)
    if not cover:
        raise HTTPException(404, 'Cover not found')
    return safe_file(str(cover), roots, IMAGE_TYPES)