from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os

class Settings(BaseSettings):
    APP_NAME: str = "BM Radio"
    APP_ENV: str = "development"
    TZ: str = "America/Chicago"

    NAS_DATA_ROOT: str = r"C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data"
    MUSIC_ROOT: str = r"C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music"
    MUSIC_LIBRARY_ROOT: str = r"C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Library"
    MUSIC_FLAC_ROOT: str = r"C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Library\FLAC"
    MUSIC_MP3_ROOT: str = r"C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Library\MP3"
    MUSIC_DISCOGRAPHIES_ROOT: str = r"C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Discographies"
    MUSIC_PLAYLISTS_ROOT: str = r"C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Playlists"
    MUSIC_METADATA_ROOT: str = r"C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Metadata"
    AUDIOBOOKS_ROOT: str = r"C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Audiobooks\Library"

    DATABASE_URL: str = "sqlite:///./bm_radio.db"

    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8094
    FRONTEND_PORT: int = 5174

    PUBLIC_ACCESS: bool = False
    ALLOW_FILE_MUTATION: bool = False
    ALLOW_DELETE: bool = False
    ALLOW_TAG_WRITES: bool = False
    SCAN_INGEST_FOLDERS: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
