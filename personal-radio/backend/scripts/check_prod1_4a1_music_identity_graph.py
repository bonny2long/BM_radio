from __future__ import annotations

from hashlib import sha256
import inspect
from pathlib import Path
import shutil
import sys

from sqlalchemy import create_engine, inspect as sqlalchemy_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import media_identity, models, music_identity_graph
from app.media_identity import (
    infer_music_recording_type,
    music_album_release_key,
    music_recording_key,
    music_track_release_key,
    normalize_music_source_scope,
)
from app.music_identity_graph import materialize_music_identity_for_track, materialize_music_identity_graph
from app.schema_maintenance import ensure_scan_reconciliation_columns


def make_db(base: Path):
    db_path = base / "prod1_4a1.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def write_file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def add_track(
    db,
    title: str,
    artist: str,
    album: str,
    *,
    album_artist: str | None = None,
    relative_path: str | None = None,
    path: str | None = None,
    year: int = 2020,
    duration: float = 180.0,
    file_ext: str = ".mp3",
    availability: str = "available",
):
    rel = relative_path or f"Music/{artist}/{album}/{title}{file_ext}"
    row = models.Track(
        path=path or f"C:/archive/{rel}",
        relative_path=rel,
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist or artist,
        genre="Hip-Hop",
        year=year,
        duration_seconds=duration,
        file_ext=file_ext,
        library_area="Library",
        library_availability=availability,
    )
    db.add(row)
    db.flush()
    return row


def assert_schema(engine) -> None:
    inspector = sqlalchemy_inspect(engine)
    tables = set(inspector.get_table_names())
    for table in ["music_releases", "music_editions", "music_recordings", "music_track_identities"]:
        assert table in tables, f"missing table {table}"

    indexes = {table: {tuple(index["column_names"]) for index in inspector.get_indexes(table)} for table in tables}
    assert ("identity_key",) in indexes["music_releases"]
    assert ("album_artist",) in indexes["music_releases"]
    assert ("title",) in indexes["music_releases"]
    assert ("identity_key",) in indexes["music_editions"]
    assert ("release_id",) in indexes["music_editions"]
    assert ("source_scope",) in indexes["music_editions"]
    assert ("identity_key",) in indexes["music_recordings"]
    assert ("artist",) in indexes["music_recordings"]
    assert ("title",) in indexes["music_recordings"]
    assert ("recording_type",) in indexes["music_recordings"]
    assert ("track_id",) in indexes["music_track_identities"]
    assert ("edition_id",) in indexes["music_track_identities"]
    assert ("recording_id",) in indexes["music_track_identities"]


def assert_unique_identity_keys(db) -> None:
    db.add(models.MusicRelease(identity_key="duplicate-release", normalized_album_artist="a", normalized_title="b"))
    db.add(models.MusicRelease(identity_key="duplicate-release", normalized_album_artist="a", normalized_title="b"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        raise AssertionError("music_releases.identity_key is not unique")


def link_for(db, track):
    return db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).one()


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_4a1_music_identity_graph"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    fixture = write_file(tmp / "media_fixture.bin", b"a1 identity graph fixture")
    fixture_hash = digest(fixture)
    engine = None
    try:
        engine, Session = make_db(tmp)
        assert_schema(engine)
        db = Session()
        try:
            assert_unique_identity_keys(db)

            # Case B/C - one Track materializes a complete graph and repeats idempotently.
            first = add_track(db, "First Song", "First Artist", "First Album", relative_path="FLAC/First Artist/First Album/01 - First Song.flac", file_ext=".flac")
            result = materialize_music_identity_graph(db, track_ids=[first.id])
            db.commit()
            assert result["tracks_seen"] == 1
            assert db.query(models.MusicRelease).count() == 1
            assert db.query(models.MusicEdition).count() == 1
            assert db.query(models.MusicRecording).count() == 1
            assert db.query(models.MusicTrackIdentity).count() == 1
            first_link_id = link_for(db, first).id
            materialize_music_identity_graph(db, track_ids=[first.id])
            db.commit()
            assert db.query(models.MusicRelease).count() == 1
            assert db.query(models.MusicEdition).count() == 1
            assert db.query(models.MusicRecording).count() == 1
            assert db.query(models.MusicTrackIdentity).count() == 1
            assert link_for(db, first).id == first_link_id

            # Case D - same source album directory shares one edition.
            same_dir_1 = add_track(db, "Dir Song 1", "Dir Artist", "Dir Album", relative_path="Library/Dir Artist/Dir Album/01 - Dir Song 1.mp3")
            same_dir_2 = add_track(db, "Dir Song 2", "Dir Artist", "Dir Album", relative_path="Library/Dir Artist/Dir Album/02 - Dir Song 2.mp3")
            materialize_music_identity_graph(db, track_ids=[same_dir_1.id, same_dir_2.id])
            db.commit()
            assert link_for(db, same_dir_1).edition_id == link_for(db, same_dir_2).edition_id

            # Case E/F - same logical release across source folders gets separate editions but shared recording.
            flac = add_track(db, "Shared Song", "Graph Artist", "Graph Album", relative_path="FLAC/Graph Artist/2020 - Graph Album/01 - Shared Song.flac", file_ext=".flac", duration=180.1)
            mp3 = add_track(db, "Shared Song", "Graph Artist", "Graph Album", relative_path="MP3/Graph Artist/2020 - Graph Album/01 - Shared Song.mp3", file_ext=".mp3", duration=183.9)
            materialize_music_identity_graph(db, track_ids=[flac.id, mp3.id])
            db.commit()
            flac_link = link_for(db, flac)
            mp3_link = link_for(db, mp3)
            assert flac_link.edition_id != mp3_link.edition_id
            assert flac_link.edition.release_id == mp3_link.edition.release_id
            assert flac_link.recording_id == mp3_link.recording_id
            assert not hasattr(flac_link.edition, "preferred_track_id")
            assert flac_link.edition.source_format_family == "FLAC"
            assert mp3_link.edition.source_format_family == "MP3"

            # Case G - same recording on album and single can group while release/edition context differs.
            album_song = add_track(db, "Radio Song", "Single Artist", "Full Album", relative_path="Library/Single Artist/Full Album/05 - Radio Song.mp3", duration=201)
            single_song = add_track(db, "Radio Song", "Single Artist", "Radio Song Single", relative_path="Library/Single Artist/Radio Song Single/01 - Radio Song.mp3", duration=202)
            materialize_music_identity_graph(db, track_ids=[album_song.id, single_song.id])
            db.commit()
            assert link_for(db, album_song).recording_id == link_for(db, single_song).recording_id
            assert link_for(db, album_song).edition.release_id != link_for(db, single_song).edition.release_id

            # Case H/I - explicit live and alternate versions stay separate.
            plain = add_track(db, "Version Song", "Version Artist", "Studio-ish Album", relative_path="Library/Version Artist/Album/01 - Version Song.mp3", duration=190)
            live = add_track(db, "Version Song", "Version Artist", "Live at Wembley", relative_path="Library/Version Artist/Live at Wembley/01 - Version Song.mp3", duration=190)
            acoustic = add_track(db, "Version Song (Acoustic)", "Version Artist", "Album", relative_path="Library/Version Artist/Acoustic/01 - Version Song Acoustic.mp3", duration=190)
            remix = add_track(db, "Version Song (Remix)", "Version Artist", "Album", relative_path="Library/Version Artist/Remix/01 - Version Song Remix.mp3", duration=190)
            instrumental = add_track(db, "Version Song (Instrumental)", "Version Artist", "Album", relative_path="Library/Version Artist/Instrumental/01 - Version Song Instrumental.mp3", duration=190)
            radio_edit = add_track(db, "Version Song (Radio Edit)", "Version Artist", "Album", relative_path="Library/Version Artist/Radio Edit/01 - Version Song Radio Edit.mp3", duration=190)
            materialize_music_identity_graph(db, track_ids=[plain.id, live.id, acoustic.id, remix.id, instrumental.id, radio_edit.id])
            db.commit()
            assert link_for(db, live).recording.recording_type == "live"
            assert link_for(db, plain).recording_id != link_for(db, live).recording_id
            variant_ids = {link_for(db, row).recording_id for row in [plain, live, acoustic, remix, instrumental, radio_edit]}
            assert len(variant_ids) == 6
            assert infer_music_recording_type("Song (Radio Edit)", "Album") == "radio_edit"
            assert infer_music_recording_type("Song", "Unplugged Sessions") == "acoustic"

            # Case J - same title by different artist stays separate.
            artist_a = add_track(db, "Same Title", "Artist A", "Album", relative_path="Library/Artist A/Album/01 - Same Title.mp3")
            artist_b = add_track(db, "Same Title", "Artist B", "Album", relative_path="Library/Artist B/Album/01 - Same Title.mp3")
            materialize_music_identity_graph(db, track_ids=[artist_a.id, artist_b.id])
            db.commit()
            assert link_for(db, artist_a).recording_id != link_for(db, artist_b).recording_id

            # Case K - weak/generic metadata cannot globally collapse unrelated folders.
            unknown_a = add_track(db, "Unknown Track", "Unknown Artist", "Unknown Album", relative_path="Folder A/Unknown Artist/Unknown Album/track01.mp3")
            unknown_b = add_track(db, "Unknown Track", "Unknown Artist", "Unknown Album", relative_path="Folder B/Unknown Artist/Unknown Album/track01.mp3")
            materialize_music_identity_graph(db, track_ids=[unknown_a.id, unknown_b.id])
            db.commit()
            assert link_for(db, unknown_a).edition.release_id != link_for(db, unknown_b).edition.release_id
            assert link_for(db, unknown_a).recording_id != link_for(db, unknown_b).recording_id

            # Case L/M/N - unavailable Track materializes, metadata rebinding preserves user state.
            unavailable = add_track(db, "Unavailable Song", "Gone Artist", "Gone Album", availability="unavailable", relative_path="Library/Gone Artist/Gone Album/01 - Unavailable Song.mp3")
            rebound = add_track(db, "Before Title", "State Artist", "Before Album", relative_path="Library/State Artist/Before Album/01 - Before Title.mp3")
            station = models.Station(name="State Station", type="artist", seed_value="State Artist")
            playlist = models.Playlist(name="State Playlist", kind="manual")
            db.add_all([station, playlist])
            db.flush()
            db.add_all([
                models.TrackFavorite(track_id=rebound.id),
                models.TrackThumb(track_id=rebound.id, station_id=station.id, value=models.ThumbValue.up),
                models.PlaylistTrack(playlist_id=playlist.id, track_id=rebound.id, position=1),
                models.PlaybackEvent(track_id=rebound.id, station_id=station.id, event_type="qualified_play"),
            ])
            materialize_music_identity_graph(db, track_ids=[unavailable.id, rebound.id])
            db.commit()
            assert link_for(db, unavailable).track_id == unavailable.id
            old_recording_id = link_for(db, rebound).recording_id
            rebound.title = "After Title"
            rebound.album = "After Album"
            rebound.relative_path = "Library/State Artist/After Album/01 - After Title.mp3"
            db.commit()
            materialize_music_identity_for_track(db, rebound)
            db.commit()
            new_link = link_for(db, rebound)
            assert new_link.track_id == rebound.id
            assert new_link.recording_id != old_recording_id
            assert db.query(models.MusicTrackIdentity).filter_by(track_id=rebound.id).count() == 1
            assert db.query(models.TrackFavorite).filter_by(track_id=rebound.id).count() == 1
            assert db.query(models.TrackThumb).filter_by(track_id=rebound.id).count() == 1
            assert db.query(models.PlaylistTrack).filter_by(track_id=rebound.id).count() == 1
            assert db.query(models.PlaybackEvent).filter_by(track_id=rebound.id).count() == 1

            # Case O - source-scope normalization is separator-stable and database-only.
            assert normalize_music_source_scope("Music\\Artist\\Album\\01 Song.mp3") == normalize_music_source_scope("Music/Artist/Album/01 Song.mp3")
            assert normalize_music_source_scope(None, "C:\\Music\\Artist\\Album\\01 Song.mp3") == normalize_music_source_scope(None, "C:/Music/Artist/Album/01 Song.mp3")

            # Case P - no filesystem or audio-reader access in identity materialization.
            service_source = inspect.getsource(music_identity_graph)
            helper_source = inspect.getsource(media_identity)
            forbidden = ["Path.exists", "Path.resolve", "open(", "read_bytes", "mutagen", "Mutagen"]
            for token in forbidden:
                assert token not in service_source
                assert token not in helper_source

            # Case Q - existing heuristic identity helper outputs remain stable.
            assert music_track_release_key("The Artist", "The Album", "Song's?", 2020, 1) == "music_track_release|artist|album|2020|1|songs"
            assert music_recording_key("The Artist", "Song", 123) == "music_recording|artist|song|125"
            assert music_album_release_key("The Artist", "The Album", 2020, 10) == "music_album_release|artist|album|2020|10"

            # Case R and non-goals - current scanner/station/preference behavior remains untouched here.
            assert not hasattr(models.MusicRecording, "preferred_track_id")
            assert not hasattr(models.MusicEdition, "preferred_track_id")
            assert db.query(models.Track).filter_by(id=first.id).count() == 1
            assert digest(fixture) == fixture_hash
        finally:
            db.close()
    finally:
        if engine is not None:
            engine.dispose()
        if tmp.exists():
            shutil.rmtree(tmp)

    print("PASS: BM-PROD1.4A1 music identity graph foundation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())