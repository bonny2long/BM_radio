from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models, radio_genres
from ..availability import active_track_ids, active_tracks, available_track_filter
from ..db import get_db
from ..perf import perf_segment
from ..radio_profiles import load_radio_profile_cache, profile_for_track_cached
from ..station_engine import display_genre, norm_genre, track_genre, track_matches_genre
from ..station_candidates import current_feedback_by_station_track, favorite_ids_by_station_track, load_station_candidate_tracks, logical_station_count

router = APIRouter()


class StationCreate(BaseModel):
    name: str
    type: str
    seed_value: str | None = None
    seed_track_id: int | None = None


class StationPatch(BaseModel):
    name: str | None = None
    favorite: bool | None = None



def build_station_count_maps(db: Session) -> dict:
    with perf_segment('stations.count_maps'):
        tracks = load_station_candidate_tracks(db, limit=5000)
        artist_counts: dict[str, int] = {}
        album_artist_counts: dict[str, int] = {}
        artist_union_ids: dict[str, set[int]] = {}
        genre_counts: dict[str, int] = {}
        family_counts: dict[str, int] = {}
        profile_cache = load_radio_profile_cache(db)
        for track in tracks:
            if track.artist:
                artist_counts[track.artist] = artist_counts.get(track.artist, 0) + 1
            if track.album_artist:
                album_artist_counts[track.album_artist] = album_artist_counts.get(track.album_artist, 0) + 1
            for name in {track.artist, track.album_artist}:
                if name:
                    artist_union_ids.setdefault(name, set()).add(track.id)
            profile = profile_for_track_cached(track, profile_cache)
            tokens = {token for token in radio_genres.radio_genre_tokens(track, profile) if token and not radio_genres.is_generic_genre(token)}
            families = {radio_genres.genre_family(token) for token in tokens}
            for key in tokens:
                if key and key != 'unknown':
                    genre_counts[key] = genre_counts.get(key, 0) + 1
            for family in families:
                if family and family != 'unknown':
                    family_counts[family] = family_counts.get(family, 0) + 1
        artist_union_counts = {name: len(ids) for name, ids in artist_union_ids.items()}
        total = len(tracks)
    return {'artist': artist_counts, 'album_artist': album_artist_counts, 'artist_union': artist_union_counts, 'genre': genre_counts, 'genre_family': family_counts, 'total': total}


def station_track_count_from_maps(station: models.Station, counts: dict) -> int:
    if station.type == 'artist' and station.seed_value:
        return int(counts.get('artist_union', {}).get(station.seed_value, 0) or 0)
    if station.type == 'genre' and station.seed_value:
        seed = norm_genre(station.seed_value)
        if radio_genres.is_family_genre(seed):
            return int(counts.get('genre_family', {}).get(seed, 0) or counts['genre'].get(seed, 0) or 0)
        return int(counts['genre'].get(seed, 0) or 0)
    if station.type == 'song':
        return 0
    return int(counts.get('total', 0) or 0)


def station_to_dict_fast(station: models.Station, counts: dict) -> dict:
    return {
        'id': station.id,
        'name': station.name,
        'type': station.type,
        'seed_value': station.seed_value,
        'track_count': station_track_count_from_maps(station, counts),
        'source': 'user',
        'favorite': station.favorite,
    }

def station_track_count(station: models.Station, db: Session) -> int:
    return logical_station_count(db, station_type=station.type, seed_value=station.seed_value)


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


def genre_station_dict(key: str, count: int, featured: bool = False, is_family_station: bool | None = None) -> dict:
    family = radio_genres.genre_family(key) or key
    family_station = radio_genres.is_family_genre(key) if is_family_station is None else is_family_station
    return {
        'name': f'{display_genre(key)} Radio',
        'type': 'genre',
        'seed_value': display_genre(key),
        'track_count': int(count),
        'source': 'system',
        'family': family,
        'display_family': radio_genres.display_family(key),
        'featured': bool(featured),
        'is_family_station': bool(family_station),
    }


def useful_genre_station_rows(counts: dict) -> list[dict]:
    family_counts = counts.get('genre_family', {})
    exact_counts = counts.get('genre', {})
    rows: list[tuple[str, int, bool]] = []
    for family, count in family_counts.items():
        if count >= 2 and radio_genres.is_family_genre(family):
            rows.append((family, int(count), True))
    for key, count in exact_counts.items():
        if count < 2 or radio_genres.is_generic_genre(key) or radio_genres.is_family_genre(key):
            continue
        rows.append((key, int(count), False))
    seen: set[str] = set()
    unique: list[tuple[str, int, bool]] = []
    for key, count, is_family in sorted(rows, key=lambda item: (not item[2], -item[1], display_genre(item[0]))):
        if key in seen:
            continue
        seen.add(key)
        unique.append((key, count, is_family))
    featured_keys = {key for key, _, _ in sorted([item for item in unique if item[2]], key=lambda item: item[1], reverse=True)[:5]}
    if len(featured_keys) < 5:
        remaining_featured = [key for key, _, _ in sorted(unique, key=lambda item: item[1], reverse=True) if key not in featured_keys]
        featured_keys |= set(remaining_featured[:5 - len(featured_keys)])
    return [genre_station_dict(key, count, key in featured_keys, is_family) for key, count, is_family in unique]


@router.get('/')
async def get_stations(db: Session = Depends(get_db)):
    counts = build_station_count_maps(db)
    total = counts['total']

    with perf_segment('stations.feedback_counts'):
        candidate_tracks = load_station_candidate_tracks(db, limit=5000)
        feedback = current_feedback_by_station_track(db, candidate_tracks)
        favorites = favorite_ids_by_station_track(db, candidate_tracks)
        favorite_count = len([track for track in candidate_tracks if track.id in favorites or feedback.get(track.id) == 'up'])

    with perf_segment('stations.system_station_build'):
        stations: list[dict] = []
        if total:
            stations.extend([
                {'name': 'Favorites Radio', 'type': 'favorites', 'track_count': favorite_count, 'source': 'system'},
                {'name': 'Recently Added', 'type': 'recently_added', 'track_count': total, 'source': 'system'},
                {'name': 'Deep Cuts', 'type': 'deep_cuts', 'track_count': total, 'source': 'system'},
            ])
        stations.extend(useful_genre_station_rows(counts))
        for artist, count in sorted(counts['artist'].items(), key=lambda item: item[1], reverse=True)[:5]:
            if not artist:
                continue
            stations.append({
                'name': f'{artist} Radio',
                'type': 'artist',
                'seed_value': artist,
                'track_count': count,
                'source': 'system',
            })

    with perf_segment('stations.load_user_stations'):
        user_stations = db.query(models.Station).order_by(models.Station.created_at.desc()).limit(50).all()
    with perf_segment('stations.user_station_counts'):
        for station in user_stations:
            stations.append(station_to_dict_fast(station, counts))

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

