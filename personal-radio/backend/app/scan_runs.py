from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .models import Audiobook, AudiobookChapter, ScanRun, Track

MEDIA_KIND_AUDIOBOOK = "audiobook"
MEDIA_KIND_MUSIC = "music"
SCAN_STATUS_FAILED = "failed"
SCAN_STATUS_RUNNING = "running"
SCAN_STATUS_SUCCEEDED = "succeeded"
LIBRARY_AVAILABLE = "available"
LIBRARY_UNAVAILABLE = "unavailable"
ERROR_SUMMARY_MAX_LENGTH = 1000

VALID_MEDIA_KINDS = {MEDIA_KIND_MUSIC, MEDIA_KIND_AUDIOBOOK}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _bounded_error_summary(error_summary: str) -> str:
    summary = str(error_summary).strip()
    if len(summary) <= ERROR_SUMMARY_MAX_LENGTH:
        return summary
    return summary[: ERROR_SUMMARY_MAX_LENGTH - 3].rstrip() + "..."


def _path_inside_root(path_value: str | None, root: Path) -> bool:
    if not path_value:
        return False
    try:
        Path(path_value).resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _path_prefix_filters(column, roots: Iterable[Path]):
    filters = []
    for root in roots:
        root_text = str(root)
        if root_text:
            filters.append(column.like(f"{root_text}%"))
    return filters


def start_scan_run(
    db: Session,
    *,
    media_kind: str,
    roots: list[str],
) -> ScanRun:
    if media_kind not in VALID_MEDIA_KINDS:
        raise ValueError(f"unsupported scan media_kind: {media_kind}")
    scan_run = ScanRun(
        media_kind=media_kind,
        status=SCAN_STATUS_RUNNING,
        started_at=_utc_now(),
        roots_json=json.dumps([str(root) for root in roots]),
        items_discovered=0,
        items_added=0,
        items_updated=0,
        items_unavailable=0,
        error_count=0,
    )
    db.add(scan_run)
    db.flush()
    return scan_run


def mark_track_seen(
    track: Track,
    *,
    scan_run_id: int,
) -> None:
    track.last_seen_scan_id = scan_run_id
    track.library_availability = LIBRARY_AVAILABLE
    track.unavailable_since = None


def mark_audiobook_seen(
    audiobook: Audiobook,
    *,
    scan_run_id: int,
) -> None:
    audiobook.last_seen_scan_id = scan_run_id
    audiobook.library_availability = LIBRARY_AVAILABLE
    audiobook.unavailable_since = None


def mark_audiobook_chapter_seen(
    chapter: AudiobookChapter,
    *,
    scan_run_id: int,
) -> None:
    chapter.last_seen_scan_id = scan_run_id
    chapter.library_availability = LIBRARY_AVAILABLE
    chapter.unavailable_since = None


def reconcile_unseen_tracks(
    db: Session,
    *,
    scan_run_id: int,
    scanned_roots: list[Path | str],
    unavailable_at: datetime | None = None,
) -> int:
    roots = [Path(root) for root in scanned_roots]
    if not roots:
        return 0

    prefix_filters = _path_prefix_filters(Track.path, roots)
    if not prefix_filters:
        return 0

    candidates = (
        db.query(Track.id, Track.path)
        .filter(Track.library_availability == LIBRARY_AVAILABLE)
        .filter(or_(Track.last_seen_scan_id.is_(None), Track.last_seen_scan_id != scan_run_id))
        .filter(or_(*prefix_filters))
        .all()
    )
    track_ids = [
        track_id
        for track_id, path_value in candidates
        if any(_path_inside_root(path_value, root) for root in roots)
    ]
    if not track_ids:
        return 0

    timestamp = unavailable_at or _utc_now()
    updated = (
        db.query(Track)
        .filter(Track.id.in_(track_ids))
        .update(
            {
                Track.library_availability: LIBRARY_UNAVAILABLE,
                Track.unavailable_since: timestamp,
            },
            synchronize_session=False,
        )
    )
    db.flush()
    return int(updated or 0)


def reconcile_unseen_audiobook_chapters(
    db: Session,
    *,
    scan_run_id: int,
    audiobook_ids: list[int],
    unavailable_at: datetime | None = None,
) -> int:
    if not audiobook_ids:
        return 0
    timestamp = unavailable_at or _utc_now()
    updated = (
        db.query(AudiobookChapter)
        .filter(AudiobookChapter.audiobook_id.in_(audiobook_ids))
        .filter(AudiobookChapter.library_availability == LIBRARY_AVAILABLE)
        .filter(or_(AudiobookChapter.last_seen_scan_id.is_(None), AudiobookChapter.last_seen_scan_id != scan_run_id))
        .update(
            {
                AudiobookChapter.library_availability: LIBRARY_UNAVAILABLE,
                AudiobookChapter.unavailable_since: timestamp,
            },
            synchronize_session=False,
        )
    )
    db.flush()
    return int(updated or 0)


def mark_audiobook_chapters_unavailable(
    db: Session,
    *,
    audiobook_ids: list[int],
    unavailable_at: datetime,
) -> int:
    if not audiobook_ids:
        return 0
    updated = (
        db.query(AudiobookChapter)
        .filter(AudiobookChapter.audiobook_id.in_(audiobook_ids))
        .filter(AudiobookChapter.library_availability == LIBRARY_AVAILABLE)
        .update(
            {
                AudiobookChapter.library_availability: LIBRARY_UNAVAILABLE,
                AudiobookChapter.unavailable_since: unavailable_at,
            },
            synchronize_session=False,
        )
    )
    db.flush()
    return int(updated or 0)


def reconcile_unseen_audiobooks(
    db: Session,
    *,
    scan_run_id: int,
    scanned_root: Path | str,
    unavailable_at: datetime | None = None,
) -> tuple[int, int]:
    root = Path(scanned_root)
    prefix_filters = _path_prefix_filters(Audiobook.path, [root])
    if not prefix_filters:
        return (0, 0)

    candidates = (
        db.query(Audiobook.id, Audiobook.path)
        .filter(Audiobook.library_availability == LIBRARY_AVAILABLE)
        .filter(or_(Audiobook.last_seen_scan_id.is_(None), Audiobook.last_seen_scan_id != scan_run_id))
        .filter(or_(*prefix_filters))
        .all()
    )
    audiobook_ids = [
        audiobook_id
        for audiobook_id, path_value in candidates
        if _path_inside_root(path_value, root)
    ]
    if not audiobook_ids:
        return (0, 0)

    timestamp = unavailable_at or _utc_now()
    books_updated = (
        db.query(Audiobook)
        .filter(Audiobook.id.in_(audiobook_ids))
        .update(
            {
                Audiobook.library_availability: LIBRARY_UNAVAILABLE,
                Audiobook.unavailable_since: timestamp,
            },
            synchronize_session=False,
        )
    )
    chapters_updated = mark_audiobook_chapters_unavailable(db, audiobook_ids=audiobook_ids, unavailable_at=timestamp)
    db.flush()
    return (int(books_updated or 0), chapters_updated)


def complete_scan_run(
    db: Session,
    scan_run: ScanRun,
    *,
    items_discovered: int,
    items_added: int,
    items_updated: int,
    items_unavailable: int = 0,
    error_count: int = 0,
) -> ScanRun:
    scan_run.status = SCAN_STATUS_SUCCEEDED
    scan_run.completed_at = _utc_now()
    scan_run.items_discovered = items_discovered
    scan_run.items_added = items_added
    scan_run.items_updated = items_updated
    scan_run.items_unavailable = items_unavailable
    scan_run.error_count = error_count
    db.flush()
    return scan_run


def fail_scan_run(
    db: Session,
    scan_run: ScanRun,
    *,
    error_summary: str,
    error_count: int = 1,
) -> ScanRun:
    scan_run.status = SCAN_STATUS_FAILED
    scan_run.completed_at = _utc_now()
    scan_run.error_count = error_count
    scan_run.error_summary = _bounded_error_summary(error_summary)
    db.flush()
    return scan_run