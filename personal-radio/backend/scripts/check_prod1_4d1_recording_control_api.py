from __future__ import annotations

from contextlib import contextmanager
import inspect
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Iterator
from fastapi import HTTPException

from sqlalchemy import create_engine, event, inspect as sqlalchemy_inspect
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.config import settings
from app.db import get_db
from app.music_recording_participation import (
    PARTICIPATION_INCLUDED,
    clear_music_recording_participation,
    get_music_recording_participation,
    set_music_recording_participation,
)
from app.music_source_preference import evaluate_music_recording_preference, resolve_effective_music_source
from app.routes import music_recordings
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
def temporary_settings() -> Iterator[None]:
    original = {name: getattr(settings, name) for name in ROOT_SETTING_NAMES}
    try:
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


@contextmanager
def patched_read_metadata(mapping: dict[str, dict[str, Any]]):
    original = music_scanner.read_metadata

    def fake(path: Path):
        return mapping.get(str(path)) or mapping[path.name]

    try:
        music_scanner.read_metadata = fake
        yield
    finally:
        music_scanner.read_metadata = original


def scan(db, mapping: dict[str, dict[str, Any]]):
    with patched_read_metadata(mapping):
        result = music_scanner.scan_music(db)
    assert result["status"] == "ok", result
    db.expire_all()
    return result


def write_media(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"d1 synthetic media bytes")
    return path


def meta(path: Path, *, title: str = "Song", artist: str = "Artist", album: str = "Album") -> dict[str, Any]:
    ext = path.suffix.lower().lstrip(".") or "mp3"
    is_lossless = ext == "flac"
    return {
        "duration_seconds": 180.0,
        "title": title,
        "artist": artist,
        "album": album,
        "album_artist": artist,
        "technical": {
            "probe_status": "ok",
            "probe_source": "mutagen",
            "probe_version": 1,
            "codec": ext,
            "container": ext,
            "is_lossless": is_lossless,
            "sample_rate_hz": 44100,
            "bit_depth_bits": 16 if is_lossless else None,
            "bitrate_bps": None if is_lossless else 320000,
            "channel_count": 2,
            "file_size_bytes": path.stat().st_size,
        },
    }


def add_release(db, suffix: str = "main") -> models.MusicRelease:
    row = models.MusicRelease(
        identity_key=f"release-{suffix}-{db.query(models.MusicRelease).count()}",
        album_artist="Artist",
        title=f"Album {suffix}",
        normalized_album_artist="artist",
        normalized_title=f"album {suffix}",
        release_type="album",
    )
    db.add(row)
    db.flush()
    return row


def add_recording(db, title: str = "Song") -> models.MusicRecording:
    row = models.MusicRecording(
        identity_key=f"recording-{title}-{db.query(models.MusicRecording).count()}",
        artist="Artist",
        title=title,
        normalized_artist="artist",
        normalized_title=title.lower(),
        recording_type="studio",
        duration_bucket="180",
    )
    db.add(row)
    db.flush()
    return row


def add_candidate(
    db,
    recording: models.MusicRecording,
    *,
    suffix: str,
    availability: str = LIBRARY_AVAILABLE,
    codec: str = "mp3",
    is_lossless: bool | None = False,
    bitrate: int | None = 320000,
    source_scope: str | None = None,
) -> models.Track:
    index = db.query(models.Track).count() + 1
    release = add_release(db, suffix)
    edition = models.MusicEdition(
        identity_key=f"edition-{recording.id}-{suffix}-{index}",
        release_id=release.id,
        display_title=f"Album {suffix}",
        year=2026,
        edition_type="standard",
        source_scope=source_scope or f"scope-{suffix}",
        source_format_family="LOSSLESS" if is_lossless else "LOSSY",
    )
    track = models.Track(
        path=f"C:/synthetic/absolute/{recording.id}/{index:03d}-{suffix}.{codec}",
        relative_path=f"Artist/Album/{index:03d}-{suffix}.{codec}",
        title=recording.title,
        artist="Artist",
        album=f"Album {suffix}",
        album_artist="Artist",
        year=2026,
        duration_seconds=180.0,
        file_ext=f".{codec}",
        track_number=index,
        disc_number=1,
        library_availability=availability,
    )
    db.add_all([edition, track])
    db.flush()
    db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=recording.id))
    db.add(models.MusicTechnicalProfile(
        track_id=track.id,
        probe_status="ok",
        codec=codec,
        container=codec,
        is_lossless=is_lossless,
        sample_rate_hz=44100,
        bit_depth_bits=16 if is_lossless else None,
        bitrate_bps=bitrate,
        channel_count=2,
        file_size_bytes=1000 + index,
        replaygain_track_gain_db=-7.5,
        replaygain_album_gain_db=-8.0,
        replaygain_track_peak=0.91,
        replaygain_album_peak=0.93,
    ))
    db.flush()
    return track


def route_call(func, *args, **kwargs):
    try:
        return 200, func(*args, **kwargs)
    except HTTPException as exc:
        return exc.status_code, exc.detail

def flatten_json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def case_a_schema(tmp: Path) -> None:
    engine, _ = make_db(tmp, "case_a")
    inspector = sqlalchemy_inspect(engine)
    raw_indexes = inspector.get_indexes("music_recording_participation")
    indexes = {tuple(index["column_names"]) for index in raw_indexes}
    unique_indexes = {tuple(index["column_names"]) for index in raw_indexes if index.get("unique")}
    uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("music_recording_participation")}
    assert ("recording_id",) in indexes
    assert ("recording_id",) in uniques or ("recording_id",) in unique_indexes
    assert ("participation_state",) in indexes
    assert ("state_source",) in indexes
    engine.dispose()


def case_b_to_e_participation_service(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_b_to_e")
    db = Session()
    try:
        rec = add_recording(db)
        default = get_music_recording_participation(db, recording_id=rec.id)
        assert default.participation_state == PARTICIPATION_INCLUDED
        assert default.explicit is False and default.state_source is None

        row = set_music_recording_participation(db, recording_id=rec.id, participation_state="library_only", reason_code=" exclude_from_radio ")
        db.commit()
        row_id = row.id
        state = get_music_recording_participation(db, recording_id=rec.id)
        assert state.explicit is True
        assert state.participation_state == "library_only"
        assert state.state_source == "user"
        assert state.reason_code == "exclude_from_radio"

        row = set_music_recording_participation(db, recording_id=rec.id, participation_state="archived", reason_code="archive_variant")
        db.commit()
        assert row.id == row_id
        assert get_music_recording_participation(db, recording_id=rec.id).participation_state == "archived"

        clear_music_recording_participation(db, recording_id=rec.id)
        db.commit()
        assert db.query(models.MusicRecordingParticipation).count() == 0
        assert get_music_recording_participation(db, recording_id=rec.id).participation_state == PARTICIPATION_INCLUDED
    finally:
        db.close()


def case_f_blocked_non_destructive(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_f")
    db = Session()
    try:
        rec = add_recording(db, "Blocked")
        track = add_candidate(db, rec, suffix="mp3")
        evaluate_music_recording_preference(db, recording_id=rec.id)
        playlist = models.Playlist(name="Keep", kind="manual")
        db.add(playlist)
        db.flush()
        db.add_all([
            models.TrackFavorite(track_id=track.id),
            models.TrackThumb(track_id=track.id, value=models.ThumbValue.up),
            models.PlaybackEvent(track_id=track.id, event_type="qualified_play"),
            models.PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=1),
        ])
        db.commit()
        before = count_state_rows(db)
        set_music_recording_participation(db, recording_id=rec.id, participation_state="blocked", reason_code="review_hold")
        db.commit()
        after = count_state_rows(db)
        assert before == after
        assert db.query(models.MusicRecordingParticipation).count() == 1
    finally:
        db.close()


def count_state_rows(db) -> dict[str, int]:
    return {
        "tracks": db.query(models.Track).count(),
        "preferences": db.query(models.MusicRecordingPreference).count(),
        "identities": db.query(models.MusicTrackIdentity).count(),
        "profiles": db.query(models.MusicTechnicalProfile).count(),
        "favorites": db.query(models.TrackFavorite).count(),
        "thumbs": db.query(models.TrackThumb).count(),
        "playlist_tracks": db.query(models.PlaylistTrack).count(),
        "playback_events": db.query(models.PlaybackEvent).count(),
    }


def case_g_to_q_api(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_g_to_q")
    db = Session()
    try:
        rec = add_recording(db, "Control")
        flac = add_candidate(db, rec, suffix="flac", codec="flac", is_lossless=True, bitrate=None, source_scope="lossless-scope")
        mp3 = add_candidate(db, rec, suffix="mp3", codec="mp3", is_lossless=False, bitrate=320000, source_scope="lossy-scope")
        evaluate_music_recording_preference(db, recording_id=rec.id)
        other = add_recording(db, "Other")
        other_track = add_candidate(db, other, suffix="other", codec="mp3", is_lossless=False)
        evaluate_music_recording_preference(db, recording_id=other.id)
        db.commit()
        rec_id = rec.id
        flac_id = flac.id
        mp3_id = mp3.id
        other_track_id = other_track.id

        status, body = route_call(music_recordings.get_recording_control, rec_id, db)
        assert status == 200, body
        assert body["recording"]["id"] == rec_id
        assert body["participation"]["state"] == "included"
        assert body["participation"]["explicit"] is False
        assert len(body["candidates"]) == 2
        assert body["preference"]["auto_preferred_track_id"] == flac_id
        assert body["effective_source"]["track_id"] == flac_id
        assert all("relative_path" in item["track"] for item in body["candidates"])
        assert all("path" not in item["track"] for item in body["candidates"])
        assert "C:/synthetic/absolute" not in flatten_json_text(body)
        assert body["candidates"][0]["track_id"] == flac_id
        technical = body["candidates"][0]["technical"]
        assert technical["probe_status"] == "ok"
        assert "replaygain_track_gain_db" in technical
        assert body["candidates"][0]["identity"]["recording_id"] == rec_id
        assert body["candidates"][0]["edition"]["source_scope"] in {"lossless-scope", "lossy-scope"}

        status, body = route_call(music_recordings.put_preferred_track, rec_id, music_recordings.PreferredTrackPayload(track_id=mp3_id), db)
        assert status == 200, body
        assert body["preference"]["user_preferred_track_id"] == mp3_id
        assert body["preference"]["auto_preferred_track_id"] == flac_id
        assert body["effective_source"]["track_id"] == mp3_id
        flags_by_track = {item["track_id"]: item["preference_flags"] for item in body["candidates"]}
        assert flags_by_track[flac_id]["is_auto_preferred"] is True
        assert flags_by_track[mp3_id]["is_user_preferred"] is True
        assert flags_by_track[mp3_id]["is_effective_source"] is True

        status, body = route_call(music_recordings.delete_preferred_track, rec_id, db)
        assert status == 200, body
        assert body["preference"]["user_preferred_track_id"] is None
        assert body["preference"]["auto_preferred_track_id"] == flac_id
        assert body["effective_source"]["track_id"] == flac_id

        status, _ = route_call(music_recordings.put_preferred_track, rec_id, music_recordings.PreferredTrackPayload(track_id=mp3_id), db)
        assert status == 200
        db.get(models.Track, mp3_id).library_availability = LIBRARY_UNAVAILABLE
        db.commit()
        status, body = route_call(music_recordings.get_recording_control, rec_id, db)
        assert status == 200
        assert body["preference"]["user_preferred_track_id"] == mp3_id
        assert body["effective_source"]["track_id"] == flac_id
        db.get(models.Track, mp3_id).library_availability = LIBRARY_AVAILABLE
        db.commit()
        status, body = route_call(music_recordings.get_recording_control, rec_id, db)
        assert status == 200 and body["effective_source"]["track_id"] == mp3_id

        before = body["preference"]
        status, detail = route_call(music_recordings.put_preferred_track, rec_id, music_recordings.PreferredTrackPayload(track_id=other_track_id), db)
        assert status == 409, detail
        status, body = route_call(music_recordings.get_recording_control, rec_id, db)
        assert body["preference"]["user_preferred_track_id"] == before["user_preferred_track_id"]

        unknown = 999999
        assert route_call(music_recordings.get_recording_control, unknown, db)[0] == 404
        assert route_call(music_recordings.put_preferred_track, unknown, music_recordings.PreferredTrackPayload(track_id=mp3_id), db)[0] == 404
        assert route_call(music_recordings.delete_preferred_track, unknown, db)[0] == 404
        assert route_call(music_recordings.put_participation, unknown, music_recordings.ParticipationPayload(state="blocked"), db)[0] == 404
        assert route_call(music_recordings.delete_participation, unknown, db)[0] == 404
        assert route_call(music_recordings.put_preferred_track, rec_id, music_recordings.PreferredTrackPayload(track_id=unknown), db)[0] == 404

        try:
            bad_payload = music_recordings.ParticipationPayload(state="bad_state")
        except Exception:
            bad_payload = None
            invalid_status = 422
        else:
            invalid_status = route_call(music_recordings.put_participation, rec_id, bad_payload, db)[0]
        assert invalid_status == 422
        assert db.query(models.MusicRecordingParticipation).filter_by(recording_id=rec_id).count() == 0

        status, body = route_call(music_recordings.put_participation, rec_id, music_recordings.ParticipationPayload(state="library_only", reason_code="exclude_from_radio"), db)
        assert status == 200, body
        assert body["participation"]["state"] == "library_only"
        assert body["participation"]["state_source"] == "user"
        assert body["participation"]["reason_code"] == "exclude_from_radio"
        assert body["preference"]["user_preferred_track_id"] == mp3_id

        status, body = route_call(music_recordings.delete_participation, rec_id, db)
        assert status == 200, body
        assert body["participation"]["state"] == "included"
        assert body["preference"]["user_preferred_track_id"] == mp3_id

        assert route_call(music_recordings.put_participation, rec_id, music_recordings.ParticipationPayload(state="blocked", reason_code="review_hold"), db)[0] == 200
        status, body = route_call(music_recordings.delete_preferred_track, rec_id, db)
        assert status == 200, body
        assert body["preference"]["user_preferred_track_id"] is None
        assert body["participation"]["state"] == "blocked"
    finally:
        db.close()
        engine.dispose()

def case_r_scanner_sparse_default(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_r")
    with temporary_settings():
        roots = configure_roots(tmp / "case_r_roots")
        media = write_media(roots["mp3"] / "Artist" / "Album" / "01 - Scan.mp3")
        db = Session()
        try:
            scan(db, {media.name: meta(media, title="Scan")})
            assert db.query(models.MusicRecording).count() == 1
            assert db.query(models.MusicRecordingPreference).count() == 1
            assert db.query(models.MusicRecordingParticipation).count() == 0
            rec_id = db.query(models.MusicRecording.id).one()[0]
            state = get_music_recording_participation(db, recording_id=rec_id)
            assert state.participation_state == "included" and state.explicit is False
        finally:
            db.close()


def case_s_query_count(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_s")
    db = Session()
    try:
        rec = add_recording(db, "Many")
        for i in range(100):
            add_candidate(db, rec, suffix=f"cand-{i}", codec="mp3", is_lossless=False, bitrate=128000 + i)
        evaluate_music_recording_preference(db, recording_id=rec.id)
        db.commit()
        rec_id = rec.id
    finally:
        db.close()

    db = Session()
    counts = {"selects": 0}

    def count_select(conn, cursor, statement, parameters, context, executemany):
        if statement.lower().lstrip().startswith("select"):
            counts["selects"] += 1

    event.listen(engine, "before_cursor_execute", count_select)
    try:
        detail = music_recordings.control_detail(db, rec_id)
    finally:
        event.remove(engine, "before_cursor_execute", count_select)
        db.close()
    assert len(detail["candidates"]) == 100
    assert counts["selects"] < 40, counts
    engine.dispose()


def case_t_u_v_static_boundaries() -> None:
    route_source = inspect.getsource(music_recordings)
    preference_source = inspect.getsource(sys.modules["app.music_source_preference"])
    for forbidden in ["release_preferences", "quality_rank", "choose_preferred_tracks", "rank_recording_variant"]:
        assert forbidden not in route_source
        assert forbidden not in preference_source

    root = Path(__file__).resolve().parents[1]
    reader_files = [
        "app/routes/library.py",
        "app/routes/search.py",
        "app/routes/queue.py",
        "app/routes/playlists.py",
        "app/routes/stations.py",
        "app/routes/playback.py",
        "app/routes/media.py",
    ]
    for rel in reader_files:
        text = (root / rel).read_text(encoding="utf-8")
        assert "MusicRecordingParticipation" not in text
        assert "participation_state" not in text

    for text in [route_source, inspect.getsource(sys.modules["app.music_recording_participation"]), preference_source]:
        for forbidden in ["unlink(", "rename(", "replace(", "write_bytes", "write_text", "mutagen", "Mutagen"]:
            assert forbidden not in text

    frontend = root.parent / "frontend"
    frontend_hits = [path for path in frontend.rglob("*") if path.is_file() and path.suffix in {".js", ".jsx", ".ts", ".tsx", ".css"} and "music/recordings" in path.read_text(encoding="utf-8", errors="ignore")]
    assert not frontend_hits, frontend_hits


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4d1_recording_control_api"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_schema(tmp)
        case_b_to_e_participation_service(tmp)
        case_f_blocked_non_destructive(tmp)
        case_g_to_q_api(tmp)
        case_r_scanner_sparse_default(tmp)
        case_s_query_count(tmp)
        case_t_u_v_static_boundaries()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.4D1 recording curation and preference control API")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
