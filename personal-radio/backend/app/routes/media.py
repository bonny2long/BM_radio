from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import re
from threading import Lock
import time
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from .. import models
from ..availability import active_tracks, is_audiobook_available, is_chapter_available, is_track_available
from ..config import settings
from ..db import SessionLocal, get_db
from ..music_playback_policy import validate_music_playback_context
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
AUDIOBOOK_ACCEL_PREFIX = '/__bm_audiobooks/'
AUDIOBOOK_AUTH_CACHE_TTL_SECONDS = 2.0
AUDIOBOOK_AUTH_CACHE_MAX_ENTRIES = 128
AUDIOBOOK_OPEN_RANGE_INITIAL_BYTES = 4 * 1024 * 1024
AUDIOBOOK_OPEN_RANGE_BYTES = 64 * 1024
OPEN_ENDED_BYTE_RANGE = re.compile(r'bytes=(\d+)-', re.IGNORECASE)


@dataclass(frozen=True)
class AudiobookFileMetadata:
    path: Path
    size: int
    media_type: str
    content_disposition: str
    accel_redirect: str


_audiobook_auth_cache: OrderedDict[tuple[int, int], tuple[float, AudiobookFileMetadata]] = OrderedDict()
_audiobook_auth_cache_lock = Lock()


def music_media_roots() -> list[Path]:
    roots = [Path(settings.MUSIC_LIBRARY_ROOT)]
    if settings.BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN:
        roots.append(Path(settings.MUSIC_DISCOGRAPHIES_ROOT))
    return roots


def cached_audiobook_file_metadata(audiobook_id: int, chapter_id: int) -> AudiobookFileMetadata | None:
    key = (audiobook_id, chapter_id)
    now = time.monotonic()
    with _audiobook_auth_cache_lock:
        cached = _audiobook_auth_cache.get(key)
        if cached is None:
            return None
        expires_at, metadata = cached
        if expires_at <= now:
            _audiobook_auth_cache.pop(key, None)
            return None
        _audiobook_auth_cache.move_to_end(key)
    return metadata


def cache_audiobook_file_metadata(audiobook_id: int, chapter_id: int, metadata: AudiobookFileMetadata) -> None:
    key = (audiobook_id, chapter_id)
    with _audiobook_auth_cache_lock:
        _audiobook_auth_cache[key] = (time.monotonic() + AUDIOBOOK_AUTH_CACHE_TTL_SECONDS, metadata)
        _audiobook_auth_cache.move_to_end(key)
        while len(_audiobook_auth_cache) > AUDIOBOOK_AUTH_CACHE_MAX_ENTRIES:
            _audiobook_auth_cache.popitem(last=False)


def safe_file(path_value: str, roots: list[Path], types: dict[str, str], *, accel_prefix: str | None = None):
    path = Path(path_value)
    suffix = path.suffix.lower()
    if not path.is_file():
        raise HTTPException(404, 'File not found')
    if suffix not in types:
        raise HTTPException(415, 'Unsupported file type')
    if not is_approved_path(path, roots):
        raise HTTPException(403, 'Path is outside the final library')
    headers = CACHE_HEADERS if types is IMAGE_TYPES else None
    if accel_prefix is not None:
        relative = path.resolve().relative_to(roots[0].resolve()).as_posix()
        headers = {'X-Accel-Redirect': accel_prefix + quote(relative, safe='/')}
    return FileResponse(path, media_type=types[suffix], filename=path.name, headers=headers)


def validated_audiobook_file_metadata(path_value: str) -> AudiobookFileMetadata:
    path = Path(path_value)
    suffix = path.suffix.lower()
    root = Path(settings.AUDIOBOOKS_ROOT)
    if not path.is_file():
        raise HTTPException(404, 'File not found')
    if suffix not in MEDIA_TYPES:
        raise HTTPException(415, 'Unsupported file type')
    if not is_approved_path(path, [root]):
        raise HTTPException(403, 'Path is outside the final library')
    resolved = path.resolve()
    relative = resolved.relative_to(root.resolve()).as_posix()
    return AudiobookFileMetadata(
        path=resolved,
        size=resolved.stat().st_size,
        media_type=MEDIA_TYPES[suffix],
        content_disposition=f"attachment; filename*=utf-8''{quote(resolved.name, safe='')}",
        accel_redirect=AUDIOBOOK_ACCEL_PREFIX + quote(relative, safe='/'),
    )


def safe_audiobook_file(metadata: AudiobookFileMetadata, request: Request | None):
    """Serve Chromium open-ended probes as bounded, connection-reusable responses."""
    range_header = request.headers.get('range', '') if request is not None else ''
    match = OPEN_ENDED_BYTE_RANGE.fullmatch(range_header.strip())
    if match is None:
        return FileResponse(
            metadata.path, media_type=metadata.media_type, filename=metadata.path.name,
            headers={'X-Accel-Redirect': metadata.accel_redirect},
        )
    start = int(match.group(1))
    if start >= metadata.size:
        raise HTTPException(
            416, 'Requested range not satisfiable',
            headers={'Content-Range': f'bytes */{metadata.size}', 'Accept-Ranges': 'bytes'},
        )
    limit = AUDIOBOOK_OPEN_RANGE_INITIAL_BYTES if start == 0 else AUDIOBOOK_OPEN_RANGE_BYTES
    end = min(metadata.size - 1, start + limit - 1)
    try:
        with metadata.path.open('rb') as stream:
            stream.seek(start)
            content = stream.read(end - start + 1)
    except FileNotFoundError:
        raise HTTPException(404, 'File not found') from None
    headers = {
        'Accept-Ranges': 'bytes',
        'Content-Range': f'bytes {start}-{end}/{metadata.size}',
        'Content-Length': str(len(content)),
        'Content-Disposition': metadata.content_disposition,
    }
    return Response(content, status_code=206, media_type=metadata.media_type, headers=headers)


def resolve_audiobook_file_metadata(audiobook_id: int, chapter_id: int) -> AudiobookFileMetadata:
    """Open PostgreSQL only for an authorization-cache miss."""
    with SessionLocal() as db:
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
        return validated_audiobook_file_metadata(chapter.path)


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
def stream_track(track_id: int, db: Session = Depends(get_db, scope="function")):
    track = db.get(models.Track, track_id)
    if not track:
        raise HTTPException(404, 'Track not found')
    if not is_track_available(track):
        raise HTTPException(409, TRACK_UNAVAILABLE_MESSAGE)
    validate_music_playback_context(db, track)
    return safe_file(track.path, music_media_roots(), MEDIA_TYPES)


@router.get('/tracks/{track_id}/cover')
def track_cover(track_id: int, db: Session = Depends(get_db, scope="function")):
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
def album_cover(artist: str, album: str, db: Session = Depends(get_db, scope="function")):
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
async def stream_audiobook_chapter(audiobook_id: int, chapter_id: int, request: Request = None):
    cached_metadata = cached_audiobook_file_metadata(audiobook_id, chapter_id)
    if cached_metadata is None:
        cached_metadata = await run_in_threadpool(resolve_audiobook_file_metadata, audiobook_id, chapter_id)
        cache_audiobook_file_metadata(audiobook_id, chapter_id, cached_metadata)
    return safe_audiobook_file(cached_metadata, request)


@router.get('/audiobooks/{audiobook_id}/cover')
def audiobook_cover(audiobook_id: int, db: Session = Depends(get_db, scope="function")):
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
