from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings
from .origin_guard import OriginGuardMiddleware

CORS_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_ALLOWED_HEADERS = ["Accept", "Authorization", "Content-Type", "Range"]

UNSAFE_RUNTIME_FLAGS = {
    "PUBLIC_ACCESS": "PUBLIC_ACCESS must remain false; BM Radio is private-only.",
    "ALLOW_FILE_MUTATION": "ALLOW_FILE_MUTATION must remain false; BM Radio does not mutate archive media.",
    "ALLOW_DELETE": "ALLOW_DELETE must remain false; BM Radio does not own archive deletion.",
    "ALLOW_TAG_WRITES": "ALLOW_TAG_WRITES must remain false; BM Radio does not write archive media tags.",
    "SCAN_INGEST_FOLDERS": "SCAN_INGEST_FOLDERS must remain false; BM Radio reads final libraries only.",
}


def fastapi_docs_config(settings: Settings) -> dict[str, str | None]:
    if settings.BM_RADIO_API_DOCS_ENABLED:
        return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


def validate_runtime_safety(settings: Settings) -> None:
    for name, message in UNSAFE_RUNTIME_FLAGS.items():
        if bool(getattr(settings, name)):
            raise RuntimeError(message)


def configure_origin_guard(app: FastAPI, settings: Settings) -> None:
    """Refuse changing requests from pages that are not one of the configured origins.

    With no configured origins the app's own pages could not make changes at all, so
    loopback origins are accepted in that case.
    """
    app.add_middleware(
        OriginGuardMiddleware,
        get_allowed_origins=lambda: settings.BM_RADIO_CORS_ORIGINS,
        allow_loopback=not settings.BM_RADIO_CORS_ORIGINS,
    )


def configure_cors(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.BM_RADIO_CORS_ORIGINS),
        allow_credentials=False,
        allow_methods=CORS_ALLOWED_METHODS,
        allow_headers=CORS_ALLOWED_HEADERS,
    )