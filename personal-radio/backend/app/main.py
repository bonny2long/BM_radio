from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from . import models, db
from .config import settings
from .routes import health, library, stations, audiobooks, queue, playback, media, search, playlists

# Create database tables
models.Base.metadata.create_all(bind=db.engine)

app = FastAPI(title=settings.APP_NAME)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.APP_NAME} API"}
