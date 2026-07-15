from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from . import models
from .media_identity import (
    duration_bucket,
    infer_music_recording_type,
    music_edition_identity_key,
    music_recording_identity_key,
    music_recording_version_hint,
    music_release_identity_key,
    music_source_format_family,
    normalize_music_recording_title,
    normalize_music_source_scope,
    normalize_people,
    normalize_text,
)


def _track_album_artist(track: models.Track) -> str | None:
    return track.album_artist or track.artist


def _track_release_title(track: models.Track) -> str | None:
    return track.album or track.title


def _get_or_create_music_release(db: Session, track: models.Track, source_scope: str) -> tuple[models.MusicRelease, bool]:
    album_artist = _track_album_artist(track)
    release_title = _track_release_title(track)
    identity_key = music_release_identity_key(album_artist, release_title, source_scope=source_scope)
    row = db.query(models.MusicRelease).filter_by(identity_key=identity_key).one_or_none()
    created = False
    if row is None:
        row = models.MusicRelease(identity_key=identity_key)
        db.add(row)
        created = True
    row.album_artist = album_artist
    row.title = release_title
    row.normalized_album_artist = normalize_people(album_artist)
    row.normalized_title = normalize_text(release_title)
    if not row.release_type:
        row.release_type = "unknown"
    db.flush()
    return row, created


def _get_or_create_music_edition(db: Session, track: models.Track, release: models.MusicRelease, source_scope: str) -> tuple[models.MusicEdition, bool]:
    identity_key = music_edition_identity_key(release.identity_key, source_scope)
    row = db.query(models.MusicEdition).filter_by(identity_key=identity_key).one_or_none()
    created = False
    if row is None:
        row = models.MusicEdition(identity_key=identity_key)
        db.add(row)
        created = True
    row.release_id = release.id
    row.display_title = track.album or release.title or track.title
    row.year = track.year
    if not row.edition_type:
        row.edition_type = "unknown"
    row.source_scope = source_scope
    row.source_format_family = music_source_format_family(track.file_ext, track.path)
    row.source_manifest_path = track.source_manifest_path
    db.flush()
    return row, created


def _get_or_create_music_recording(db: Session, track: models.Track, source_scope: str) -> tuple[models.MusicRecording, bool]:
    recording_type = infer_music_recording_type(track.title, track.album)
    identity_key = music_recording_identity_key(
        track.artist,
        track.title,
        recording_type,
        track.duration_seconds,
        source_scope=source_scope,
        relative_path=track.relative_path,
        path=track.path,
    )
    row = db.query(models.MusicRecording).filter_by(identity_key=identity_key).one_or_none()
    created = False
    if row is None:
        row = models.MusicRecording(identity_key=identity_key)
        db.add(row)
        created = True
    row.artist = track.artist
    row.title = track.title
    row.normalized_artist = normalize_people(track.artist)
    row.normalized_title = normalize_music_recording_title(track.title)
    row.recording_type = recording_type
    row.version_hint = music_recording_version_hint(track.title, track.album) or None
    row.duration_bucket = duration_bucket(track.duration_seconds, tolerance=10)
    db.flush()
    return row, created


def materialize_music_identity_for_track(db: Session, track: models.Track) -> models.MusicTrackIdentity:
    """Create or update the identity assignment for one physical Track row.

    This is intentionally database-only. It derives identity keys from existing
    Track metadata and path strings without inspecting the filesystem.
    """
    source_scope = normalize_music_source_scope(track.relative_path, track.path)
    release, _ = _get_or_create_music_release(db, track, source_scope)
    edition, _ = _get_or_create_music_edition(db, track, release, source_scope)
    recording, _ = _get_or_create_music_recording(db, track, source_scope)

    link = db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).one_or_none()
    if link is None:
        link = models.MusicTrackIdentity(track_id=track.id)
        db.add(link)
    link.edition_id = edition.id
    link.recording_id = recording.id
    db.flush()
    return link


def _selected_tracks(db: Session, track_ids: Iterable[int] | None) -> list[models.Track]:
    query = db.query(models.Track).order_by(models.Track.id.asc())
    if track_ids is not None:
        ids = list(dict.fromkeys(int(track_id) for track_id in track_ids))
        if not ids:
            return []
        query = query.filter(models.Track.id.in_(ids))
    return query.all()


def materialize_music_identity_graph(
    db: Session,
    *,
    track_ids: list[int] | None = None,
) -> dict[str, int]:
    """Materialize identity rows for selected Tracks without pruning or playback changes."""
    before = {
        "releases": db.query(models.MusicRelease).count(),
        "editions": db.query(models.MusicEdition).count(),
        "recordings": db.query(models.MusicRecording).count(),
        "track_identities": db.query(models.MusicTrackIdentity).count(),
    }
    tracks = _selected_tracks(db, track_ids)
    for track in tracks:
        materialize_music_identity_for_track(db, track)
    db.flush()
    after = {
        "releases": db.query(models.MusicRelease).count(),
        "editions": db.query(models.MusicEdition).count(),
        "recordings": db.query(models.MusicRecording).count(),
        "track_identities": db.query(models.MusicTrackIdentity).count(),
    }
    return {
        "tracks_seen": len(tracks),
        "releases_created": after["releases"] - before["releases"],
        "editions_created": after["editions"] - before["editions"],
        "recordings_created": after["recordings"] - before["recordings"],
        "track_identities_created": after["track_identities"] - before["track_identities"],
        "releases_total": after["releases"],
        "editions_total": after["editions"],
        "recordings_total": after["recordings"],
        "track_identities_total": after["track_identities"],
    }