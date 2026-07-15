from __future__ import annotations

from pathlib import Path
import shutil
import sys

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.music_scan_index import MAX_DUPLICATE_WARNING_SAMPLES, collect_music_scan_identity_diagnostics
from app.schema_maintenance import ensure_scan_reconciliation_columns


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def add_release(db, key: str, title: str = "Release") -> models.MusicRelease:
    row = models.MusicRelease(
        identity_key=key,
        album_artist="Artist",
        title=title,
        normalized_album_artist="artist",
        normalized_title=title.lower(),
    )
    db.add(row)
    db.flush()
    return row


def add_recording(db, key: str = "recording") -> models.MusicRecording:
    row = models.MusicRecording(
        identity_key=key,
        artist="Artist",
        title="Song",
        normalized_artist="artist",
        normalized_title="song",
        recording_type="unknown",
        duration_bucket="180",
    )
    db.add(row)
    db.flush()
    return row


def add_track(db, *, path: str, recording_id: int, release_id: int, title: str = "Song") -> models.Track:
    edition = models.MusicEdition(
        identity_key=f"edition:{path}",
        release_id=release_id,
        display_title="Release",
        source_scope=path,
    )
    track = models.Track(
        path=path,
        relative_path=path,
        title=title,
        artist="Artist",
        album="Release",
        album_artist="Artist",
        duration_seconds=180,
        file_ext=".mp3",
        library_availability="available",
    )
    db.add_all([edition, track])
    db.flush()
    db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=recording_id))
    db.flush()
    return track


def base_pair(db, *, same_release: bool = True):
    recording = add_recording(db, "recording:pair")
    release_a = add_release(db, "release:a", "Album")
    release_b = release_a if same_release else add_release(db, "release:b", "Single")
    a = add_track(db, path="C:/diag/A.mp3", recording_id=recording.id, release_id=release_a.id)
    b = add_track(db, path="C:/diag/B.mp3", recording_id=recording.id, release_id=release_b.id)
    db.commit()
    return a, b


def warning_types(result: dict) -> list[str]:
    return [item["type"] for item in result["duplicate_warnings"]]


def relationship_keys(result: dict) -> list[tuple]:
    keys = []
    for item in result["duplicate_warnings"]:
        keys.append((item["type"], tuple(item.get("track_ids") or []), tuple(item.get("release_ids") or []), item.get("recording_id")))
    return keys


def case_a_same_release_pair(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_a")
    db = Session()
    try:
        a, b = base_pair(db, same_release=True)
        result = collect_music_scan_identity_diagnostics(db, track_ids=[a.id, b.id])
        assert result["physical_sources_preserved"] == 2, result
        assert result["duplicates_suspected"] == 0, result
        assert warning_types(result) == ["physical_source_preserved"], result
        assert result["duplicate_warning_relationships"] == 1, result
        assert result["duplicate_warnings_truncated"] is False, result
        assert result["duplicate_warnings"][0]["track_ids"] == sorted([a.id, b.id])
    finally:
        db.close()


def case_b_cross_release_pair(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_b")
    db = Session()
    try:
        a, b = base_pair(db, same_release=False)
        result = collect_music_scan_identity_diagnostics(db, track_ids=[a.id, b.id])
        assert result["physical_sources_preserved"] == 0, result
        assert result["duplicates_suspected"] == 2, result
        assert warning_types(result) == ["recording_duplicate_detected"], result
        assert result["duplicate_warning_relationships"] == 1, result
        assert result["duplicate_warnings_truncated"] is False, result
        assert result["duplicate_warnings"][0]["track_ids"] == sorted([a.id, b.id])
    finally:
        db.close()


def case_c_reversed_input_order(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_c")
    db = Session()
    try:
        a, b = base_pair(db, same_release=False)
        forward = collect_music_scan_identity_diagnostics(db, track_ids=[a.id, b.id])
        reverse = collect_music_scan_identity_diagnostics(db, track_ids=[b.id, a.id])
        assert forward == reverse
    finally:
        db.close()


def case_d_three_same_release_no_directional_duplicates(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_d")
    db = Session()
    try:
        recording = add_recording(db, "recording:three")
        release = add_release(db, "release:three")
        tracks = [add_track(db, path=f"C:/diag/three/{idx}.mp3", recording_id=recording.id, release_id=release.id) for idx in range(3)]
        db.commit()
        result = collect_music_scan_identity_diagnostics(db, track_ids=[track.id for track in tracks])
        assert result["physical_sources_preserved"] == 3, result
        keys = relationship_keys(result)
        assert keys
        assert len(keys) == len(set(keys)), keys
        for _type, track_ids, _release_ids, _recording_id in keys:
            assert list(track_ids) == sorted(track_ids), keys
    finally:
        db.close()


def case_e_mixed_warning_types(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_e")
    db = Session()
    try:
        recording = add_recording(db, "recording:mixed")
        release_a = add_release(db, "release:mixed:a", "Album")
        release_b = add_release(db, "release:mixed:b", "Single")
        a = add_track(db, path="C:/diag/mixed/A.mp3", recording_id=recording.id, release_id=release_a.id)
        b = add_track(db, path="C:/diag/mixed/B.mp3", recording_id=recording.id, release_id=release_a.id)
        c = add_track(db, path="C:/diag/mixed/C.mp3", recording_id=recording.id, release_id=release_b.id)
        db.commit()
        result = collect_music_scan_identity_diagnostics(db, track_ids=[a.id, b.id, c.id])
        assert result["physical_sources_preserved"] == 2, result
        assert result["duplicates_suspected"] == 3, result
        assert "physical_source_preserved" in warning_types(result), result
        assert "recording_duplicate_detected" in warning_types(result), result
        assert result["duplicate_warning_relationships"] == len(result["duplicate_warnings"])
    finally:
        db.close()


def case_f_raw_counters_no_false_truncation(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_f")
    db = Session()
    try:
        a, b = base_pair(db, same_release=True)
        result = collect_music_scan_identity_diagnostics(db, track_ids=[a.id, b.id])
        assert result["physical_sources_preserved"] > result["duplicate_warning_relationships"]
        assert result["duplicate_warning_relationships"] <= MAX_DUPLICATE_WARNING_SAMPLES
        assert result["duplicate_warnings_truncated"] is False, result
    finally:
        db.close()


def case_g_actual_overflow_truncates(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_g")
    db = Session()
    try:
        affected_ids = []
        for idx in range(MAX_DUPLICATE_WARNING_SAMPLES + 1):
            recording = add_recording(db, f"recording:overflow:{idx}")
            release = add_release(db, f"release:overflow:{idx}")
            affected = add_track(db, path=f"C:/diag/overflow/{idx}/A.mp3", recording_id=recording.id, release_id=release.id)
            add_track(db, path=f"C:/diag/overflow/{idx}/B.mp3", recording_id=recording.id, release_id=release.id)
            affected_ids.append(affected.id)
        db.commit()
        result = collect_music_scan_identity_diagnostics(db, track_ids=affected_ids)
        assert result["physical_sources_preserved"] == MAX_DUPLICATE_WARNING_SAMPLES + 1, result
        assert result["duplicate_warning_relationships"] == MAX_DUPLICATE_WARNING_SAMPLES + 1, result
        assert len(result["duplicate_warnings"]) == MAX_DUPLICATE_WARNING_SAMPLES, result
        assert result["duplicate_warnings_truncated"] is True, result
    finally:
        db.close()


def case_h_repeated_runs_deterministic(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_h")
    db = Session()
    try:
        a, b = base_pair(db, same_release=False)
        first = collect_music_scan_identity_diagnostics(db, track_ids=[b.id, a.id, a.id])
        second = collect_music_scan_identity_diagnostics(db, track_ids=[a.id, b.id])
        third = collect_music_scan_identity_diagnostics(db, track_ids=[b.id, a.id])
        assert first == second == third
    finally:
        db.close()


def case_i_select_behavior_bounded(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_i")
    db = Session()
    try:
        affected_ids = []
        for idx in range(120):
            recording = add_recording(db, f"recording:bounded:{idx}")
            release = add_release(db, f"release:bounded:{idx}")
            affected = add_track(db, path=f"C:/diag/bounded/{idx}/A.mp3", recording_id=recording.id, release_id=release.id)
            add_track(db, path=f"C:/diag/bounded/{idx}/B.mp3", recording_id=recording.id, release_id=release.id)
            affected_ids.append(affected.id)
        db.commit()
        selects = {"count": 0}

        def count_select(conn, cursor, statement, parameters, context, executemany):
            lowered = statement.lower().lstrip()
            if lowered.startswith("select") and "music_track_identities" in lowered:
                selects["count"] += 1

        event.listen(engine, "before_cursor_execute", count_select)
        try:
            result = collect_music_scan_identity_diagnostics(db, track_ids=affected_ids)
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert result["duplicate_warning_relationships"] == 120, result
        assert selects["count"] <= 4, selects
    finally:
        db.close()
        engine.dispose()


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod3_2_1_scanner_diagnostic_pair_canonicalization"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        case_a_same_release_pair(tmp)
        case_b_cross_release_pair(tmp)
        case_c_reversed_input_order(tmp)
        case_d_three_same_release_no_directional_duplicates(tmp)
        case_e_mixed_warning_types(tmp)
        case_f_raw_counters_no_false_truncation(tmp)
        case_g_actual_overflow_truncates(tmp)
        case_h_repeated_runs_deterministic(tmp)
        case_i_select_behavior_bounded(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD3.2.1 scanner diagnostic pair canonicalization")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())