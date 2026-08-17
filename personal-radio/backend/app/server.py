from __future__ import annotations

import uvicorn

from .config import settings
from .database_dialect import require_supported_database_url


def validate_production_server() -> None:
    environment = settings.APP_ENV.strip().lower()
    target = require_supported_database_url(settings.BM_RADIO_DB_URL)
    if environment not in {"production", "prod"}:
        raise RuntimeError("the container server requires APP_ENV=production")
    if not target.is_postgresql or target.driver != "psycopg":
        raise RuntimeError("the production container requires postgresql+psycopg")
    if settings.BM_RADIO_API_HOST != "0.0.0.0":
        raise RuntimeError("the container server must bind to 0.0.0.0")
    if settings.BM_RADIO_API_PORT != 8094:
        raise RuntimeError("the container server requires BM_RADIO_API_PORT=8094")


def main() -> None:
    validate_production_server()
    uvicorn.run(
        "app.main:app",
        host=settings.BM_RADIO_API_HOST,
        port=settings.BM_RADIO_API_PORT,
        reload=False,
        access_log=True,
    )


if __name__ == "__main__":
    main()
