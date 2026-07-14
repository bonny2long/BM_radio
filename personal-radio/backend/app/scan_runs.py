from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy.orm import Session

from .models import Audiobook, ScanRun, Track

MEDIA_KIND_AUDIOBOOK = "audiobook"
MEDIA_KIND_MUSIC = "music"
SCAN_STATUS_FAILED = "failed"
SCAN_STATUS_RUNNING = "running"
SCAN_STATUS_SUCCEEDED = "succeeded"
LIBRARY_AVAILABLE = "available"
ERROR_SUMMARY_MAX_LENGTH = 1000

VALID_MEDIA_KINDS = {MEDIA_KIND_MUSIC, MEDIA_KIND_AUDIOBOOK}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _bounded_error_summary(error_summary: str) -> str:
    summary = str(error_summary).strip()
    if len(summary) <= ERROR_SUMMARY_MAX_LENGTH:
        return summary
    return summary[: ERROR_SUMMARY_MAX_LENGTH - 3].rstrip() + "..."


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