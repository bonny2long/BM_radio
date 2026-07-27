from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import shutil
import sys
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.config import settings
from app.schema_maintenance import ensure_scan_reconciliation_columns
from app.scanner import music_scanner


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


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def configure_roots(base: Path, *, legacy_enabled: bool = False, flac: bool = True, mp3: bool = True, disc: bool = False) -> dict[str, Path]:
    nas = base / "nas-data"
    music = nas / "Music"
    library = music / "Library"
    roots = {
        "nas": nas,
        "music": music,
        "library": library,
        "flac": library / "FLAC",
        "mp3": library / "MP3",
        "disc": music / "Discographies",
    }
    for key in ("nas", "music", "library"):
        roots[key].mkdir(parents=True, exist_ok=True)
    if flac:
        roots["flac"].mkdir(parents=True, exist_ok=True)
    if mp3:
        roots["mp3"].mkdir(parents=True, exist_ok=True)
    if disc:
        roots["disc"].mkdir(parents=True, exist_ok=True)
    settings.NAS_DATA_ROOT = str(roots["nas"])
    settings.MUSIC_ROOT = str(roots["music"])
    settings.MUSIC_LIBRARY_ROOT = str(roots["library"])
    settings.MUSIC_FLAC_ROOT = str(roots["flac"])
    settings.MUSIC_MP3_ROOT = str(roots["mp3"])
    settings.MUSIC_DISCOGRAPHIES_ROOT = str(roots["disc"])
    settings.BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN = legacy_enabled
    return roots


def write_media(path: Path, data: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if data is not None else b"synthetic audio fixture")
    return path


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def scan(db):
    result = music_scanner.scan_music(db)
    assert result["scan_run_id"], result
    db.expire_all()
    return result, db.get(models.ScanRun, result["scan_run_id"])


def track_by_path(db, path: Path) -> models.Track:
    track = db.query(models.Track).filter_by(path=str(path)).one_or_none()
    assert track is not None, str(path)
    return track


def tracks_by_path(db) -> dict[str, models.Track]:
    return {track.path: track for track in db.query(models.Track).all()}


def case_a_first_successful_scan(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_a")
    with temporary_settings():
        roots = configure_roots(tmp / "case_a_roots")
        flac_file = write_media(roots["flac"] / "Artist A" / "Album A" / "01 - First.flac")
        mp3_file = write_media(roots["mp3"] / "Artist B" / "Album B" / "01 - Second.mp3")
        db = Session()
        try:
            result, scan_run = scan(db)
            assert result["status"] == "ok", result
            assert result["scan_run_status"] == "succeeded", result
            assert scan_run.status == "succeeded"
            assert scan_run.items_added == 2
            assert scan_run.items_unavailable == 0
            assert db.query(models.Track).count() == 2
            for path in (flac_file, mp3_file):
                track = track_by_path(db, path)
                assert track.library_availability == "available"
                assert track.last_seen_scan_id == scan_run.id
                assert track.unavailable_since is None
        finally:
            db.close()


def case_b_identical_rescan_idempotent(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_b")
    with temporary_settings():
        roots = configure_roots(tmp / "case_b_roots")
        files = [
            write_media(roots["flac"] / "Artist A" / "Album A" / "01 - First.flac"),
            write_media(roots["mp3"] / "Artist B" / "Album B" / "01 - Second.mp3"),
        ]
        db = Session()
        try:
            _, first_run = scan(db)
            ids = {path: track_by_path(db, path).id for path in files}
            result, second_run = scan(db)
            assert result["tracks_unavailable"] == 0
            assert db.query(models.Track).count() == 2
            assert second_run.id != first_run.id
            for path in files:
                track = track_by_path(db, path)
                assert track.id == ids[path]
                assert track.last_seen_scan_id == second_run.id
        finally:
            db.close()


def case_c_missing_file_becomes_unavailable(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_c")
    with temporary_settings():
        roots = configure_roots(tmp / "case_c_roots")
        missing = write_media(roots["flac"] / "Artist A" / "Album A" / "01 - Missing.flac")
        present = write_media(roots["mp3"] / "Artist B" / "Album B" / "01 - Present.mp3")
        db = Session()
        try:
            scan(db)
            missing_id = track_by_path(db, missing).id
            missing.unlink()
            result, scan_run = scan(db)
            missing_track = track_by_path(db, missing)
            present_track = track_by_path(db, present)
            assert missing_track.id == missing_id
            assert missing_track.library_availability == "unavailable"
            assert missing_track.unavailable_since is not None
            assert present_track.library_availability == "available"
            assert scan_run.items_unavailable == 1
            assert result["tracks_unavailable"] == 1
        finally:
            db.close()


def case_d_returning_file_restores_same_track(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_d")
    with temporary_settings():
        roots = configure_roots(tmp / "case_d_roots")
        media = write_media(roots["flac"] / "Artist A" / "Album A" / "01 - Return.flac")
        db = Session()
        try:
            scan(db)
            track_id = track_by_path(db, media).id
            media.unlink()
            scan(db)
            assert track_by_path(db, media).library_availability == "unavailable"
            write_media(media)
            _, scan_run = scan(db)
            restored = track_by_path(db, media)
            assert restored.id == track_id
            assert restored.library_availability == "available"
            assert restored.unavailable_since is None
            assert restored.last_seen_scan_id == scan_run.id
            assert db.query(models.Track).filter_by(path=str(media)).count() == 1
        finally:
            db.close()


def case_e_user_state_survives(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_e")
    with temporary_settings():
        roots = configure_roots(tmp / "case_e_roots")
        media = write_media(roots["flac"] / "Artist A" / "Album A" / "01 - State.flac")
        db = Session()
        try:
            scan(db)
            track = track_by_path(db, media)
            favorite = models.TrackFavorite(track_id=track.id)
            thumb = models.TrackThumb(track_id=track.id, value=models.ThumbValue.up)
            db.add_all([favorite, thumb])
            db.commit()
            favorite_id = favorite.id
            thumb_id = thumb.id
            media.unlink()
            scan(db)
            write_media(media)
            scan(db)
            assert db.get(models.TrackFavorite, favorite_id).track_id == track.id
            assert db.get(models.TrackThumb, thumb_id).value == models.ThumbValue.up
            assert track_by_path(db, media).library_availability == "available"
        finally:
            db.close()


def case_f_outside_root_untouched(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_f")
    with temporary_settings():
        roots = configure_roots(tmp / "case_f_roots")
        write_media(roots["flac"] / "Artist A" / "Album A" / "01 - Present.flac")
        outside = tmp / "outside" / "Track.flac"
        db = Session()
        try:
            db.add(models.Track(path=str(outside), title="Outside", library_availability="available"))
            db.commit()
            scan(db)
            row = track_by_path(db, outside)
            assert row.library_availability == "available"
            assert row.unavailable_since is None
        finally:
            db.close()


def case_g_path_boundary_false_positive_blocked(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_g")
    with temporary_settings():
        roots = configure_roots(tmp / "case_g_roots")
        write_media(roots["flac"] / "Artist A" / "Album A" / "01 - Present.flac")
        flac_old = roots["library"] / "FLAC-OLD" / "Artist" / "Album" / "01 - Old.flac"
        db = Session()
        try:
            db.add(models.Track(path=str(flac_old), title="Old", library_availability="available"))
            db.commit()
            scan(db)
            row = track_by_path(db, flac_old)
            assert row.library_availability == "available"
            assert row.unavailable_since is None
        finally:
            db.close()


def case_h_missing_configured_root_not_reconciled(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_h")
    with temporary_settings():
        roots = configure_roots(tmp / "case_h_roots", flac=True, mp3=False)
        write_media(roots["flac"] / "Artist A" / "Album A" / "01 - Present.flac")
        mp3_missing = roots["mp3"] / "Artist B" / "Album B" / "01 - Missing.mp3"
        db = Session()
        try:
            db.add(models.Track(path=str(mp3_missing), title="Missing MP3", library_availability="available"))
            db.commit()
            result, _ = scan(db)
            assert str(roots["mp3"]) in result["skipped_roots"]
            row = track_by_path(db, mp3_missing)
            assert row.library_availability == "available"
            assert result["tracks_unavailable"] == 0
        finally:
            db.close()


def case_i_zero_existing_roots_fail_closed(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_i")
    with temporary_settings():
        roots = configure_roots(tmp / "case_i_roots", flac=False, mp3=False)
        missing = roots["flac"] / "Artist" / "Album" / "01 - Existing.flac"
        db = Session()
        try:
            db.add(models.Track(path=str(missing), title="Existing", library_availability="available"))
            db.commit()
            result, scan_run = scan(db)
            row = track_by_path(db, missing)
            assert result["status"] == "failed", result
            assert scan_run.status == "failed"
            assert row.library_availability == "available"
            assert result["tracks_unavailable"] == 0
            assert result["errors"], result
        finally:
            db.close()


def case_j_per_file_error_prevents_reconciliation(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_j")
    with temporary_settings():
        roots = configure_roots(tmp / "case_j_roots")
        present = write_media(roots["flac"] / "Artist A" / "Album A" / "01 - Bad.flac")
        absent = roots["flac"] / "Artist A" / "Album A" / "02 - Absent.flac"
        db = Session()
        original_read_metadata = music_scanner.read_metadata
        try:
            db.add(models.Track(path=str(absent), title="Absent", library_availability="available"))
            db.commit()

            def broken_read_metadata(path: Path):
                if path == present:
                    raise RuntimeError("deterministic metadata failure")
                return original_read_metadata(path)

            music_scanner.read_metadata = broken_read_metadata
            result, scan_run = scan(db)
            row = track_by_path(db, absent)
            assert result["status"] == "failed", result
            assert scan_run.status == "failed"
            assert scan_run.error_count > 0
            assert row.library_availability == "available"
            assert result["tracks_unavailable"] == 0
        finally:
            music_scanner.read_metadata = original_read_metadata
            db.close()


def case_k_exact_path_survives_duplicate_suppression(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_k")
    with temporary_settings():
        roots = configure_roots(tmp / "case_k_roots")
        flac = write_media(roots["flac"] / "Artist A" / "Album A" / "01 - Same.flac")
        mp3 = write_media(roots["mp3"] / "Artist A" / "Album A" / "01 - Same.mp3")
        db = Session()
        try:
            db.add_all([
                models.Track(path=str(flac), title="Same", artist="Artist A", album="Album A", album_artist="Artist A", library_availability="available"),
                models.Track(path=str(mp3), title="Same", artist="Artist A", album="Album A", album_artist="Artist A", library_availability="available"),
            ])
            db.commit()
            result, scan_run = scan(db)
            assert result["status"] == "ok", result
            assert track_by_path(db, flac).last_seen_scan_id == scan_run.id
            assert track_by_path(db, mp3).last_seen_scan_id == scan_run.id
            assert track_by_path(db, flac).library_availability == "available"
            assert track_by_path(db, mp3).library_availability == "available"
        finally:
            db.close()


def case_l_unavailable_old_duplicate_does_not_suppress_new_file(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_l")
    with temporary_settings():
        roots = configure_roots(tmp / "case_l_roots")
        old_path = roots["flac"] / "Artist A" / "Album A" / "01 - Same.flac"
        new_path = write_media(roots["mp3"] / "Artist A" / "Album A" / "01 - Same.mp3")
        db = Session()
        try:
            db.add(models.Track(path=str(old_path), title="Same", artist="Artist A", album="Album A", album_artist="Artist A", library_availability="unavailable"))
            db.commit()
            result, _ = scan(db)
            assert result["tracks_added"] == 1, result
            assert db.query(models.Track).count() == 2
            assert track_by_path(db, old_path).library_availability == "unavailable"
            assert track_by_path(db, new_path).library_availability == "available"
        finally:
            db.close()


def case_m_legacy_discographies_disabled(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_m")
    with temporary_settings():
        roots = configure_roots(tmp / "case_m_roots", legacy_enabled=False, flac=True, mp3=True, disc=True)
        legacy = roots["disc"] / "Artist" / "Album" / "01 - Legacy.flac"
        db = Session()
        try:
            db.add(models.Track(path=str(legacy), title="Legacy", library_availability="available"))
            db.commit()
            scan(db)
            row = track_by_path(db, legacy)
            assert row.library_availability == "available"
            assert row.unavailable_since is None
        finally:
            db.close()


def case_n_legacy_discographies_enabled(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_n")
    with temporary_settings():
        roots = configure_roots(tmp / "case_n_roots", legacy_enabled=True, flac=True, mp3=True, disc=True)
        legacy = roots["disc"] / "Artist" / "Album" / "01 - Legacy.flac"
        db = Session()
        try:
            db.add(models.Track(path=str(legacy), title="Legacy", library_availability="available"))
            db.commit()
            result, _ = scan(db)
            row = track_by_path(db, legacy)
            assert str(roots["disc"]) in result["roots_scanned"]
            assert row.library_availability == "unavailable"
            assert result["tracks_unavailable"] == 1
        finally:
            db.close()


def case_o_no_file_mutation(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_o")
    with temporary_settings():
        roots = configure_roots(tmp / "case_o_roots")
        keep = write_media(roots["flac"] / "Artist" / "Album" / "01 - Keep.flac", b"keep these bytes exactly")
        before = digest(keep)
        db = Session()
        try:
            scan(db)
            scan(db)
            assert keep.exists()
            assert digest(keep) == before
        finally:
            db.close()


def main() -> None:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_3b_music_scan_reconciliation"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_first_successful_scan(tmp)
        case_b_identical_rescan_idempotent(tmp)
        case_c_missing_file_becomes_unavailable(tmp)
        case_d_returning_file_restores_same_track(tmp)
        case_e_user_state_survives(tmp)
        case_f_outside_root_untouched(tmp)
        case_g_path_boundary_false_positive_blocked(tmp)
        case_h_missing_configured_root_not_reconciled(tmp)
        case_i_zero_existing_roots_fail_closed(tmp)
        case_j_per_file_error_prevents_reconciliation(tmp)
        case_k_exact_path_survives_duplicate_suppression(tmp)
        case_l_unavailable_old_duplicate_does_not_suppress_new_file(tmp)
        case_m_legacy_discographies_disabled(tmp)
        case_n_legacy_discographies_enabled(tmp)
        case_o_no_file_mutation(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.3B music scan reconciliation")


if __name__ == "__main__":
    main()
