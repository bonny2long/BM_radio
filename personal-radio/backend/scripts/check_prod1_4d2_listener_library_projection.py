from __future__ import annotations

from pathlib import Path
import inspect
import shutil
import sys
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import listener_library, models
from app.listener_library import (
    global_music_search,
    library_search,
    listener_album_tracks,
    listener_albums,
    listener_artists,
    listener_summary,
    listener_tracks,
    listener_tracks_page,
)
from app.music_recording_participation import set_music_recording_participation
from app.music_source_preference import evaluate_music_recording_preference, set_music_recording_user_preference
from app.routes import search as search_route
from app.scan_runs import LIBRARY_AVAILABLE, LIBRARY_UNAVAILABLE
from app.schema_maintenance import ensure_scan_reconciliation_columns


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def add_release(db, *, title: str, artist: str = "Artist", release_type: str = "album") -> models.MusicRelease:
    index = db.query(models.MusicRelease).count() + 1
    row = models.MusicRelease(
        identity_key=f"release-{index}-{artist}-{title}",
        album_artist=artist,
        title=title,
        normalized_album_artist=artist.lower(),
        normalized_title=title.lower(),
        release_type=release_type,
    )
    db.add(row)
    db.flush()
    return row


def add_recording(db, *, title: str, artist: str = "Artist", kind: str = "studio") -> models.MusicRecording:
    index = db.query(models.MusicRecording).count() + 1
    row = models.MusicRecording(
        identity_key=f"recording-{index}-{artist}-{title}-{kind}",
        artist=artist,
        title=title,
        normalized_artist=artist.lower(),
        normalized_title=title.lower(),
        recording_type=kind,
        version_hint=kind,
        duration_bucket="180",
    )
    db.add(row)
    db.flush()
    return row


def add_track(
    db,
    *,
    release: models.MusicRelease,
    recording: models.MusicRecording,
    edition_suffix: str,
    track_suffix: str,
    availability: str = LIBRARY_AVAILABLE,
    codec: str = "mp3",
    is_lossless: bool | None = False,
    bitrate: int | None = 320000,
    track_number: int | None = 1,
    disc_number: int | None = 1,
    genre: str = "Soul",
) -> models.Track:
    index = db.query(models.Track).count() + 1
    edition = models.MusicEdition(
        identity_key=f"edition-{release.id}-{recording.id}-{edition_suffix}-{index}",
        release_id=release.id,
        display_title=release.title,
        year=2026,
        edition_type="standard",
        source_scope=f"scope-{edition_suffix}",
        source_format_family="LOSSLESS" if is_lossless else "LOSSY",
    )
    track = models.Track(
        path=f"C:/synthetic/d2/{release.id}/{recording.id}/{track_suffix}.{codec}",
        relative_path=f"{release.album_artist}/{release.title}/{track_suffix}.{codec}",
        title=recording.title,
        artist=recording.artist,
        album=release.title,
        album_artist=release.album_artist,
        genre=genre,
        primary_genre=genre,
        year=2026,
        duration_seconds=180.0,
        file_ext=f".{codec}",
        library_area="Library",
        track_number=track_number,
        disc_number=disc_number,
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
    ))
    db.flush()
    return track


def ids(items: list[dict], key: str) -> list[int]:
    return [int(item[key]) for item in items]


def case_a_to_e_occurrence_identity(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_a_to_e")
    db = Session()
    try:
        release = add_release(db, title="Album")
        rec = add_recording(db, title="Song")
        flac = add_track(db, release=release, recording=rec, edition_suffix="flac", track_suffix="01-song-flac", codec="flac", is_lossless=True, bitrate=None)
        mp3 = add_track(db, release=release, recording=rec, edition_suffix="mp3", track_suffix="01-song-mp3", codec="mp3", is_lossless=False)
        evaluate_music_recording_preference(db, recording_id=rec.id)
        db.commit()
        items = listener_tracks(db)
        assert len(items) == 1
        assert items[0]["recording_id"] == rec.id and items[0]["release_id"] == release.id
        assert items[0]["id"] == flac.id and items[0]["effective_track_id"] == flac.id
        assert db.query(models.Track).count() == 2
        assert db.query(models.MusicTrackIdentity).count() == 2

        single = add_release(db, title="Song Single", release_type="single")
        single_track = add_track(db, release=single, recording=rec, edition_suffix="single", track_suffix="01-song-single", codec="mp3", is_lossless=False)
        db.commit()
        items = listener_tracks(db, q="Song")
        assert len(items) == 2
        assert {item["release_id"] for item in items} == {release.id, single.id}
        assert {item["recording_id"] for item in items} == {rec.id}

        live = add_recording(db, title="Song", kind="live")
        add_track(db, release=release, recording=live, edition_suffix="live", track_suffix="02-song-live", codec="mp3", is_lossless=False, track_number=2)
        db.commit()
        assert len(listener_tracks(db, q="Song")) == 3
        assert len({item["recording_id"] for item in listener_tracks(db, q="Song")}) == 2

        multi = add_recording(db, title="Edition Collapse")
        add_track(db, release=release, recording=multi, edition_suffix="edition-a", track_suffix="03-edition-a", codec="mp3", is_lossless=False, track_number=3)
        add_track(db, release=release, recording=multi, edition_suffix="edition-b", track_suffix="03-edition-b", codec="flac", is_lossless=True, bitrate=None, track_number=3)
        db.commit()
        assert len([item for item in listener_tracks(db, q="Edition Collapse") if item["release_id"] == release.id]) == 1
    finally:
        db.close()


def case_f_to_j_participation(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_f_to_j")
    db = Session()
    try:
        release = add_release(db, title="Policy")
        states = [None, "included", "library_only", "archived", "blocked"]
        recording_ids = {}
        for index, state in enumerate(states, start=1):
            rec = add_recording(db, title=f"Policy {state or 'implicit'}")
            add_track(db, release=release, recording=rec, edition_suffix=str(index), track_suffix=f"{index}-policy", track_number=index)
            if state is not None:
                set_music_recording_participation(db, recording_id=rec.id, participation_state=state, reason_code="test")
            recording_ids[state or "implicit"] = rec.id
        db.commit()
        items = listener_tracks(db, q="Policy")
        visible_ids = {item["recording_id"] for item in items}
        assert recording_ids["implicit"] in visible_ids
        assert recording_ids["included"] in visible_ids
        assert recording_ids["library_only"] in visible_ids
        assert recording_ids["archived"] not in visible_ids
        assert recording_ids["blocked"] not in visible_ids
        assert db.query(models.MusicRecordingParticipation).count() == 4
        search_ids = {item["recording_id"] for item in library_search(db, q="Policy")}
        assert recording_ids["library_only"] in search_ids
        assert recording_ids["archived"] not in search_ids and recording_ids["blocked"] not in search_ids
    finally:
        db.close()


def case_k_to_p_counts_and_album_identity(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_k_to_p")
    db = Session()
    try:
        release_a = add_release(db, title="Same Title", artist="Artist")
        release_b = add_release(db, title="Same Title", artist="Artist")
        rec_a = add_recording(db, title="Count A")
        rec_b = add_recording(db, title="Count B")
        add_track(db, release=release_a, recording=rec_a, edition_suffix="a1", track_suffix="01-a-mp3", codec="mp3")
        add_track(db, release=release_a, recording=rec_a, edition_suffix="a2", track_suffix="01-a-flac", codec="flac", is_lossless=True, bitrate=None)
        add_track(db, release=release_b, recording=rec_b, edition_suffix="b1", track_suffix="01-b", codec="mp3")
        db.commit()
        summary = listener_summary(db)
        assert summary["tracks"] == 2
        assert summary["albums"] == 2
        artist = listener_artists(db)[0]
        assert artist["track_count"] == 2 and artist["album_count"] == 2
        albums = listener_albums(db)
        assert len(albums) == 2
        assert {album["release_id"] for album in albums} == {release_a.id, release_b.id}
        assert all(album["track_count"] == 1 for album in albums)
        assert len(listener_album_tracks(db, release_id=release_a.id)) == 1
        compat = listener_album_tracks(db, artist="Artist", album="Same Title")
        assert len(compat) == 1
        assert len({item["release_id"] for item in compat}) == 1
    finally:
        db.close()


def case_q_to_x_source_projection(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_q_to_x")
    db = Session()
    try:
        release = add_release(db, title="Projection")
        rec = add_recording(db, title="Override Song")
        flac = add_track(db, release=release, recording=rec, edition_suffix="flac", track_suffix="01-override-flac", codec="flac", is_lossless=True, bitrate=None)
        mp3 = add_track(db, release=release, recording=rec, edition_suffix="mp3", track_suffix="01-override-mp3", codec="mp3", is_lossless=False)
        pref = evaluate_music_recording_preference(db, recording_id=rec.id)
        assert pref.auto_preferred_track_id == flac.id
        set_music_recording_user_preference(db, recording_id=rec.id, track_id=mp3.id)
        db.commit()
        item = listener_tracks(db, q="Override Song")[0]
        assert item["id"] == mp3.id and item["effective_track_id"] == mp3.id
        assert item["presentation_track_id"] == flac.id
        assert item["album"] == "Projection"
        assert item["cover_url"] == f"/api/media/tracks/{flac.id}/cover"
        assert item["stream_url"] == f"/api/media/tracks/{mp3.id}/stream"

        ambiguous = add_recording(db, title="Ambiguous Song")
        a = add_track(db, release=release, recording=ambiguous, edition_suffix="amb-a", track_suffix="02-amb-a", codec="flac", is_lossless=True, bitrate=None, track_number=2)
        b = add_track(db, release=release, recording=ambiguous, edition_suffix="amb-b", track_suffix="02-amb-b", codec="flac", is_lossless=True, bitrate=None, track_number=2)
        before_pref_count = db.query(models.MusicRecordingPreference).count()
        item = listener_tracks(db, q="Ambiguous Song")[0]
        assert item["source_resolution"] == "deterministic_fallback"
        assert item["source_confidence"] == "low"
        assert item["effective_track_id"] == min(a.id, b.id)
        assert db.query(models.MusicRecordingPreference).count() == before_pref_count

        db.get(models.Track, mp3.id).library_availability = LIBRARY_UNAVAILABLE
        db.commit()
        item = listener_tracks(db, q="Override Song")[0]
        assert item["effective_track_id"] == flac.id
        assert item["source_reason_code"] == "user_override_unavailable_fallback"
        assert db.query(models.MusicRecordingPreference).filter_by(recording_id=rec.id).one().user_preferred_track_id == mp3.id
    finally:
        db.close()


def case_t_u_availability_scope(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_t_u")
    db = Session()
    try:
        unavailable_release = add_release(db, title="Unavailable Album")
        visible_release = add_release(db, title="Visible Single", release_type="single")
        rec = add_recording(db, title="Scoped Source")
        old_track = add_track(db, release=unavailable_release, recording=rec, edition_suffix="old", track_suffix="01-old", availability=LIBRARY_UNAVAILABLE)
        new_track = add_track(db, release=visible_release, recording=rec, edition_suffix="new", track_suffix="01-new", availability=LIBRARY_AVAILABLE)
        db.commit()
        items = listener_tracks(db, q="Scoped Source")
        assert len(items) == 1
        assert items[0]["release_id"] == visible_release.id
        assert db.get(models.Track, old_track.id) is not None and db.get(models.Track, new_track.id) is not None

        no_source_rec = add_recording(db, title="No Source")
        no_source_track = add_track(db, release=unavailable_release, recording=no_source_rec, edition_suffix="none", track_suffix="02-none", availability=LIBRARY_UNAVAILABLE)
        db.commit()
        assert listener_tracks(db, q="No Source") == []
        assert db.get(models.Track, no_source_track.id) is not None
    finally:
        db.close()


def case_v_y_z_aa_ab_ac_contracts(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_contracts")
    db = Session()
    try:
        release = add_release(db, title="Contract Album", artist="Contract Artist")
        for i in range(5):
            rec = add_recording(db, title=f"Contract Song {i}", artist="Contract Artist")
            add_track(db, release=release, recording=rec, edition_suffix=f"{i}a", track_suffix=f"{i}-a", track_number=i + 1)
            add_track(db, release=release, recording=rec, edition_suffix=f"{i}b", track_suffix=f"{i}-b", track_number=i + 1)
        book = models.Audiobook(path="C:/books/contract.mp3", relative_path="contract.mp3", title="Contract Book", author="Contract Author", library_availability=LIBRARY_AVAILABLE)
        db.add(book)
        db.commit()
        before_counts = state_counts(db)
        page1 = listener_tracks_page(db, limit=2, offset=0)
        page2 = listener_tracks_page(db, limit=2, offset=2)
        page3 = listener_tracks_page(db, limit=2, offset=4)
        all_items = page1["items"] + page2["items"] + page3["items"]
        assert page1["total"] == 5
        assert len(all_items) == 5
        assert len({(item["release_id"], item["recording_id"]) for item in all_items}) == 5
        item = all_items[0]
        for field in ["id", "title", "artist", "album", "genre", "primary_genre", "year", "duration_seconds", "file_ext", "library_area", "track_number", "disc_number", "library_availability", "stream_url", "cover_url", "recording_id", "release_id", "edition_id", "presentation_track_id", "effective_track_id", "participation_state", "source_resolution", "source_confidence", "source_reason_code"]:
            assert field in item, field
        assert item["id"] == item["effective_track_id"]
        assert state_counts(db) == before_counts

        global_result = global_music_search(db, q="Contract")
        assert len(global_result["tracks"]) == 5
        assert global_result["artists"][0]["track_count"] == 5
        assert global_result["albums"][0]["release_id"] == release.id
        routed = search_route.global_search("Contract", db)
        assert any(book_item["title"] == "Contract Book" for book_item in routed["audiobooks"])
    finally:
        db.close()


def state_counts(db) -> dict[str, int]:
    return {
        "tracks": db.query(models.Track).count(),
        "identities": db.query(models.MusicTrackIdentity).count(),
        "profiles": db.query(models.MusicTechnicalProfile).count(),
        "preferences": db.query(models.MusicRecordingPreference).count(),
        "participation": db.query(models.MusicRecordingParticipation).count(),
    }


def case_ad_query_counts(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_ad")
    db = Session()
    try:
        release = add_release(db, title="Query Album", artist="Query Artist")
        for i in range(100):
            rec = add_recording(db, title=f"Query Song {i}", artist="Query Artist")
            add_track(db, release=release, recording=rec, edition_suffix=f"{i}a", track_suffix=f"{i}-a", track_number=i + 1)
            add_track(db, release=release, recording=rec, edition_suffix=f"{i}b", track_suffix=f"{i}-b", track_number=i + 1)
        db.commit()
        counts = {"selects": 0}

        def count_select(conn, cursor, statement, parameters, context, executemany):
            if statement.lower().lstrip().startswith("select"):
                counts["selects"] += 1

        event.listen(engine, "before_cursor_execute", count_select)
        try:
            assert len(listener_tracks(db, limit=100)) == 100
            assert len(library_search(db, q="Query")) == 100
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert counts["selects"] < 40, counts
    finally:
        db.close()
        engine.dispose()


def case_ae_af_ag_static_scope() -> None:
    projection_source = inspect.getsource(listener_library)
    for forbidden in ["evaluate_music_recording_preferences", "evaluate_music_recording_preference(", "release_preferences", "quality_rank", "choose_preferred_tracks", "rank_recording_variant"]:
        assert forbidden not in projection_source
    root = Path(__file__).resolve().parents[1]
    for rel in ["app/routes/queue.py", "app/routes/playlists.py", "app/routes/stations.py", "app/station_engine.py", "app/routes/playback.py", "app/routes/media.py"]:
        text = (root / rel).read_text(encoding="utf-8")
        assert "listener_library" not in text
        assert "MusicRecordingParticipation" not in text
    frontend = root.parent / "frontend"
    frontend_hits = [path for path in frontend.rglob("*") if path.is_file() and path.suffix in {".js", ".jsx", ".ts", ".tsx", ".css"} and "release_id" in path.read_text(encoding="utf-8", errors="ignore")]
    assert not frontend_hits, frontend_hits


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4d2_listener_library_projection"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_to_e_occurrence_identity(tmp)
        case_f_to_j_participation(tmp)
        case_k_to_p_counts_and_album_identity(tmp)
        case_q_to_x_source_projection(tmp)
        case_t_u_availability_scope(tmp)
        case_v_y_z_aa_ab_ac_contracts(tmp)
        case_ad_query_counts(tmp)
        case_ae_af_ag_static_scope()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.4D2 listener library and search projection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())