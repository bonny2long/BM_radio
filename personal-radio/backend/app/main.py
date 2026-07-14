from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from . import models, db
from .config import settings
from .radio_profiles import seed_default_radio_profiles
from .perf import ensure_performance_indexes, install_performance_tools
from .schema_maintenance import ensure_manifest_ingestion_columns
from .runtime_security import configure_cors, fastapi_docs_config, validate_runtime_safety
from .routes import health, library, stations, audiobooks, queue, playback, media, search, playlists, radio_profiles, library_integrity

# Validate private runtime invariants before startup side effects.
validate_runtime_safety(settings)

# Create database tables
models.Base.metadata.create_all(bind=db.engine)
ensure_manifest_ingestion_columns(db.engine)
ensure_performance_indexes()
with db.SessionLocal() as seed_db:
    seed_default_radio_profiles(seed_db)

app = FastAPI(title=settings.APP_NAME, **fastapi_docs_config(settings))
install_performance_tools(app)
configure_cors(app, settings)

# Include routers
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(library.router, prefix="/api/library", tags=["Library"])
app.include_router(stations.router, prefix="/api/stations", tags=["Stations"])
app.include_router(audiobooks.router, prefix="/api/audiobooks", tags=["Audiobooks"])
app.include_router(queue.router, prefix="/api/queue", tags=["Queue"])
app.include_router(playback.router, prefix="/api/playback", tags=["Playback"])
app.include_router(media.router, prefix="/api/media", tags=["Media"])
app.include_router(search.router, prefix="/api", tags=["Search"])
app.include_router(playlists.router, prefix="/api/playlists", tags=["Playlists"])
app.include_router(radio_profiles.router, prefix="/api/radio-profiles", tags=["Radio Profiles"])
app.include_router(library_integrity.router, prefix="/api/library", tags=["Library Integrity"])

@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.APP_NAME} API"}
