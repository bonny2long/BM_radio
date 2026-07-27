from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import inspect
import shutil
import sys
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import listener_library, models
from app.listener_library import (
    global_music_search,
    listener_albums,
    listener_artist_albums,
    listener_artists,
    listener_summary,
)
from app.music_recording_participation import set_music_recording_participation
from app.music_source_preference import evaluate_music_recording_preference
from app.scan_runs import LIBRARY_AVAILABLE, LIBRARY_UNAVAILABLE
from app.schema_maintenance import ensure_scan_reconciliation_columns

UTC = timezone.utc


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def add_release(db, *, title: str, artist: str = "Artist", release_type: str = "album") -> models.MusicRelease:
    index = db.query(models.MusicRelease).count() + 1
    row = models.MusicRelease(identity_key=f"release-{index}-{artist}-{title}", album_artist=artist, title=title, normalized_album_artist=artist.lower(), normalized_title=title.lower(), release_type=release_type)
    db.add(row)
    db.flush()
    return row


def add_recording(db, *, title: str, artist: str = "Artist", kind: str = "studio") -> models.MusicRecording:
    index = db.query(models.MusicRecording).count() + 1
    row = models.MusicRecording(identity_key=f"recording-{index}-{artist}-{title}-{kind}", artist=artist, title=title, normalized_artist=artist.lower(), normalized_title=title.lower(), recording_type=kind, duration_bucket="180")
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
    track_number: int | None = 1,
    created_at: datetime | None = None,
) -> models.Track:
    index = db.query(models.Track).count() + 1
    edition = models.MusicEdition(identity_key=f"edition-{release.id}-{recording.id}-{suffix}-{index}", release_id=release.id, display_title=release.title, year=2026, edition_type="standard", source_scope=f"scope-{suffix}", source_format_family="LOSSLESS" if is_lossless else "LOSSY")
    track = models.Track(
        path=f"C:/synthetic/d2_1/{release.id}/{recording.id}/{suffix}.{codec}",
        relative_path=f"{release.album_artist}/{release.title}/{suffix}.{codec}",
        title=recording.title,
        artist=recording.artist,
        album=release.title,
        album_artist=release.album_artist,
        genre="Scale",
        primary_genre="Scale",
        year=2026,
        duration_seconds=180.0,
        file_ext=f".{codec}",
        library_area="Library",
        track_number=track_number,
        disc_number=1,
        library_availability=availability,
        created_at=created_at,
        last_indexed_at=created_at,
    )
    db.add_all([edition, track])
    db.flush()
    db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=recording.id))
    db.add(models.MusicTechnicalProfile(track_id=track.id, probe_status="ok", codec=codec, container=codec, is_lossless=is_lossless, sample_rate_hz=44100, bit_depth_bits=16 if is_lossless else None, bitrate_bps=None if is_lossless else 320000, channel_count=2, file_size_bytes=1000 + index))
    db.flush()
    return track


@contextmanager
def forbidden_materializers(*names: str) -> Iterator[None]:
    originals = {name: getattr(listener_library, name) for name in names}

    def fail(*args, **kwargs):
        raise AssertionError("unbounded materializer called")

    try:
        for name in names:
            setattr(listener_library, name, fail)
        yield
    finally:
        for name, original in originals.items():
            setattr(listener_library, name, original)


def state_counts(db) -> dict[str, int]:
    return {
        "tracks": db.query(models.Track).count(),
        "identities": db.query(models.MusicTrackIdentity).count(),
        "profiles": db.query(models.MusicTechnicalProfile).count(),
        "preferences": db.query(models.MusicRecordingPreference).count(),
        "participation": db.query(models.MusicRecordingParticipation).count(),
    }


def case_a_summary_sql(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_a")
    db = Session()
    try:
        for i in range(300):
            release = add_release(db, title=f"Album {i:03d}", artist=f"Artist {i % 30:03d}")
            rec = add_recording(db, title=f"Song {i:03d}", artist=f"Artist {i % 30:03d}")
            add_track(db, release=release, recording=rec, suffix=f"{i}-a")
            add_track(db, release=release, recording=rec, suffix=f"{i}-b", codec="flac", is_lossless=True)
        db.commit()
        with forbidden_materializers("occurrence_keys", "serialize_occurrences"):
            summary = listener_summary(db)
        assert summary == {"tracks": 300, "artists": 30, "albums": 300}
    finally:
        db.close()


def case_b_c_artist_pagination_and_search(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_bc")
    db = Session()
    try:
        for i in range(1000):
            artist = f"Artist {i:04d}"
            release = add_release(db, title=f"Album {i:04d}", artist=artist)
            rec = add_recording(db, title=f"Song {i:04d}", artist=artist)
            add_track(db, release=release, recording=rec, suffix=f"{i}")
        db.commit()
        with forbidden_materializers("occurrence_keys", "serialize_occurrences"):
            page = listener_artists(db, limit=25, offset=500)
        assert len(page) == 25
        assert page[0]["name"] == "Artist 0500"
        assert page[-1]["name"] == "Artist 0524"
        with forbidden_materializers("occurrence_keys", "serialize_occurrences"):
            artists = listener_artists(db, q="Artist 09", limit=20)
        assert 1 <= len(artists) <= 20
        assert all("Artist 09" in row["name"] for row in artists)
        results = global_music_search(db, q="Artist 09")
        assert results["artists"] == artists
    finally:
        db.close()


def case_d_e_f_release_pagination_recent_artist_filter(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_def")
    db = Session()
    try:
        base = datetime(2026, 1, 1, tzinfo=UTC)
        for i in range(1000):
            artist = "Target Artist" if 200 <= i < 210 else f"Artist {i % 50:03d}"
            release = add_release(db, title=f"Release {i:04d}", artist=artist)
            for j in range(2):
                rec = add_recording(db, title=f"Song {i:04d}-{j}", artist=artist)
                add_track(db, release=release, recording=rec, suffix=f"{i}-{j}-a", track_number=j + 1, created_at=base + timedelta(minutes=i))
                add_track(db, release=release, recording=rec, suffix=f"{i}-{j}-b", codec="flac", is_lossless=True, track_number=j + 1, created_at=base + timedelta(minutes=i))
        db.commit()
        with forbidden_materializers("occurrence_keys", "serialize_occurrences"):
            page = listener_albums(db, limit=25, offset=500)
        assert len(page) == 25
        assert all(row["track_count"] == 2 for row in page)
        assert page[0]["release_id"] < page[-1]["release_id"]
        with forbidden_materializers("occurrence_keys", "serialize_occurrences"):
            recent = listener_albums(db, limit=8, recent=True)
        assert [row["title"] for row in recent] == [f"Release {i:04d}" for i in range(999, 991, -1)]
        with forbidden_materializers("occurrence_keys", "serialize_occurrences"):
            artist_albums = listener_artist_albums(db, "Target Artist")
        assert len(artist_albums) == 10
        assert all(row["artist"] == "Target Artist" for row in artist_albums)
    finally:
        db.close()


def case_g_to_k_semantics(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_gk")
    db = Session()
    try:
        release = add_release(db, title="Semantics Album", artist="Semantics Artist")
        rec = add_recording(db, title="Duplicate Source", artist="Semantics Artist")
        add_track(db, release=release, recording=rec, suffix="dup-mp3")
        add_track(db, release=release, recording=rec, suffix="dup-flac", codec="flac", is_lossless=True)

        single = add_release(db, title="Semantics Single", artist="Semantics Artist", release_type="single")
        add_track(db, release=single, recording=rec, suffix="single")

        states = ["included", "library_only", "archived", "blocked"]
        for idx, state in enumerate(states):
            state_release = add_release(db, title=f"State {state}", artist="Policy Artist")
            state_rec = add_recording(db, title=f"State {state}", artist="Policy Artist")
            add_track(db, release=state_release, recording=state_rec, suffix=state)
            set_music_recording_participation(db, recording_id=state_rec.id, participation_state=state)

        unavailable_release = add_release(db, title="Unavailable Only", artist="Policy Artist")
        unavailable_rec = add_recording(db, title="Unavailable Only", artist="Policy Artist")
        unavailable_track = add_track(db, release=unavailable_release, recording=unavailable_rec, suffix="gone", availability=LIBRARY_UNAVAILABLE)
        db.commit()

        summary = listener_summary(db)
        assert summary["tracks"] == 4  # album+single duplicate source, included, library_only
        assert summary["albums"] == 4
        policy_albums = listener_albums(db, q="State")
        assert {row["title"] for row in policy_albums} == {"State included", "State library_only"}
        assert db.get(models.Track, unavailable_track.id) is not None
    finally:
        db.close()


def case_l_read_only_and_n_query_count(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_ln")
    db = Session()
    try:
        for i in range(120):
            release = add_release(db, title=f"Read {i:03d}", artist=f"Read Artist {i % 12:02d}")
            rec = add_recording(db, title=f"Read Song {i:03d}", artist=f"Read Artist {i % 12:02d}")
            add_track(db, release=release, recording=rec, suffix=f"{i}")
            if i % 10 == 0:
                evaluate_music_recording_preference(db, recording_id=rec.id)
        db.commit()
        before = state_counts(db)
        counts = {"selects": 0}

        def count_select(conn, cursor, statement, parameters, context, executemany):
            if statement.lower().lstrip().startswith("select"):
                counts["selects"] += 1

        event.listen(engine, "before_cursor_execute", count_select)
        try:
            listener_summary(db)
            listener_artists(db, limit=25, offset=50)
            listener_albums(db, limit=25, offset=50)
            listener_albums(db, limit=8, recent=True)
            global_music_search(db, q="Read")
        finally:
            event.remove(engine, "before_cursor_execute", count_select)
        assert state_counts(db) == before
        assert counts["selects"] < 60, counts
    finally:
        db.close()
        engine.dispose()


def case_m_static_guards() -> None:
    source = inspect.getsource(listener_library)
    summary_body = source.split("def listener_summary", 1)[1].split("def listener_artists", 1)[0]
    artists_body = source.split("def listener_artists", 1)[1].split("def listener_artist_detail", 1)[0]
    albums_body = source.split("def listener_albums", 1)[1].split("def listener_artist_albums", 1)[0]
    artist_albums_body = source.split("def listener_artist_albums", 1)[1].split("def listener_album_tracks", 1)[0]
    global_body = source.split("def global_music_search", 1)[1]
    for body in [summary_body, artists_body, albums_body, artist_albums_body]:
        assert "occurrence_keys(db)" not in body
        assert "serialize_occurrences" not in body
    assert "listener_artists(db)" not in global_body
    assert "[:20]" not in global_body
    for forbidden in ["release_preferences", "quality_rank", "choose_preferred_tracks", "rank_recording_variant"]:
        assert forbidden not in source
    root = Path(__file__).resolve().parents[1]
    for rel in ["app/routes/queue.py", "app/routes/playlists.py", "app/routes/stations.py", "app/station_engine.py", "app/routes/playback.py", "app/routes/media.py", "app/scanner/music_scanner.py"]:
        text = (root / rel).read_text(encoding="utf-8")
        assert "listener_library" not in text


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4d2_1_listener_projection_scale"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_summary_sql(tmp)
        case_b_c_artist_pagination_and_search(tmp)
        case_d_e_f_release_pagination_recent_artist_filter(tmp)
        case_g_to_k_semantics(tmp)
        case_l_read_only_and_n_query_count(tmp)
        case_m_static_guards()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.4D2.1 listener projection scale stabilization")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())