from fastapi import APIRouter

router = APIRouter()

@router.get("/current")
async def get_current_queue():
    return {"queue": []}
