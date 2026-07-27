from fastapi import APIRouter, Request
from ..config import settings

router = APIRouter()


@router.get("/health")
async def health_check(request: Request):
    readiness = getattr(request.app.state, "database_readiness", None)
    response = {
        "status": "ok",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
    }
    if readiness is not None:
        response["database_ready"] = readiness.ready
        response["database_revision"] = readiness.current_revision
    return response
