from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from . import models
from .music_source_preference import evaluate_music_recording_preference
from .scan_runs import LIBRARY_AVAILABLE


UTC = timezone.utc
FIXED_RANDOM_SEEDS = (11, 23, 47, 71, 101)
FAMILY_GENRES = {
    "hip-hop": ("Hip-Hop", "Rap", "Trap", "Alternative Hip-Hop", "Jazz Rap"),
    "electronic": ("Electronic", "House", "Techno", "Ambient", "Downtempo"),
    "rock": ("Rock", "Classic Rock", "Progressive Rock", "Indie Rock", "Hard Rock"),
    "r&b": ("R&B", "Soul", "Funk", "Neo Soul", "Alternative R&B"),
    "jazz": ("Jazz", "Bebop", "Hard Bop", "Modal Jazz", "Cool Jazz"),
}


@dataclass(frozen=True)
class StationQualityFixture:
    logical_recordings: int
    physical_tracks: int
    artists: tuple[str, ...]
    releases: tuple[str, ...]
    genre_families: tuple[str, ...]
    recording_types: tuple[str, ...]
    seed_tracks: dict[str, int]
    recording_by_track: dict[int, int]
    family_by_track: dict[int, str]
    physical_variant_recording_id: int
    physical_variant_track_ids: tuple[int, int]
    preferred_variant_track_id: int
    down_recording_ids: tuple[int, ...]
    favorite_recording_ids: tuple[int, ...]
    up_recording_ids: tuple[int, ...]


def fixture_manifest() -> dict:
    """Static, DB-free description used by preflight and the permanent contract."""
    return {
        "logical_recordings": 200,
        "physical_tracks": 201,
        "artists": 25,
        "releases": 50,
        "genre_families": tuple(FAMILY_GENRES),
        "related_boundary": True,
        "unrelated_boundary": True,
        "feedback_and_history": True,
        "physical_source_variants": True,
        "recording_types": ("studio", "standard", "live", "acoustic", "remix", "instrumental"),
        "random_seeds": FIXED_RANDOM_SEEDS,
        "synthetic_only": True,
    }


def create_fixture_database(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    try:
        fixture = populate_station_quality_fixture(db)
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        engine.dispose()
        raise
    return engine, db, fixture


def _recording_type(family: str, family_index: int, global_index: int) -> str:
    if family == "hip-hop" and family_index < 8:
        return "live"
    if family == "hip-hop" and family_index < 16:
        return "acoustic"
    if family == "electronic" and family_index < 15:
        return "remix"
    if family == "rock" and family_index < 15:
        return "instrumental"
    return "studio" if global_index % 2 == 0 else "standard"


def populate_station_quality_fixture(db) -> StationQualityFixture:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    artists: list[str] = []
    releases: list[str] = []
    recording_by_track: dict[int, int] = {}
    family_by_track: dict[int, str] = {}
    seed_tracks: dict[str, int] = {}
    all_rows: list[tuple[models.MusicRecording, models.Track]] = []

    global_index = 0
    for family_index, (family, genres) in enumerate(FAMILY_GENRES.items()):
        family_artists = [f"SQ {family.title()} Artist {index + 1}" for index in range(5)]
        artists.extend(family_artists)
        for artist_index, artist in enumerate(family_artists):
            related = [name for name in family_artists if name != artist][:3]
            db.add(models.ArtistRadioProfile(
                artist=artist,
                primary_genre=genres[artist_index],
                subgenres_json=json.dumps([genres[artist_index]]),
                moods_json='["focused", "warm"]',
                energy="medium",
                era="2020s",
                related_artists_json=json.dumps(related),
                source="prod6b-synthetic",
            ))
            for local_track_index in range(8):
                release_slot = local_track_index // 4
                release_title = f"SQ {family.title()} Release {artist_index + 1}-{release_slot + 1}"
                release = models.MusicRelease(
                    identity_key=f"prod6b-release-{family_index}-{artist_index}-{release_slot}",
                    album_artist=artist,
                    title=release_title,
                    normalized_album_artist=artist.lower(),
                    normalized_title=release_title.lower(),
                    release_type="album",
                )
                if local_track_index % 4 == 0:
                    db.add(release)
                    db.flush()
                    releases.append(release_title)
                else:
                    release = db.query(models.MusicRelease).filter_by(
                        identity_key=f"prod6b-release-{family_index}-{artist_index}-{release_slot}"
                    ).one()

                within_family = artist_index * 8 + local_track_index
                kind = _recording_type(family, within_family, global_index)
                title = f"SQ Recording {global_index + 1:03d}"
                recording = models.MusicRecording(
                    identity_key=f"prod6b-recording-{global_index:03d}",
                    artist=artist,
                    title=title,
                    normalized_artist=artist.lower(),
                    normalized_title=title.lower(),
                    recording_type=kind,
                    version_hint=kind,
                    duration_bucket=str(180 + global_index % 20),
                )
                db.add(recording)
                db.flush()
                # A coprime permutation keeps creation time deterministic without
                # accidentally encoding album/artist ingestion order.
                created = now - timedelta(hours=(global_index * 37) % 200)
                track = models.Track(
                    path=f"C:/bm-prod6b-synthetic/{global_index:03d}.mp3",
                    relative_path=f"prod6b/{global_index:03d}.mp3",
                    title=title,
                    artist=artist,
                    album=release_title,
                    album_artist=artist,
                    genre=genres[artist_index],
                    primary_genre=genres[artist_index],
                    year=2026,
                    duration_seconds=float(180 + global_index % 20),
                    file_ext=".mp3",
                    library_area="Library",
                    track_number=local_track_index + 1,
                    disc_number=1,
                    library_availability=LIBRARY_AVAILABLE,
                    created_at=created,
                    last_indexed_at=created,
                )
                db.add(track)
                db.flush()
                edition = models.MusicEdition(
                    identity_key=f"prod6b-edition-{global_index:03d}",
                    release_id=release.id,
                    display_title=release_title,
                    year=2026,
                    edition_type="standard",
                    source_scope=f"prod6b-scope-{global_index:03d}",
                    source_format_family="LOSSY",
                )
                db.add(edition)
                db.flush()
                db.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition.id, recording_id=recording.id))
                db.add(models.MusicTechnicalProfile(
                    track_id=track.id, probe_status="ok", codec="mp3", container="mp3",
                    is_lossless=False, sample_rate_hz=44100, bitrate_bps=320000,
                    channel_count=2, file_size_bytes=4_000_000 + global_index,
                ))
                db.add(models.TrackRadioProfile(
                    track_id=track.id,
                    primary_genre=genres[artist_index],
                    subgenres_json=json.dumps([genres[artist_index]]),
                    moods_json='["focused", "warm"]',
                    energy="medium",
                    radio_tags_json=json.dumps([family]),
                    source="prod6b-synthetic",
                ))
                db.flush()
                recording_by_track[track.id] = recording.id
                family_by_track[track.id] = family
                all_rows.append((recording, track))
                if local_track_index == 0 and artist_index == 0:
                    seed_tracks[f"artist:{family}"] = track.id
                if kind in {"live", "acoustic", "remix", "instrumental"} and f"type:{kind}" not in seed_tracks:
                    seed_tracks[f"type:{kind}"] = track.id
                global_index += 1

    # One logical recording has both MP3 and lossless FLAC sources.
    variant_recording, mp3_track = all_rows[0]
    identity = db.query(models.MusicTrackIdentity).filter_by(track_id=mp3_track.id).one()
    flac_track = models.Track(
        path="C:/bm-prod6b-synthetic/000-preferred.flac",
        relative_path="prod6b/000-preferred.flac",
        title=mp3_track.title,
        artist=mp3_track.artist,
        album=mp3_track.album,
        album_artist=mp3_track.album_artist,
        genre=mp3_track.genre,
        primary_genre=mp3_track.primary_genre,
        year=2026,
        duration_seconds=mp3_track.duration_seconds,
        file_ext=".flac",
        library_area="Library",
        track_number=mp3_track.track_number,
        disc_number=1,
        library_availability=LIBRARY_AVAILABLE,
        created_at=mp3_track.created_at,
        last_indexed_at=mp3_track.last_indexed_at,
    )
    db.add(flac_track)
    db.flush()
    flac_edition = models.MusicEdition(
        identity_key="prod6b-edition-000-lossless", release_id=identity.edition_id,
        display_title=mp3_track.album, year=2026, edition_type="lossless",
        source_scope="prod6b-scope-000-lossless", source_format_family="LOSSLESS",
    )
    # The edition must refer to a release, not another edition.
    flac_edition.release_id = db.get(models.MusicEdition, identity.edition_id).release_id
    db.add(flac_edition)
    db.flush()
    db.add(models.MusicTrackIdentity(track_id=flac_track.id, edition_id=flac_edition.id, recording_id=variant_recording.id))
    db.add(models.MusicTechnicalProfile(
        track_id=flac_track.id, probe_status="ok", codec="flac", container="flac",
        is_lossless=True, sample_rate_hz=96000, bit_depth_bits=24,
        channel_count=2, file_size_bytes=30_000_000,
    ))
    db.add(models.TrackRadioProfile(
        track_id=flac_track.id, primary_genre=mp3_track.genre,
        subgenres_json=json.dumps([mp3_track.genre]), moods_json='["focused", "warm"]',
        energy="medium", radio_tags_json='["hip-hop"]', source="prod6b-synthetic",
    ))
    db.flush()
    recording_by_track[flac_track.id] = variant_recording.id
    family_by_track[flac_track.id] = "hip-hop"
    evaluate_music_recording_preference(db, recording_id=variant_recording.id)

    down_rows = (all_rows[5], all_rows[55], all_rows[125])
    favorite_rows = (all_rows[6], all_rows[56], all_rows[126], down_rows[0])
    up_rows = (all_rows[7], all_rows[57], all_rows[127])
    for recording, track in favorite_rows:
        db.add(models.TrackFavorite(track_id=track.id, recording_id=recording.id, created_at=now - timedelta(minutes=30)))
    for recording, track in up_rows:
        db.add(models.TrackThumb(track_id=track.id, recording_id=recording.id, value=models.ThumbValue.up, created_at=now - timedelta(minutes=20)))
    for recording, track in down_rows:
        db.add(models.TrackThumb(track_id=track.id, recording_id=recording.id, value=models.ThumbValue.down, created_at=now - timedelta(minutes=10)))

    # Stable range of 0..5 qualified plays provides both deep and familiar material.
    for index, (recording, track) in enumerate(all_rows):
        for play_index in range(index % 6):
            db.add(models.PlaybackEvent(
                track_id=track.id, recording_id=recording.id, event_type="qualified_play",
                position_seconds=120.0,
                created_at=now - timedelta(days=20 + play_index, minutes=index),
            ))
    db.flush()
    preferred = db.query(models.MusicRecordingPreference).filter_by(recording_id=variant_recording.id).one()
    return StationQualityFixture(
        logical_recordings=200,
        physical_tracks=201,
        artists=tuple(artists),
        releases=tuple(releases),
        genre_families=tuple(FAMILY_GENRES),
        recording_types=("studio", "standard", "live", "acoustic", "remix", "instrumental"),
        seed_tracks=seed_tracks,
        recording_by_track=recording_by_track,
        family_by_track=family_by_track,
        physical_variant_recording_id=variant_recording.id,
        physical_variant_track_ids=(mp3_track.id, flac_track.id),
        preferred_variant_track_id=int(preferred.auto_preferred_track_id),
        down_recording_ids=tuple(row[0].id for row in down_rows),
        favorite_recording_ids=tuple(row[0].id for row in favorite_rows),
        up_recording_ids=tuple(row[0].id for row in up_rows),
    )
