from fastapi import APIRouter

router = APIRouter()

@router.post("/event")
async def register_event():
    return {"message": "Playback event registered"}

@router.post("/tracks/{track_id}/thumb")
async def track_thumb(track_id: int):
    return {"message": f"Thumb registered for {track_id}"}

@router.post("/tracks/{track_id}/favorite")
async def track_favorite(track_id: int):
    return {"message": f"Favorite registered for {track_id}"}
