from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models
from ..db import get_db
router = APIRouter()

@router.get("/")
async def get_stations(db: Session = Depends(get_db)):
    total = db.query(func.count(models.Track.id)).scalar()
    if not total: return []
    stations = [{"name": "Favorites Radio", "type": "favorites", "track_count": db.query(func.count(models.TrackFavorite.id)).scalar()}, {"name": "Recently Added", "type": "recently_added", "track_count": total}, {"name": "Deep Cuts", "type": "deep_cuts", "track_count": total}]
    for genre, count in db.query(models.Track.genre, func.count(models.Track.id)).filter(models.Track.genre.isnot(None)).group_by(models.Track.genre).order_by(func.count(models.Track.id).desc()).limit(5): stations.append({"name": f"{genre} Radio", "type": "genre", "track_count": count})
    for artist, count in db.query(models.Track.artist, func.count(models.Track.id)).group_by(models.Track.artist).order_by(func.count(models.Track.id).desc()).limit(5): stations.append({"name": f"{artist} Radio", "type": "artist", "track_count": count})
    return stations

@router.post("/")
async def create_station(): return {"message": "Station created"}
@router.get("/{station_id}")
async def get_station(station_id: int): return {"id": station_id}
@router.post("/{station_id}/favorite")
async def favorite_station(station_id: int): return {"message": f"Station {station_id} favorited"}
@router.post("/{station_id}/queue")
async def queue_station(station_id: int): return {"message": f"Station {station_id} added to queue"}
