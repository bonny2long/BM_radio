from __future__ import annotations

from pathlib import Path
import inspect
import shutil
import sys

from sqlalchemy import create_engine, event, text
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
    occurrence_page,
    presentation_tracks_for_occurrences,
)
from app.music_recording_participation import set_music_recording_participation
from app.music_source_preference import evaluate_music_recording_preference, set_music_recording_user_preference
from app.perf_benchmark import BenchmarkContext, run_benchmarks
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine
from app.schema_maintenance import ensure_scan_reconciliation_columns
from app.scan_runs import LIBRARY_AVAILABLE, LIBRARY_UNAVAILABLE


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def add_release(db, *, title: str, artist: str = "Artist", release_type: str = "album", created_index: int = 0) -> models.MusicRelease:
    index = db.query(models.MusicRelease).count() + 1
    row = models.MusicRelease(
        identity_key=f"release-3-3-{index}-{artist}-{title}",
        album_artist=artist,
        title=title,
        normalized_album_artist=artist.lower(),
        normalized_title=title.lower(),
        release_type=release_type,
    )
    db.add(row)
    db.flush()
    return row


def add_recording(db, *, title: str, artist: str = "Artist", kind: str = "unknown") -> models.MusicRecording:
    index = db.query(models.MusicRecording).count() + 1
    row = models.MusicRecording(
        identity_key=f"recording-3-3-{index}-{artist}-{title}-{kind}",
        artist=artist,
        title=title,
        normalized_artist=artist.lower(),
        normalized_title=title.lower(),
        recording_type=kind,
        version_hint=None if kind == "unknown" else kind,
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
    suffix: str,
    availability: str = LIBRARY_AVAILABLE,
    codec: str = "mp3",
    is_lossless: bool | None = False,
    bitrate: int | None = 320000,
    track_number: int | None = 1,
    disc_number: int | None = 1,
    genre: str = "Soul",
    path_prefix: str = "C:/synthetic/prod3_3",
) -> models.Track:
    index = db.query(models.Track).count() + 1
    edition = models.MusicEdition(
        identity_key=f"edition-3-3-{release.id}-{recording.id}-{suffix}-{index}",
        release_id=release.id,
        display_title=release.title,
        year=2026,
        edition_type="standard",
        source_scope=f"scope-{suffix}",
        source_format_family="LOSSLESS" if is_lossless else "LOSSY",
    )
    track = models.Track(
        path=f"{path_prefix}/{release.id}/{recording.id}/{suffix}.{codec}",
        relative_path=f"{release.album_artist}/{release.title}/{suffix}.{codec}",
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


def table_counts(db) -> dict[str, int]:
    names = [row[0] for row in db.execute(text("select name from sqlite_master where type='table' and name not like 'sqlite_%'")).all()]
    return {name: int(db.execute(text(f'select count(*) from "{name}"')).scalar_one() or 0) for name in names}


def case_a_structural_guard() -> None:
    source = inspect.getsource(listener_library)
    assert "def _base_occurrence_query" not in source
    assert "row_number().over" not in source
    assert "partition_by=(models.MusicEdition.release_id, models.MusicTrackIdentity.recording_id)" not in source
    assert "def _grouped_occurrence_query" in source
    assert "def occurrence_page" in source
    assert "def presentation_tracks_for_occurrences" in source


def case_b_to_f_identity_visibility_and_availability(tmp: Path) -> None:
    _, Session = make_db(tmp, "identity_visibility")
    db = Session()
    try:
        album = add_release(db, title="Album")
        single = add_release(db, title="Single", release_type="single")
        rec = add_recording(db, title="Song")
        flac = add_track(db, release=album, recording=rec, suffix="01-song-flac", codec="flac", is_lossless=True, bitrate=None)
        add_track(db, release=album, recording=rec, suffix="01-song-mp3", codec="mp3")
        single_track = add_track(db, release=single, recording=rec, suffix="01-song-single", codec="mp3")
        live = add_recording(db, title="Song", kind="live")
        add_track(db, release=album, recording=live, suffix="02-song-live", codec="mp3", track_number=2)
        archived = add_recording(db, title="Hidden Archived")
        add_track(db, release=album, recording=archived, suffix="03-hidden", track_number=3)
        set_music_recording_participation(db, recording_id=archived.id, participation_state="archived", reason_code="test")
        unavailable_release = add_release(db, title="Unavailable Context")
        add_track(db, release=unavailable_release, recording=rec, suffix="99-unavailable", availability=LIBRARY_UNAVAILABLE)
        evaluate_music_recording_preference(db, recording_id=rec.id)
        db.commit()

        song_items = listener_tracks(db, q="Song")
        pairs = {(item["release_id"], item["recording_id"]) for item in song_items}
        assert (album.id, rec.id) in pairs
        assert (single.id, rec.id) in pairs
        assert (album.id, live.id) in pairs
        assert (unavailable_release.id, rec.id) not in pairs
        assert len([item for item in song_items if item["release_id"] == album.id and item["recording_id"] == rec.id]) == 1
        assert len([item for item in song_items if item["recording_id"] == rec.id]) == 2
        assert all(item["recording_id"] != archived.id for item in listener_tracks(db, q="Hidden"))
        item = next(item for item in song_items if item["release_id"] == album.id and item["recording_id"] == rec.id)
        assert item["presentation_track_id"] == flac.id
        assert item["effective_track_id"] == flac.id
        assert single_track.id in {item["presentation_track_id"] for item in song_items}
    finally:
        db.close()


def case_g_presentation_order(tmp: Path) -> None:
    _, Session = make_db(tmp, "presentation_order")
    db = Session()
    try:
        release = add_release(db, title="Ordering")
        rec = add_recording(db, title="Ordered")
        null_track = add_track(db, release=release, recording=rec, suffix="zz-null", track_number=None, disc_number=None)
        second = add_track(db, release=release, recording=rec, suffix="02-second", track_number=2, disc_number=1)
        first = add_track(db, release=release, recording=rec, suffix="01-first", track_number=1, disc_number=1)
        db.commit()
        selected = presentation_tracks_for_occurrences(db, occurrence_keys=[(release.id, rec.id)])[(release.id, rec.id)]
        assert selected[0] == first.id, selected
        null_track.library_availability = LIBRARY_UNAVAILABLE
        second.library_availability = LIBRARY_UNAVAILABLE
        first.library_availability = LIBRARY_UNAVAILABLE
        db.commit()
        selected = presentation_tracks_for_occurrences(db, occurrence_keys=[(release.id, rec.id)])[(release.id, rec.id)]
        assert selected[0] == first.id, selected
    finally:
        db.close()


def case_h_exact_pair_enrichment(tmp: Path) -> None:
    _, Session = make_db(tmp, "pair_enrichment")
    db = Session()
    try:
        release_a = add_release(db, title="Release A")
        release_b = add_release(db, title="Release B")
        rec_1 = add_recording(db, title="One")
        rec_2 = add_recording(db, title="Two")
        a1 = add_track(db, release=release_a, recording=rec_1, suffix="a1")
        add_track(db, release=release_a, recording=rec_2, suffix="a2")
        add_track(db, release=release_b, recording=rec_1, suffix="b1")
        b2 = add_track(db, release=release_b, recording=rec_2, suffix="b2")
        db.commit()
        selected = presentation_tracks_for_occurrences(db, occurrence_keys=[(release_a.id, rec_1.id), (release_b.id, rec_2.id)])
        assert selected == {(release_a.id, rec_1.id): (a1.id, a1.music_identity.id), (release_b.id, rec_2.id): (b2.id, b2.music_identity.id)}
    finally:
        db.close()


def case_i_to_l_page_total_and_paging(tmp: Path) -> None:
    engine, Session = make_db(tmp, "paging")
    db = Session()
    try:
        release = add_release(db, title="Paging")
        for idx in range(12):
            rec = add_recording(db, title=f"Page {idx:02d}")
            add_track(db, release=release, recording=rec, suffix=f"{idx:02d}", track_number=idx + 1)
        db.commit()
        occurrence_selects = {"count": 0}

        def count_occurrence(conn, cursor, statement, parameters, context, executemany):
            lowered = statement.lower()
            if lowered.lstrip().startswith("select") and "count(*) over" in lowered:
                occurrence_selects["count"] += 1

        event.listen(engine, "before_cursor_execute", count_occurrence)
        try:
            page = listener_tracks_page(db, limit=5, offset=0, q="Page")
        finally:
            event.remove(engine, "before_cursor_execute", count_occurrence)
        assert page["total"] == 12 and len(page["items"]) == 5 and page["has_more"] is True
        assert occurrence_selects["count"] == 1, occurrence_selects
        beyond = listener_tracks_page(db, limit=5, offset=100, q="Page")
        assert beyond["total"] == 12 and beyond["items"] == [] and beyond["has_more"] is False
        seen = []
        for offset in range(0, 12, 5):
            seen.extend((item["release_id"], item["recording_id"]) for item in listener_tracks_page(db, limit=5, offset=offset, q="Page")["items"])
        assert len(seen) == 12 and len(set(seen)) == 12
    finally:
        db.close()
        engine.dispose()


def case_m_sort_modes(tmp: Path) -> None:
    _, Session = make_db(tmp, "sort_modes")
    db = Session()
    try:
        rel_b = add_release(db, title="Beta", artist="B Artist")
        rel_a = add_release(db, title="Alpha", artist="A Artist")
        rec_z = add_recording(db, title="Zulu", artist="B Artist")
        rec_a = add_recording(db, title="Alpha Song", artist="A Artist")
        add_track(db, release=rel_b, recording=rec_z, suffix="02-z", track_number=2)
        add_track(db, release=rel_a, recording=rec_a, suffix="01-a", track_number=1)
        db.commit()
        assert listener_tracks(db, sort="artist_album_track")[0]["artist"] == "A Artist"
        assert listener_tracks(db, sort="title")[0]["title"] == "Alpha Song"
        assert listener_tracks(db, sort="album")[0]["album"] == "Alpha"
        assert listener_tracks(db, sort="created_desc")[0]["release_id"] in {rel_a.id, rel_b.id}
    finally:
        db.close()


def case_n_to_q_search_and_filters(tmp: Path) -> None:
    _, Session = make_db(tmp, "search_filters")
    db = Session()
    try:
        release = add_release(db, title="Search Album", artist="Search Artist")
        rec = add_recording(db, title="Search Song", artist="Search Artist")
        add_track(db, release=release, recording=rec, suffix="search-mp3", genre="RareGenre")
        add_track(db, release=release, recording=rec, suffix="search-flac", codec="flac", is_lossless=True, bitrate=None, genre="RareGenre")
        other_release = add_release(db, title="Other", artist="Other Artist")
        other_rec = add_recording(db, title="Other Song", artist="Other Artist")
        add_track(db, release=other_release, recording=other_rec, suffix="other")
        db.commit()
        assert len(library_search(db, q="RareGenre")) == 1
        assert len(library_search(db, q="Search Song")) == 1
        assert len(listener_tracks(db, artist="Search Artist")) == 1
        assert len(listener_tracks(db, album="Search Album")) == 1
        assert len(listener_tracks(db, release_id=release.id)) == 1
        music = global_music_search(db, q="Search")
        assert music["tracks"] and music["albums"] and music["artists"]
    finally:
        db.close()


def case_r_to_v_aggregates_recent_album(tmp: Path) -> None:
    _, Session = make_db(tmp, "aggregates")
    db = Session()
    try:
        release_a = add_release(db, title="Same Title", artist="Artist")
        release_b = add_release(db, title="Same Title", artist="Artist")
        rec_a = add_recording(db, title="Aggregate A")
        rec_b = add_recording(db, title="Aggregate B")
        add_track(db, release=release_a, recording=rec_a, suffix="a-mp3")
        add_track(db, release=release_a, recording=rec_a, suffix="a-flac", codec="flac", is_lossless=True, bitrate=None)
        add_track(db, release=release_b, recording=rec_b, suffix="b")
        db.commit()
        summary = listener_summary(db)
        assert summary == {"tracks": 2, "artists": 1, "albums": 2}, summary
        artists = listener_artists(db)
        assert artists[0]["track_count"] == 2 and artists[0]["album_count"] == 2
        albums = listener_albums(db)
        assert len(albums) == 2 and {album["release_id"] for album in albums} == {release_a.id, release_b.id}
        assert all(album["track_count"] == 1 for album in albums)
        recent = listener_albums(db, recent=True)
        assert {album["release_id"] for album in recent} == {release_a.id, release_b.id}
        exact = listener_album_tracks(db, release_id=release_a.id)
        compat = listener_album_tracks(db, artist="Artist", album="Same Title")
        assert len(exact) == 1 and exact[0]["release_id"] == release_a.id
        assert len(compat) == 1 and compat[0]["release_id"] in {release_a.id, release_b.id}
    finally:
        db.close()


def case_w_x_effective_source_projection(tmp: Path) -> None:
    _, Session = make_db(tmp, "source_projection")
    db = Session()
    try:
        release = add_release(db, title="Projection")
        rec = add_recording(db, title="Override Song")
        flac = add_track(db, release=release, recording=rec, suffix="override-flac", codec="flac", is_lossless=True, bitrate=None)
        mp3 = add_track(db, release=release, recording=rec, suffix="override-mp3")
        pref = evaluate_music_recording_preference(db, recording_id=rec.id)
        assert pref.auto_preferred_track_id == flac.id
        set_music_recording_user_preference(db, recording_id=rec.id, track_id=mp3.id)
        ambiguous = add_recording(db, title="Ambiguous Song")
        amb_a = add_track(db, release=release, recording=ambiguous, suffix="amb-a", codec="flac", is_lossless=True, bitrate=None, track_number=2)
        add_track(db, release=release, recording=ambiguous, suffix="amb-b", codec="flac", is_lossless=True, bitrate=None, track_number=2)
        db.commit()
        item = listener_tracks(db, q="Override Song")[0]
        assert item["effective_track_id"] == mp3.id
        assert item["presentation_track_id"] == flac.id
        assert item["album"] == "Projection"
        assert item["cover_url"] == f"/api/media/tracks/{flac.id}/cover"
        assert item["stream_url"] == f"/api/media/tracks/{mp3.id}/stream"
        ambiguous_item = listener_tracks(db, q="Ambiguous Song")[0]
        assert ambiguous_item["source_resolution"] == "deterministic_fallback"
        assert ambiguous_item["effective_track_id"] == amb_a.id
    finally:
        db.close()


def case_y_read_only(tmp: Path) -> None:
    _, Session = make_db(tmp, "read_only")
    db = Session()
    try:
        release = add_release(db, title="Read Only")
        rec = add_recording(db, title="Read Only Song")
        add_track(db, release=release, recording=rec, suffix="read")
        db.commit()
        before = table_counts(db)
        listener_tracks_page(db, limit=10, offset=0)
        listener_summary(db)
        listener_artists(db)
        listener_albums(db)
        global_music_search(db, q="Read")
        db.rollback()
        assert table_counts(db) == before
    finally:
        db.close()


def case_z_no_listener_n_plus_one(tmp: Path) -> None:
    engine, Session = make_db(tmp, "n_plus_one")
    db = Session()
    try:
        release = add_release(db, title="Scale")
        for idx in range(120):
            rec = add_recording(db, title=f"Scale {idx:03d}")
            add_track(db, release=release, recording=rec, suffix=f"{idx:03d}-mp3", track_number=idx + 1)
            add_track(db, release=release, recording=rec, suffix=f"{idx:03d}-flac", codec="flac", is_lossless=True, bitrate=None, track_number=idx + 1)
        db.commit()
        selects = {"count": 0}

        def count_select(conn, cursor, statement, parameters, context, executemany):
            if statement.lower().lstrip().startswith("select"):
                selects["count"] += 1

        event.listen(engine, "before_cursor_execute", count_select)
        try:
            page = listener_tracks_page(db, limit=100, offset=0, q="Scale")
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert len(page["items"]) == 100 and page["total"] == 120
        assert selects["count"] < 30, selects
    finally:
        db.close()
        engine.dispose()


def case_aa_50k_bounded_python(tmp: Path) -> None:
    engine, Session = create_temp_engine(tmp / "large_50k.db")
    db = Session()
    try:
        build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=50_000))
        loaded = {"tracks": 0}

        def count_load(target, context):
            loaded["tracks"] += 1

        event.listen(models.Track, "load", count_load)
        try:
            page = listener_tracks_page(db, limit=50, offset=0)
            search = library_search(db, q="Artist")
        finally:
            event.remove(models.Track, "load", count_load)
        assert len(page["items"]) == 50
        assert search
        assert loaded["tracks"] < 1000, loaded
    finally:
        db.close()
        engine.dispose()


def case_ab_benchmark_uses_production_helpers(tmp: Path) -> None:
    source = inspect.getsource(listener_library)
    bench_source = Path("app/perf_benchmark.py").read_text(encoding="utf-8")
    assert "occurrence_page" in source
    assert "presentation_tracks_for_occurrences" in source
    assert "listener_tracks_page" in bench_source
    assert "global_music_search" in bench_source
    engine, Session = create_temp_engine(tmp / "benchmark_contract.db")
    db = Session()
    try:
        summary = build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=1000))
        ctx = BenchmarkContext(db=db, engine=engine, temp_root=tmp / "bench", summary=summary)
        metrics = run_benchmarks(ctx, iterations=1, warmups=0, include_scanner=False, include_station_observation=False)
        names = {metric["name"] for metric in metrics}
        assert {"library.tracks.first", "library.tracks.deep", "library.albums.first", "library.search.broad"} <= names
    finally:
        db.close()
        engine.dispose()


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod3_3_listener_occurrence_query_optimization"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        case_a_structural_guard()
        case_b_to_f_identity_visibility_and_availability(tmp)
        case_g_presentation_order(tmp)
        case_h_exact_pair_enrichment(tmp)
        case_i_to_l_page_total_and_paging(tmp)
        case_m_sort_modes(tmp)
        case_n_to_q_search_and_filters(tmp)
        case_r_to_v_aggregates_recent_album(tmp)
        case_w_x_effective_source_projection(tmp)
        case_y_read_only(tmp)
        case_z_no_listener_n_plus_one(tmp)
        case_aa_50k_bounded_python(tmp)
        case_ab_benchmark_uses_production_helpers(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD3.3 listener occurrence query optimization")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())