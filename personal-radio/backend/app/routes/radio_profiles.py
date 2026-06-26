from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..radio_profiles import apply_artist_profile, apply_track_profile, artist_profile_payload, seed_default_radio_profiles, track_profile_payload

router = APIRouter()


class ArtistProfilePatch(BaseModel):
    primary_genre: str | None = None
    subgenres: list[str] | None = None
    moods: list[str] | None = None
    energy: str | None = None
    era: str | None = None
    related_artists: list[str] | None = None
    source: str | None = 'manual'


class TrackProfilePatch(BaseModel):
    primary_genre: str | None = None
    subgenres: list[str] | None = None
    moods: list[str] | None = None
    energy: str | None = None
    tempo_bucket: str | None = None
    radio_tags: list[str] | None = None
    source: str | None = 'manual'


@router.get('/artists')
def artist_profiles(db: Session = Depends(get_db)):
    seed_default_radio_profiles(db)
    rows = db.query(models.ArtistRadioProfile).order_by(models.ArtistRadioProfile.artist).all()
    return [artist_profile_payload(row) for row in rows]


@router.get('/artists/{artist}')
def artist_profile(artist: str, db: Session = Depends(get_db)):
    seed_default_radio_profiles(db)
    row = db.query(models.ArtistRadioProfile).filter_by(artist=artist).one_or_none()
    if not row:
        raise HTTPException(404, 'Artist radio profile not found')
    return artist_profile_payload(row)


@router.patch('/artists/{artist}')
def update_artist_profile(artist: str, payload: ArtistProfilePatch, db: Session = Depends(get_db)):
    row = db.query(models.ArtistRadioProfile).filter_by(artist=artist).one_or_none()
    if not row:
        row = models.ArtistRadioProfile(artist=artist, source='manual')
        db.add(row)
    apply_artist_profile(row, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(row)
    return artist_profile_payload(row)


@router.get('/tracks/{track_id}')
def track_profile(track_id: int, db: Session = Depends(get_db)):
    seed_default_radio_profiles(db)
    track = db.get(models.Track, track_id)
    if not track:
        raise HTTPException(404, 'Track not found')
    return track_profile_payload(db, track)


@router.patch('/tracks/{track_id}')
def update_track_profile(track_id: int, payload: TrackProfilePatch, db: Session = Depends(get_db)):
    track = db.get(models.Track, track_id)
    if not track:
        raise HTTPException(404, 'Track not found')
    row = db.query(models.TrackRadioProfile).filter_by(track_id=track_id).one_or_none()
    if not row:
        row = models.TrackRadioProfile(track_id=track_id, source='manual')
        db.add(row)
    apply_track_profile(row, payload.model_dump(exclude_unset=True))
    db.commit()
    return track_profile_payload(db, track)