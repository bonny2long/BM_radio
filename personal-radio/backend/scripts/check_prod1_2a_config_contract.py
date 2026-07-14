from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import sys
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DEFAULT_API_HOST, DEFAULT_API_PORT, DEFAULT_MUSIC_ROOT, Settings, settings
from app.scanner.music_scanner import configured_music_scan_roots

CONFIG_ENV_NAMES = (
    "BM_RADIO_DB_URL",
    "BM_RADIO_MUSIC_ROOT",
    "BM_RADIO_AUDIOBOOK_ROOT",
    "BM_RADIO_BOOK_ROOT",
    "BM_RADIO_CACHE_ROOT",
    "BM_RADIO_ARTWORK_CACHE_ROOT",
    "BM_RADIO_API_HOST",
    "BM_RADIO_API_PORT",
    "BM_RADIO_CORS_ORIGINS",
    "BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN",
    "DATABASE_URL",
    "MUSIC_ROOT",
    "MUSIC_LIBRARY_ROOT",
    "MUSIC_FLAC_ROOT",
    "MUSIC_MP3_ROOT",
    "MUSIC_DISCOGRAPHIES_ROOT",
    "MUSIC_PLAYLISTS_ROOT",
    "MUSIC_METADATA_ROOT",
    "AUDIOBOOKS_ROOT",
    "BACKEND_HOST",
    "BACKEND_PORT",
)

GLOBAL_SETTING_NAMES = (
    "BM_RADIO_MUSIC_ROOT",
    "BM_RADIO_AUDIOBOOK_ROOT",
    "BM_RADIO_BOOK_ROOT",
    "BM_RADIO_CACHE_ROOT",
    "BM_RADIO_ARTWORK_CACHE_ROOT",
    "BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN",
    "MUSIC_ROOT",
    "MUSIC_LIBRARY_ROOT",
    "MUSIC_FLAC_ROOT",
    "MUSIC_MP3_ROOT",
    "MUSIC_DISCOGRAPHIES_ROOT",
    "MUSIC_PLAYLISTS_ROOT",
    "MUSIC_METADATA_ROOT",
    "AUDIOBOOKS_ROOT",
)


@contextmanager
def isolated_env(**overrides: str) -> Iterator[None]:
    original = {name: os.environ.get(name) for name in CONFIG_ENV_NAMES}
    try:
        for name in CONFIG_ENV_NAMES:
            os.environ.pop(name, None)
        for name, value in overrides.items():
            os.environ[name] = value
        yield
    finally:
        for name in CONFIG_ENV_NAMES:
            os.environ.pop(name, None)
        for name, value in original.items():
            if value is not None:
                os.environ[name] = value


@contextmanager
def temporary_global_settings(resolved: Settings) -> Iterator[None]:
    original = {name: getattr(settings, name) for name in GLOBAL_SETTING_NAMES}
    try:
        for name in GLOBAL_SETTING_NAMES:
            setattr(settings, name, getattr(resolved, name))
        yield
    finally:
        for name, value in original.items():
            setattr(settings, name, value)


def build_settings(**env: str) -> Settings:
    with isolated_env(**env):
        return Settings(_env_file=None)


def assert_fails(**env: str) -> None:
    try:
        build_settings(**env)
    except ValueError as exc:
        assert str(exc), "validation error should have a message"
        return
    raise AssertionError(f"expected configuration failure for {env}")


def base_env(base: Path) -> dict[str, str]:
    return {
        "BM_RADIO_DB_URL": "sqlite:///test.db",
        "BM_RADIO_MUSIC_ROOT": str(base / "Music"),
        "BM_RADIO_AUDIOBOOK_ROOT": str(base / "Audiobooks" / "Library"),
        "BM_RADIO_BOOK_ROOT": str(base / "Books"),
        "BM_RADIO_CACHE_ROOT": str(base / "app-cache"),
        "BM_RADIO_ARTWORK_CACHE_ROOT": str(base / "app-cache" / "artwork"),
        "BM_RADIO_API_HOST": "127.0.0.9",
        "BM_RADIO_API_PORT": "8194",
        "BM_RADIO_CORS_ORIGINS": '["http://127.0.0.1:5174", " http://localhost:5174 "]',
    }


def case_a_canonical_environment_names_load(base: Path) -> None:
    env = base_env(base)
    resolved = build_settings(**env)
    assert resolved.BM_RADIO_DB_URL == env["BM_RADIO_DB_URL"]
    assert resolved.BM_RADIO_MUSIC_ROOT == env["BM_RADIO_MUSIC_ROOT"]
    assert resolved.BM_RADIO_AUDIOBOOK_ROOT == env["BM_RADIO_AUDIOBOOK_ROOT"]
    assert resolved.BM_RADIO_BOOK_ROOT == env["BM_RADIO_BOOK_ROOT"]
    assert resolved.BM_RADIO_CACHE_ROOT == env["BM_RADIO_CACHE_ROOT"]
    assert resolved.BM_RADIO_ARTWORK_CACHE_ROOT == env["BM_RADIO_ARTWORK_CACHE_ROOT"]
    assert resolved.BM_RADIO_API_HOST == env["BM_RADIO_API_HOST"]
    assert resolved.BM_RADIO_API_PORT == 8194
    assert resolved.BM_RADIO_CORS_ORIGINS == ["http://127.0.0.1:5174", "http://localhost:5174"]


def case_b_audiobook_independence(base: Path) -> None:
    music = base / "Music"
    audiobook = base / "SeparateAudiobooks" / "Library"
    resolved = build_settings(
        BM_RADIO_MUSIC_ROOT=str(music),
        BM_RADIO_AUDIOBOOK_ROOT=str(audiobook),
        BM_RADIO_CACHE_ROOT=str(base / "cache"),
        BM_RADIO_ARTWORK_CACHE_ROOT=str(base / "cache" / "artwork"),
    )
    assert resolved.BM_RADIO_AUDIOBOOK_ROOT == str(audiobook)
    assert Path(resolved.AUDIOBOOKS_ROOT) == audiobook
    assert not str(audiobook).startswith(str(music))


def case_c_music_derived_roots(base: Path) -> None:
    music = base / "Music"
    resolved = build_settings(
        BM_RADIO_MUSIC_ROOT=str(music),
        BM_RADIO_CACHE_ROOT=str(base / "cache"),
        BM_RADIO_ARTWORK_CACHE_ROOT=str(base / "cache" / "artwork"),
    )
    assert resolved.MUSIC_LIBRARY_ROOT == str(music / "Library")
    assert resolved.MUSIC_FLAC_ROOT == str(music / "Library" / "FLAC")
    assert resolved.MUSIC_MP3_ROOT == str(music / "Library" / "MP3")
    assert resolved.MUSIC_DISCOGRAPHIES_ROOT == str(music / "Discographies")
    assert resolved.MUSIC_PLAYLISTS_ROOT == str(music / "Playlists")
    assert resolved.MUSIC_METADATA_ROOT == str(music / "Metadata")
    with temporary_global_settings(resolved):
        assert [str(path) for path in configured_music_scan_roots()] == [
            str(music / "Library" / "FLAC"),
            str(music / "Library" / "MP3"),
        ]


def case_d_legacy_compatibility(base: Path) -> None:
    resolved = build_settings(
        DATABASE_URL="sqlite:///legacy.db",
        MUSIC_ROOT=str(base / "LegacyMusic"),
        AUDIOBOOKS_ROOT=str(base / "LegacyAudiobooks"),
        BACKEND_HOST="127.0.0.8",
        BACKEND_PORT="8294",
        BM_RADIO_CACHE_ROOT=str(base / "cache"),
        BM_RADIO_ARTWORK_CACHE_ROOT=str(base / "cache" / "artwork"),
    )
    assert resolved.BM_RADIO_DB_URL == "sqlite:///legacy.db"
    assert resolved.BM_RADIO_MUSIC_ROOT == str(base / "LegacyMusic")
    assert resolved.BM_RADIO_AUDIOBOOK_ROOT == str(base / "LegacyAudiobooks")
    assert resolved.BM_RADIO_API_HOST == "127.0.0.8"
    assert resolved.BM_RADIO_API_PORT == 8294


def case_e_new_names_win(base: Path) -> None:
    resolved = build_settings(
        BM_RADIO_DB_URL="sqlite:///new.db",
        DATABASE_URL="sqlite:///legacy.db",
        BM_RADIO_MUSIC_ROOT=str(base / "NewMusic"),
        MUSIC_ROOT=str(base / "LegacyMusic"),
        MUSIC_FLAC_ROOT=str(base / "LegacyLeaf" / "FLAC"),
        BM_RADIO_AUDIOBOOK_ROOT=str(base / "NewAudiobooks"),
        AUDIOBOOKS_ROOT=str(base / "LegacyAudiobooks"),
        BM_RADIO_API_HOST="127.0.0.7",
        BACKEND_HOST="0.0.0.0",
        BM_RADIO_API_PORT="8394",
        BACKEND_PORT="9999",
        BM_RADIO_CACHE_ROOT=str(base / "cache"),
        BM_RADIO_ARTWORK_CACHE_ROOT=str(base / "cache" / "artwork"),
    )
    assert resolved.BM_RADIO_DB_URL == "sqlite:///new.db"
    assert resolved.DATABASE_URL == "sqlite:///new.db"
    assert resolved.BM_RADIO_MUSIC_ROOT == str(base / "NewMusic")
    assert resolved.MUSIC_FLAC_ROOT == str(base / "NewMusic" / "Library" / "FLAC")
    assert resolved.BM_RADIO_AUDIOBOOK_ROOT == str(base / "NewAudiobooks")
    assert resolved.BM_RADIO_API_HOST == "127.0.0.7"
    assert resolved.BM_RADIO_API_PORT == 8394


def case_f_safe_network_defaults() -> None:
    resolved = build_settings()
    assert resolved.BM_RADIO_API_HOST == DEFAULT_API_HOST == "127.0.0.1"
    assert resolved.BM_RADIO_API_PORT == DEFAULT_API_PORT == 8094


def case_g_cors_parsing(base: Path) -> None:
    resolved = build_settings(
        BM_RADIO_MUSIC_ROOT=str(base / "Music"),
        BM_RADIO_CACHE_ROOT=str(base / "cache"),
        BM_RADIO_ARTWORK_CACHE_ROOT=str(base / "cache" / "artwork"),
        BM_RADIO_CORS_ORIGINS="http://127.0.0.1:5174, http://localhost:5174",
    )
    assert resolved.BM_RADIO_CORS_ORIGINS == ["http://127.0.0.1:5174", "http://localhost:5174"]
    assert "*" not in resolved.BM_RADIO_CORS_ORIGINS
    assert "" not in resolved.BM_RADIO_CORS_ORIGINS


def case_h_cache_media_separation(base: Path) -> None:
    normal = build_settings(
        BM_RADIO_MUSIC_ROOT=str(base / "Music"),
        BM_RADIO_AUDIOBOOK_ROOT=str(base / "Audiobooks"),
        BM_RADIO_BOOK_ROOT=str(base / "Books"),
        BM_RADIO_CACHE_ROOT=str(base / "cache"),
        BM_RADIO_ARTWORK_CACHE_ROOT=str(base / "cache" / "artwork"),
    )
    assert normal.BM_RADIO_CACHE_ROOT == str(base / "cache")

    for media_key, media_root in (
        ("BM_RADIO_MUSIC_ROOT", base / "Music"),
        ("BM_RADIO_AUDIOBOOK_ROOT", base / "Audiobooks"),
        ("BM_RADIO_BOOK_ROOT", base / "Books"),
    ):
        env = base_env(base / f"invalid-cache-{media_key}")
        env[media_key] = str(media_root)
        env["BM_RADIO_CACHE_ROOT"] = str(media_root / "cache")
        assert_fails(**env)
        env = base_env(base / f"invalid-artwork-{media_key}")
        env[media_key] = str(media_root)
        env["BM_RADIO_ARTWORK_CACHE_ROOT"] = str(media_root / "artwork-cache")
        assert_fails(**env)


def case_i_forbidden_workflow_lanes(base: Path) -> None:
    for media_key in ("BM_RADIO_MUSIC_ROOT", "BM_RADIO_AUDIOBOOK_ROOT", "BM_RADIO_BOOK_ROOT"):
        for lane in ("_INGEST", "_STAGING", "_QUARANTINE"):
            env = base_env(base / f"forbidden-{media_key}-{lane}")
            env[media_key] = str(base / lane / "Media")
            assert_fails(**env)


def case_j_env_file_isolation() -> None:
    with isolated_env():
        resolved = Settings(_env_file=None)
    assert resolved.BM_RADIO_MUSIC_ROOT == DEFAULT_MUSIC_ROOT


def main() -> None:
    base = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_2a_config_contract"
    if base.exists():
        import shutil
        shutil.rmtree(base)
    base.mkdir(parents=True)
    try:
        case_a_canonical_environment_names_load(base / "case_a")
        case_b_audiobook_independence(base / "case_b")
        case_c_music_derived_roots(base / "case_c")
        case_d_legacy_compatibility(base / "case_d")
        case_e_new_names_win(base / "case_e")
        case_f_safe_network_defaults()
        case_g_cors_parsing(base / "case_g")
        case_h_cache_media_separation(base / "case_h")
        case_i_forbidden_workflow_lanes(base / "case_i")
        case_j_env_file_isolation()
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)
    print("PASS: BM-PROD1.2A configuration contract")


if __name__ == "__main__":
    main()
