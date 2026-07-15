from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from . import models
from .availability import LIBRARY_AVAILABLE
from .music_recording_participation import PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY
from .music_source_preference import resolve_effective_music_sources_read_only

VISIBLE_PARTICIPATION_STATES = (PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY)
MAX_TRACK_LIMIT = 500
MAX_PAGE_LIMIT = 200


@dataclass(frozen=True)
class OccurrenceKey:
    release_id: int
    recording_id: int
    presentation_track_id: int
    edition_id: int
    artist_sort: str
    album_sort: str
    title_sort: str
    created_sort: object | None
    indexed_sort: object | None



def _identity_graph_present(db: Session) -> bool:
    return bool(db.query(models.MusicTrackIdentity.id).first())


def _legacy_track_query(db: Session, *, artist: str | None = None, album: str | None = None, q: str | None = None, sort: str = "artist_album_track"):
    query = db.query(models.Track).filter(models.Track.library_availability == LIBRARY_AVAILABLE)
    if artist:
        query = query.filter(or_(models.Track.artist == artist, models.Track.album_artist == artist))
    if album:
        query = query.filter(models.Track.album == album)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(or_(models.Track.title.ilike(term), models.Track.artist.ilike(term), models.Track.album.ilike(term), models.Track.album_artist.ilike(term), models.Track.genre.ilike(term), models.Track.relative_path.ilike(term), models.Track.library_area.ilike(term)))
    if sort == "title":
        query = query.order_by(models.Track.title)
    elif sort == "album":
        query = query.order_by(models.Track.album, models.Track.relative_path, models.Track.title)
    elif sort == "created_desc":
        query = query.order_by(models.Track.created_at.desc())
    else:
        query = query.order_by(models.Track.artist, models.Track.album, models.Track.relative_path, models.Track.title)
    return query


def _legacy_track_item(track: models.Track) -> dict:
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "genre": track.genre,
        "primary_genre": getattr(track, "primary_genre", None),
        "year": track.year,
        "duration_seconds": track.duration_seconds,
        "file_ext": track.file_ext,
        "library_area": track.library_area,
        "metadata_source": getattr(track, "metadata_source", None),
        "source_manifest_path": getattr(track, "source_manifest_path", None),
        "source_manifest_version": getattr(track, "source_manifest_version", None),
        "source_metadata_version": getattr(track, "source_metadata_version", None),
        "track_number": getattr(track, "track_number", None),
        "disc_number": getattr(track, "disc_number", None),
        "library_availability": getattr(track, "library_availability", LIBRARY_AVAILABLE),
        "unavailable_since": _iso(getattr(track, "unavailable_since", None)),
        "stream_url": f"/api/media/tracks/{track.id}/stream",
        "cover_url": f"/api/media/tracks/{track.id}/cover",
    }


def _legacy_tracks(db: Session, *, limit: int = 100, offset: int = 0, artist: str | None = None, album: str | None = None, q: str | None = None, sort: str = "artist_album_track") -> list[dict]:
    rows = _legacy_track_query(db, artist=artist, album=album, q=q, sort=sort).offset(max(offset, 0)).limit(min(max(limit, 1), MAX_TRACK_LIMIT)).all()
    return [_legacy_track_item(row) for row in rows]


def _legacy_tracks_page(db: Session, *, limit: int = 100, offset: int = 0, artist: str | None = None, album: str | None = None, q: str | None = None, sort: str = "artist_album_track") -> dict:
    bounded_limit = min(max(limit, 1), MAX_PAGE_LIMIT)
    bounded_offset = max(offset, 0)
    query = _legacy_track_query(db, artist=artist, album=album, q=q, sort=sort)
    total = int(query.order_by(None).count() or 0)
    items = [_legacy_track_item(row) for row in query.offset(bounded_offset).limit(bounded_limit).all()]
    return {"items": items, "total": total, "limit": bounded_limit, "offset": bounded_offset, "has_more": bounded_offset + len(items) < total}


def _legacy_summary(db: Session) -> dict:
    query = db.query(models.Track).filter(models.Track.library_availability == LIBRARY_AVAILABLE)
    return {
        "tracks": int(query.with_entities(func.count(models.Track.id)).scalar() or 0),
        "artists": int(query.with_entities(func.count(func.distinct(models.Track.artist))).scalar() or 0),
        "albums": int(query.with_entities(func.count(func.distinct(models.Track.album))).scalar() or 0),
    }


def _legacy_artists(db: Session, *, limit: int | None = None, offset: int = 0, q: str | None = None) -> list[dict]:
    query = (
        db.query(models.Track.artist, func.count(models.Track.id), func.count(func.distinct(models.Track.album)))
        .filter(models.Track.library_availability == LIBRARY_AVAILABLE)
        .group_by(models.Track.artist)
        .order_by(models.Track.artist)
    )
    if offset:
        query = query.offset(max(offset, 0))
    if limit is not None:
        query = query.limit(min(max(limit, 1), MAX_PAGE_LIMIT))
    return [{"name": name, "track_count": count, "album_count": albums} for name, count, albums in query.all() if name]


def _legacy_albums(db: Session, *, limit: int | None = None, offset: int = 0, q: str | None = None, recent: bool = False, artist: str | None = None) -> list[dict]:
    query = (
        db.query(models.Track.album, models.Track.artist, func.min(models.Track.year), func.count(models.Track.id), func.min(models.Track.id))
        .filter(models.Track.library_availability == LIBRARY_AVAILABLE)
    )
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(or_(models.Track.album.ilike(term), models.Track.artist.ilike(term), models.Track.genre.ilike(term)))
    query = query.group_by(models.Track.album, models.Track.artist)
    query = query.order_by(func.max(models.Track.created_at).desc() if recent else models.Track.artist, models.Track.album)
    if offset:
        query = query.offset(max(offset, 0))
    if limit is not None:
        query = query.limit(min(max(limit, 1), MAX_PAGE_LIMIT))
    return [{"title": album, "artist": artist, "year": year, "track_count": count, "cover_url": f"/api/media/albums/cover?artist={artist}&album={album}"} for album, artist, year, count, _track_id in query.all()]


def _legacy_global_music_search(db: Session, *, q: str) -> dict:
    term = q.strip().lower()
    artists = _legacy_artists(db, q=q, limit=20)
    albums = _legacy_albums(db, q=q, limit=30)
    tracks = _legacy_tracks(db, q=q, limit=80)
    stations = [{"name": item["name"] + " Radio", "type": "artist", "seed_value": item["name"], "track_count": item["track_count"]} for item in artists[:5]]
    return {"artists": artists, "albums": albums, "tracks": tracks, "stations": stations}

def _nonempty(column):
    return func.nullif(func.trim(column), "")


def _display_artist_expr():
    return func.coalesce(
        _nonempty(models.MusicRelease.album_artist),
        _nonempty(models.MusicRecording.artist),
        _nonempty(models.Track.artist),
        "",
    )


def _base_occurrence_query(
    db: Session,
    *,
    artist: str | None = None,
    album: str | None = None,
    q: str | None = None,
    release_id: int | None = None,
):
    display_artist = _display_artist_expr().label("artist_sort")
    album_sort = func.coalesce(_nonempty(models.MusicRelease.title), _nonempty(models.Track.album), "").label("album_sort")
    title_sort = func.coalesce(_nonempty(models.MusicRecording.title), _nonempty(models.Track.title), "").label("title_sort")
    disc_null = case((models.Track.disc_number.is_(None), 1), else_=0)
    track_null = case((models.Track.track_number.is_(None), 1), else_=0)
    row_number = func.row_number().over(
        partition_by=(models.MusicEdition.release_id, models.MusicTrackIdentity.recording_id),
        order_by=(
            disc_null.asc(),
            models.Track.disc_number.asc(),
            track_null.asc(),
            models.Track.track_number.asc(),
            models.Track.relative_path.asc(),
            models.Track.id.asc(),
        ),
    ).label("rn")

    query = (
        db.query(
            models.MusicEdition.release_id.label("release_id"),
            models.MusicTrackIdentity.recording_id.label("recording_id"),
            models.Track.id.label("presentation_track_id"),
            models.MusicTrackIdentity.edition_id.label("edition_id"),
            display_artist,
            album_sort,
            title_sort,
            models.Track.created_at.label("created_sort"),
            models.Track.last_indexed_at.label("indexed_sort"),
            row_number,
        )
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .join(models.MusicEdition, models.MusicEdition.id == models.MusicTrackIdentity.edition_id)
        .join(models.MusicRelease, models.MusicRelease.id == models.MusicEdition.release_id)
        .join(models.MusicRecording, models.MusicRecording.id == models.MusicTrackIdentity.recording_id)
        .outerjoin(models.MusicRecordingParticipation, models.MusicRecordingParticipation.recording_id == models.MusicRecording.id)
        .filter(models.Track.library_availability == LIBRARY_AVAILABLE)
        .filter(or_(models.MusicRecordingParticipation.id.is_(None), models.MusicRecordingParticipation.participation_state.in_(VISIBLE_PARTICIPATION_STATES)))
    )
    if release_id is not None:
        query = query.filter(models.MusicEdition.release_id == int(release_id))
    if artist:
        value = artist.strip()
        query = query.filter(or_(models.MusicRelease.album_artist == value, models.MusicRecording.artist == value, models.Track.artist == value, models.Track.album_artist == value))
    if album:
        value = album.strip()
        query = query.filter(or_(models.MusicRelease.title == value, models.Track.album == value))
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(or_(
            models.MusicRecording.title.ilike(term),
            models.MusicRecording.artist.ilike(term),
            models.MusicRelease.title.ilike(term),
            models.MusicRelease.album_artist.ilike(term),
            models.Track.genre.ilike(term),
            models.Track.primary_genre.ilike(term),
            models.Track.relative_path.ilike(term),
            models.Track.title.ilike(term),
            models.Track.artist.ilike(term),
            models.Track.album.ilike(term),
            models.Track.album_artist.ilike(term),
        ))
    return query


def occurrence_query(
    db: Session,
    *,
    artist: str | None = None,
    album: str | None = None,
    q: str | None = None,
    release_id: int | None = None,
    sort: str = "artist_album_track",
):
    subq = _base_occurrence_query(db, artist=artist, album=album, q=q, release_id=release_id).subquery()
    query = db.query(subq).filter(subq.c.rn == 1)
    if sort == "title":
        query = query.order_by(subq.c.title_sort.asc(), subq.c.artist_sort.asc(), subq.c.album_sort.asc(), subq.c.presentation_track_id.asc())
    elif sort == "album":
        query = query.order_by(subq.c.album_sort.asc(), subq.c.artist_sort.asc(), subq.c.title_sort.asc(), subq.c.presentation_track_id.asc())
    elif sort == "created_desc":
        query = query.order_by(subq.c.created_sort.desc(), subq.c.indexed_sort.desc(), subq.c.presentation_track_id.desc())
    else:
        query = query.order_by(subq.c.artist_sort.asc(), subq.c.album_sort.asc(), subq.c.presentation_track_id.asc(), subq.c.title_sort.asc(), subq.c.release_id.asc(), subq.c.recording_id.asc())
    return query


def occurrence_keys(
    db: Session,
    *,
    limit: int | None = None,
    offset: int = 0,
    artist: str | None = None,
    album: str | None = None,
    q: str | None = None,
    release_id: int | None = None,
    sort: str = "artist_album_track",
) -> list[OccurrenceKey]:
    query = occurrence_query(db, artist=artist, album=album, q=q, release_id=release_id, sort=sort)
    if offset:
        query = query.offset(max(offset, 0))
    if limit is not None:
        query = query.limit(max(1, limit))
    return [
        OccurrenceKey(
            release_id=int(row.release_id),
            recording_id=int(row.recording_id),
            presentation_track_id=int(row.presentation_track_id),
            edition_id=int(row.edition_id),
            artist_sort=row.artist_sort or "",
            album_sort=row.album_sort or "",
            title_sort=row.title_sort or "",
            created_sort=row.created_sort,
            indexed_sort=row.indexed_sort,
        )
        for row in query.all()
    ]


def occurrence_count(db: Session, **filters) -> int:
    query = occurrence_query(db, **filters)
    return int(query.order_by(None).count() or 0)



def _occurrence_subquery(
    db: Session,
    *,
    artist: str | None = None,
    album: str | None = None,
    q: str | None = None,
    release_id: int | None = None,
):
    return occurrence_query(db, artist=artist, album=album, q=q, release_id=release_id).order_by(None).subquery()


def _artist_aggregate_query(db: Session, *, q: str | None = None):
    occ = _occurrence_subquery(db)
    query = (
        db.query(
            occ.c.artist_sort.label("name"),
            func.count().label("track_count"),
            func.count(func.distinct(occ.c.release_id)).label("album_count"),
        )
        .filter(func.trim(occ.c.artist_sort) != "")
        .group_by(occ.c.artist_sort)
    )
    if q:
        query = query.filter(occ.c.artist_sort.ilike(f"%{q.strip()}%"))
    return query.order_by(occ.c.artist_sort.asc())


def _release_aggregate_query(
    db: Session,
    *,
    artist: str | None = None,
    q: str | None = None,
    recent: bool = False,
):
    occ = _occurrence_subquery(db, artist=artist, q=q)
    title_expr = func.coalesce(_nonempty(models.MusicRelease.title), occ.c.album_sort, "")
    artist_expr = func.coalesce(_nonempty(models.MusicRelease.album_artist), occ.c.artist_sort, "")
    recent_created = func.max(occ.c.created_sort)
    recent_indexed = func.max(occ.c.indexed_sort)
    query = (
        db.query(
            occ.c.release_id.label("release_id"),
            models.MusicRelease.release_type.label("release_type"),
            title_expr.label("title"),
            artist_expr.label("artist"),
            func.min(models.Track.year).label("year"),
            func.count().label("track_count"),
            func.min(occ.c.presentation_track_id).label("presentation_track_id"),
            recent_created.label("recent_created"),
            recent_indexed.label("recent_indexed"),
        )
        .join(models.MusicRelease, models.MusicRelease.id == occ.c.release_id)
        .join(models.Track, models.Track.id == occ.c.presentation_track_id)
        .group_by(occ.c.release_id, models.MusicRelease.release_type, title_expr, artist_expr)
    )
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(or_(title_expr.ilike(term), artist_expr.ilike(term)))
    if recent:
        query = query.order_by(recent_created.desc(), recent_indexed.desc(), occ.c.release_id.desc())
    else:
        query = query.order_by(artist_expr.asc(), title_expr.asc(), occ.c.release_id.asc())
    return query


def _release_row_item(row) -> dict:
    presentation_track_id = int(row.presentation_track_id) if row.presentation_track_id is not None else 0
    return {
        "release_id": int(row.release_id),
        "release_type": row.release_type,
        "title": row.title,
        "artist": row.artist,
        "year": row.year,
        "track_count": int(row.track_count or 0),
        "cover_url": f"/api/media/tracks/{presentation_track_id}/cover",
    }

def _track_rows_by_ids(db: Session, track_ids: Iterable[int]) -> dict[int, models.Track]:
    ids = list(dict.fromkeys(int(track_id) for track_id in track_ids if track_id is not None))
    if not ids:
        return {}
    return {row.id: row for row in db.query(models.Track).filter(models.Track.id.in_(ids)).all()}


def _context_rows(db: Session, keys: list[OccurrenceKey]):
    presentation_ids = [key.presentation_track_id for key in keys]
    if not presentation_ids:
        return {}
    rows = (
        db.query(
            models.Track,
            models.MusicTrackIdentity,
            models.MusicEdition,
            models.MusicRelease,
            models.MusicRecording,
            models.MusicRecordingParticipation,
        )
        .join(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.Track.id)
        .join(models.MusicEdition, models.MusicEdition.id == models.MusicTrackIdentity.edition_id)
        .join(models.MusicRelease, models.MusicRelease.id == models.MusicEdition.release_id)
        .join(models.MusicRecording, models.MusicRecording.id == models.MusicTrackIdentity.recording_id)
        .outerjoin(models.MusicRecordingParticipation, models.MusicRecordingParticipation.recording_id == models.MusicRecording.id)
        .filter(models.Track.id.in_(presentation_ids))
        .all()
    )
    return {track.id: (track, identity, edition, release, recording, participation) for track, identity, edition, release, recording, participation in rows}


def _iso(value):
    return value.isoformat() if value else None


def _serialize_item(
    *,
    presentation_track: models.Track,
    effective_track: models.Track,
    identity: models.MusicTrackIdentity,
    edition: models.MusicEdition,
    release: models.MusicRelease,
    recording: models.MusicRecording,
    participation: models.MusicRecordingParticipation | None,
    resolution,
) -> dict:
    participation_state = participation.participation_state if participation is not None else PARTICIPATION_INCLUDED
    title = recording.title or presentation_track.title
    artist = recording.artist or presentation_track.artist
    album = release.title or presentation_track.album
    return {
        "id": effective_track.id,
        "title": title,
        "artist": artist,
        "album": album,
        "album_artist": release.album_artist or presentation_track.album_artist,
        "genre": presentation_track.genre,
        "primary_genre": getattr(presentation_track, "primary_genre", None),
        "year": presentation_track.year or edition.year,
        "duration_seconds": presentation_track.duration_seconds,
        "file_ext": effective_track.file_ext,
        "library_area": effective_track.library_area,
        "metadata_source": getattr(presentation_track, "metadata_source", None),
        "source_manifest_path": getattr(presentation_track, "source_manifest_path", None),
        "source_manifest_version": getattr(presentation_track, "source_manifest_version", None),
        "source_metadata_version": getattr(presentation_track, "source_metadata_version", None),
        "track_number": presentation_track.track_number,
        "disc_number": presentation_track.disc_number,
        "library_availability": effective_track.library_availability,
        "unavailable_since": _iso(getattr(effective_track, "unavailable_since", None)),
        "stream_url": f"/api/media/tracks/{effective_track.id}/stream",
        "cover_url": f"/api/media/tracks/{presentation_track.id}/cover",
        "recording_id": recording.id,
        "release_id": release.id,
        "edition_id": edition.id,
        "presentation_track_id": presentation_track.id,
        "effective_track_id": effective_track.id,
        "participation_state": participation_state,
        "source_resolution": resolution.source,
        "source_confidence": resolution.confidence,
        "source_reason_code": resolution.reason_code,
        "release_type": release.release_type,
    }


def serialize_occurrences(db: Session, keys: list[OccurrenceKey]) -> list[dict]:
    if not keys:
        return []
    contexts = _context_rows(db, keys)
    recording_ids = [key.recording_id for key in keys]
    resolutions = resolve_effective_music_sources_read_only(db, recording_ids=recording_ids)
    effective_tracks = _track_rows_by_ids(db, [resolution.track_id for resolution in resolutions.values() if resolution.track_id is not None])
    items: list[dict] = []
    for key in keys:
        context = contexts.get(key.presentation_track_id)
        resolution = resolutions.get(key.recording_id)
        if context is None or resolution is None or resolution.track_id is None:
            continue
        effective_track = effective_tracks.get(resolution.track_id)
        if effective_track is None:
            continue
        presentation_track, identity, edition, release, recording, participation = context
        items.append(_serialize_item(
            presentation_track=presentation_track,
            effective_track=effective_track,
            identity=identity,
            edition=edition,
            release=release,
            recording=recording,
            participation=participation,
            resolution=resolution,
        ))
    return items


def listener_tracks(
    db: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    artist: str | None = None,
    album: str | None = None,
    q: str | None = None,
    release_id: int | None = None,
    sort: str = "artist_album_track",
) -> list[dict]:
    if not _identity_graph_present(db):
        return _legacy_tracks(db, limit=limit, offset=offset, artist=artist, album=album, q=q, sort=sort)
    bounded_limit = min(max(limit, 1), MAX_TRACK_LIMIT)
    keys = occurrence_keys(db, limit=bounded_limit, offset=max(offset, 0), artist=artist, album=album, q=q, release_id=release_id, sort=sort)
    return serialize_occurrences(db, keys)


def listener_tracks_page(
    db: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    artist: str | None = None,
    album: str | None = None,
    q: str | None = None,
    sort: str = "artist_album_track",
) -> dict:
    if not _identity_graph_present(db):
        return _legacy_tracks_page(db, limit=limit, offset=offset, artist=artist, album=album, q=q, sort=sort)
    bounded_limit = min(max(limit, 1), MAX_PAGE_LIMIT)
    bounded_offset = max(offset, 0)
    total = occurrence_count(db, artist=artist, album=album, q=q, sort=sort)
    items = listener_tracks(db, limit=bounded_limit, offset=bounded_offset, artist=artist, album=album, q=q, sort=sort)
    return {"items": items, "total": total, "limit": bounded_limit, "offset": bounded_offset, "has_more": bounded_offset + len(items) < total}


def listener_summary(db: Session) -> dict:
    if not _identity_graph_present(db):
        return _legacy_summary(db)
    occ = _occurrence_subquery(db)
    row = db.query(
        func.count().label("tracks"),
        func.count(func.distinct(case((func.trim(occ.c.artist_sort) != "", occ.c.artist_sort)))).label("artists"),
        func.count(func.distinct(occ.c.release_id)).label("albums"),
    ).one()
    return {"tracks": int(row.tracks or 0), "artists": int(row.artists or 0), "albums": int(row.albums or 0)}

def listener_artists(db: Session, *, limit: int | None = None, offset: int = 0, q: str | None = None) -> list[dict]:
    if not _identity_graph_present(db):
        return _legacy_artists(db, limit=limit, offset=offset, q=q)
    query = _artist_aggregate_query(db, q=q)
    if offset:
        query = query.offset(max(offset, 0))
    if limit is not None:
        query = query.limit(min(max(limit, 1), MAX_PAGE_LIMIT))
    return [
        {"name": row.name, "track_count": int(row.track_count or 0), "album_count": int(row.album_count or 0)}
        for row in query.all()
        if row.name
    ]

def listener_artist_detail(db: Session, artist: str) -> dict:
    tracks_page = listener_tracks_page(db, artist=artist, limit=50, offset=0)
    albums = listener_artist_albums(db, artist)
    return {"name": artist, "track_count": tracks_page["total"], "album_count": len(albums), "albums": albums, "tracks": tracks_page["items"]}


def _album_groups(db: Session, *, q: str | None = None) -> list[dict]:
    return listener_albums(db, q=q)

def listener_albums(db: Session, *, limit: int | None = None, offset: int = 0, q: str | None = None, recent: bool = False, artist: str | None = None) -> list[dict]:
    if not _identity_graph_present(db):
        return _legacy_albums(db, limit=limit, offset=offset, q=q, recent=recent, artist=artist)
    query = _release_aggregate_query(db, artist=artist, q=q, recent=recent)
    if offset:
        query = query.offset(max(offset, 0))
    if limit is not None:
        query = query.limit(min(max(limit, 1), MAX_PAGE_LIMIT))
    return [_release_row_item(row) for row in query.all()]

def listener_artist_albums(db: Session, artist: str) -> list[dict]:
    return listener_albums(db, artist=artist)

def listener_album_tracks(
    db: Session,
    *,
    release_id: int | None = None,
    artist: str | None = None,
    album: str | None = None,
) -> list[dict]:
    if not _identity_graph_present(db):
        return _legacy_tracks(db, artist=artist, album=album, limit=MAX_TRACK_LIMIT)
    if release_id is not None:
        return listener_tracks(db, release_id=release_id, limit=MAX_TRACK_LIMIT, sort="artist_album_track")
    if not artist or not album:
        return []
    keys = occurrence_keys(db, artist=artist, album=album, sort="created_desc")
    if not keys:
        return []
    by_release: dict[int, list[OccurrenceKey]] = defaultdict(list)
    for key in keys:
        by_release[key.release_id].append(key)
    selected_release_id = sorted(by_release, key=lambda rid: max(k.created_sort or k.indexed_sort or 0 for k in by_release[rid]), reverse=True)[0]
    return listener_tracks(db, release_id=selected_release_id, limit=MAX_TRACK_LIMIT, sort="artist_album_track")


def library_search(db: Session, *, q: str) -> list[dict]:
    return listener_tracks(db, q=q, limit=300, sort="artist_album_track")


def global_music_search(db: Session, *, q: str) -> dict:
    if not _identity_graph_present(db):
        return _legacy_global_music_search(db, q=q)
    artists = listener_artists(db, q=q, limit=20)
    albums = listener_albums(db, q=q, limit=30)
    tracks = listener_tracks(db, q=q, limit=80)
    stations = [{"name": item["name"] + " Radio", "type": "artist", "seed_value": item["name"], "track_count": item["track_count"]} for item in artists[:5]]
    return {"artists": artists, "albums": albums, "tracks": tracks, "stations": stations}