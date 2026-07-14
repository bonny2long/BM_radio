from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import sys
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import settings
from app.scanner.music_scanner import configured_music_scan_roots, scan_music


ROOT_SETTING_NAMES = (
    "NAS_DATA_ROOT",
    "MUSIC_ROOT",
    "MUSIC_LIBRARY_ROOT",
    "MUSIC_FLAC_ROOT",
    "MUSIC_MP3_ROOT",
    "MUSIC_DISCOGRAPHIES_ROOT",
    "BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN",
)


@contextmanager
def temporary_settings(**overrides: object) -> Iterator[None]:
    original = {name: getattr(settings, name) for name in ROOT_SETTING_NAMES}
    try:
        for name, value in overrides.items():
            setattr(settings, name, value)
        yield
    finally:
        for name, value in original.items():
            setattr(settings, name, value)


def configure_roots(base: Path, *, legacy_enabled: bool, flac: Path | None = None, mp3: Path | None = None, disc: Path | None = None) -> dict[str, Path]:
    nas = base / "nas-data"
    music = nas / "Music"
    library = music / "Library"
    roots = {
        "nas": nas,
        "music": music,
        "library": library,
        "flac": flac or library / "FLAC",
        "mp3": mp3 or library / "MP3",
        "disc": disc or music / "Discographies",
    }
    for key in ("nas", "music", "library"):
        roots[key].mkdir(parents=True, exist_ok=True)
    settings.NAS_DATA_ROOT = str(roots["nas"])
    settings.MUSIC_ROOT = str(roots["music"])
    settings.MUSIC_LIBRARY_ROOT = str(roots["library"])
    settings.MUSIC_FLAC_ROOT = str(roots["flac"])
    settings.MUSIC_MP3_ROOT = str(roots["mp3"])
    settings.MUSIC_DISCOGRAPHIES_ROOT = str(roots["disc"])
    settings.BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN = legacy_enabled
    return roots


def root_strings() -> list[str]:
    return [str(path) for path in configured_music_scan_roots()]


def session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def assert_case_a_default_canonical_policy(base: Path) -> None:
    with temporary_settings():
        roots = configure_roots(base, legacy_enabled=False)
        roots["flac"].mkdir(parents=True)
        roots["mp3"].mkdir(parents=True)
        roots["disc"].mkdir(parents=True)
        assert root_strings() == [str(roots["flac"]), str(roots["mp3"])], root_strings()


def assert_case_b_explicit_legacy_compatibility(base: Path) -> None:
    with temporary_settings():
        roots = configure_roots(base, legacy_enabled=True)
        assert root_strings() == [str(roots["flac"]), str(roots["mp3"]), str(roots["disc"])], root_strings()


def assert_case_c_no_broad_fallback(base: Path) -> None:
    with temporary_settings():
        roots = configure_roots(base, legacy_enabled=False)
        roots["mp3"].mkdir(parents=True)
        selected = root_strings()
        assert selected == [str(roots["flac"]), str(roots["mp3"])], selected
        assert str(roots["nas"]) not in selected, selected
        assert str(roots["music"]) not in selected, selected
        assert str(roots["library"]) not in selected, selected
        assert not roots["flac"].exists(), roots["flac"]


def assert_case_d_deterministic_deduplication(base: Path) -> None:
    with temporary_settings():
        shared = base / "shared-root"
        configure_roots(base, legacy_enabled=True, flac=shared, mp3=shared, disc=shared)
        selected = root_strings()
        assert selected == [str(shared)], selected


def assert_case_e_scanner_result_policy(base: Path) -> None:
    with temporary_settings():
        roots = configure_roots(base, legacy_enabled=False)
        roots["flac"].mkdir(parents=True)
        roots["mp3"].mkdir(parents=True)
        roots["disc"].mkdir(parents=True)
        Session = session_factory()
        db = Session()
        try:
            result = scan_music(db)
        finally:
            db.close()
        assert result["legacy_discography_scan_enabled"] is False, result
        assert str(roots["disc"]) not in result["roots_scanned"], result
        assert str(roots["disc"]) not in result["skipped_roots"], result

    with temporary_settings():
        roots = configure_roots(base, legacy_enabled=True)
        roots["flac"].mkdir(parents=True, exist_ok=True)
        roots["mp3"].mkdir(parents=True, exist_ok=True)
        roots["disc"].mkdir(parents=True, exist_ok=True)
        Session = session_factory()
        db = Session()
        try:
            result = scan_music(db)
        finally:
            db.close()
        assert result["legacy_discography_scan_enabled"] is True, result
        assert str(roots["disc"]) in result["roots_scanned"], result


def main() -> None:
    tmp_base = Path(__file__).resolve().parents[1] / "tmp_tests"
    tmp_base.mkdir(exist_ok=True)
    base = tmp_base / "prod1_1_canonical_music_roots"
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    try:
        assert_case_a_default_canonical_policy(base / "case_a")
        assert_case_b_explicit_legacy_compatibility(base / "case_b")
        assert_case_c_no_broad_fallback(base / "case_c")
        assert_case_d_deterministic_deduplication(base / "case_d")
        assert_case_e_scanner_result_policy(base / "case_e")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("PASS: BM-PROD1.1 canonical music roots")

if __name__ == "__main__":
    main()
