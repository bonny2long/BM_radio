from __future__ import annotations

import json
import shutil
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import settings
from app.scanner import music_scanner
from app.scanner.music_scanner import normalized_year


def approved(value):
    return {"approved": True, "value": value}


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="bm-aa-music-manifest-"))
    if base.exists():
        shutil.rmtree(base)
    music_root = base / "Music"
    mp3_root = music_root / "Library" / "MP3"
    flac_root = music_root / "Library" / "FLAC"
    disc_root = music_root / "Discographies"
    album_dir = mp3_root / "Wrong Path Artist" / "Wrong Album"
    metadata_dir = album_dir / "metadata"
    metadata_dir.mkdir(parents=True)
    flac_root.mkdir(parents=True)
    disc_root.mkdir(parents=True)
    media_file = album_dir / "04 - Skew It On The Bar-B.mp3"
    (metadata_dir / "music-album.json").write_text(json.dumps({
        "metadata_version": "test-1",
        "metadata_contract": {"fields": {
            "artist": approved("OutKast"),
            "albumartist": approved("OutKast"),
            "album": approved("Aquemini"),
            "year": approved("1998"),
            "genre": approved("Hip-Hop"),
        }},
        "release_profile": {"release_title": "Aquemini", "primary_genre": "Hip-Hop"},
        "track_profiles": [{
            "file_name": media_file.name,
            "track_profile": {"track_number": 4, "track_title": "Skew It On The Bar-B", "primary_genre": "Hip-Hop"},
        }],
    }), encoding="utf-8")

    unknown_album_dir = mp3_root / "Acceptance Artist" / "Unknown Date Album"
    unknown_metadata_dir = unknown_album_dir / "metadata"
    unknown_metadata_dir.mkdir(parents=True)
    unknown_media_file = unknown_album_dir / "01 - Timeless Test.mp3"
    (unknown_metadata_dir / "move_manifest.json").write_text(json.dumps({
        "manifest_version": "v1",
        "metadata_version": "test-unknown-year",
        "summary": {
            "album_artist": "Acceptance Artist",
            "album_title": "Unknown Date Album",
            "year": "Unknown Year",
            "format": "MP3",
        },
        "confirmed_metadata": {
            "album_artist": "Acceptance Artist",
            "album_title": "Unknown Date Album",
            "year": "Unknown Year",
        },
    }), encoding="utf-8")

    settings.MUSIC_ROOT = str(music_root)
    settings.MUSIC_MP3_ROOT = str(mp3_root)
    settings.MUSIC_FLAC_ROOT = str(flac_root)
    settings.MUSIC_DISCOGRAPHIES_ROOT = str(disc_root)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(models.ArtistRadioProfile(artist="OutKast", primary_genre="Manual Genre", source="manual"))
    db.commit()

    virtual_media = (media_file, unknown_media_file)
    original_safe_media_files = music_scanner.safe_media_files
    original_read_metadata = music_scanner.read_metadata

    def virtual_safe_media_files(root: Path, _extensions, _roots):
        return [path for path in virtual_media if path.is_relative_to(root)]

    def virtual_read_metadata(path: Path):
        if path == media_file:
            return {
                "duration_seconds": 180.0,
                "title": "Wrong Embedded Title",
                "artist": "Wrong Embedded Artist",
                "album": "Wrong Embedded Album",
                "album_artist": "Wrong Embedded Artist",
                "genre": "Wrong Embedded Genre",
                "year": 2000,
            }
        return {
            "duration_seconds": 181.0,
            "title": "Timeless Test",
            "artist": "Acceptance Artist",
            "album": "Unknown Date Album",
            "album_artist": "Acceptance Artist",
            "genre": None,
            "year": None,
        }

    music_scanner.safe_media_files = virtual_safe_media_files
    music_scanner.read_metadata = virtual_read_metadata
    try:
        result = music_scanner.scan_music(db)
    finally:
        music_scanner.safe_media_files = original_safe_media_files
        music_scanner.read_metadata = original_read_metadata
    assert result["errors"] == [], result["errors"]
    track = db.query(models.Track).filter_by(path=str(media_file)).one()
    assert track.artist == "OutKast", track.artist
    assert track.album_artist == "OutKast", track.album_artist
    assert track.album == "Aquemini", track.album
    assert track.year == 1998, track.year
    assert track.genre == "Hip-Hop", track.genre
    assert track.primary_genre == "Hip-Hop", track.primary_genre
    assert track.title == "Skew It On The Bar-B", track.title
    assert track.track_number == 4, track.track_number
    assert track.metadata_source == "archive_assistant_manifest", track.metadata_source
    manual = db.query(models.ArtistRadioProfile).filter_by(artist="OutKast").one()
    assert manual.primary_genre == "Manual Genre", manual.primary_genre
    assert manual.source == "manual", manual.source
    track_profile = db.query(models.TrackRadioProfile).filter_by(track_id=track.id).one()
    assert track_profile.primary_genre == "Hip-Hop", track_profile.primary_genre
    assert track_profile.source == "archive_assistant_manifest", track_profile.source
    unknown_track = db.query(models.Track).filter_by(path=str(unknown_media_file)).one()
    assert unknown_track.year is None, unknown_track.year
    assert result["tracks_added"] == 2, result
    assert normalized_year("Unknown Year") is None
    assert normalized_year("1998") == 1998
    assert normalized_year("Released 1998") == 1998
    assert normalized_year("1898") is None
    assert normalized_year("not a year") is None
    assert normalized_year(True) is None
    assert normalized_year(None) is None
    assert not media_file.exists() and not unknown_media_file.exists()
    db.close()
    engine.dispose()
    shutil.rmtree(base, ignore_errors=True)
    print("ok: AA music manifest import")


if __name__ == "__main__":
    main()
