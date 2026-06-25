from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
from .queue import display_genre, track_genre
router = APIRouter()

@router.get('/')
async def get_stations(db: Session = Depends(get_db)):
    total = db.query(func.count(models.Track.id)).scalar()
    if not total: return []
    fav_ids={r[0] for r in db.query(models.TrackFavorite.track_id).all()}
    latest={}
    for row in db.query(models.TrackThumb).order_by(models.TrackThumb.created_at.asc()).all(): latest[row.track_id]=row.value.value
    favorite_count = len(fav_ids | {tid for tid,value in latest.items() if value=='up'})
    stations = [
        {'name': 'Favorites Radio', 'type': 'favorites', 'track_count': favorite_count},
        {'name': 'Recently Added', 'type': 'recently_added', 'track_count': total},
        {'name': 'Deep Cuts', 'type': 'deep_cuts', 'track_count': total},
    ]
    genre_counts:dict[str,int]={}
    for track in db.query(models.Track).limit(5000).all():
        key=track_genre(track)
        if key: genre_counts[key]=genre_counts.get(key,0)+1
    for key,count in sorted(genre_counts.items(), key=lambda item:item[1], reverse=True)[:5]:
        stations.append({'name': f'{display_genre(key)} Radio', 'type': 'genre', 'seed_value': display_genre(key), 'track_count': count})
    for artist, count in db.query(models.Track.artist, func.count(models.Track.id)).group_by(models.Track.artist).order_by(func.count(models.Track.id).desc()).limit(5):
        stations.append({'name': f'{artist} Radio', 'type': 'artist', 'seed_value': artist, 'track_count': count})
    return stations

@router.post('/')
async def create_station(): return {'message': 'Station created'}
@router.get('/{station_id}')
async def get_station(station_id: int): return {'id': station_id}
@router.post('/{station_id}/favorite')
async def favorite_station(station_id: int): return {'message': f'Station {station_id} favorited'}
@router.post('/{station_id}/queue')
async def queue_station(station_id: int): return {'message': f'Station {station_id} added to queue'}
