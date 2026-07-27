from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from .. import models
from ..availability import active_track_ids, active_tracks, available_track_filter
from ..db import get_db
from ..listener_queue import album_queue_items, artist_queue_items, playlist_projected_items, smart_queue_items
from ..music_recording_feedback import smart_music_candidate_track_ids
from ..queue_contracts import (
    AlbumQueueRequest,
    ArtistQueueRequest,
    PlaylistQueueRequest,
    SmartPlaylistQueueRequest,
    StationQueueRequest,
)
from ..station_engine import build_station_debug, build_station_queue

router = APIRouter()


@router.post('/station/debug')
def station_queue_debug(req: StationQueueRequest, db: Session = Depends(get_db)):
    return build_station_debug(req, db)


@router.post('/station')
def station_queue(req: StationQueueRequest, db: Session = Depends(get_db)):
    return build_station_queue(req, db)


def smart_track_ids(db: Session, key: str, limit: int = 1000) -> list[int]:
    return smart_music_candidate_track_ids(db, key=key, limit=limit)


@router.post('/album')
def album_queue(req: AlbumQueueRequest, db: Session = Depends(get_db)):
    return {'queue': album_queue_items(db, artist=req.artist, album=req.album, release_id=req.release_id, limit=req.limit, shuffle=req.shuffle)}


@router.post('/artist')
def artist_queue(req: ArtistQueueRequest, db: Session = Depends(get_db)):
    return {'queue': artist_queue_items(db, artist=req.artist, limit=req.limit, shuffle=req.shuffle)}


@router.post('/playlist')
def playlist_queue(req: PlaylistQueueRequest, db: Session = Depends(get_db)):
    return {'queue': playlist_projected_items(db, playlist_id=req.playlist_id, shuffle=req.shuffle)}


@router.post('/smart-playlist')
def smart_playlist_queue(req: SmartPlaylistQueueRequest, db: Session = Depends(get_db)):
    ids = smart_track_ids(db, req.key, req.limit)
    if not ids:
        return {'queue': []}
    return {'queue': smart_queue_items(db, track_ids=ids, key=req.key, shuffle=req.shuffle)}


@router.get('/current')
def get_current_queue():
    return {'queue': []}