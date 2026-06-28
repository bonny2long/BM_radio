import random

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..queue_contracts import (
    AlbumQueueRequest,
    ArtistQueueRequest,
    PlaylistQueueRequest,
    SmartPlaylistQueueRequest,
    StationQueueRequest,
)
from ..queue_payloads import payload
from ..release_preferences import choose_preferred_tracks
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
            .order_by(models.TrackFavorite.created_at.desc())
            .limit(limit)
            .all()
        ]
    if key == 'thumbs_up':
        rows = db.query(models.TrackThumb).order_by(models.TrackThumb.created_at.asc()).all()
        latest = {r.track_id: r.value.value for r in rows}
        return [tid for tid, value in latest.items() if value == 'up'][:limit]
    if key == 'most_played':
        rows = (
            db.query(models.PlaybackEvent.track_id, func.count(models.PlaybackEvent.id))
            .filter(models.PlaybackEvent.track_id.isnot(None), models.PlaybackEvent.event_type == 'qualified_play')
            .group_by(models.PlaybackEvent.track_id)
            .order_by(func.count(models.PlaybackEvent.id).desc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]
    if key == 'recently_played':
        rows = (
            db.query(models.PlaybackEvent.track_id)
            .filter(models.PlaybackEvent.track_id.isnot(None), models.PlaybackEvent.event_type == 'qualified_play')
            .order_by(models.PlaybackEvent.created_at.desc())
            .limit(limit * 4)
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
            for r in db.query(models.Track.id)
            .order_by(models.Track.created_at.desc(), models.Track.last_indexed_at.desc())
            .limit(limit)
            .all()
        ]
    if key == 'never_played':
        rows = (
            db.query(models.Track.id)
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
    tracks = (
        db.query(models.Track)
        .filter_by(artist=req.artist, album=req.album)
        .order_by(models.Track.relative_path, models.Track.title)
        .limit(min(max(req.limit, 1), 2000))
        .all()
    )
    if req.shuffle:
        random.shuffle(tracks)
    return payload(tracks)


@router.post('/artist')
def artist_queue(req: ArtistQueueRequest, db: Session = Depends(get_db)):
    max_tracks = min(max(req.limit, 1), 5000)
    tracks = (
        db.query(models.Track)
        .filter(or_(models.Track.artist == req.artist, models.Track.album_artist == req.artist))
        .order_by(models.Track.album, models.Track.relative_path, models.Track.title)
        .limit(max_tracks)
        .all()
    )
    if req.shuffle:
        random.shuffle(tracks)
    return payload(tracks)


@router.post('/playlist')
def playlist_queue(req: PlaylistQueueRequest, db: Session = Depends(get_db)):
    rows = (
        db.query(models.PlaylistTrack)
        .filter_by(playlist_id=req.playlist_id)
        .order_by(models.PlaylistTrack.position, models.PlaylistTrack.id)
        .all()
    )
    tracks = [r.track for r in rows if r.track]
    if req.shuffle:
        random.shuffle(tracks)
    return payload(tracks)


@router.post('/smart-playlist')
def smart_playlist_queue(req: SmartPlaylistQueueRequest, db: Session = Depends(get_db)):
    ids = smart_track_ids(db, req.key, req.limit)
    if not ids:
        return {'queue': []}
    tracks = [db.get(models.Track, tid) for tid in ids]
    tracks = [t for t in tracks if t]
    if req.shuffle:
        random.shuffle(tracks)
    return payload(choose_preferred_tracks(tracks, mode="smart_playlist"))


@router.get('/current')
def get_current_queue():
    return {'queue': []}

