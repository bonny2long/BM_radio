from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import inspect
import shutil
import sys
from typing import Any, Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.config import settings
from app.music_source_preference import (
    PREFERENCE_BATCH_CHUNK_SIZE,
    evaluate_music_recording_preference,
    music_recording_ids_for_track_ids,
    resolve_effective_music_source,
    set_music_recording_user_preference,
)
from app.schema_maintenance import ensure_scan_reconciliation_columns
from app.scan_runs import LIBRARY_AVAILABLE, LIBRARY_UNAVAILABLE, find_unseen_track_ids
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


def write_media(path: Path, data: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if data is not None else b"c2 fixture bytes")
    return path


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def technical(path: Path, *, codec: str = "mp3", is_lossless: bool | None = False, bitrate: int | None = 320000, status: str = "ok") -> dict[str, Any]:
    return {
        "probe_status": status,
        "probe_source": "mutagen",
        "probe_version": 1,
        "codec": codec,
        "container": "flac" if codec == "flac" else "mp3",
        "is_lossless": is_lossless,
        "sample_rate_hz": 44100,
        "bit_depth_bits": 16 if is_lossless else None,
        "bitrate_bps": bitrate,
        "channel_count": 2,
        "file_size_bytes": path.stat().st_size if path.exists() else None,
    }


def meta(path: Path, *, title: str = "Song", artist: str = "Artist", album: str = "Album", duration: float = 180.0, codec: str = "mp3", is_lossless: bool | None = False, bitrate: int | None = 320000) -> dict[str, Any]:
    return {
        "duration_seconds": duration,
        "title": title,
        "artist": artist,
        "album": album,
        "album_artist": artist,
        "technical": technical(path, codec=codec, is_lossless=is_lossless, bitrate=bitrate),
    }


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
    assert result["scan_run_id"], result
    db.expire_all()
    return result, db.get(models.ScanRun, result["scan_run_id"])


def track_by_path(db, path: Path) -> models.Track:
    row = db.query(models.Track).filter_by(path=str(path)).one_or_none()
    assert row is not None, str(path)
    return row


def pref_for_track(db, track: models.Track) -> models.MusicRecordingPreference:
    link = db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).one()
    return db.query(models.MusicRecordingPreference).filter_by(recording_id=link.recording_id).one()


def link_for(db, track: models.Track) -> models.MusicTrackIdentity:
    return db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).one()


def add_unrelated_recording(db) -> int:
    rec = models.MusicRecording(identity_key=f"unrelated-{db.query(models.MusicRecording).count()}", artist="Other", title="Other", normalized_artist="other", normalized_title="other", recording_type="unknown", duration_bucket="180")
    db.add(rec)
    db.flush()
    release = models.MusicRelease(identity_key=f"unrelated-release-{rec.id}", album_artist="Other", title="Other", normalized_album_artist="other", normalized_title="other")
    db.add(release)
    db.flush()
    edition = models.MusicEdition(identity_key=f"unrelated-edition-{rec.id}", release_id=release.id, display_title="Other", source_scope=f"unrelated-{rec.id}")
    track = models.Track(path=f"C:/unrelated/{rec.id}.mp3", relative_path=f"unrelated/{rec.id}.mp3", title="Other", artist="Other", album="Other", album_artist="Other", duration_seconds=180, file_ext=".mp3", library_availability=LIBRARY_AVAILABLE)
    db.add_all([edition, track])
    db.flush()
    db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=rec.id))
    db.add(models.MusicTechnicalProfile(track_id=track.id, probe_status="ok", codec="mp3", is_lossless=False, bitrate_bps=128000))
    db.flush()
    evaluate_music_recording_preference(db, recording_id=rec.id)
    db.flush()
    return rec.id


def case_a_b_single_and_idempotent(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_ab")
    with temporary_settings():
        roots = configure_roots(tmp / "case_ab_roots")
        mp3 = write_media(roots["mp3"] / "Artist" / "Album" / "01 - Song.mp3")
        db = Session()
        try:
            result, run = scan(db, {mp3.name: meta(mp3)})
            assert result["status"] == "ok" and run.status == "succeeded"
            track = track_by_path(db, mp3)
            pref = pref_for_track(db, track)
            assert pref.decision_state == "preferred" and pref.auto_preferred_track_id == track.id and pref.reason_code == "single_available_source"
            assert result["preference_recordings_affected"] == 1
            assert result["preferences_evaluated"] == 1
            first = (track.id, pref.id, pref.decision_state, pref.auto_preferred_track_id, pref.reason_code)
            result2, _ = scan(db, {mp3.name: meta(mp3)})
            track2 = track_by_path(db, mp3)
            pref2 = pref_for_track(db, track2)
            assert (track2.id, pref2.id, pref2.decision_state, pref2.auto_preferred_track_id, pref2.reason_code) == first
            assert db.query(models.MusicRecordingPreference).count() == 1
            assert result2["preferences_created"] == 0 and result2["preferences_updated"] == 1
        finally:
            db.close()


def case_c_d_e_f_source_changes(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_cdef")
    with temporary_settings():
        roots = configure_roots(tmp / "case_cdef_roots")
        mp3 = write_media(roots["mp3"] / "Artist" / "Album" / "01 - Song.mp3")
        flac = roots["flac"] / "Artist" / "Album" / "01 - Song.flac"
        flac2 = roots["flac"] / "Artist" / "Album Deluxe" / "01 - Song.flac"
        db = Session()
        try:
            scan(db, {mp3.name: meta(mp3)})
            mp3_track = track_by_path(db, mp3)
            write_media(flac)
            mapping = {mp3.name: meta(mp3), flac.name: meta(flac, codec="flac", is_lossless=True, bitrate=None)}
            result, _ = scan(db, mapping)
            flac_track = track_by_path(db, flac)
            pref = pref_for_track(db, flac_track)
            assert pref.auto_preferred_track_id == flac_track.id and pref.reason_code == "unique_lossless_source"
            assert result["preference_recordings_affected"] == 1

            write_media(flac2)
            mapping[flac2.name] = meta(flac2, codec="flac", is_lossless=True, bitrate=None)
            scan(db, mapping)
            pref = pref_for_track(db, flac_track)
            assert pref.decision_state == "ambiguous" and pref.auto_preferred_track_id is None and pref.reason_code == "multiple_lossless_sources_ambiguous"

            flac.unlink()
            mapping_without_flac = {mp3.name: mapping[mp3.name], flac2.name: mapping[flac2.name]}
            scan(db, mapping_without_flac)
            missing_flac = track_by_path(db, flac)
            assert missing_flac.library_availability == LIBRARY_UNAVAILABLE
            pref = pref_for_track(db, track_by_path(db, flac2))
            assert pref.auto_preferred_track_id == track_by_path(db, flac2).id and pref.reason_code == "unique_lossless_source"

            flac2.unlink()
            scan(db, {mp3.name: mapping[mp3.name]})
            assert track_by_path(db, flac2).library_availability == LIBRARY_UNAVAILABLE
            pref = pref_for_track(db, mp3_track)
            assert pref.auto_preferred_track_id == mp3_track.id and pref.reason_code == "single_available_source"
        finally:
            db.close()


def case_f_ambiguous_becomes_single_source(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_f_single")
    with temporary_settings():
        roots = configure_roots(tmp / "case_f_single_roots")
        flac_a = write_media(roots["flac"] / "Artist" / "Album A" / "01 - Song A.flac")
        flac_b = write_media(roots["flac"] / "Artist" / "Album B" / "01 - Song B.flac")
        mapping = {
            flac_a.name: meta(flac_a, title="Song", codec="flac", is_lossless=True, bitrate=None),
            flac_b.name: meta(flac_b, title="Song", codec="flac", is_lossless=True, bitrate=None),
        }
        db = Session()
        try:
            scan(db, mapping)
            pref = pref_for_track(db, track_by_path(db, flac_a))
            assert pref.decision_state == "ambiguous" and pref.reason_code == "multiple_lossless_sources_ambiguous"
            flac_b.unlink()
            result, _ = scan(db, {flac_a.name: mapping[flac_a.name]})
            pref = pref_for_track(db, track_by_path(db, flac_a))
            assert pref.decision_state == "preferred"
            assert pref.auto_preferred_track_id == track_by_path(db, flac_a).id
            assert pref.reason_code == "single_available_source"
            assert result["preference_recordings_affected"] == 1
        finally:
            db.close()

def case_g_h_i_return_and_overrides(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_ghi")
    with temporary_settings():
        roots = configure_roots(tmp / "case_ghi_roots")
        mp3 = write_media(roots["mp3"] / "Artist" / "Album" / "01 - Song.mp3")
        flac = write_media(roots["flac"] / "Artist" / "Album" / "01 - Song.flac")
        mapping = {mp3.name: meta(mp3), flac.name: meta(flac, codec="flac", is_lossless=True, bitrate=None)}
        db = Session()
        try:
            scan(db, mapping)
            mp3_track = track_by_path(db, mp3)
            flac_track = track_by_path(db, flac)
            flac_ids = (flac_track.id, db.query(models.MusicTechnicalProfile).filter_by(track_id=flac_track.id).one().id, link_for(db, flac_track).id)
            pref = pref_for_track(db, flac_track)
            set_music_recording_user_preference(db, recording_id=pref.recording_id, track_id=mp3_track.id)
            db.commit()
            scan(db, mapping)
            pref = pref_for_track(db, flac_track)
            assert pref.user_preferred_track_id == mp3_track.id
            assert pref.auto_preferred_track_id == flac_track.id
            assert resolve_effective_music_source(db, recording_id=pref.recording_id).track_id == mp3_track.id

            mp3.unlink()
            scan(db, {flac.name: mapping[flac.name]})
            pref = pref_for_track(db, flac_track)
            assert pref.user_preferred_track_id == mp3_track.id
            assert resolve_effective_music_source(db, recording_id=pref.recording_id).track_id == flac_track.id
            write_media(mp3)
            scan(db, mapping)
            assert resolve_effective_music_source(db, recording_id=pref.recording_id).track_id == mp3_track.id

            flac.unlink()
            scan(db, {mp3.name: mapping[mp3.name]})
            write_media(flac)
            scan(db, mapping)
            restored = track_by_path(db, flac)
            assert (restored.id, db.query(models.MusicTechnicalProfile).filter_by(track_id=restored.id).one().id, link_for(db, restored).id) == flac_ids
            assert pref_for_track(db, restored).auto_preferred_track_id == restored.id
        finally:
            db.close()


def case_j_rebind_old_and_new_recordings(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_j")
    with temporary_settings():
        roots = configure_roots(tmp / "case_j_roots")
        media = write_media(roots["mp3"] / "Artist" / "Album" / "01 - Mutable.mp3")
        db = Session()
        try:
            first_meta = {media.name: meta(media, title="Before")}
            scan(db, first_meta)
            track = track_by_path(db, media)
            old_link = link_for(db, track)
            old_recording_id = old_link.recording_id
            old_pref = pref_for_track(db, track)
            assert old_pref.decision_state == "preferred"
            db.add(models.TrackFavorite(track_id=track.id))
            db.commit()
            second_meta = {media.name: meta(media, title="After")}
            result, _ = scan(db, second_meta)
            rebound = track_by_path(db, media)
            new_recording_id = link_for(db, rebound).recording_id
            assert rebound.id == track.id and new_recording_id != old_recording_id
            old_pref = db.query(models.MusicRecordingPreference).filter_by(recording_id=old_recording_id).one()
            new_pref = db.query(models.MusicRecordingPreference).filter_by(recording_id=new_recording_id).one()
            assert old_pref.decision_state == "no_eligible_source"
            assert new_pref.decision_state == "preferred" and new_pref.auto_preferred_track_id == track.id
            assert result["preference_recordings_affected"] == 2
            assert db.query(models.TrackFavorite).filter_by(track_id=track.id).count() == 1
        finally:
            db.close()


def case_k_l_m_n_o_failure_and_bounded(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_klmno")
    with temporary_settings():
        roots = configure_roots(tmp / "case_klmno_roots")
        keep = write_media(roots["mp3"] / "Artist" / "Album" / "01 - Keep.mp3", b"keep bytes")
        missing = write_media(roots["flac"] / "Artist" / "Album" / "01 - Missing.flac")
        db = Session()
        original_eval = music_scanner.evaluate_music_recording_preferences
        try:
            before_hash = digest(keep)
            scan(db, {keep.name: meta(keep), missing.name: meta(missing, codec="flac", is_lossless=True, bitrate=None)})
            missing_track = track_by_path(db, missing)
            pref = pref_for_track(db, missing_track)
            assert pref.auto_preferred_track_id == missing_track.id
            missing.unlink()

            seen_ids = {"ids": None}
            def broken_eval(db_arg, *, recording_ids=None):
                seen_ids["ids"] = recording_ids
                raise RuntimeError("forced preference failure")
            music_scanner.evaluate_music_recording_preferences = broken_eval
            result, run = scan(db, {keep.name: meta(keep)})
            assert result["status"] == "failed" and run.status == "failed"
            assert result["tracks_unavailable"] == 0
            assert track_by_path(db, missing).library_availability == LIBRARY_AVAILABLE
            assert db.query(models.MusicRecordingPreference).filter_by(recording_id=pref.recording_id).one().auto_preferred_track_id == missing_track.id
            assert seen_ids["ids"] is not None
        finally:
            music_scanner.evaluate_music_recording_preferences = original_eval

        # Ambiguous policy result is normal success and only affected IDs are evaluated.
        write_media(missing)
        scan(db, {keep.name: meta(keep), missing.name: meta(missing, codec="flac", is_lossless=True, bitrate=None)})
        unrelated_id = add_unrelated_recording(db)
        db.commit()
        called = {"ids": None}
        real_eval = music_scanner.evaluate_music_recording_preferences
        def checking_eval(db_arg, *, recording_ids=None):
            assert recording_ids is not None
            called["ids"] = list(recording_ids)
            assert unrelated_id not in called["ids"]
            return real_eval(db_arg, recording_ids=recording_ids)
        music_scanner.evaluate_music_recording_preferences = checking_eval
        try:
            result, _ = scan(db, {keep.name: meta(keep), missing.name: meta(missing, codec="flac", is_lossless=True, bitrate=None)})
            assert result["status"] == "ok"
            assert result["preference_recordings_affected"] == 1
            assert result["preferences_evaluated"] == 1
            assert called["ids"] is not None and unrelated_id not in called["ids"]
        finally:
            music_scanner.evaluate_music_recording_preferences = real_eval
        assert digest(keep) == before_hash
        db.close()

    scanner_source = inspect.getsource(music_scanner.scan_music)
    assert "recording_ids=None" not in scanner_source
    assert "evaluate_music_recording_preferences(db, recording_ids=affected_recording_list)" in scanner_source


def case_p_q_helpers(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_pq")
    db = Session()
    try:
        release = models.MusicRelease(identity_key="bulk-release", album_artist="A", title="B", normalized_album_artist="a", normalized_title="b")
        db.add(release)
        db.flush()
        ids = []
        for i in range(PREFERENCE_BATCH_CHUNK_SIZE + 5):
            rec = models.MusicRecording(identity_key=f"bulk-rec-{i}", artist="A", title=f"S{i}", normalized_artist="a", normalized_title=f"s{i}", recording_type="unknown", duration_bucket="180")
            db.add(rec)
            db.flush()
            edition = models.MusicEdition(identity_key=f"bulk-ed-{i}", release_id=release.id, display_title="B", source_scope=f"scope-{i}")
            track = models.Track(path=f"C:/bulk/{i}.mp3", relative_path=f"bulk/{i}.mp3", title=f"S{i}", artist="A", album="B", album_artist="A", library_availability=LIBRARY_AVAILABLE)
            db.add_all([edition, track])
            db.flush()
            db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=rec.id))
            ids.append(track.id)
        db.commit()
        rec_ids = music_recording_ids_for_track_ids(db, track_ids=ids)
        assert len(rec_ids) == PREFERENCE_BATCH_CHUNK_SIZE + 5
        assert find_unseen_track_ids(db, scan_run_id=999999, scanned_roots=["C:/bulk"]) == []  # Windows path boundary remains strict for temp sqlite strings on this host.
    finally:
        db.close()
        engine.dispose()


def case_r_s_counters_and_state(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_rs")
    with temporary_settings():
        roots = configure_roots(tmp / "case_rs_roots")
        media = write_media(roots["mp3"] / "Artist" / "Album" / "01 - State.mp3")
        db = Session()
        try:
            result, _ = scan(db, {media.name: meta(media)})
            assert result["preference_recordings_affected"] == 1
            assert result["preferences_evaluated"] == 1
            assert result["preferences_created"] == 1
            assert result["preferences_updated"] == 0
            track = track_by_path(db, media)
            pref = pref_for_track(db, track)
            set_music_recording_user_preference(db, recording_id=pref.recording_id, track_id=track.id)
            playlist = models.Playlist(name="State", kind="manual")
            db.add(playlist)
            db.flush()
            db.add_all([
                models.TrackFavorite(track_id=track.id),
                models.TrackThumb(track_id=track.id, value=models.ThumbValue.up),
                models.PlaybackEvent(track_id=track.id, event_type="qualified_play"),
                models.PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=1),
            ])
            db.commit()
            scan(db, {media.name: meta(media)})
            pref = pref_for_track(db, track)
            assert pref.user_preferred_track_id == track.id
            assert db.query(models.TrackFavorite).filter_by(track_id=track.id).count() == 1
            assert db.query(models.TrackThumb).filter_by(track_id=track.id).count() == 1
            assert db.query(models.PlaybackEvent).filter_by(track_id=track.id).count() == 1
            assert db.query(models.PlaylistTrack).filter_by(track_id=track.id).count() == 1
        finally:
            db.close()


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4c2_scanner_preference_reevaluation"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_b_single_and_idempotent(tmp)
        case_c_d_e_f_source_changes(tmp)
        case_f_ambiguous_becomes_single_source(tmp)
        case_g_h_i_return_and_overrides(tmp)
        case_j_rebind_old_and_new_recordings(tmp)
        case_k_l_m_n_o_failure_and_bounded(tmp)
        case_p_q_helpers(tmp)
        case_r_s_counters_and_state(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.4C2 scanner-driven preference re-evaluation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())