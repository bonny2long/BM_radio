from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import shutil
import sys
import types
from typing import Any, Iterator

from sqlalchemy import create_engine, event, inspect as sqlalchemy_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.config import settings
from app.music_identity_graph import materialize_music_identity_graph
from app.music_technical_profile import technical_profile_from_media, upsert_music_technical_profiles
from app.scan_runs import LIBRARY_AVAILABLE
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


class FakeInfo:
    def __init__(self, *, codec: str | None = None, sample_rate: int | None = None, bits_per_sample: int | None = None, bitrate: int | None = None, channels: int | None = None, length: float | None = 180.0):
        self.codec = codec
        self.sample_rate = sample_rate
        self.bits_per_sample = bits_per_sample
        self.bitrate = bitrate
        self.channels = channels
        self.length = length


class FakeMedia:
    def __init__(self, info: FakeInfo, tags: dict[str, Any] | None = None, mime: list[str] | None = None):
        self.info = info
        self.tags = tags or {}
        self.mime = mime or []


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


def write_media(path: Path, data: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if data is not None else b"technical fixture")
    return path


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def scan(db):
    result = music_scanner.scan_music(db)
    assert result["scan_run_id"], result
    db.expire_all()
    return result, db.get(models.ScanRun, result["scan_run_id"])


def track_by_path(db, path: Path) -> models.Track:
    row = db.query(models.Track).filter_by(path=str(path)).one_or_none()
    assert row is not None, str(path)
    return row


def profile_for(db, track: models.Track) -> models.MusicTechnicalProfile:
    return db.query(models.MusicTechnicalProfile).filter_by(track_id=track.id).one()


def link_for(db, track: models.Track) -> models.MusicTrackIdentity:
    return db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).one()


@contextmanager
def patched_read_metadata(mapping: dict[str, dict[str, Any]]):
    original = music_scanner.read_metadata
    def fake(path: Path):
        return mapping[path.name]
    try:
        music_scanner.read_metadata = fake
        yield
    finally:
        music_scanner.read_metadata = original


def profile(path: Path, media: FakeMedia | None = None, error: BaseException | str | None = None) -> dict[str, Any]:
    return technical_profile_from_media(path, media, error=error)


def add_track(db, i: int) -> models.Track:
    row = models.Track(path=f"C:/profiles/{i}.mp3", relative_path=f"profiles/{i}.mp3", title=f"Song {i}", artist="Artist", album="Album", album_artist="Artist", duration_seconds=180, file_ext=".mp3", library_availability=LIBRARY_AVAILABLE)
    db.add(row)
    db.flush()
    return row


def case_a_schema(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_a")
    inspector = sqlalchemy_inspect(engine)
    assert "music_technical_profiles" in inspector.get_table_names()
    indexes = {tuple(index["column_names"]) for index in inspector.get_indexes("music_technical_profiles")}
    assert ("track_id",) in indexes
    assert ("probe_status",) in indexes
    assert ("codec",) in indexes
    assert ("is_lossless",) in indexes
    db = Session()
    try:
        track = add_track(db, 1)
        db.add_all([
            models.MusicTechnicalProfile(track_id=track.id, probe_status="ok", codec="mp3"),
            models.MusicTechnicalProfile(track_id=track.id, probe_status="ok", codec="mp3"),
        ])
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("track_id unique constraint missing")
    finally:
        db.close()
        engine.dispose()


def case_b_to_k_probe_normalization(tmp: Path) -> None:
    flac_hi = write_media(tmp / "hi.flac", b"123456789")
    row = profile(flac_hi, FakeMedia(FakeInfo(codec="FLAC", sample_rate=96000, bits_per_sample=24, channels=2), mime=["audio/flac"]))
    assert row["codec"] == "flac" and row["container"] == "flac" and row["is_lossless"] is True
    assert row["sample_rate_hz"] == 96000 and row["bit_depth_bits"] == 24 and row["channel_count"] == 2
    assert row["probe_status"] == "ok"

    flac_cd = write_media(tmp / "cd.flac")
    row = profile(flac_cd, FakeMedia(FakeInfo(codec="FLAC", sample_rate=44100, bits_per_sample=16, channels=2)))
    assert row["sample_rate_hz"] == 44100 and row["bit_depth_bits"] == 16 and row["is_lossless"] is True
    assert "quality_score" not in row

    mp3 = write_media(tmp / "song.mp3")
    row = profile(mp3, FakeMedia(FakeInfo(codec="MP3", sample_rate=44100, bitrate=320000, channels=2)))
    assert row["codec"] == "mp3" and row["is_lossless"] is False and row["bitrate_bps"] == 320000

    aac = write_media(tmp / "aac.m4a")
    alac = write_media(tmp / "alac.m4a")
    ambiguous = write_media(tmp / "ambiguous.m4a")
    assert profile(aac, FakeMedia(FakeInfo(codec="AAC", sample_rate=44100, bitrate=256000, channels=2)))["is_lossless"] is False
    alac_row = profile(alac, FakeMedia(FakeInfo(codec="ALAC", sample_rate=48000, bits_per_sample=24, channels=2)))
    assert alac_row["codec"] == "alac" and alac_row["container"] == "mp4" and alac_row["is_lossless"] is True
    ambiguous_row = profile(ambiguous, FakeMedia(FakeInfo(sample_rate=44100, channels=2)))
    assert ambiguous_row["codec"] == "unknown" and ambiguous_row["is_lossless"] is None and ambiguous_row["probe_status"] == "partial"

    wav = write_media(tmp / "pcm.wav")
    wav_row = profile(wav, FakeMedia(FakeInfo(codec="PCM", sample_rate=48000, bits_per_sample=24, channels=2)))
    assert wav_row["container"] == "wav" and wav_row["codec"] == "pcm" and wav_row["is_lossless"] is True

    rg = profile(write_media(tmp / "rg.flac"), FakeMedia(FakeInfo(codec="FLAC", sample_rate=44100, bits_per_sample=16, channels=2), tags={
        "replaygain_track_gain": "-7.23 dB",
        "replaygain_album_gain": "+1.50 dB",
        "replaygain_track_peak": "0.987654",
        "replaygain_album_peak": "not-a-number",
    }))
    assert rg["replaygain_track_gain_db"] == -7.23
    assert rg["replaygain_album_gain_db"] == 1.50
    assert rg["replaygain_track_peak"] == 0.987654
    assert rg["replaygain_album_peak"] is None

    failed = profile(write_media(tmp / "broken.mp3"), None, error=RuntimeError("secret path should not be stored"))
    assert failed["probe_status"] == "failed"
    assert failed["probe_error_code"] == "RuntimeError"
    assert "secret" not in failed["probe_error_code"]

    partial = profile(write_media(tmp / "partial.ogg"), FakeMedia(FakeInfo(codec="Vorbis")))
    assert partial["probe_status"] == "partial"
    assert partial["sample_rate_hz"] is None and partial["bitrate_bps"] is None

    sized = write_media(tmp / "sized.flac", b"12345")
    before = digest(sized)
    assert profile(sized, FakeMedia(FakeInfo(codec="FLAC", sample_rate=44100, bits_per_sample=16, channels=2)))["file_size_bytes"] == 5
    assert digest(sized) == before


def case_l_single_open_scanner(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_l")
    with temporary_settings():
        roots = configure_roots(tmp / "case_l_roots")
        media_file = write_media(roots["flac"] / "Artist" / "Album" / "01 - One.flac")
        calls = {"count": 0}
        fake_module = types.SimpleNamespace()
        def fake_file(path: Path, easy: bool = True):
            calls["count"] += 1
            return FakeMedia(FakeInfo(codec="FLAC", sample_rate=44100, bits_per_sample=16, channels=2), tags={"title": "One", "artist": "Artist", "album": "Album", "albumartist": "Artist"})
        fake_module.File = fake_file
        old_mutagen = sys.modules.get("mutagen")
        sys.modules["mutagen"] = fake_module
        db = Session()
        try:
            result, _ = scan(db)
            assert result["status"] == "ok", result
            assert calls["count"] == 1
            track = track_by_path(db, media_file)
            assert profile_for(db, track).codec == "flac"
            assert result["technical_probe_ok"] == 1
        finally:
            if old_mutagen is None:
                sys.modules.pop("mutagen", None)
            else:
                sys.modules["mutagen"] = old_mutagen
            db.close()
            engine.dispose()


def case_m_to_q_scanner_integration(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_mq")
    with temporary_settings():
        roots = configure_roots(tmp / "case_mq_roots")
        flac = write_media(roots["flac"] / "Artist" / "Album" / "01 - Shared.flac")
        mp3 = write_media(roots["mp3"] / "Artist" / "Album" / "01 - Shared.mp3")
        bad = write_media(roots["flac"] / "Bad" / "Album" / "01 - Bad.flac")
        mapping = {
            flac.name: {"duration_seconds": 180, "title": "Shared", "artist": "Artist", "album": "Album", "album_artist": "Artist", "technical": profile(flac, FakeMedia(FakeInfo(codec="FLAC", sample_rate=96000, bits_per_sample=24, channels=2)))},
            mp3.name: {"duration_seconds": 180, "title": "Shared", "artist": "Artist", "album": "Album", "album_artist": "Artist", "technical": profile(mp3, FakeMedia(FakeInfo(codec="MP3", sample_rate=44100, bitrate=320000, channels=2)))},
            bad.name: {"duration_seconds": 100, "title": "Bad", "artist": "Bad", "album": "Album", "album_artist": "Bad", "technical": profile(bad, None, error="UnreadableMedia")},
        }
        db = Session()
        try:
            with patched_read_metadata(mapping):
                result, run = scan(db)
                assert result["status"] == "ok", result
                assert run.status == "succeeded"
                assert db.query(models.Track).count() == 3
                assert db.query(models.MusicTechnicalProfile).count() == 3
                assert db.query(models.MusicTrackIdentity).count() == 3
                assert result["technical_profiles_updated"] == 3
                assert result["technical_probe_ok"] == 2
                assert result["technical_probe_failed"] == 1
                flac_track = track_by_path(db, flac)
                mp3_track = track_by_path(db, mp3)
                bad_track = track_by_path(db, bad)
                assert profile_for(db, flac_track).id
                assert profile_for(db, bad_track).probe_status == "failed"
                assert link_for(db, flac_track).recording_id == link_for(db, mp3_track).recording_id
                assert not hasattr(models.MusicTechnicalProfile, "quality_score")
                assert not hasattr(models.MusicTechnicalProfile, "preferred_track_id")
                first_profile_id = profile_for(db, flac_track).id
                first_link_id = link_for(db, flac_track).id
                with patched_read_metadata(mapping):
                    scan(db)
                assert track_by_path(db, flac).id == flac_track.id
                assert profile_for(db, track_by_path(db, flac)).id == first_profile_id
                assert link_for(db, track_by_path(db, flac)).id == first_link_id
                refreshed = dict(mapping)
                refreshed[flac.name] = {**refreshed[flac.name], "technical": profile(flac, FakeMedia(FakeInfo(codec="FLAC", sample_rate=44100, bits_per_sample=16, channels=2)))}
                db.add_all([models.TrackFavorite(track_id=flac_track.id), models.TrackThumb(track_id=flac_track.id, value=models.ThumbValue.up), models.PlaybackEvent(track_id=flac_track.id, event_type="qualified_play")])
                playlist = models.Playlist(name="State", kind="manual")
                db.add(playlist)
                db.flush()
                db.add(models.PlaylistTrack(playlist_id=playlist.id, track_id=flac_track.id, position=1))
                db.commit()
                with patched_read_metadata(refreshed):
                    scan(db)
                assert profile_for(db, track_by_path(db, flac)).id == first_profile_id
                assert profile_for(db, track_by_path(db, flac)).sample_rate_hz == 44100
                assert db.query(models.TrackFavorite).filter_by(track_id=flac_track.id).count() == 1
                assert db.query(models.TrackThumb).filter_by(track_id=flac_track.id).count() == 1
                assert db.query(models.PlaybackEvent).filter_by(track_id=flac_track.id).count() == 1
                assert db.query(models.PlaylistTrack).filter_by(track_id=flac_track.id).count() == 1
        finally:
            db.close()


def case_r_s_failure_and_lifecycle(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_rs")
    with temporary_settings():
        roots = configure_roots(tmp / "case_rs_roots")
        present = write_media(roots["flac"] / "Artist" / "Album" / "01 - Present.flac")
        absent = roots["flac"] / "Artist" / "Album" / "02 - Absent.flac"
        db = Session()
        original_upsert = music_scanner.upsert_music_technical_profiles
        try:
            db.add(models.Track(path=str(absent), relative_path="Library/FLAC/Artist/Album/02 - Absent.flac", title="Absent", artist="Artist", album="Album", album_artist="Artist", library_availability=LIBRARY_AVAILABLE))
            db.commit()
            music_scanner.upsert_music_technical_profiles = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("forced profile db failure"))
            with patched_read_metadata({present.name: {"duration_seconds": 100, "title": "Present", "artist": "Artist", "album": "Album", "album_artist": "Artist", "technical": profile(present, FakeMedia(FakeInfo(codec="FLAC", sample_rate=44100, bits_per_sample=16, channels=2)))}}):
                result, run = scan(db)
            assert result["status"] == "failed", result
            assert run.status == "failed"
            assert result["tracks_unavailable"] == 0
            assert track_by_path(db, absent).library_availability == LIBRARY_AVAILABLE
        finally:
            music_scanner.upsert_music_technical_profiles = original_upsert
            db.close()

    _, Session2 = make_db(tmp, "case_s")
    with temporary_settings():
        roots = configure_roots(tmp / "case_s_roots")
        media = write_media(roots["flac"] / "Artist" / "Album" / "01 - Return.flac")
        mapping = {media.name: {"duration_seconds": 100, "title": "Return", "artist": "Artist", "album": "Album", "album_artist": "Artist", "technical": profile(media, FakeMedia(FakeInfo(codec="FLAC", sample_rate=44100, bits_per_sample=16, channels=2)))}}
        db2 = Session2()
        try:
            with patched_read_metadata(mapping):
                scan(db2)
            track = track_by_path(db2, media)
            profile_id = profile_for(db2, track).id
            link_id = link_for(db2, track).id
            media.unlink()
            with patched_read_metadata(mapping):
                scan(db2)
            unavailable = track_by_path(db2, media)
            assert unavailable.library_availability == "unavailable"
            assert profile_for(db2, unavailable).id == profile_id
            assert link_for(db2, unavailable).id == link_id
            write_media(media)
            with patched_read_metadata(mapping):
                scan(db2)
            restored = track_by_path(db2, media)
            assert restored.id == track.id
            assert profile_for(db2, restored).id == profile_id
            assert link_for(db2, restored).id == link_id
        finally:
            db2.close()


def case_u_v_w_batch_and_non_goals(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_uvw")
    db = Session()
    try:
        tracks = [add_track(db, i) for i in range(125)]
        db.commit()
        profiles = {track.id: {"probe_status": "ok", "probe_source": "mutagen", "probe_version": 1, "codec": "mp3", "container": "mp3", "is_lossless": False, "bitrate_bps": 320000} for track in tracks}
        select_count = {"profiles": 0}
        def count_select(conn, cursor, statement, parameters, context, executemany):
            lowered = statement.lower()
            if lowered.lstrip().startswith("select") and "music_technical_profiles" in lowered:
                select_count["profiles"] += 1
        event.listen(engine, "before_cursor_execute", count_select)
        try:
            result = upsert_music_technical_profiles(db, profiles)
            db.commit()
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert result["profiles_seen"] == 125
        assert db.query(models.MusicTechnicalProfile).count() == 125
        assert select_count["profiles"] < 10, select_count
        assert not hasattr(models.MusicTechnicalProfile, "quality_score")
        assert not hasattr(models.MusicTechnicalProfile, "preferred_track_id")
        assert not hasattr(models.MusicEdition, "preferred_track_id")
        assert not hasattr(models.MusicRecording, "preferred_track_id")
        fixture = write_media(tmp / "unchanged.flac", b"do not change")
        before = digest(fixture)
        technical_profile_from_media(fixture, FakeMedia(FakeInfo(codec="FLAC", sample_rate=44100, bits_per_sample=16, channels=2)))
        assert digest(fixture) == before
        materialize_music_identity_graph(db, track_ids=[track.id for track in tracks[:2]])
        assert db.query(models.MusicTrackIdentity).count() == 2
    finally:
        db.close()
        engine.dispose()


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4b1_music_technical_profile"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_schema(tmp)
        case_b_to_k_probe_normalization(tmp)
        case_l_single_open_scanner(tmp)
        case_m_to_q_scanner_integration(tmp)
        case_r_s_failure_and_lifecycle(tmp)
        case_u_v_w_batch_and_non_goals(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.4B1 objective music technical profile foundation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())