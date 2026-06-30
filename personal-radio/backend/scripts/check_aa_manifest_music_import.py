from __future__ import annotations

import json
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import settings
from app.scanner.music_scanner import scan_music


def approved(value):
    return {"approved": True, "value": value}


def main() -> None:
    tmp_base = Path(__file__).resolve().parents[1] / "tmp_tests"
    tmp_base.mkdir(exist_ok=True)
    base = tmp_base / "music_manifest"
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
    media_file.write_bytes(b"not real audio")
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

    result = scan_music(db)
    assert result["errors"] == [], result["errors"]
    track = db.query(models.Track).one()
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
    print("ok: AA music manifest import")


if __name__ == "__main__":
    main()