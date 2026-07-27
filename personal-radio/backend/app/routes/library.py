from pathlib import Path
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..listener_library import (
    library_search,
    listener_album_tracks,
    listener_albums,
    listener_artist_albums,
    listener_artist_detail,
    listener_artists,
    listener_summary,
    listener_tracks,
    listener_tracks_page,
)
from ..scanner.music_scanner import scan_music

router = APIRouter()


@router.get('/summary')
async def get_summary(db: Session = Depends(get_db)):
    return listener_summary(db)


@router.get('/paths')
async def get_paths():
    paths = {'nas_data_root': settings.NAS_DATA_ROOT, 'music_root': settings.MUSIC_ROOT, 'music_library_root': settings.MUSIC_LIBRARY_ROOT, 'music_mp3_root': settings.MUSIC_MP3_ROOT, 'music_flac_root': settings.MUSIC_FLAC_ROOT, 'music_discographies_root': settings.MUSIC_DISCOGRAPHIES_ROOT, 'audiobooks_root': settings.AUDIOBOOKS_ROOT, 'book_root': settings.BM_RADIO_BOOK_ROOT, 'cache_root': settings.BM_RADIO_CACHE_ROOT, 'artwork_cache_root': settings.BM_RADIO_ARTWORK_CACHE_ROOT}
    response = dict(paths)
    response.update({f'{key}_exists': Path(value).is_dir() for key, value in paths.items()})
    response['config'] = {'api_host': settings.BM_RADIO_API_HOST, 'api_port': settings.BM_RADIO_API_PORT, 'legacy_discography_scan_enabled': settings.BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN}
    response['safety'] = {'public_access': settings.PUBLIC_ACCESS, 'allow_file_mutation': settings.ALLOW_FILE_MUTATION, 'allow_delete': settings.ALLOW_DELETE, 'allow_tag_writes': settings.ALLOW_TAG_WRITES, 'scan_ingest_folders': settings.SCAN_INGEST_FOLDERS}
    return response


@router.get('/tracks')
async def get_tracks(limit: int = 100, offset: int = 0, artist: str | None = None, album: str | None = None, q: str | None = None, sort: str = 'artist_album_track', db: Session = Depends(get_db)):
    return listener_tracks(db, limit=limit, offset=offset, artist=artist, album=album, q=q, sort=sort)


@router.get('/tracks-page')
def get_tracks_page(limit: int = 100, offset: int = 0, artist: str | None = None, album: str | None = None, q: str | None = None, sort: str = 'artist_album_track', db: Session = Depends(get_db)):
    return listener_tracks_page(db, limit=limit, offset=offset, artist=artist, album=album, q=q, sort=sort)


@router.get('/artists')
async def get_artists(db: Session = Depends(get_db)):
    return listener_artists(db)


@router.get('/artists-page')
def get_artists_page(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return {'items': listener_artists(db, limit=limit, offset=offset), 'limit': min(max(limit, 1), 200), 'offset': max(offset, 0)}


@router.get('/artists/{artist}/detail')
def artist_detail(artist: str, db: Session = Depends(get_db)):
    return listener_artist_detail(db, artist)


@router.get('/artists/{artist}/tracks')
def artist_tracks(artist: str, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return listener_tracks_page(db, limit=limit, offset=offset, artist=artist)


@router.get('/artists/{artist}/albums')
def artist_albums(artist: str, db: Session = Depends(get_db)):
    return listener_artist_albums(db, artist)


@router.get('/albums')
async def get_albums(db: Session = Depends(get_db)):
    return listener_albums(db)


@router.get('/albums-page')
def get_albums_page(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return {'items': listener_albums(db, limit=limit, offset=offset), 'limit': min(max(limit, 1), 200), 'offset': max(offset, 0)}


@router.get('/recent-albums')
def get_recent_albums(limit: int = 8, db: Session = Depends(get_db)):
    return listener_albums(db, limit=limit, recent=True)


@router.get('/search')
async def search(q: str, db: Session = Depends(get_db)):
    return library_search(db, q=q)


@router.post('/scan/music')
async def scan_music_route(db: Session = Depends(get_db)):
    return scan_music(db)


@router.get('/album-tracks')
def playback_album_tracks(artist: str | None = None, album: str | None = None, release_id: int | None = None, db: Session = Depends(get_db)):
    return listener_album_tracks(db, release_id=release_id, artist=artist, album=album)