from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import random
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from . import models
from .perf import INDEX_STATEMENTS
from .schema_maintenance import ensure_playback_identity_columns, ensure_recording_feedback_columns, ensure_scan_reconciliation_columns

UTC = timezone.utc
FIXTURE_VERSION = 1
DEFAULT_SEED = 31031


@dataclass(frozen=True)
class SyntheticLibrarySpec:
    physical_tracks: int
    seed: int = DEFAULT_SEED


@dataclass(frozen=True)
class SyntheticLibrarySummary:
    physical_tracks: int
    recordings: int
    releases: int
    artists: int
    editions: int
    playlists: int
    stations: int
    favorites: int
    thumbs: int
    playback_events: int
    preferences: int
    participation_rows: int
    checksum: str
    fixture_version: int = FIXTURE_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_temp_engine(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    ensure_playback_identity_columns(engine)
    ensure_recording_feedback_columns(engine)
    with engine.begin() as conn:
        for statement in INDEX_STATEMENTS:
            conn.execute(text(statement))
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def synthetic_track_path(track_id: int, *, codec: str, artist: str, release: str) -> str:
    root = "Music/Library/FLAC" if codec == "flac" else "Music/Library/MP3"
    return f"{root}/{artist}/{release}/{track_id:06d} Track {track_id:06d}.{codec}"


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()[:16]


def build_synthetic_library(db, spec: SyntheticLibrarySpec) -> SyntheticLibrarySummary:
    total = int(spec.physical_tracks)
    if total <= 0:
        raise ValueError("physical_tracks must be positive")
    rng = random.Random(spec.seed)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    artist_count = max(5, min(max(total // 50, 20), 2000))
    release_count = max(1, math.ceil(total / 10))
    recording_count = max(1, int(total * 0.75))
    playlist_count = max(1, min(10, total // 250 + 1))

    artists = [f"Artist {idx:04d}" for idx in range(artist_count)]
    release_rows = []
    for rid in range(1, release_count + 1):
        artist = artists[(rid - 1) % artist_count]
        title = f"Release {rid:05d}"
        release_rows.append({
            "id": rid,
            "identity_key": f"synthetic-release-{rid:06d}",
            "album_artist": artist,
            "title": title,
            "normalized_album_artist": _norm(artist),
            "normalized_title": _norm(title),
            "release_type": "album" if rid % 11 else "single",
            "created_at": now + timedelta(seconds=rid),
        })

    recording_types = ["unknown", "live", "acoustic", "remix", "instrumental", "radio_edit"]
    recording_rows = []
    for rec_id in range(1, recording_count + 1):
        artist = artists[(rec_id - 1) % artist_count]
        title = f"Track {rec_id:06d}"
        kind = recording_types[rec_id % len(recording_types)]
        recording_rows.append({
            "id": rec_id,
            "identity_key": f"synthetic-recording-{rec_id:06d}",
            "artist": artist,
            "title": title,
            "normalized_artist": _norm(artist),
            "normalized_title": _norm(title),
            "recording_type": kind,
            "version_hint": kind,
            "duration_bucket": str(170 + (rec_id % 90)),
            "created_at": now + timedelta(seconds=rec_id),
        })

    track_rows: list[dict[str, Any]] = []
    edition_rows: list[dict[str, Any]] = []
    identity_rows: list[dict[str, Any]] = []
    technical_rows: list[dict[str, Any]] = []
    radio_profile_rows: list[dict[str, Any]] = []
    first_track_by_recording: dict[int, int] = {}
    second_track_by_recording: dict[int, int] = {}
    for track_id in range(1, total + 1):
        rec_id = ((track_id - 1) % recording_count) + 1
        release_id = ((track_id - 1) // 10) % release_count + 1
        if track_id % 37 == 0:
            release_id = (release_id % release_count) + 1
        rec = recording_rows[rec_id - 1]
        release = release_rows[release_id - 1]
        codec = "flac" if track_id % 3 == 0 else "mp3"
        path = synthetic_track_path(track_id, codec=codec, artist=release["album_artist"], release=release["title"])
        track_rows.append({
            "id": track_id,
            "path": path,
            "relative_path": path,
            "title": rec["title"],
            "artist": rec["artist"],
            "album": release["title"],
            "album_artist": release["album_artist"],
            "genre": "Hip-Hop" if track_id % 5 == 0 else "Soul" if track_id % 5 == 1 else "Electronic" if track_id % 5 == 2 else "Rock" if track_id % 5 == 3 else "Jazz",
            "primary_genre": "Hip-Hop" if track_id % 5 == 0 else "Soul" if track_id % 5 == 1 else "Electronic" if track_id % 5 == 2 else "Rock" if track_id % 5 == 3 else "Jazz",
            "year": 1990 + (track_id % 36),
            "duration_seconds": 170.0 + (rec_id % 90),
            "file_ext": f".{codec}",
            "library_area": "Library" if track_id % 17 else "Discographies",
            "track_number": ((track_id - 1) % 10) + 1,
            "disc_number": 1,
            "metadata_source": "synthetic",
            "library_availability": "available",
            "created_at": now + timedelta(seconds=track_id),
            "last_indexed_at": now + timedelta(seconds=track_id),
        })
        edition_rows.append({
            "id": track_id,
            "identity_key": f"synthetic-edition-{track_id:06d}",
            "release_id": release_id,
            "display_title": release["title"],
            "year": 1990 + (track_id % 36),
            "edition_type": "standard",
            "source_scope": f"source-{track_id:06d}",
            "source_format_family": "LOSSLESS" if codec == "flac" else "LOSSY",
            "created_at": now + timedelta(seconds=track_id),
        })
        identity_rows.append({"id": track_id, "track_id": track_id, "edition_id": track_id, "recording_id": rec_id, "created_at": now + timedelta(seconds=track_id)})
        technical_rows.append({
            "id": track_id,
            "track_id": track_id,
            "probe_status": "ok",
            "probe_source": "synthetic",
            "probe_version": 1,
            "codec": codec,
            "container": codec,
            "is_lossless": codec == "flac",
            "sample_rate_hz": 48000 if codec == "flac" and track_id % 9 == 0 else 44100,
            "bit_depth_bits": 24 if codec == "flac" and track_id % 9 == 0 else 16 if codec == "flac" else None,
            "bitrate_bps": None if codec == "flac" else 320000,
            "channel_count": 2,
            "file_size_bytes": 3_000_000 + track_id,
            "probed_at": now + timedelta(seconds=track_id),
        })
        radio_profile_rows.append({
            "id": track_id,
            "track_id": track_id,
            "primary_genre": track_rows[-1]["primary_genre"],
            "subgenres_json": json.dumps([track_rows[-1]["primary_genre"].lower(), f"synthetic-{track_id % 7}"]),
            "moods_json": json.dumps(["warm" if track_id % 2 else "bright"]),
            "energy": "high" if track_id % 3 == 0 else "medium",
            "tempo_bucket": "mid",
            "radio_tags_json": "[]",
            "source": "synthetic",
        })
        if rec_id not in first_track_by_recording:
            first_track_by_recording[rec_id] = track_id
        elif rec_id not in second_track_by_recording:
            second_track_by_recording[rec_id] = track_id

    participation_rows = []
    for rec_id in range(1, recording_count + 1):
        if rec_id % 29 == 0:
            state = "blocked"
        elif rec_id % 23 == 0:
            state = "archived"
        elif rec_id % 11 == 0:
            state = "library_only"
        else:
            state = "included"
        participation_rows.append({"id": rec_id, "recording_id": rec_id, "participation_state": state, "state_source": "system", "reason_code": "synthetic"})

    preference_rows = []
    for rec_id, track_id in first_track_by_recording.items():
        if rec_id % 4 != 0:
            continue
        user_track_id = second_track_by_recording.get(rec_id) if rec_id % 31 == 0 else None
        preference_rows.append({
            "id": len(preference_rows) + 1,
            "recording_id": rec_id,
            "auto_preferred_track_id": track_id,
            "user_preferred_track_id": user_track_id,
            "decision_state": "selected",
            "confidence": "high",
            "reason_code": "synthetic_preference",
            "policy_version": 1,
            "candidate_count": 2 if rec_id in second_track_by_recording else 1,
            "eligible_candidate_count": 2 if rec_id in second_track_by_recording else 1,
            "evaluated_at": now,
        })

    favorite_rows = []
    thumb_rows = []
    playback_rows = []
    for rec_id, track_id in first_track_by_recording.items():
        if rec_id % 13 == 0:
            favorite_rows.append({"id": len(favorite_rows) + 1, "track_id": track_id, "recording_id": rec_id, "created_at": now + timedelta(minutes=rec_id)})
        if rec_id % 17 == 0:
            thumb_rows.append({"id": len(thumb_rows) + 1, "track_id": track_id, "recording_id": rec_id, "value": "down" if rec_id % 34 == 0 else "up", "created_at": now + timedelta(minutes=rec_id)})
        if rec_id % 3 == 0:
            playback_rows.append({"id": len(playback_rows) + 1, "track_id": track_id, "recording_id": rec_id, "event_type": "qualified_play", "position_seconds": 120.0, "created_at": now + timedelta(minutes=rec_id)})

    playlist_rows = [{"id": idx, "name": f"Synthetic Playlist {idx}", "description": "Synthetic benchmark playlist", "kind": "manual", "created_at": now} for idx in range(1, playlist_count + 1)]
    station_rows = [
        {"id": 1, "name": "Synthetic Favorites Radio", "type": "favorites", "seed_value": None, "favorite": True, "created_at": now},
        {"id": 2, "name": "Synthetic Recently Added", "type": "recently_added", "seed_value": None, "favorite": False, "created_at": now},
        {"id": 3, "name": "Synthetic Deep Cuts", "type": "deep_cuts", "seed_value": None, "favorite": False, "created_at": now},
        {"id": 4, "name": f"{artists[1]} Radio", "type": "artist", "seed_value": artists[1], "favorite": False, "created_at": now},
        {"id": 5, "name": "Electronic Radio", "type": "genre", "seed_value": "Electronic", "favorite": False, "created_at": now},
    ]
    playlist_track_rows = []
    for playlist_id in range(1, playlist_count + 1):
        for pos in range(1, min(100, total) + 1):
            track_id = ((playlist_id - 1) * 97 + pos - 1) % total + 1
            playlist_track_rows.append({"id": len(playlist_track_rows) + 1, "playlist_id": playlist_id, "track_id": track_id, "position": pos, "added_at": now + timedelta(seconds=pos)})

    table_data = [
        (models.MusicRelease, release_rows),
        (models.MusicRecording, recording_rows),
        (models.Track, track_rows),
        (models.MusicEdition, edition_rows),
        (models.MusicTrackIdentity, identity_rows),
        (models.MusicTechnicalProfile, technical_rows),
        (models.TrackRadioProfile, radio_profile_rows),
        (models.MusicRecordingParticipation, participation_rows),
        (models.MusicRecordingPreference, preference_rows),
        (models.TrackFavorite, favorite_rows),
        (models.TrackThumb, thumb_rows),
        (models.PlaybackEvent, playback_rows),
        (models.Playlist, playlist_rows),
        (models.Station, station_rows),
        (models.PlaylistTrack, playlist_track_rows),
    ]
    for model, rows in table_data:
        if rows:
            db.bulk_insert_mappings(model, rows)
    db.commit()

    payload = {
        "physical_tracks": total,
        "recordings": recording_count,
        "releases": release_count,
        "artists": artist_count,
        "first_paths": [track_rows[index]["relative_path"] for index in range(min(5, len(track_rows)))],
        "participation_sample": participation_rows[:12],
        "preference_sample": preference_rows[:12],
    }
    return SyntheticLibrarySummary(
        physical_tracks=total,
        recordings=recording_count,
        releases=release_count,
        artists=artist_count,
        editions=len(edition_rows),
        playlists=len(playlist_rows),
        stations=len(station_rows),
        favorites=len(favorite_rows),
        thumbs=len(thumb_rows),
        playback_events=len(playback_rows),
        preferences=len(preference_rows),
        participation_rows=len(participation_rows),
        checksum=_hash_payload(payload),
    )


def fixture_counts(db) -> dict[str, int]:
    tables = [
        "tracks", "music_releases", "music_editions", "music_recordings", "music_track_identities",
        "music_technical_profiles", "music_recording_preferences", "music_recording_participation",
        "track_favorites", "track_thumbs", "playback_events", "playlists", "playlist_tracks", "stations",
    ]
    return {table: int(db.execute(text(f'select count(*) from "{table}"')).scalar_one() or 0) for table in tables}


def database_checksum(db) -> str:
    payload = {
        "counts": fixture_counts(db),
        "paths": [row[0] for row in db.execute(text("select relative_path from tracks order by id limit 10")).all()],
        "recording_types": [row[0] for row in db.execute(text("select recording_type from music_recordings order by id limit 20")).all()],
    }
    return _hash_payload(payload)
