from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models
from ..availability import TRACK_UNAVAILABLE_MESSAGE, active_track_ids, active_tracks, available_track_filter, is_track_available
from ..db import get_db
from ..music_recording_feedback import smart_music_candidate_count, smart_music_candidate_track_ids
from ..listener_queue import (
    playlist_active_count,
    playlist_has_occurrence,
    playlist_projected_items,
    remove_playlist_occurrence,
    reorder_playlist_by_occurrences,
    track_occurrences_by_id,
    validate_track_addition,
)

router = APIRouter()


class PlaylistCreate(BaseModel):
    name: str
    description: str | None = None


class PlaylistPatch(BaseModel):
    name: str | None = None
    description: str | None = None


class PlaylistTrackCreate(BaseModel):
    track_id: int


class ReorderPayload(BaseModel):
    track_ids: list[int]


class TrackListPlaylistCreate(BaseModel):
    name: str
    description: str | None = None
    track_ids: list[int]


def smart_track_ids(db: Session, key: str, limit: int = 1000):
    return smart_music_candidate_track_ids(db, key=key, limit=limit)


def smart_count(db: Session, key: str):
    return smart_music_candidate_count(db, key=key)


def smart_summary(db: Session, key: str, name: str, description: str):
    return {'id': key, 'name': name, 'kind': 'smart', 'track_count': smart_count(db, key), 'description': description}


def summary(p: models.Playlist, db: Session):
    return {'id': p.id, 'name': p.name, 'description': p.description, 'kind': p.kind, 'track_count': playlist_active_count(db, playlist_id=p.id) or 0}


def detail(p: models.Playlist, db: Session):
    return {**summary(p, db), 'tracks': playlist_projected_items(db, playlist_id=p.id)}


def get_playlist_or_404(playlist_id: int, db: Session):
    p = db.get(models.Playlist, playlist_id)
    if not p:
        raise HTTPException(404, 'Playlist not found')
    return p


@router.get('')
def get_playlists(db: Session = Depends(get_db)):
    return [summary(p, db) for p in db.query(models.Playlist).order_by(models.Playlist.created_at.desc(), models.Playlist.name).all()]


@router.get('/smart')
def get_smart_playlists(db: Session = Depends(get_db)):
    return [
        smart_summary(db, 'favorites', 'Favorites', 'Hearted tracks'),
        smart_summary(db, 'most_played', 'Most Played', 'Tracks you play the most'),
        smart_summary(db, 'recently_played', 'Recently Played', 'Latest unique tracks from your listening history'),
        smart_summary(db, 'recently_added', 'Recently Added', 'Newest tracks in your library'),
        smart_summary(db, 'never_played', 'Never Played', 'Tracks with no playback history'),
        smart_summary(db, 'thumbs_up', 'Thumbs Up', 'Tracks you rated thumbs up'),
    ]


@router.post('')
def create_playlist(payload: PlaylistCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, 'Playlist name is required')
    p = models.Playlist(name=name, description=payload.description, kind='manual')
    db.add(p)
    db.commit()
    db.refresh(p)
    return summary(p, db)


def _append_track_if_allowed(db: Session, playlist_id: int, track_id: int, position: int | None = None) -> bool:
    try:
        occurrence = validate_track_addition(db, track_id=track_id)
    except ValueError:
        return False
    except PermissionError as exc:
        raise HTTPException(409, str(exc) or TRACK_UNAVAILABLE_MESSAGE) from exc
    if playlist_has_occurrence(db, playlist_id=playlist_id, occurrence_key=occurrence.key):
        return False
    if position is None:
        position = db.query(func.max(models.PlaylistTrack.position)).filter_by(playlist_id=playlist_id).scalar() or 0
        position += 1
    db.add(models.PlaylistTrack(playlist_id=playlist_id, track_id=track_id, position=position))
    return True


@router.post('/from-track-list')
def create_from_track_list(payload: TrackListPlaylistCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, 'Playlist name is required')
    selected: list[int] = []
    seen_occurrences: set[tuple] = set()
    for track_id in payload.track_ids:
        try:
            occurrence = validate_track_addition(db, track_id=track_id)
        except ValueError:
            continue
        except PermissionError as exc:
            raise HTTPException(409, str(exc) or TRACK_UNAVAILABLE_MESSAGE) from exc
        if occurrence.key in seen_occurrences:
            continue
        seen_occurrences.add(occurrence.key)
        selected.append(track_id)
    p = models.Playlist(name=name, description=payload.description, kind='manual')
    db.add(p)
    db.flush()
    for position, track_id in enumerate(selected, start=1):
        db.add(models.PlaylistTrack(playlist_id=p.id, track_id=track_id, position=position))
    db.commit()
    db.refresh(p)
    return detail(p, db)

@router.get('/{playlist_id}')
def get_playlist(playlist_id: int, db: Session = Depends(get_db)):
    return detail(get_playlist_or_404(playlist_id, db), db)


@router.patch('/{playlist_id}')
def patch_playlist(playlist_id: int, payload: PlaylistPatch, db: Session = Depends(get_db)):
    p = get_playlist_or_404(playlist_id, db)
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(422, 'Playlist name is required')
        p.name = name
    if payload.description is not None:
        p.description = payload.description
    db.commit()
    return summary(p, db)


@router.delete('/{playlist_id}')
def delete_playlist(playlist_id: int, db: Session = Depends(get_db)):
    p = get_playlist_or_404(playlist_id, db)
    db.delete(p)
    db.commit()
    return {'deleted': True}


@router.post('/{playlist_id}/tracks')
def add_track(playlist_id: int, payload: PlaylistTrackCreate, db: Session = Depends(get_db)):
    p = get_playlist_or_404(playlist_id, db)
    track = db.get(models.Track, payload.track_id)
    if not track:
        raise HTTPException(404, 'Track not found')
    if not is_track_available(track):
        raise HTTPException(409, TRACK_UNAVAILABLE_MESSAGE)
    _append_track_if_allowed(db, p.id, payload.track_id)
    db.commit()
    return detail(p, db)


@router.delete('/{playlist_id}/tracks/{track_id}')
def remove_track(playlist_id: int, track_id: int, db: Session = Depends(get_db)):
    p = get_playlist_or_404(playlist_id, db)
    remove_playlist_occurrence(db, playlist_id=p.id, track_id=track_id)
    db.commit()
    return detail(p, db)


@router.patch('/{playlist_id}/tracks/reorder')
def reorder_tracks(playlist_id: int, payload: ReorderPayload, db: Session = Depends(get_db)):
    p = get_playlist_or_404(playlist_id, db)
    reorder_playlist_by_occurrences(db, playlist_id=p.id, track_ids=payload.track_ids)
    db.commit()
    return detail(p, db)