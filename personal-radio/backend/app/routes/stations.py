from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_stations():
    return []

@router.post("/")
async def create_station():
    return {"message": "Station created"}

@router.get("/{station_id}")
async def get_station(station_id: int):
    return {"id": station_id}

@router.post("/{station_id}/favorite")
async def favorite_station(station_id: int):
    return {"message": f"Station {station_id} favorited"}

@router.post("/{station_id}/queue")
async def queue_station(station_id: int):
    return {"message": f"Station {station_id} added to queue"}
