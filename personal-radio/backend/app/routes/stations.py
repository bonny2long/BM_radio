from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from .queue import display_genre, norm_genre, track_genre

router = APIRouter()


class StationCreate(BaseModel):
    name: str
    type: str
    seed_value: str | None = None
    seed_track_id: int | None = None


class StationPatch(BaseModel):
    name: str | None = None
    favorite: bool | None = None


def station_track_count(station: models.Station, db: Session) -> int:
    if station.type == 'artist' and station.seed_value:
        return db.query(func.count(models.Track.id)).filter(
            or_(models.Track.artist == station.seed_value, models.Track.album_artist == station.seed_value)
        ).scalar() or 0
    if station.type == 'genre' and station.seed_value:
        target = norm_genre(station.seed_value)
        all_tracks = db.query(models.Track).limit(5000).all()
        return sum(1 for track in all_tracks if track_genre(track) == target)
    return db.query(func.count(models.Track.id)).scalar() or 0


def station_to_dict(station: models.Station, db: Session) -> dict:
    return {
        'id': station.id,
        'name': station.name,
        'type': station.type,
        'seed_value': station.seed_value,
        'track_count': station_track_count(station, db),
        'source': 'user',
        'favorite': station.favorite,
    }


@router.get('/')
async def get_stations(db: Session = Depends(get_db)):
    total = db.query(func.count(models.Track.id)).scalar()
    if not total:
        return []

    fav_ids = {r[0] for r in db.query(models.TrackFavorite.track_id).all()}
    latest: dict[int, str] = {}
    for row in db.query(models.TrackThumb).order_by(models.TrackThumb.created_at.asc()).all():
        latest[row.track_id] = row.value.value
    favorite_count = len(fav_ids | {tid for tid, value in latest.items() if value == 'up'})

    stations: list[dict] = [
        {'name': 'Favorites Radio', 'type': 'favorites', 'track_count': favorite_count, 'source': 'system'},
        {'name': 'Recently Added', 'type': 'recently_added', 'track_count': total, 'source': 'system'},
        {'name': 'Deep Cuts', 'type': 'deep_cuts', 'track_count': total, 'source': 'system'},
    ]

    genre_counts: dict[str, int] = {}
    for track in db.query(models.Track).limit(5000).all():
        key = track_genre(track)
        if key:
            genre_counts[key] = genre_counts.get(key, 0) + 1
    for key, count in sorted(genre_counts.items(), key=lambda item: item[1], reverse=True)[:5]:
        stations.append({
            'name': f'{display_genre(key)} Radio',
            'type': 'genre',
            'seed_value': display_genre(key),
            'track_count': count,
            'source': 'system',
        })

    for artist, count in (
        db.query(models.Track.artist, func.count(models.Track.id))
        .group_by(models.Track.artist)
        .order_by(func.count(models.Track.id).desc())
        .limit(5)
    ):
        if not artist:
            continue
        stations.append({
            'name': f'{artist} Radio',
            'type': 'artist',
            'seed_value': artist,
            'track_count': count,
            'source': 'system',
        })

    user_stations = db.query(models.Station).order_by(models.Station.created_at.desc()).limit(50).all()
    for station in user_stations:
        stations.append(station_to_dict(station, db))

    return stations


@router.post('/')
async def create_station(payload: StationCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, 'Station name is required')

    seed_value = payload.seed_value
    if payload.type == 'song' and not seed_value and payload.seed_track_id is not None:
        seed_value = str(payload.seed_track_id)

    existing = None
    if seed_value:
        existing = db.query(models.Station).filter_by(type=payload.type, seed_value=seed_value).first()
    if existing:
        return station_to_dict(existing, db)

    station = models.Station(name=name, type=payload.type, seed_value=seed_value)
    db.add(station)
    db.commit()
    db.refresh(station)
    return station_to_dict(station, db)


@router.get('/{station_id}')
async def get_station(station_id: int, db: Session = Depends(get_db)):
    station = db.get(models.Station, station_id)
    if not station:
        raise HTTPException(404, 'Station not found')
    return station_to_dict(station, db)


@router.patch('/{station_id}')
async def patch_station(station_id: int, payload: StationPatch, db: Session = Depends(get_db)):
    station = db.get(models.Station, station_id)
    if not station:
        raise HTTPException(404, 'Station not found')
    if payload.name is not None:
        station.name = payload.name.strip()
    if payload.favorite is not None:
        station.favorite = payload.favorite
    db.commit()
    db.refresh(station)
    return station_to_dict(station, db)


@router.delete('/{station_id}')
async def delete_station(station_id: int, db: Session = Depends(get_db)):
    station = db.get(models.Station, station_id)
    if not station:
        raise HTTPException(404, 'Station not found')
    db.delete(station)
    db.commit()
    return {'deleted': True}


@router.post('/{station_id}/favorite')
async def favorite_station(station_id: int, db: Session = Depends(get_db)):
    station = db.get(models.Station, station_id)
    if not station:
        raise HTTPException(404, 'Station not found')
    station.favorite = not station.favorite
    db.commit()
    return {'favorite': station.favorite}