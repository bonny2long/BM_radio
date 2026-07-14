from __future__ import annotations

from sqlalchemy.orm import Session

from . import models


LIBRARY_AVAILABLE = "available"
LIBRARY_UNAVAILABLE = "unavailable"


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


def is_track_available(track: models.Track | None) -> bool:
    return bool(track and track.library_availability == LIBRARY_AVAILABLE)


def is_audiobook_available(book: models.Audiobook | None) -> bool:
    return bool(book and book.library_availability == LIBRARY_AVAILABLE)


def is_chapter_available(chapter: models.AudiobookChapter | None) -> bool:
    return bool(chapter and chapter.library_availability == LIBRARY_AVAILABLE)
