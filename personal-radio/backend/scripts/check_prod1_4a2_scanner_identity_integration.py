from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import inspect
import shutil
import sys
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models, music_identity_graph
from app.config import settings
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


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


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


def write_media(path: Path, data: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if data is not None else b"synthetic music bytes")
    return path


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


@contextmanager
def patched_metadata(mapping: dict[str, dict], manifests: dict[str, str | None] | None = None):
    original_read = music_scanner.read_metadata
    original_manifest = music_scanner.extract_music_manifest_metadata
    manifests = manifests or {}

    def fake_read(path: Path):
        value = mapping.get(path.name) or mapping.get(path.stem) or {}
        return {"duration_seconds": None, **value}

    def fake_manifest(context, path: Path):
        if path.name not in manifests:
            return {}
        return {"metadata_source": "archive_assistant_manifest", "source_manifest_path": manifests[path.name]}

    try:
        music_scanner.read_metadata = fake_read
        music_scanner.extract_music_manifest_metadata = fake_manifest
        yield
    finally:
        music_scanner.read_metadata = original_read
        music_scanner.extract_music_manifest_metadata = original_manifest


def scan(db):
    result = music_scanner.scan_music(db)
    assert result["scan_run_id"], result
    db.expire_all()
    return result, db.get(models.ScanRun, result["scan_run_id"])


def track_by_path(db, path: Path) -> models.Track:
    row = db.query(models.Track).filter_by(path=str(path)).one_or_none()
    assert row is not None, str(path)
    return row


def link_for(db, track: models.Track) -> models.MusicTrackIdentity:
    return db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).one()


def add_track(db, i: int, *, album: str = "Batch Album") -> models.Track:
    row = models.Track(
        path=f"C:/synthetic/Artist/{album}/{i:03d}.mp3",
        relative_path=f"Library/MP3/Artist/{album}/{i:03d}.mp3",
        title=f"Song {i}",
        artist="Batch Artist",
        album=album,
        album_artist="Batch Artist",
        duration_seconds=180 + i,
        file_ext=".mp3",
        library_availability=LIBRARY_AVAILABLE,
    )
    db.add(row)
    db.flush()
    return row


def case_a_b_c_d_identity_and_physical_preservation(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_abcd")
    with temporary_settings():
        roots = configure_roots(tmp / "case_abcd_roots")
        flac = write_media(roots["flac"] / "Graph Artist" / "2020 - Graph Album" / "01 - Shared Song.flac", b"flac bytes")
        mp3 = write_media(roots["mp3"] / "Graph Artist" / "2020 - Graph Album" / "01 - Shared Song.mp3", b"mp3 bytes")
        metadata = {
            flac.name: {"title": "Shared Song", "artist": "Graph Artist", "album": "Graph Album", "album_artist": "Graph Artist", "duration_seconds": 180},
            mp3.name: {"title": "Shared Song", "artist": "Graph Artist", "album": "Graph Album", "album_artist": "Graph Artist", "duration_seconds": 180},
        }
        db = Session()
        try:
            with patched_metadata(metadata):
                result, scan_run = scan(db)
                assert result["status"] == "ok", result
                assert scan_run.status == "succeeded"
                assert result["tracks_added"] == 2
                assert result["duplicates_skipped"] == 0
                assert result["physical_sources_preserved"] >= 1
                assert result["identity_tracks_materialized"] == 2
                assert db.query(models.Track).count() == 2
                assert db.query(models.MusicTrackIdentity).count() == 2
                assert db.query(models.MusicRelease).count() == 1
                assert db.query(models.MusicEdition).count() == 2
                assert db.query(models.MusicRecording).count() == 1
                assert not hasattr(models.MusicEdition, "preferred_track_id")
                assert not hasattr(models.MusicRecording, "preferred_track_id")
                flac_track = track_by_path(db, flac)
                mp3_track = track_by_path(db, mp3)
                flac_link = link_for(db, flac_track)
                mp3_link = link_for(db, mp3_track)
                first_ids = (flac_track.id, mp3_track.id, flac_link.id, mp3_link.id)
                result2, scan_run2 = scan(db)
                assert result2["tracks_added"] == 0
                assert result2["tracks_updated"] == 2
                assert result2["identity_tracks_materialized"] == 2
                assert track_by_path(db, flac).id == first_ids[0]
                assert track_by_path(db, mp3).id == first_ids[1]
                assert link_for(db, track_by_path(db, flac)).id == first_ids[2]
                assert link_for(db, track_by_path(db, mp3)).id == first_ids[3]
                assert track_by_path(db, flac).last_seen_scan_id == scan_run2.id
        finally:
            db.close()


def case_e_f_g_same_edition_aggregates(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_efg")
    with temporary_settings():
        roots = configure_roots(tmp / "case_efg_roots")
        a = write_media(roots["flac"] / "Mix Artist" / "Mix Album" / "01 - One.flac")
        b = write_media(roots["flac"] / "Mix Artist" / "Mix Album" / "02 - Two.mp3")
        metadata = {
            a.name: {"title": "One", "artist": "Mix Artist", "album": "Mix Album", "album_artist": "Mix Artist", "duration_seconds": 100},
            b.name: {"title": "Two", "artist": "Mix Artist", "album": "Mix Album", "album_artist": "Mix Artist", "duration_seconds": 110},
        }
        db = Session()
        try:
            with patched_metadata(metadata, {a.name: "shared-manifest.json", b.name: "shared-manifest.json"}):
                result, _ = scan(db)
                assert result["status"] == "ok", result
                assert db.query(models.MusicEdition).count() == 1
                edition = db.query(models.MusicEdition).one()
                assert edition.source_format_family == "MIXED"
                assert edition.source_manifest_path == "shared-manifest.json"
            db.close()

            # Conflicting manifest order must converge to neutral None.
            _, Session2 = make_db(tmp, "case_efg_conflict")
            db2 = Session2()
            roots2 = configure_roots(tmp / "case_efg_conflict_roots")
            c = write_media(roots2["flac"] / "Mix Artist" / "Mix Album" / "01 - One.flac")
            d = write_media(roots2["flac"] / "Mix Artist" / "Mix Album" / "02 - Two.mp3")
            with patched_metadata(metadata, {c.name: "manifest-a.json", d.name: "manifest-b.json"}):
                scan(db2)
                edition2 = db2.query(models.MusicEdition).one()
                assert edition2.source_format_family == "MIXED"
                assert edition2.source_manifest_path is None
            db2.close()
        finally:
            pass


def case_h_i_album_single_and_alternates(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_hi")
    with temporary_settings():
        roots = configure_roots(tmp / "case_hi_roots")
        files = [
            write_media(roots["flac"] / "Artist" / "Album" / "01 - Song.flac"),
            write_media(roots["flac"] / "Artist" / "Song Single" / "01 - Song.flac"),
            write_media(roots["flac"] / "Artist" / "Live" / "01 - Song Live.flac"),
            write_media(roots["flac"] / "Artist" / "Acoustic" / "01 - Song Acoustic.flac"),
            write_media(roots["flac"] / "Artist" / "Remix" / "01 - Song Remix.flac"),
            write_media(roots["flac"] / "Artist" / "Instrumental" / "01 - Song Instrumental.flac"),
            write_media(roots["flac"] / "Artist" / "Radio Edit" / "01 - Song Radio Edit.flac"),
        ]
        metadata = {
            files[0].name: {"title": "Song", "artist": "Artist", "album": "Album", "album_artist": "Artist", "duration_seconds": 200},
            files[1].name: {"title": "Song", "artist": "Artist", "album": "Song Single", "album_artist": "Artist", "duration_seconds": 200},
            files[2].name: {"title": "Song (Live)", "artist": "Artist", "album": "Live", "album_artist": "Artist", "duration_seconds": 200},
            files[3].name: {"title": "Song (Acoustic)", "artist": "Artist", "album": "Acoustic", "album_artist": "Artist", "duration_seconds": 200},
            files[4].name: {"title": "Song (Remix)", "artist": "Artist", "album": "Remix", "album_artist": "Artist", "duration_seconds": 200},
            files[5].name: {"title": "Song (Instrumental)", "artist": "Artist", "album": "Instrumental", "album_artist": "Artist", "duration_seconds": 200},
            files[6].name: {"title": "Song (Radio Edit)", "artist": "Artist", "album": "Radio Edit", "album_artist": "Artist", "duration_seconds": 200},
        }
        db = Session()
        try:
            with patched_metadata(metadata):
                scan(db)
                album_link = link_for(db, track_by_path(db, files[0]))
                single_link = link_for(db, track_by_path(db, files[1]))
                assert album_link.recording_id == single_link.recording_id
                assert album_link.edition.release_id != single_link.edition.release_id
                recording_types = {link_for(db, track_by_path(db, path)).recording.recording_type for path in files[2:]}
                assert recording_types == {"live", "acoustic", "remix", "instrumental", "radio_edit"}
                assert len({link_for(db, track_by_path(db, path)).recording_id for path in files}) == 6
        finally:
            db.close()


def case_j_k_l_unavailable_lifecycle(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_jkl")
    with temporary_settings():
        roots = configure_roots(tmp / "case_jkl_roots")
        old = roots["mp3"] / "Artist" / "Album" / "01 - Same.mp3"
        new = write_media(roots["flac"] / "Artist" / "Album" / "01 - Same.flac")
        metadata = {new.name: {"title": "Same", "artist": "Artist", "album": "Album", "album_artist": "Artist", "duration_seconds": 180}}
        db = Session()
        try:
            db.add(models.Track(path=str(old), relative_path="Library/MP3/Artist/Album/01 - Same.mp3", title="Same", artist="Artist", album="Album", album_artist="Artist", duration_seconds=180, file_ext=".mp3", library_availability=LIBRARY_UNAVAILABLE))
            db.commit()
            with patched_metadata(metadata):
                scan(db)
                assert db.query(models.Track).count() == 2
                assert link_for(db, track_by_path(db, new)) is not None
                new_track = track_by_path(db, new)
                new_link = link_for(db, new_track)
                new.unlink()
                scan(db)
                missing = track_by_path(db, new)
                assert missing.id == new_track.id
                assert missing.library_availability == LIBRARY_UNAVAILABLE
                assert link_for(db, missing).id == new_link.id
                assert db.query(models.MusicEdition).count() >= 1
                assert db.query(models.MusicRelease).count() >= 1
                assert db.query(models.MusicRecording).count() >= 1
                write_media(new)
                scan(db)
                restored = track_by_path(db, new)
                assert restored.id == new_track.id
                assert restored.library_availability == LIBRARY_AVAILABLE
                assert link_for(db, restored).id == new_link.id
        finally:
            db.close()


def case_m_metadata_rebind_preserves_state(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_m")
    with temporary_settings():
        roots = configure_roots(tmp / "case_m_roots")
        media = write_media(roots["flac"] / "Artist" / "Album" / "01 - Mutable.flac")
        first_meta = {media.name: {"title": "Before", "artist": "Artist", "album": "Album", "album_artist": "Artist", "duration_seconds": 120}}
        second_meta = {media.name: {"title": "After", "artist": "Artist", "album": "Album", "album_artist": "Artist", "duration_seconds": 120}}
        db = Session()
        try:
            with patched_metadata(first_meta):
                scan(db)
            track = track_by_path(db, media)
            link = link_for(db, track)
            db.add_all([
                models.TrackFavorite(track_id=track.id),
                models.TrackThumb(track_id=track.id, value=models.ThumbValue.up),
                models.PlaybackEvent(track_id=track.id, event_type="qualified_play"),
            ])
            playlist = models.Playlist(name="State", kind="manual")
            db.add(playlist)
            db.flush()
            db.add(models.PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=1))
            db.commit()
            old_recording_id = link.recording_id
            with patched_metadata(second_meta):
                scan(db)
            rebound = track_by_path(db, media)
            rebound_link = link_for(db, rebound)
            assert rebound.id == track.id
            assert rebound_link.id == link.id
            assert rebound_link.recording_id != old_recording_id
            assert db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).count() == 1
            assert db.query(models.TrackFavorite).filter_by(track_id=track.id).count() == 1
            assert db.query(models.TrackThumb).filter_by(track_id=track.id).count() == 1
            assert db.query(models.PlaybackEvent).filter_by(track_id=track.id).count() == 1
            assert db.query(models.PlaylistTrack).filter_by(track_id=track.id).count() == 1
        finally:
            db.close()


def case_n_o_failure_rules(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_no")
    with temporary_settings():
        roots = configure_roots(tmp / "case_no_roots")
        present = write_media(roots["flac"] / "Artist" / "Album" / "01 - Present.flac")
        absent = roots["flac"] / "Artist" / "Album" / "02 - Absent.flac"
        db = Session()
        original_materialize = music_scanner.materialize_music_identity_graph
        try:
            db.add(models.Track(path=str(absent), title="Absent", library_availability=LIBRARY_AVAILABLE))
            db.commit()
            music_scanner.materialize_music_identity_graph = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("forced identity failure"))
            with patched_metadata({present.name: {"title": "Present", "artist": "Artist", "album": "Album", "album_artist": "Artist", "duration_seconds": 100}}):
                result, run = scan(db)
            assert result["status"] == "failed", result
            assert run.status == "failed"
            assert track_by_path(db, absent).library_availability == LIBRARY_AVAILABLE
            assert db.query(models.Track).filter_by(path=str(present)).count() == 0
        finally:
            music_scanner.materialize_music_identity_graph = original_materialize
            db.close()

    _, Session2 = make_db(tmp, "case_o")
    with temporary_settings():
        roots = configure_roots(tmp / "case_o_roots")
        present = write_media(roots["flac"] / "Artist" / "Album" / "01 - Bad.flac")
        absent = roots["flac"] / "Artist" / "Album" / "02 - Absent.flac"
        db2 = Session2()
        original_read = music_scanner.read_metadata
        try:
            db2.add(models.Track(path=str(absent), title="Absent", library_availability=LIBRARY_AVAILABLE))
            db2.commit()
            def broken(path: Path):
                if path == present:
                    raise RuntimeError("forced per-file failure")
                return original_read(path)
            music_scanner.read_metadata = broken
            result, run = scan(db2)
            assert result["status"] == "failed", result
            assert run.status == "failed"
            assert track_by_path(db2, absent).library_availability == LIBRARY_AVAILABLE
        finally:
            music_scanner.read_metadata = original_read
            db2.close()


def case_p_q_r_batch_behavior(tmp: Path) -> None:
    source = inspect.getsource(music_scanner.scan_music)
    assert "materialize_music_identity_for_track" not in source
    assert "materialize_music_identity_graph" in source

    engine, Session = make_db(tmp, "case_pqr")
    db = Session()
    try:
        tracks = [add_track(db, i) for i in range(125)]
        db.commit()
        select_count = {"identity": 0}
        def count_select(conn, cursor, statement, parameters, context, executemany):
            lowered = statement.lower()
            if lowered.lstrip().startswith("select") and any(name in lowered for name in ["music_releases", "music_editions", "music_recordings", "music_track_identities"]):
                select_count["identity"] += 1
        event.listen(engine, "before_cursor_execute", count_select)
        try:
            music_identity_graph.materialize_music_identity_graph(db, track_ids=[track.id for track in tracks])
            db.commit()
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert db.query(models.MusicTrackIdentity).count() == 125
        assert select_count["identity"] < 40, select_count

        more = [add_track(db, 1000 + i, album="Chunk Album") for i in range(music_identity_graph.IDENTITY_BATCH_CHUNK_SIZE + 5)]
        db.commit()
        result = music_identity_graph.materialize_music_identity_graph(db, track_ids=[track.id for track in more])
        db.commit()
        assert result["tracks_seen"] == music_identity_graph.IDENTITY_BATCH_CHUNK_SIZE + 5
        assert db.query(models.MusicTrackIdentity).filter(models.MusicTrackIdentity.track_id.in_([track.id for track in more])).count() == music_identity_graph.IDENTITY_BATCH_CHUNK_SIZE + 5
    finally:
        db.close()
        engine.dispose()


def case_t_no_media_mutation(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_t")
    with temporary_settings():
        roots = configure_roots(tmp / "case_t_roots")
        media = write_media(roots["flac"] / "Artist" / "Album" / "01 - Keep.flac", b"keep exactly")
        before = digest(media)
        db = Session()
        try:
            with patched_metadata({media.name: {"title": "Keep", "artist": "Artist", "album": "Album", "album_artist": "Artist", "duration_seconds": 100}}):
                scan(db)
                scan(db)
            assert media.exists()
            assert digest(media) == before
        finally:
            db.close()


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4a2_scanner_identity_integration"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_b_c_d_identity_and_physical_preservation(tmp)
        case_e_f_g_same_edition_aggregates(tmp)
        case_h_i_album_single_and_alternates(tmp)
        case_j_k_l_unavailable_lifecycle(tmp)
        case_m_metadata_rebind_preserves_state(tmp)
        case_n_o_failure_rules(tmp)
        case_p_q_r_batch_behavior(tmp)
        case_t_no_media_mutation(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.4A2 scanner identity integration and physical-source preservation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())