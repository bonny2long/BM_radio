from fastapi import APIRouter

router = APIRouter()

@router.get("/summary")
async def get_summary():
    return {"message": "Library summary placeholder"}

@router.get("/tracks")
async def get_tracks():
    return []

@router.get("/artists")
async def get_artists():
    return []

@router.get("/albums")
async def get_albums():
    return []

@router.get("/search")
async def search(q: str):
    return []

@router.post("/scan/music")
async def scan_music():
    return {"message": "Scanning music..."}
