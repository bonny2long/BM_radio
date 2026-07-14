from __future__ import annotations

from sqlalchemy.orm import Session

from . import models


LIBRARY_AVAILABLE = "available"
LIBRARY_UNAVAILABLE = "unavailable"
TRACK_UNAVAILABLE_MESSAGE = "Track is unavailable in the current library"
AUDIOBOOK_UNAVAILABLE_MESSAGE = "Audiobook is unavailable in the current library"
CHAPTER_UNAVAILABLE_MESSAGE = "Audiobook chapter is unavailable in the current library"


def available_track_filter():
    return models.Track.library_availability == LIBRARY_AVAILABLE


def available_audiobook_filter():
    return models.Audiobook.library_availability == LIBRARY_AVAILABLE


def available_chapter_filter():
    return models.AudiobookChapter.library_availability == LIBRARY_AVAILABLE


def active_tracks(db: Session):
    return db.query(models.Track).filter(available_track_filter())


def active_audiobooks(db: Session):
    return db.query(models.Audiobook).filter(available_audiobook_filter())


def active_chapters(db: Session):
    return db.query(models.AudiobookChapter).filter(available_chapter_filter())


def active_track_ids(db: Session, track_ids) -> set[int]:
    ids = [int(track_id) for track_id in track_ids if track_id is not None]
    if not ids:
        return set()
    return {row[0] for row in active_tracks(db).with_entities(models.Track.id).filter(models.Track.id.in_(ids)).all()}


def active_tracks_by_ids(db: Session, track_ids) -> list[models.Track]:
    ids = [int(track_id) for track_id in track_ids if track_id is not None]
    if not ids:
        return []
    rows = active_tracks(db).filter(models.Track.id.in_(ids)).all()
    by_id = {row.id: row for row in rows}
    seen: set[int] = set()
    ordered: list[models.Track] = []
    for track_id in ids:
        if track_id in seen:
            continue
        track = by_id.get(track_id)
        if track:
            ordered.append(track)
            seen.add(track_id)
    return ordered


def is_track_available(track: models.Track | None) -> bool:
    return bool(track and track.library_availability == LIBRARY_AVAILABLE)


def is_audiobook_available(book: models.Audiobook | None) -> bool:
    return bool(book and book.library_availability == LIBRARY_AVAILABLE)


def is_chapter_available(chapter: models.AudiobookChapter | None) -> bool:
    return bool(chapter and chapter.library_availability == LIBRARY_AVAILABLE)