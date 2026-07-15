from __future__ import annotations

from dataclasses import dataclass
from random import shuffle as shuffle_items
from typing import Iterable

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from . import models
from .availability import LIBRARY_AVAILABLE, is_track_available
from .listener_library import OccurrenceKey, listener_album_tracks, occurrence_keys, serialize_occurrences
from .music_recording_participation import PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY
from .routes.serializers import track_item

QUEUE_VISIBLE_STATES = {PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY}
QUEUE_INCLUDED_ONLY = {PARTICIPATION_INCLUDED}
SMART_USER_STATE_KEYS = {"favorites", "thumbs_up", "most_played", "recently_played"}
SMART_DISCOVERY_KEYS = {"recently_added", "never_played"}


@dataclass(frozen=True)
class TrackOccurrence:
    track_id: int
    release_id: int | None
    recording_id: int | None
    edition_id: int | None
    participation_state: str | None
    track: models.Track

    @property
    def key(self) -> tuple[str, int, int] | tuple[str, int]:
        if self.release_id is not None and self.recording_id is not None:
            return ("occurrence", self.release_id, self.recording_id)
        return ("track", self.track_id)

    @property
    def identity_backed(self) -> bool:
        return self.release_id is not None and self.recording_id is not None



def _identity_graph_present(db: Session) -> bool:
    return bool(db.query(models.MusicTrackIdentity.id).first())


def _legacy_album_queue_items(db: Session, *, artist: str | None, album: str | None, limit: int, shuffle: bool) -> list[dict]:
    query = db.query(models.Track).filter(models.Track.library_availability == LIBRARY_AVAILABLE)
    if artist:
        query = query.filter(models.Track.artist == artist)
    if album:
        query = query.filter(models.Track.album == album)
    rows = query.order_by(models.Track.relative_path, models.Track.title).limit(max(1, min(limit, 2000))).all()
    items = [track_item(row) for row in rows if is_track_available(row)]
    if shuffle:
        shuffle_items(items)
    return items


def _legacy_artist_queue_items(db: Session, *, artist: str, limit: int, shuffle: bool) -> list[dict]:
    rows = (
        db.query(models.Track)
        .filter(models.Track.library_availability == LIBRARY_AVAILABLE)
        .filter(or_(models.Track.artist == artist, models.Track.album_artist == artist))
        .order_by(models.Track.album, models.Track.relative_path, models.Track.title)
        .limit(max(1, min(limit, 5000)))
        .all()
    )
    items = [track_item(row) for row in rows if is_track_available(row)]
    if shuffle:
        shuffle_items(items)
    return items
def _chunks(values: list[int], size: int = 500):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _unique_ids(values: Iterable[int]) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value is None:
            continue
        item = int(value)
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def track_occurrences_by_id(db: Session, track_ids: list[int]) -> dict[int, TrackOccurrence]:
    ids = _unique_ids(track_ids)
    if not ids:
        return {}
    result: dict[int, TrackOccurrence] = {}
    for chunk in _chunks(ids):
        rows = (
            db.query(models.Track, models.MusicTrackIdentity, models.MusicEdition, models.MusicRecordingParticipation)
            .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.Track.id)
            .outerjoin(models.MusicEdition, models.MusicEdition.id == models.MusicTrackIdentity.edition_id)
            .outerjoin(models.MusicRecordingParticipation, models.MusicRecordingParticipation.recording_id == models.MusicTrackIdentity.recording_id)
            .filter(models.Track.id.in_(chunk))
            .all()
        )
        for track, identity, edition, participation in rows:
            result[track.id] = TrackOccurrence(
                track_id=track.id,
                release_id=edition.release_id if edition is not None else None,
                recording_id=identity.recording_id if identity is not None else None,
                edition_id=identity.edition_id if identity is not None else None,
                participation_state=participation.participation_state if participation is not None else (PARTICIPATION_INCLUDED if identity is not None else None),
                track=track,
            )
    return result


def _presentation_keys_for_occurrences(db: Session, occurrences: list[TrackOccurrence]) -> dict[tuple[int, int], OccurrenceKey]:
    pairs = [(int(item.release_id), int(item.recording_id)) for item in occurrences if item.release_id is not None and item.recording_id is not None]
    if not pairs:
        return {}
    release_ids = sorted({release_id for release_id, _recording_id in pairs})
    recording_ids = sorted({recording_id for _release_id, recording_id in pairs})
    wanted = set(pairs)
    disc_null = case((models.Track.disc_number.is_(None), 1), else_=0)
    track_null = case((models.Track.track_number.is_(None), 1), else_=0)
    row_number = func.row_number().over(
        partition_by=(models.MusicEdition.release_id, models.MusicTrackIdentity.recording_id),
        order_by=(disc_null.asc(), models.Track.disc_number.asc(), track_null.asc(), models.Track.track_number.asc(), models.Track.relative_path.asc(), models.Track.id.asc()),
    ).label("rn")
    subq = (
        db.query(
            models.MusicEdition.release_id.label("release_id"),
            models.MusicTrackIdentity.recording_id.label("recording_id"),
            models.Track.id.label("presentation_track_id"),
            models.MusicTrackIdentity.edition_id.label("edition_id"),
            func.coalesce(func.nullif(func.trim(models.MusicRelease.album_artist), ""), func.nullif(func.trim(models.MusicRecording.artist), ""), func.nullif(func.trim(models.Track.artist), ""), "").label("artist_sort"),
            func.coalesce(func.nullif(func.trim(models.MusicRelease.title), ""), func.nullif(func.trim(models.Track.album), ""), "").label("album_sort"),
            func.coalesce(func.nullif(func.trim(models.MusicRecording.title), ""), func.nullif(func.trim(models.Track.title), ""), "").label("title_sort"),
            models.Track.created_at.label("created_sort"),
            models.Track.last_indexed_at.label("indexed_sort"),
            row_number,
        )
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .join(models.MusicEdition, models.MusicEdition.id == models.MusicTrackIdentity.edition_id)
        .join(models.MusicRelease, models.MusicRelease.id == models.MusicEdition.release_id)
        .join(models.MusicRecording, models.MusicRecording.id == models.MusicTrackIdentity.recording_id)
        .filter(models.Track.library_availability == LIBRARY_AVAILABLE)
        .filter(models.MusicEdition.release_id.in_(release_ids), models.MusicTrackIdentity.recording_id.in_(recording_ids))
        .subquery()
    )
    rows = db.query(subq).filter(subq.c.rn == 1).all()
    result: dict[tuple[int, int], OccurrenceKey] = {}
    for row in rows:
        pair = (int(row.release_id), int(row.recording_id))
        if pair not in wanted:
            continue
        result[pair] = OccurrenceKey(
            release_id=pair[0],
            recording_id=pair[1],
            presentation_track_id=int(row.presentation_track_id),
            edition_id=int(row.edition_id),
            artist_sort=row.artist_sort or "",
            album_sort=row.album_sort or "",
            title_sort=row.title_sort or "",
            created_sort=row.created_sort,
            indexed_sort=row.indexed_sort,
        )
    return result


def _legacy_item(track: models.Track) -> dict | None:
    return track_item(track) if is_track_available(track) else None


def project_track_ids_to_listener_queue(
    db: Session,
    *,
    track_ids: list[int],
    allowed_participation_states: set[str],
    dedupe_occurrences: bool = True,
) -> list[dict]:
    occurrence_map = track_occurrences_by_id(db, track_ids)
    ordered_occurrences: list[TrackOccurrence] = []
    legacy_items: list[tuple[int, dict]] = []
    seen_keys: set[tuple] = set()
    for index, track_id in enumerate(track_ids):
        occurrence = occurrence_map.get(int(track_id))
        if occurrence is None:
            continue
        if occurrence.identity_backed:
            if occurrence.participation_state not in allowed_participation_states:
                continue
            key = occurrence.key
            if dedupe_occurrences and key in seen_keys:
                continue
            seen_keys.add(key)
            ordered_occurrences.append(occurrence)
            continue
        item = _legacy_item(occurrence.track)
        if item is None:
            continue
        key = occurrence.key
        if dedupe_occurrences and key in seen_keys:
            continue
        seen_keys.add(key)
        legacy_items.append((index, item))

    key_by_pair = _presentation_keys_for_occurrences(db, ordered_occurrences)
    keys: list[OccurrenceKey] = []
    order_slots: list[tuple[int, tuple[int, int]]] = []
    for index, occurrence in enumerate(ordered_occurrences):
        pair = (int(occurrence.release_id), int(occurrence.recording_id))
        key = key_by_pair.get(pair)
        if key is None:
            continue
        keys.append(key)
        order_slots.append((index, pair))
    projected = serialize_occurrences(db, keys)
    by_pair = {(item["release_id"], item["recording_id"]): item for item in projected}
    combined: list[tuple[int, dict]] = []
    combined.extend(legacy_items)
    for index, pair in order_slots:
        item = by_pair.get(pair)
        if item is not None:
            combined.append((index, item))
    combined.sort(key=lambda row: row[0])
    return [item for _index, item in combined]


def album_queue_items(db: Session, *, artist: str | None, album: str | None, release_id: int | None, limit: int, shuffle: bool) -> list[dict]:
    if not _identity_graph_present(db):
        return _legacy_album_queue_items(db, artist=artist, album=album, limit=limit, shuffle=shuffle)
    items = listener_album_tracks(db, release_id=release_id, artist=artist, album=album)[:max(1, min(limit, 2000))]
    if shuffle:
        shuffle_items(items)
    return items


def artist_queue_items(db: Session, *, artist: str, limit: int, shuffle: bool) -> list[dict]:
    if not _identity_graph_present(db):
        return _legacy_artist_queue_items(db, artist=artist, limit=limit, shuffle=shuffle)
    allowed = QUEUE_INCLUDED_ONLY if shuffle else QUEUE_VISIBLE_STATES
    keys = occurrence_keys(db, artist=artist, limit=max(1, min(limit * 4, 5000)), sort="artist_album_track")
    items = serialize_occurrences(db, keys)
    items = [item for item in items if item.get("participation_state") in allowed]
    items = items[:max(1, min(limit, 5000))]
    if shuffle:
        shuffle_items(items)
    return items


def playlist_projected_items(db: Session, *, playlist_id: int, shuffle: bool = False) -> list[dict]:
    rows = db.query(models.PlaylistTrack).filter_by(playlist_id=playlist_id).order_by(models.PlaylistTrack.position, models.PlaylistTrack.id).all()
    items = project_track_ids_to_listener_queue(db, track_ids=[row.track_id for row in rows], allowed_participation_states=QUEUE_VISIBLE_STATES, dedupe_occurrences=True)
    if shuffle:
        shuffle_items(items)
    return items


def playlist_active_count(db: Session, *, playlist_id: int) -> int:
    return len(playlist_projected_items(db, playlist_id=playlist_id))


def _occurrence_key_for_track_id(db: Session, track_id: int) -> tuple | None:
    occurrence = track_occurrences_by_id(db, [track_id]).get(int(track_id))
    return occurrence.key if occurrence is not None else None


def validate_track_addition(db: Session, *, track_id: int) -> TrackOccurrence:
    occurrence = track_occurrences_by_id(db, [track_id]).get(int(track_id))
    if occurrence is None:
        raise ValueError("Track not found")
    if not is_track_available(occurrence.track):
        raise PermissionError("Track is unavailable in the current library")
    if occurrence.identity_backed and occurrence.participation_state not in QUEUE_VISIBLE_STATES:
        raise PermissionError("Recording is not visible in active playlists")
    return occurrence


def playlist_has_occurrence(db: Session, *, playlist_id: int, occurrence_key: tuple) -> bool:
    rows = db.query(models.PlaylistTrack.track_id).filter_by(playlist_id=playlist_id).all()
    existing = track_occurrences_by_id(db, [row[0] for row in rows])
    for row in rows:
        occurrence = existing.get(row[0])
        if occurrence is not None and occurrence.key == occurrence_key:
            return True
    return False


def remove_playlist_occurrence(db: Session, *, playlist_id: int, track_id: int) -> None:
    key = _occurrence_key_for_track_id(db, track_id)
    if key is None:
        return
    rows = db.query(models.PlaylistTrack).filter_by(playlist_id=playlist_id).all()
    occurrence_map = track_occurrences_by_id(db, [row.track_id for row in rows])
    for row in rows:
        occurrence = occurrence_map.get(row.track_id)
        if occurrence is not None and occurrence.key == key:
            db.delete(row)
    db.flush()


def reorder_playlist_by_occurrences(db: Session, *, playlist_id: int, track_ids: list[int]) -> None:
    requested: dict[tuple, int] = {}
    for index, track_id in enumerate(track_ids, start=1):
        key = _occurrence_key_for_track_id(db, track_id)
        if key is not None and key not in requested:
            requested[key] = index
    rows = db.query(models.PlaylistTrack).filter_by(playlist_id=playlist_id).order_by(models.PlaylistTrack.position, models.PlaylistTrack.id).all()
    occurrence_map = track_occurrences_by_id(db, [row.track_id for row in rows])
    visible: list[models.PlaylistTrack] = []
    hidden: list[models.PlaylistTrack] = []
    for row in rows:
        occurrence = occurrence_map.get(row.track_id)
        if occurrence is not None and occurrence.key in requested:
            visible.append(row)
        else:
            hidden.append(row)
    visible.sort(key=lambda row: requested[occurrence_map[row.track_id].key])
    position = 1
    for row in visible + hidden:
        row.position = position
        position += 1
    db.flush()


def smart_allowed_states(key: str) -> set[str]:
    if key in SMART_DISCOVERY_KEYS:
        return QUEUE_INCLUDED_ONLY
    return QUEUE_VISIBLE_STATES


def smart_queue_items(db: Session, *, track_ids: list[int], key: str, shuffle: bool) -> list[dict]:
    items = project_track_ids_to_listener_queue(db, track_ids=track_ids, allowed_participation_states=smart_allowed_states(key), dedupe_occurrences=True)
    if shuffle:
        shuffle_items(items)
    return items
