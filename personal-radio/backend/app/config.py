from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .database_dialect import require_supported_database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
BACKEND_ENV_FILE = BACKEND_DIR / ".env"

DEFAULT_MEDIA_ROOT = PROJECT_ROOT / "media"
DEFAULT_MUSIC_ROOT = str(DEFAULT_MEDIA_ROOT / "Music")
DEFAULT_AUDIOBOOK_ROOT = str(DEFAULT_MEDIA_ROOT / "Audiobooks" / "Library")
DEFAULT_BOOK_ROOT = str(DEFAULT_MEDIA_ROOT / "Books")
DEFAULT_CACHE_ROOT = str(PROJECT_ROOT / "cache")
DEFAULT_ARTWORK_CACHE_ROOT = str(PROJECT_ROOT / "cache" / "artwork")
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8094
DEFAULT_CORS_ORIGINS = ["http://127.0.0.1:5174", "http://localhost:5174"]

_FORBIDDEN_MEDIA_LANES = {"_ingest", "_staging", "_quarantine"}


def _path_key(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _is_same_or_inside(child: str | Path, parent: str | Path) -> bool:
    child_key = _path_key(child)
    parent_key = _path_key(parent)
    try:
        return os.path.commonpath([child_key, parent_key]) == parent_key
    except ValueError:
        return False


def _has_forbidden_lane(value: str | Path) -> bool:
    return any(part.lower() in _FORBIDDEN_MEDIA_LANES for part in Path(value).parts)


class Settings(BaseSettings):
    APP_NAME: str = "BM Radio"
    APP_ENV: str = "development"
    TZ: str = "America/Chicago"

    BM_RADIO_DB_URL: str = "sqlite:///./bm_radio.db"
    BM_RADIO_MUSIC_ROOT: str = DEFAULT_MUSIC_ROOT
    BM_RADIO_AUDIOBOOK_ROOT: str = DEFAULT_AUDIOBOOK_ROOT
    BM_RADIO_BOOK_ROOT: str = DEFAULT_BOOK_ROOT
    BM_RADIO_CACHE_ROOT: str = DEFAULT_CACHE_ROOT
    BM_RADIO_ARTWORK_CACHE_ROOT: str = DEFAULT_ARTWORK_CACHE_ROOT
    BM_RADIO_API_HOST: str = DEFAULT_API_HOST
    BM_RADIO_API_PORT: int = DEFAULT_API_PORT
    BM_RADIO_API_DOCS_ENABLED: bool = False
    BM_RADIO_CORS_ORIGINS: list[str] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
    BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN: bool = False
    BM_RADIO_DB_POLICY_STATUS: str = Field('unvalidated', exclude=True, repr=False)

    # Temporary compatibility fields. Runtime code reads resolved values from these
    # until the broader BM-PROD configuration migration removes old names.
    DATABASE_URL: str | None = None
    NAS_DATA_ROOT: str | None = None
    MUSIC_ROOT: str | None = None
    MUSIC_LIBRARY_ROOT: str | None = None
    MUSIC_FLAC_ROOT: str | None = None
    MUSIC_MP3_ROOT: str | None = None
    MUSIC_DISCOGRAPHIES_ROOT: str | None = None
    MUSIC_PLAYLISTS_ROOT: str | None = None
    MUSIC_METADATA_ROOT: str | None = None
    AUDIOBOOKS_ROOT: str | None = None
    BACKEND_HOST: str | None = None
    BACKEND_PORT: int | None = None
    FRONTEND_PORT: int = 5174

    PUBLIC_ACCESS: bool = False
    ALLOW_FILE_MUTATION: bool = False
    ALLOW_DELETE: bool = False
    ALLOW_TAG_WRITES: bool = False
    SCAN_INGEST_FOLDERS: bool = False

    BM_RADIO_MUSIC_ROOT_SOURCE: str = Field("default", exclude=True, repr=False)

    model_config = SettingsConfigDict(env_file=BACKEND_ENV_FILE, extra="ignore", populate_by_name=True, enable_decoding=False)

    @model_validator(mode="before")
    @classmethod
    def apply_legacy_environment_aliases(cls, data: Any) -> Any:
        values = dict(data or {})
        aliases = {
            "BM_RADIO_DB_URL": "DATABASE_URL",
            "BM_RADIO_MUSIC_ROOT": "MUSIC_ROOT",
            "BM_RADIO_AUDIOBOOK_ROOT": "AUDIOBOOKS_ROOT",
            "BM_RADIO_API_HOST": "BACKEND_HOST",
            "BM_RADIO_API_PORT": "BACKEND_PORT",
        }
        for canonical, legacy in aliases.items():
            if canonical not in values and legacy in values:
                values[canonical] = values[legacy]

        if "BM_RADIO_MUSIC_ROOT" in values:
            values["BM_RADIO_MUSIC_ROOT_SOURCE"] = "canonical"
        elif "MUSIC_ROOT" in values:
            values["BM_RADIO_MUSIC_ROOT_SOURCE"] = "legacy"
        else:
            values["BM_RADIO_MUSIC_ROOT_SOURCE"] = "default"
        return values

    @field_validator("BM_RADIO_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str] | Any:
        if value is None:
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                parsed = json.loads(text)
                if not isinstance(parsed, list):
                    raise ValueError("BM_RADIO_CORS_ORIGINS JSON value must be a list")
                value = parsed
            else:
                value = text.split(",")
        if isinstance(value, (list, tuple)):
            origins = [str(item).strip() for item in value]
            if any(not origin for origin in origins):
                raise ValueError("BM_RADIO_CORS_ORIGINS must not contain empty origin entries")
            return origins
        raise ValueError("BM_RADIO_CORS_ORIGINS must be a JSON list or comma-separated string")

    @model_validator(mode="after")
    def resolve_and_validate(self) -> "Settings":
        database_target = require_supported_database_url(self.BM_RADIO_DB_URL)
        environment = self.APP_ENV.strip().lower()
        if database_target.is_sqlite and environment in {'production', 'prod', 'staging', 'stage'}:
            raise ValueError('production-like APP_ENV requires postgresql+psycopg; SQLite is development-only')
        object.__setattr__(
            self,
            'BM_RADIO_DB_POLICY_STATUS',
            'development_sqlite' if database_target.is_sqlite else 'postgresql_supported',
        )
        music_root = Path(self.BM_RADIO_MUSIC_ROOT)
        canonical_music_supplied = self.BM_RADIO_MUSIC_ROOT_SOURCE == "canonical"

        object.__setattr__(self, "DATABASE_URL", self.BM_RADIO_DB_URL)
        object.__setattr__(self, "MUSIC_ROOT", str(music_root))
        object.__setattr__(self, "AUDIOBOOKS_ROOT", self.BM_RADIO_AUDIOBOOK_ROOT)
        object.__setattr__(self, "BACKEND_HOST", self.BM_RADIO_API_HOST)
        object.__setattr__(self, "BACKEND_PORT", self.BM_RADIO_API_PORT)

        if self.NAS_DATA_ROOT is None:
            object.__setattr__(self, "NAS_DATA_ROOT", str(music_root.parent))

        library_root = music_root / "Library"
        derived = {
            "MUSIC_LIBRARY_ROOT": str(library_root),
            "MUSIC_FLAC_ROOT": str(library_root / "FLAC"),
            "MUSIC_MP3_ROOT": str(library_root / "MP3"),
            "MUSIC_DISCOGRAPHIES_ROOT": str(music_root / "Discographies"),
            "MUSIC_PLAYLISTS_ROOT": str(music_root / "Playlists"),
            "MUSIC_METADATA_ROOT": str(music_root / "Metadata"),
        }
        for name, value in derived.items():
            if canonical_music_supplied or getattr(self, name) is None:
                object.__setattr__(self, name, value)

        if not self.BM_RADIO_CORS_ORIGINS:
            object.__setattr__(self, "BM_RADIO_CORS_ORIGINS", [])
        else:
            origins = [self._validate_cors_origin(origin) for origin in self.BM_RADIO_CORS_ORIGINS]
            object.__setattr__(self, "BM_RADIO_CORS_ORIGINS", origins)

        self._validate_media_roots()
        self._validate_cache_roots()
        return self

    @staticmethod
    def _validate_cors_origin(origin: str) -> str:
        value = str(origin).strip()
        if value in {"*", "null"}:
            raise ValueError("BM_RADIO_CORS_ORIGINS must contain explicit http/https origins only")
        if "*" in value:
            raise ValueError("BM_RADIO_CORS_ORIGINS must not contain wildcard origins")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("BM_RADIO_CORS_ORIGINS entries must use http or https and include a host")
        if parsed.path or parsed.query or parsed.fragment:
            raise ValueError("BM_RADIO_CORS_ORIGINS entries must not include path, query, or fragment")
        return value

    def _validate_media_roots(self) -> None:
        media_roots = {
            "BM_RADIO_MUSIC_ROOT": self.BM_RADIO_MUSIC_ROOT,
            "BM_RADIO_AUDIOBOOK_ROOT": self.BM_RADIO_AUDIOBOOK_ROOT,
            "BM_RADIO_BOOK_ROOT": self.BM_RADIO_BOOK_ROOT,
        }
        for name, root in media_roots.items():
            if _has_forbidden_lane(root):
                raise ValueError(f"{name} must not be inside _INGEST, _STAGING, or _QUARANTINE")

    def _validate_cache_roots(self) -> None:
        media_roots = {
            "BM_RADIO_MUSIC_ROOT": self.BM_RADIO_MUSIC_ROOT,
            "BM_RADIO_AUDIOBOOK_ROOT": self.BM_RADIO_AUDIOBOOK_ROOT,
            "BM_RADIO_BOOK_ROOT": self.BM_RADIO_BOOK_ROOT,
        }
        cache_roots = {
            "BM_RADIO_CACHE_ROOT": self.BM_RADIO_CACHE_ROOT,
            "BM_RADIO_ARTWORK_CACHE_ROOT": self.BM_RADIO_ARTWORK_CACHE_ROOT,
        }
        for cache_name, cache_root in cache_roots.items():
            for media_name, media_root in media_roots.items():
                if _is_same_or_inside(cache_root, media_root):
                    raise ValueError(f"{cache_name} must not be inside {media_name}")


settings = Settings()
