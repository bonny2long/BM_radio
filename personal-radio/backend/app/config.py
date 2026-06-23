from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os

class Settings(BaseSettings):
    APP_NAME: str = "BM Radio"
    APP_ENV: str = "development"
    TZ: str = "America/Chicago"

    DATA_ROOT: str = "../nas-data"
    MUSIC_ROOT: str = "../nas-data/Music"
    AUDIOBOOK_ROOT: str = "../nas-data/Audiobooks"

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
