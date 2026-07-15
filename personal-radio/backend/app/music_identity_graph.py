from __future__ import annotations

from dataclasses import dataclass
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

IDENTITY_BATCH_CHUNK_SIZE = 500


@dataclass(frozen=True)
class TrackIdentityDescriptor:
    track: models.Track
    source_scope: str
    release_key: str
    edition_key: str
    recording_key: str
    recording_type: str
    version_hint: str | None
    format_family: str


def chunked(values: Iterable, size: int = IDENTITY_BATCH_CHUNK_SIZE):
    chunk = []
    for value in values:
        chunk.append(value)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def unique_ints(values: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(int(value) for value in values))


def _track_album_artist(track: models.Track) -> str | None:
    return track.album_artist or track.artist


def _track_release_title(track: models.Track) -> str | None:
    return track.album or track.title


def _describe_track(track: models.Track) -> TrackIdentityDescriptor:
    source_scope = normalize_music_source_scope(track.relative_path, track.path)
    release_key = music_release_identity_key(_track_album_artist(track), _track_release_title(track), source_scope=source_scope)
    edition_key = music_edition_identity_key(release_key, source_scope)
    recording_type = infer_music_recording_type(track.title, track.album)
    recording_key = music_recording_identity_key(
        track.artist,
        track.title,
        recording_type,
        track.duration_seconds,
        source_scope=source_scope,
        relative_path=track.relative_path,
        path=track.path,
    )
    return TrackIdentityDescriptor(
        track=track,
        source_scope=source_scope,
        release_key=release_key,
        edition_key=edition_key,
        recording_key=recording_key,
        recording_type=recording_type,
        version_hint=music_recording_version_hint(track.title, track.album) or None,
        format_family=music_source_format_family(track.file_ext, track.path),
    )


def _load_tracks(db: Session, track_ids: Iterable[int] | None) -> list[models.Track]:
    if track_ids is None:
        return db.query(models.Track).order_by(models.Track.id.asc()).all()

    ids = unique_ints(track_ids)
    if not ids:
        return []

    tracks_by_id: dict[int, models.Track] = {}
    for chunk in chunked(ids):
        rows = db.query(models.Track).filter(models.Track.id.in_(chunk)).all()
        tracks_by_id.update({track.id: track for track in rows})
    return [tracks_by_id[track_id] for track_id in ids if track_id in tracks_by_id]


def _existing_by_identity_key(db: Session, model, keys: Iterable[str]) -> dict[str, object]:
    found = {}
    for chunk in chunked(list(dict.fromkeys(keys))):
        for row in db.query(model).filter(model.identity_key.in_(chunk)).all():
            found[row.identity_key] = row
    return found


def _existing_links_by_track_id(db: Session, track_ids: Iterable[int]) -> dict[int, models.MusicTrackIdentity]:
    found = {}
    for chunk in chunked(unique_ints(track_ids)):
        for row in db.query(models.MusicTrackIdentity).filter(models.MusicTrackIdentity.track_id.in_(chunk)).all():
            found[row.track_id] = row
    return found


def _aggregate_format_family(families: Iterable[str]) -> str:
    values = {str(family or "UNKNOWN").upper() for family in families}
    known = {family for family in values if family != "UNKNOWN"}
    if not known:
        return "UNKNOWN"
    if len(known) == 1:
        return next(iter(known))
    return "MIXED"


def _aggregate_manifest_path(paths: Iterable[str | None]) -> str | None:
    non_null = {str(path).strip() for path in paths if path and str(path).strip()}
    if len(non_null) == 1:
        return next(iter(non_null))
    return None


def _refresh_edition_aggregates(db: Session, editions: dict[str, models.MusicEdition]) -> None:
    if not editions:
        return
    by_id = {edition.id: edition for edition in editions.values() if edition.id is not None}
    if not by_id:
        return
    for chunk in chunked(by_id.keys()):
        rows = (
            db.query(
                models.MusicTrackIdentity.edition_id,
                models.Track.file_ext,
                models.Track.path,
                models.Track.source_manifest_path,
            )
            .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
            .filter(models.MusicTrackIdentity.edition_id.in_(chunk))
            .all()
        )
        formats_by_edition: dict[int, list[str]] = {edition_id: [] for edition_id in chunk}
        manifests_by_edition: dict[int, list[str | None]] = {edition_id: [] for edition_id in chunk}
        for edition_id, file_ext, path, manifest_path in rows:
            formats_by_edition.setdefault(edition_id, []).append(music_source_format_family(file_ext, path))
            manifests_by_edition.setdefault(edition_id, []).append(manifest_path)
        for edition_id in chunk:
            edition = by_id[edition_id]
            edition.source_format_family = _aggregate_format_family(formats_by_edition.get(edition_id, []))
            edition.source_manifest_path = _aggregate_manifest_path(manifests_by_edition.get(edition_id, []))
    db.flush()


def materialize_music_identity_for_track(db: Session, track: models.Track) -> models.MusicTrackIdentity:
    """Create or update the identity assignment for one physical Track row."""
    materialize_music_identity_graph(db, track_ids=[track.id])
    return db.query(models.MusicTrackIdentity).filter_by(track_id=track.id).one()


def materialize_music_identity_graph(
    db: Session,
    *,
    track_ids: list[int] | None = None,
) -> dict[str, int]:
    """Materialize identity rows for selected Tracks without pruning or playback changes.

    The batch path derives descriptors in memory, performs chunked key lookups, creates
    missing identity nodes, then creates or rebinds one MusicTrackIdentity per Track.
    """
    before = {
        "releases": db.query(models.MusicRelease).count(),
        "editions": db.query(models.MusicEdition).count(),
        "recordings": db.query(models.MusicRecording).count(),
        "track_identities": db.query(models.MusicTrackIdentity).count(),
    }
    tracks = _load_tracks(db, track_ids)
    descriptors = [_describe_track(track) for track in tracks]
    if not descriptors:
        return {
            "tracks_seen": 0,
            "releases_created": 0,
            "editions_created": 0,
            "recordings_created": 0,
            "track_identities_created": 0,
            "releases_total": before["releases"],
            "editions_total": before["editions"],
            "recordings_total": before["recordings"],
            "track_identities_total": before["track_identities"],
        }

    release_descriptors = {descriptor.release_key: descriptor for descriptor in descriptors}
    releases = _existing_by_identity_key(db, models.MusicRelease, release_descriptors.keys())
    for release_key, descriptor in release_descriptors.items():
        release = releases.get(release_key)
        if release is None:
            release = models.MusicRelease(identity_key=release_key)
            db.add(release)
            releases[release_key] = release
        track = descriptor.track
        album_artist = _track_album_artist(track)
        release_title = _track_release_title(track)
        release.album_artist = album_artist
        release.title = release_title
        release.normalized_album_artist = normalize_people(album_artist)
        release.normalized_title = normalize_text(release_title)
        if not release.release_type:
            release.release_type = "unknown"
    db.flush()

    edition_descriptors = {descriptor.edition_key: descriptor for descriptor in descriptors}
    editions = _existing_by_identity_key(db, models.MusicEdition, edition_descriptors.keys())
    for edition_key, descriptor in edition_descriptors.items():
        edition = editions.get(edition_key)
        if edition is None:
            edition = models.MusicEdition(identity_key=edition_key)
            db.add(edition)
            editions[edition_key] = edition
        track = descriptor.track
        release = releases[descriptor.release_key]
        edition.release_id = release.id
        edition.display_title = track.album or release.title or track.title
        edition.year = track.year
        if not edition.edition_type:
            edition.edition_type = "unknown"
        edition.source_scope = descriptor.source_scope
        edition.source_format_family = descriptor.format_family
        edition.source_manifest_path = track.source_manifest_path
    db.flush()

    recording_descriptors = {descriptor.recording_key: descriptor for descriptor in descriptors}
    recordings = _existing_by_identity_key(db, models.MusicRecording, recording_descriptors.keys())
    for recording_key, descriptor in recording_descriptors.items():
        recording = recordings.get(recording_key)
        if recording is None:
            recording = models.MusicRecording(identity_key=recording_key)
            db.add(recording)
            recordings[recording_key] = recording
        track = descriptor.track
        recording.artist = track.artist
        recording.title = track.title
        recording.normalized_artist = normalize_people(track.artist)
        recording.normalized_title = normalize_music_recording_title(track.title)
        recording.recording_type = descriptor.recording_type
        recording.version_hint = descriptor.version_hint
        recording.duration_bucket = duration_bucket(track.duration_seconds, tolerance=10)
    db.flush()

    links = _existing_links_by_track_id(db, [descriptor.track.id for descriptor in descriptors])
    for descriptor in descriptors:
        track = descriptor.track
        link = links.get(track.id)
        if link is None:
            link = models.MusicTrackIdentity(track_id=track.id)
            db.add(link)
            links[track.id] = link
        link.edition_id = editions[descriptor.edition_key].id
        link.recording_id = recordings[descriptor.recording_key].id
    db.flush()
    _refresh_edition_aggregates(db, editions)

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