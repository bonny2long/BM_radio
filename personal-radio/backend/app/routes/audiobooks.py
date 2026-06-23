from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_audiobooks():
    return []

@router.get("/summary")
async def get_summary():
    return {"message": "Audiobooks summary placeholder"}

@router.get("/{audiobook_id}")
async def get_audiobook(audiobook_id: int):
    return {"id": audiobook_id}

@router.post("/scan")
async def scan_audiobooks():
    return {"message": "Scanning audiobooks..."}

@router.post("/{audiobook_id}/progress")
async def update_progress(audiobook_id: int):
    return {"message": f"Updated progress for {audiobook_id}"}
