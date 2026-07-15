from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from .. import models
from ..availability import active_track_ids, active_tracks, available_track_filter
from ..db import get_db
from ..listener_queue import album_queue_items, artist_queue_items, playlist_projected_items, smart_queue_items
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
    limit = max(1, min(limit, 1000))
    if key == 'favorites':
        return [
            r[0]
            for r in db.query(models.TrackFavorite.track_id)
            .join(models.Track, models.Track.id == models.TrackFavorite.track_id)
            .filter(available_track_filter())
            .order_by(models.TrackFavorite.created_at.desc())
            .limit(limit)
            .all()
        ]
    if key == 'thumbs_up':
        rows = db.query(models.TrackThumb).order_by(models.TrackThumb.created_at.asc()).all()
        latest = {r.track_id: r.value.value for r in rows}
        up_ids = [tid for tid, value in latest.items() if value == 'up']
        available = active_track_ids(db, up_ids)
        return [tid for tid in up_ids if tid in available][:limit]
    if key == 'most_played':
        rows = (
            db.query(models.PlaybackEvent.track_id, func.count(models.PlaybackEvent.id))
            .join(models.Track, models.Track.id == models.PlaybackEvent.track_id)
            .filter(available_track_filter(), models.PlaybackEvent.track_id.isnot(None), models.PlaybackEvent.event_type == 'qualified_play')
            .group_by(models.PlaybackEvent.track_id)
            .order_by(func.count(models.PlaybackEvent.id).desc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]
    if key == 'recently_played':
        rows = (
            db.query(models.PlaybackEvent.track_id)
            .join(models.Track, models.Track.id == models.PlaybackEvent.track_id)
            .filter(available_track_filter(), models.PlaybackEvent.track_id.isnot(None), models.PlaybackEvent.event_type == 'qualified_play')
            .order_by(models.PlaybackEvent.created_at.desc())
            .limit(limit * 6)
            .all()
        )
        out = []
        seen = set()
        for (tid,) in rows:
            if tid and tid not in seen:
                seen.add(tid)
                out.append(tid)
            if len(out) >= limit:
                break
        return out
    if key == 'recently_added':
        return [
            r[0]
            for r in active_tracks(db).with_entities(models.Track.id)
            .order_by(models.Track.created_at.desc(), models.Track.last_indexed_at.desc())
            .limit(limit)
            .all()
        ]
    if key == 'never_played':
        rows = (
            active_tracks(db).with_entities(models.Track.id)
            .outerjoin(models.PlaybackEvent, (models.PlaybackEvent.track_id == models.Track.id) & (models.PlaybackEvent.event_type == 'qualified_play'))
            .group_by(models.Track.id)
            .having(func.count(models.PlaybackEvent.id) == 0)
            .order_by(models.Track.created_at.desc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]
    return []


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