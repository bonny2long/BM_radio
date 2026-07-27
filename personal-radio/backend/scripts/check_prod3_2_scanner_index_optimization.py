from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import inspect
import shutil
import sys
from typing import Any, Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.config import settings
from app.music_scan_index import (
    EXACT_PATH_LOOKUP_CHUNK_SIZE,
    MAX_DUPLICATE_WARNING_SAMPLES,
    collect_music_scan_identity_diagnostics,
    tracks_by_exact_paths,
)
from app.perf_benchmark import BenchmarkContext, run_benchmarks
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine
from app.scan_runs import LIBRARY_AVAILABLE, LIBRARY_UNAVAILABLE
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
def temporary_settings() -> Iterator[None]:
    original = {name: getattr(settings, name) for name in ROOT_SETTING_NAMES}
    try:
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


def configure_roots(base: Path) -> dict[str, Path]:
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
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    settings.NAS_DATA_ROOT = str(nas)
    settings.MUSIC_ROOT = str(music)
    settings.MUSIC_LIBRARY_ROOT = str(library)
    settings.MUSIC_FLAC_ROOT = str(roots["flac"])
    settings.MUSIC_MP3_ROOT = str(roots["mp3"])
    settings.MUSIC_DISCOGRAPHIES_ROOT = str(roots["disc"])
    settings.BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN = False
    return roots


def write_media(path: Path, data: bytes = b"prod3.2 fixture bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def meta(path: Path, *, title: str | None = None, artist: str = "Artist", album: str = "Album", duration: float = 180.0, codec: str = "mp3", lossless: bool = False) -> dict[str, Any]:
    return {
        "duration_seconds": duration,
        "title": title or path.stem,
        "artist": artist,
        "album": album,
        "album_artist": artist,
        "genre": "Soul",
        "year": 2026,
        "technical": {
            "probe_status": "ok",
            "probe_source": "synthetic",
            "probe_version": 1,
            "codec": codec,
            "container": codec,
            "is_lossless": lossless,
            "sample_rate_hz": 44100,
            "bit_depth_bits": 16 if lossless else None,
            "bitrate_bps": None if lossless else 320000,
            "channel_count": 2,
            "file_size_bytes": path.stat().st_size if path.exists() else 0,
        },
    }


@contextmanager
def patched_metadata(mapping: dict[str, dict[str, Any]]):
    original = music_scanner.read_metadata

    def fake(path: Path):
        return mapping.get(str(path)) or mapping.get(path.name) or meta(path)

    try:
        music_scanner.read_metadata = fake
        yield
    finally:
        music_scanner.read_metadata = original


def scan(db, mapping: dict[str, dict[str, Any]]):
    with patched_metadata(mapping):
        result = music_scanner.scan_music(db)
    db.expire_all()
    return result


def track_by_path(db, path: Path) -> models.Track:
    row = db.query(models.Track).filter_by(path=str(path)).one_or_none()
    assert row is not None, str(path)
    return row


def link_for(db, track: models.Track) -> models.MusicTrackIdentity:
    return db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).one()


def add_identity_track(db, *, path: str, title: str, artist: str = "Artist", album: str = "Album", recording_id: int | None = None, release_id: int | None = None) -> models.Track:
    if release_id is None:
        release = models.MusicRelease(identity_key=f"release-{path}", album_artist=artist, title=album, normalized_album_artist=artist.lower(), normalized_title=album.lower())
        db.add(release)
        db.flush()
        release_id = release.id
    else:
        release = db.get(models.MusicRelease, release_id)
    edition = models.MusicEdition(identity_key=f"edition-{path}", release_id=release_id, display_title=album, source_scope=path)
    db.add(edition)
    if recording_id is None:
        recording = models.MusicRecording(identity_key=f"recording-{path}", artist=artist, title=title, normalized_artist=artist.lower(), normalized_title=title.lower(), recording_type="unknown", duration_bucket="180")
        db.add(recording)
        db.flush()
        recording_id = recording.id
    track = models.Track(path=path, relative_path=path, title=title, artist=artist, album=album, album_artist=artist, duration_seconds=180, file_ext=".mp3", library_availability=LIBRARY_AVAILABLE)
    db.add(track)
    db.flush()
    db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=recording_id))
    db.flush()
    return track


def case_a_structural_guard() -> None:
    source = inspect.getsource(music_scanner.scan_music)
    assert "db.query(models.Track).all()" not in source
    assert "existing_tracks =" not in source
    assert "release_seen" not in source
    assert "recording_seen" not in source
    assert "tracks_by_exact_paths" in source
    assert "collect_music_scan_identity_diagnostics" in source


def case_b_exact_path_lookup_chunked(tmp: Path) -> None:
    engine, Session = make_db(tmp, "chunked")
    db = Session()
    try:
        paths = []
        for index in range(7):
            path = f"C:/chunked/{index}.mp3"
            paths.append(path)
            db.add(models.Track(path=path, relative_path=path, title=f"Song {index}", artist="A", album="B", album_artist="A"))
        db.commit()
        selects = {"tracks": 0}

        def count_select(conn, cursor, statement, parameters, context, executemany):
            if statement.lower().lstrip().startswith("select") and "tracks" in statement.lower():
                selects["tracks"] += 1

        event.listen(engine, "before_cursor_execute", count_select)
        try:
            found = tracks_by_exact_paths(db, paths=paths + paths[:2], chunk_size=3)
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert set(found) == set(paths)
        assert selects["tracks"] == 3, selects
    finally:
        db.close()
        engine.dispose()


def case_c_large_db_small_scan(tmp: Path) -> None:
    engine, Session = create_temp_engine(tmp / "large_small.db")
    db = Session()
    try:
        build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=10_000))
        with temporary_settings():
            roots = configure_roots(tmp / "large_small_roots")
            files = [write_media(roots["mp3"] / "Incremental" / f"{index:02d} Incremental {index:02d}.mp3") for index in range(50)]
            loaded = {"tracks": 0}

            def count_track_load(target, context):
                loaded["tracks"] += 1

            event.listen(models.Track, "load", count_track_load)
            try:
                result = scan(db, {path.name: meta(path, title=f"Incremental {index:02d}", artist="Incremental", album="Batch") for index, path in enumerate(files)})
            finally:
                event.remove(models.Track, "load", count_track_load)
            assert result["status"] == "ok", result
            assert result["tracks_scanned"] == 50
            assert result["tracks_added"] == 50
            assert result["scan_path_batches"] == 1
            assert result["exact_path_tracks_loaded"] == 0
            assert loaded["tracks"] < 500, loaded
    finally:
        db.close()
        engine.dispose()


def case_d_e_f_exact_path_lifecycle(tmp: Path) -> None:
    _, Session = make_db(tmp, "lifecycle")
    with temporary_settings():
        roots = configure_roots(tmp / "lifecycle_roots")
        original = write_media(roots["mp3"] / "Artist" / "Album" / "01 - Same.mp3")
        new_path = write_media(roots["mp3"] / "Artist" / "Album" / "02 - New.mp3")
        db = Session()
        try:
            result = scan(db, {original.name: meta(original, title="Same")})
            first = track_by_path(db, original)
            db.add(models.TrackFavorite(track_id=first.id))
            db.commit()
            first.library_availability = LIBRARY_UNAVAILABLE
            db.commit()
            result = scan(db, {original.name: meta(original, title="Same"), new_path.name: meta(new_path, title="New")})
            restored = track_by_path(db, original)
            added = track_by_path(db, new_path)
            assert result["status"] == "ok", result
            assert restored.id == first.id
            assert restored.library_availability == LIBRARY_AVAILABLE
            assert db.query(models.TrackFavorite).filter_by(track_id=first.id).count() == 1
            assert added.id != restored.id
        finally:
            db.close()


def case_g_h_identity_diagnostics(tmp: Path) -> None:
    _, Session = make_db(tmp, "diagnostics")
    with temporary_settings():
        roots = configure_roots(tmp / "diagnostics_roots")
        flac = write_media(roots["flac"] / "Artist" / "Album" / "01 - Song.flac")
        mp3 = write_media(roots["mp3"] / "Artist" / "Album" / "01 - Song.mp3")
        single = write_media(roots["flac"] / "Artist" / "Single" / "01 - Song.flac")
        db = Session()
        try:
            result = scan(db, {
                flac.name: meta(flac, title="Song", album="Album", codec="flac", lossless=True),
                mp3.name: meta(mp3, title="Song", album="Album"),
                str(single): meta(single, title="Song", album="Single", codec="flac", lossless=True),
            })
            assert result["status"] == "ok", result
            assert result["physical_sources_preserved"] >= 1
            assert result["duplicates_suspected"] >= 1
            assert any(item["type"] == "physical_source_preserved" and "recording_id" in item for item in result["duplicate_warnings"])
            assert any(item["type"] == "recording_duplicate_detected" and "release_id" in item for item in result["duplicate_warnings"])
            assert db.query(models.Track).count() == 3
            assert len({link_for(db, track_by_path(db, path)).recording_id for path in [flac, mp3, single]}) == 1
        finally:
            db.close()


def case_j_k_l_diagnostic_bounds(tmp: Path) -> None:
    engine, Session = make_db(tmp, "diagnostic_bounds")
    db = Session()
    try:
        release = models.MusicRelease(identity_key="shared-release", album_artist="A", title="B", normalized_album_artist="a", normalized_title="b")
        cross_release = models.MusicRelease(identity_key="cross-release", album_artist="A", title="Single", normalized_album_artist="a", normalized_title="single")
        recording = models.MusicRecording(identity_key="shared-recording", artist="A", title="Song", normalized_artist="a", normalized_title="song", recording_type="unknown", duration_bucket="180")
        db.add_all([release, cross_release, recording])
        db.flush()
        affected_ids = []
        for index in range(MAX_DUPLICATE_WARNING_SAMPLES + 40):
            rel_id = release.id if index % 2 == 0 else cross_release.id
            track = add_identity_track(db, path=f"C:/bounds/{index}.mp3", title="Song", artist="A", album="B", recording_id=recording.id, release_id=rel_id)
            affected_ids.append(track.id)
        db.commit()
        selects = {"diagnostic": 0}

        def count_select(conn, cursor, statement, parameters, context, executemany):
            lowered = statement.lower()
            if lowered.lstrip().startswith("select") and "music_track_identities" in lowered:
                selects["diagnostic"] += 1

        event.listen(engine, "before_cursor_execute", count_select)
        try:
            result = collect_music_scan_identity_diagnostics(db, track_ids=affected_ids[:120])
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert result["physical_sources_preserved"] > 0
        assert result["duplicates_suspected"] > 0
        assert len(result["duplicate_warnings"]) <= MAX_DUPLICATE_WARNING_SAMPLES
        assert result["duplicate_warnings_truncated"] is False or len(result["duplicate_warnings"]) == MAX_DUPLICATE_WARNING_SAMPLES
        keys = {(item["type"], item["existing_id"], item["candidate_path"], item.get("recording_id"), item.get("release_id")) for item in result["duplicate_warnings"]}
        assert len(keys) == len(result["duplicate_warnings"])
        assert selects["diagnostic"] <= 4, selects
    finally:
        db.close()
        engine.dispose()


def case_n_o_p_q_preference_and_reconciliation(tmp: Path) -> None:
    _, Session = make_db(tmp, "preference_reconcile")
    with temporary_settings():
        roots = configure_roots(tmp / "preference_reconcile_roots")
        keep = write_media(roots["mp3"] / "Artist" / "Album" / "01 - Keep.mp3")
        missing = write_media(roots["flac"] / "Artist" / "Album" / "01 - Missing.flac")
        outside = Path("C:/outside/root/Outside.mp3")
        db = Session()
        original_eval = music_scanner.evaluate_music_recording_preferences
        try:
            scan(db, {keep.name: meta(keep, title="Song"), missing.name: meta(missing, title="Song", codec="flac", lossless=True)})
            missing_track = track_by_path(db, missing)
            outside_track = models.Track(path=str(outside), relative_path=str(outside), title="Outside", artist="Artist", album="Album", album_artist="Artist", library_availability=LIBRARY_AVAILABLE)
            db.add(outside_track)
            db.commit()
            missing.unlink()

            def broken_eval(db_arg, *, recording_ids=None):
                assert recording_ids is not None
                raise RuntimeError("forced preference failure")

            music_scanner.evaluate_music_recording_preferences = broken_eval
            failed = scan(db, {keep.name: meta(keep, title="Song")})
            assert failed["status"] == "failed", failed
            assert track_by_path(db, missing).library_availability == LIBRARY_AVAILABLE
            assert db.get(models.Track, outside_track.id).library_availability == LIBRARY_AVAILABLE
        finally:
            music_scanner.evaluate_music_recording_preferences = original_eval
            db.close()


def case_r_s_t_u_benchmark_contract(tmp: Path) -> None:
    engine, Session = create_temp_engine(tmp / "benchmark_contract.db")
    db = Session()
    try:
        summary = build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=1000))
        ctx = BenchmarkContext(db=db, engine=engine, temp_root=tmp / "benchmark_contract", summary=summary)
        metrics = run_benchmarks(ctx, iterations=1, warmups=0, include_scanner=True, include_station_observation=False)
        names = {metric["name"] for metric in metrics}
        assert "scanner.incremental.50" in names
        assert "scanner.startup_state" in names
        startup = next(metric for metric in metrics if metric["name"] == "scanner.startup_state")
        assert startup["rows_returned"] > 0
        assert startup["result_checksum"]
        assert startup["sql"]["select_count"] >= 1
        assert "candidate-scoped" in startup["notes"]
        incremental = next(metric for metric in metrics if metric["name"] == "scanner.incremental.50")
        assert incremental["rows_returned"] > 0
        assert incremental["result_checksum"]
        assert incremental["sql"]["insert_count"] >= 1
    finally:
        db.close()
        engine.dispose()


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod3_2_scanner_index_optimization"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        case_a_structural_guard()
        case_b_exact_path_lookup_chunked(tmp)
        case_c_large_db_small_scan(tmp)
        case_d_e_f_exact_path_lifecycle(tmp)
        case_g_h_identity_diagnostics(tmp)
        case_j_k_l_diagnostic_bounds(tmp)
        case_n_o_p_q_preference_and_reconciliation(tmp)
        case_r_s_t_u_benchmark_contract(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD3.2 scanner candidate-scoped index optimization")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())