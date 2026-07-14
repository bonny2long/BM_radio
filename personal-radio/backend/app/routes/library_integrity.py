from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .. import models
from ..availability import LIBRARY_AVAILABLE
from ..db import get_db
from ..media_identity import (
    audiobook_edition_key,
    audiobook_work_key,
    duration_bucket,
    music_duplicate_candidate_key,
    music_possible_duplicate_key,
    music_recording_key,
    normalize_text,
)

router = APIRouter()
MAX_ITEMS_PER_ISSUE = 8
STALE_SCAN_HOURS = 6
MAX_ERROR_SUMMARY_CHARS = 500


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def severity_rank(severity: str) -> int:
    return {"error": 0, "warning": 1, "notice": 2, "info": 3}.get(severity, 4)


def stable_issue_id(issue_type: str, confidence: str, items: list[dict]) -> str:
    first = items[0] if items else {}
    seed = "-".join(str(first.get(key, "")) for key in ("artist", "author", "album", "title"))
    return normalize_text(f"{issue_type}-{confidence}-{seed}").replace(" ", "-") or f"{issue_type}-{confidence}"


def add_issue(
    issues: list[dict],
    issue_type: str,
    severity: str,
    confidence: str,
    title: str,
    message: str,
    items: list[dict],
    category: str | None = None,
    issue_id: str | None = None,
    count: int | None = None,
):
    total = len(items) if count is None else int(count)
    sample = items[:MAX_ITEMS_PER_ISSUE]
    issues.append(
        {
            "id": issue_id or stable_issue_id(issue_type, confidence, sample),
            "type": issue_type,
            "category": category or issue_type,
            "severity": severity,
            "confidence": confidence,
            "title": title,
            "message": message,
            "description": message,
            "count": total,
            "items": sample,
            "sample_truncated": total > len(sample),
            "read_only": True,
        }
    )


def track_number_from_path(track: models.Track) -> str:
    name = Path((track.relative_path or track.path or "").replace("\\", "/")).name
    prefix = name.split(" ", 1)[0].split("-", 1)[0].strip()
    return prefix if prefix.isdigit() else ""


def safe_path(row) -> str | None:
    value = getattr(row, "relative_path", None) or getattr(row, "path", None)
    if not value:
        return None
    text = str(value).replace("\\", "/")
    if getattr(row, "relative_path", None):
        return text
    parts = [part for part in text.split("/") if part]
    return "/".join(parts[-4:])


def iso(value) -> str | None:
    return value.isoformat() if value else None


def short_track(track: models.Track) -> dict:
    bucket = duration_bucket(track.duration_seconds, tolerance=5)
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "year": track.year,
        "duration_seconds": track.duration_seconds,
        "duration_bucket": bucket,
        "track_number": track_number_from_path(track),
        "file_ext": track.file_ext,
        "path": safe_path(track),
        "relative_path": track.relative_path,
        "library_availability": track.library_availability,
    }


def short_audiobook(book: models.Audiobook) -> dict:
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "narrator": book.narrator,
        "year": book.year,
        "path": safe_path(book),
        "relative_path": book.relative_path,
        "library_availability": book.library_availability,
    }


def sanitize_error_summary(value: str | None) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    return text[:MAX_ERROR_SUMMARY_CHARS]


def parse_roots(value: str | None) -> tuple[list[str], bool]:
    if not value:
        return [], False
    try:
        parsed = json.loads(value)
    except Exception:
        return [], True
    if not isinstance(parsed, list):
        return [], True
    return [str(item) for item in parsed if item is not None], False


def scan_run_item(row: models.ScanRun | None, *, now: datetime | None = None) -> dict | None:
    if row is None:
        return None
    current = now or utc_now()
    roots, roots_error = parse_roots(row.roots_json)
    duration = None
    started_at = as_utc(row.started_at)
    completed_at = as_utc(row.completed_at)
    if started_at and completed_at:
        duration = max(0.0, (completed_at - started_at).total_seconds())
    stale = bool(row.status == "running" and started_at and started_at < current - timedelta(hours=STALE_SCAN_HOURS))
    item = {
        "id": row.id,
        "media_kind": row.media_kind,
        "status": row.status,
        "started_at": iso(row.started_at),
        "completed_at": iso(row.completed_at),
        "duration_seconds": duration,
        "roots": roots,
        "items_discovered": row.items_discovered,
        "items_added": row.items_added,
        "items_updated": row.items_updated,
        "items_unavailable": row.items_unavailable,
        "error_count": row.error_count,
        "error_summary": sanitize_error_summary(row.error_summary),
        "stale": stale,
    }
    if roots_error:
        item["roots_parse_error"] = True
    return item


@router.get("/scan-runs")
def scan_runs(
    media_kind: str | None = Query(default=None, pattern="^(music|audiobook)$"),
    status: str | None = Query(default=None, pattern="^(running|succeeded|failed)$"),
    limit: int = 25,
    db: Session = Depends(get_db),
):
    limit = min(max(limit, 1), 100)
    query = db.query(models.ScanRun)
    if media_kind:
        query = query.filter(models.ScanRun.media_kind == media_kind)
    if status:
        query = query.filter(models.ScanRun.status == status)
    rows = query.order_by(models.ScanRun.started_at.desc(), models.ScanRun.id.desc()).limit(limit).all()
    return {"items": [scan_run_item(row) for row in rows], "limit": limit, "read_only": True}


def suspicious_title_reason(track: models.Track) -> str | None:
    title = (track.title or "").strip()
    artist = normalize_text(track.artist)
    normalized_title = normalize_text(title)
    if not title:
        return "empty title"
    if title.startswith(("A1 ", "A2 ", "A3 ", "A4 ", "B1 ", "B2 ", "B3 ", "B4 ")):
        return "vinyl side prefix still visible"
    if normalized_title in {"2010", "2011", "2012", "2013", "2014", "2015", "2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"}:
        return "title is only a year"
    if artist and normalized_title.startswith(artist + " "):
        return "artist/year prefix may still be visible"
    return None


def scalar_count(db: Session, model, *criteria) -> int:
    query = db.query(func.count(model.id))
    for criterion in criteria:
        query = query.filter(criterion)
    return int(query.scalar() or 0)


def latest_scans(db: Session) -> dict:
    result = {}
    for kind in ("music", "audiobook"):
        row = db.query(models.ScanRun).filter(models.ScanRun.media_kind == kind).order_by(models.ScanRun.started_at.desc(), models.ScanRun.id.desc()).first()
        result[kind] = scan_run_item(row)
    return result


def scan_status_counts(db: Session) -> dict[str, int]:
    rows = db.query(models.ScanRun.status, func.count(models.ScanRun.id)).group_by(models.ScanRun.status).all()
    return {status or "unknown": int(count or 0) for status, count in rows}


def album_count_summary(db: Session) -> tuple[int, int, int]:
    available_case = func.sum(case((models.Track.library_availability == LIBRARY_AVAILABLE, 1), else_=0))
    rows = (
        db.query(models.Track.album_artist, models.Track.artist, models.Track.album, models.Track.year, func.count(models.Track.id), available_case)
        .filter(models.Track.album.isnot(None))
        .group_by(models.Track.album_artist, models.Track.artist, models.Track.album, models.Track.year)
        .all()
    )
    total = len(rows)
    available = sum(1 for *_rest, available_tracks in rows if int(available_tracks or 0) > 0)
    unavailable_only = sum(1 for *_rest, available_tracks in rows if int(available_tracks or 0) == 0)
    return total, available, unavailable_only


def grouped_chapter_counts(db: Session) -> dict[int, dict[str, int]]:
    rows = (
        db.query(
            models.AudiobookChapter.audiobook_id,
            func.count(models.AudiobookChapter.id),
            func.sum(case((models.AudiobookChapter.library_availability == LIBRARY_AVAILABLE, 1), else_=0)),
        )
        .group_by(models.AudiobookChapter.audiobook_id)
        .all()
    )
    return {int(book_id): {"total": int(total or 0), "available": int(available or 0), "unavailable": int(total or 0) - int(available or 0)} for book_id, total, available in rows}


def library_integrity_response(db: Session) -> dict:
    generated_at = utc_now()
    issues: list[dict] = []

    total_tracks = scalar_count(db, models.Track)
    available_tracks = scalar_count(db, models.Track, models.Track.library_availability == LIBRARY_AVAILABLE)
    unavailable_tracks = total_tracks - available_tracks
    total_albums, available_albums, unavailable_only_albums = album_count_summary(db)

    total_audiobooks = scalar_count(db, models.Audiobook)
    available_audiobooks = scalar_count(db, models.Audiobook, models.Audiobook.library_availability == LIBRARY_AVAILABLE)
    unavailable_audiobooks = total_audiobooks - available_audiobooks
    total_chapters = scalar_count(db, models.AudiobookChapter)
    available_chapters = scalar_count(db, models.AudiobookChapter, models.AudiobookChapter.library_availability == LIBRARY_AVAILABLE)
    unavailable_chapters = total_chapters - available_chapters

    chapter_counts = grouped_chapter_counts(db)
    partial_rows = (
        db.query(models.Audiobook.id, models.Audiobook.title, models.Audiobook.author)
        .join(models.AudiobookChapter, models.AudiobookChapter.audiobook_id == models.Audiobook.id)
        .filter(models.Audiobook.library_availability == LIBRARY_AVAILABLE, models.AudiobookChapter.library_availability != LIBRARY_AVAILABLE)
        .group_by(models.Audiobook.id)
        .all()
    )
    partial_audiobooks = len(partial_rows)

    unavailable_progress_rows = (
        db.query(models.AudiobookProgress, models.Audiobook, models.AudiobookChapter)
        .join(models.Audiobook, models.Audiobook.id == models.AudiobookProgress.audiobook_id)
        .join(models.AudiobookChapter, models.AudiobookChapter.id == models.AudiobookProgress.chapter_id)
        .filter(models.AudiobookChapter.library_availability != LIBRARY_AVAILABLE)
        .order_by(models.AudiobookProgress.updated_at.desc(), models.AudiobookProgress.id.desc())
        .all()
    )

    historical_playlist_count = int(
        db.query(func.count(models.PlaylistTrack.id))
        .join(models.Track, models.Track.id == models.PlaylistTrack.track_id)
        .filter(models.Track.library_availability != LIBRARY_AVAILABLE)
        .scalar()
        or 0
    )
    historical_favorite_count = int(
        db.query(func.count(models.TrackFavorite.id))
        .join(models.Track, models.Track.id == models.TrackFavorite.track_id)
        .filter(models.Track.library_availability != LIBRARY_AVAILABLE)
        .scalar()
        or 0
    )
    historical_thumb_count = int(
        db.query(func.count(models.TrackThumb.id))
        .join(models.Track, models.Track.id == models.TrackThumb.track_id)
        .filter(models.Track.library_availability != LIBRARY_AVAILABLE)
        .scalar()
        or 0
    )
    historical_playback_count = int(
        db.query(func.count(models.PlaybackEvent.id))
        .join(models.Track, models.Track.id == models.PlaybackEvent.track_id)
        .filter(models.Track.library_availability != LIBRARY_AVAILABLE)
        .scalar()
        or 0
    )

    status_counts = scan_status_counts(db)
    latest = latest_scans(db)
    stale_cutoff = generated_at - timedelta(hours=STALE_SCAN_HOURS)
    stale_runs = db.query(models.ScanRun).filter(models.ScanRun.status == "running", models.ScanRun.started_at < stale_cutoff).order_by(models.ScanRun.started_at.asc()).limit(MAX_ITEMS_PER_ISSUE).all()
    stale_count = int(db.query(func.count(models.ScanRun.id)).filter(models.ScanRun.status == "running", models.ScanRun.started_at < stale_cutoff).scalar() or 0)
    failed_count = int(db.query(func.count(models.ScanRun.id)).filter(models.ScanRun.status == "failed").scalar() or 0)
    failed_runs = db.query(models.ScanRun).filter(models.ScanRun.status == "failed").order_by(models.ScanRun.started_at.desc(), models.ScanRun.id.desc()).limit(MAX_ITEMS_PER_ISSUE).all()

    unavailable_track_rows = (
        db.query(models.Track)
        .filter(models.Track.library_availability != LIBRARY_AVAILABLE)
        .order_by(models.Track.unavailable_since.desc().nullslast(), models.Track.id)
        .limit(MAX_ITEMS_PER_ISSUE)
        .all()
    )
    if unavailable_tracks:
        playlist_counts = dict(db.query(models.PlaylistTrack.track_id, func.count(models.PlaylistTrack.id)).group_by(models.PlaylistTrack.track_id).all())
        playback_counts = dict(db.query(models.PlaybackEvent.track_id, func.count(models.PlaybackEvent.id)).filter(models.PlaybackEvent.track_id.isnot(None)).group_by(models.PlaybackEvent.track_id).all())
        favorite_ids = {row[0] for row in db.query(models.TrackFavorite.track_id).all()}
        add_issue(
            issues,
            "unavailable_tracks",
            "warning",
            "notice",
            "Unavailable tracks retained in history",
            "These Track rows are unavailable in the current library but remain in BM Radio history. No media file, playlist membership, favorite, thumb, or playback history was deleted.",
            [
                {
                    **short_track(track),
                    "unavailable_since": iso(track.unavailable_since),
                    "last_seen_scan_id": track.last_seen_scan_id,
                    "favorite": track.id in favorite_ids,
                    "playlist_membership_count": int(playlist_counts.get(track.id, 0) or 0),
                    "playback_event_count": int(playback_counts.get(track.id, 0) or 0),
                }
                for track in unavailable_track_rows
            ],
            "unavailable_media",
            "unavailable-tracks",
            unavailable_tracks,
        )

    unavailable_book_rows = (
        db.query(models.Audiobook)
        .filter(models.Audiobook.library_availability != LIBRARY_AVAILABLE)
        .order_by(models.Audiobook.unavailable_since.desc().nullslast(), models.Audiobook.id)
        .limit(MAX_ITEMS_PER_ISSUE)
        .all()
    )
    if unavailable_audiobooks:
        progress_by_book = {row.audiobook_id: row for row in db.query(models.AudiobookProgress).order_by(models.AudiobookProgress.updated_at.desc()).all()}
        playback_counts = dict(db.query(models.PlaybackEvent.audiobook_id, func.count(models.PlaybackEvent.id)).filter(models.PlaybackEvent.audiobook_id.isnot(None)).group_by(models.PlaybackEvent.audiobook_id).all())
        add_issue(
            issues,
            "unavailable_audiobooks",
            "warning",
            "notice",
            "Unavailable audiobooks retained in history",
            "These Audiobook rows are unavailable in the current library but status, favorites, progress, and playback history remain preserved.",
            [
                {
                    **short_audiobook(book),
                    "unavailable_since": iso(book.unavailable_since),
                    "last_seen_scan_id": book.last_seen_scan_id,
                    "status": book.status,
                    "favorite": book.favorite,
                    "progress_percent": getattr(progress_by_book.get(book.id), "progress_percent", None),
                    "progress_chapter_id": getattr(progress_by_book.get(book.id), "chapter_id", None),
                    "chapter_count": chapter_counts.get(book.id, {}).get("total", 0),
                    "unavailable_chapter_count": chapter_counts.get(book.id, {}).get("unavailable", 0),
                    "playback_event_count": int(playback_counts.get(book.id, 0) or 0),
                }
                for book in unavailable_book_rows
            ],
            "unavailable_media",
            "unavailable-audiobooks",
            unavailable_audiobooks,
        )

    if partial_audiobooks:
        items = []
        for book_id, title, author in partial_rows[:MAX_ITEMS_PER_ISSUE]:
            counts = chapter_counts.get(book_id, {"total": 0, "available": 0, "unavailable": 0})
            sample = [row[0] for row in db.query(models.AudiobookChapter.title).filter(models.AudiobookChapter.audiobook_id == book_id, models.AudiobookChapter.library_availability != LIBRARY_AVAILABLE).order_by(models.AudiobookChapter.sort_order, models.AudiobookChapter.id).limit(3).all()]
            progress = db.query(models.AudiobookProgress).filter_by(audiobook_id=book_id).order_by(models.AudiobookProgress.updated_at.desc()).first()
            progress_status = "none"
            if progress and progress.chapter_id:
                chapter = db.get(models.AudiobookChapter, progress.chapter_id)
                progress_status = "unavailable_chapter" if chapter and chapter.library_availability != LIBRARY_AVAILABLE else "available_chapter"
            items.append({"audiobook_id": book_id, "title": title, "author": author, "total_chapter_count": counts["total"], "available_chapter_count": counts["available"], "unavailable_chapter_count": counts["unavailable"], "unavailable_chapter_sample": sample, "progress_chapter_status": progress_status})
        add_issue(issues, "partial_audiobooks", "error", "strong", "Partial audiobooks", "Available Audiobooks with one or more unavailable chapter rows. The integrity endpoint is read-only and does not mark the whole book unavailable.", items, "audiobook_integrity", "partial-audiobooks", partial_audiobooks)

    if unavailable_progress_rows:
        add_issue(
            issues,
            "audiobook_progress_on_unavailable_chapter",
            "warning",
            "notice",
            "Audiobook progress points to unavailable chapters",
            "Stored progress remains unchanged, but the referenced chapter is not currently playable.",
            [
                {
                    "audiobook_id": book.id,
                    "title": book.title,
                    "progress_row_id": progress.id,
                    "chapter_id": chapter.id,
                    "chapter_title": chapter.title,
                    "position_seconds": progress.position_seconds,
                    "progress_percent": progress.progress_percent,
                    "audiobook_status": book.status,
                    "chapter_unavailable_since": iso(chapter.unavailable_since),
                }
                for progress, book, chapter in unavailable_progress_rows[:MAX_ITEMS_PER_ISSUE]
            ],
            "historical_state",
            "audiobook-progress-on-unavailable-chapter",
            len(unavailable_progress_rows),
        )

    historical_total = historical_playlist_count + historical_favorite_count + historical_thumb_count + historical_playback_count
    if historical_total:
        add_issue(
            issues,
            "historical_state_on_unavailable_tracks",
            "notice",
            "notice",
            "Historical state references unavailable tracks",
            "BM Radio preserves playlist, favorite, thumb, and playback history rows for unavailable Tracks. Active playback surfaces filter them until the media returns.",
            [{"unavailable_track_playlist_memberships": historical_playlist_count, "unavailable_track_favorites": historical_favorite_count, "unavailable_track_thumbs": historical_thumb_count, "unavailable_track_playback_events": historical_playback_count}],
            "historical_state",
            "historical-state-on-unavailable-tracks",
            historical_total,
        )

    if stale_count:
        add_issue(issues, "stale_scan_runs", "warning", "notice", "Stale running scans", f"Running scans older than {STALE_SCAN_HOURS} hours are stale. No status was changed automatically.", [scan_run_item(row, now=generated_at) for row in stale_runs], "scan_history", "stale-scan-runs", stale_count)
    if failed_count:
        add_issue(issues, "failed_scan_runs", "warning", "notice", "Failed scan runs", "Recent failed scans are reported honestly. Error summaries are bounded and normalized.", [scan_run_item(row, now=generated_at) for row in failed_runs], "scan_history", "failed-scan-runs", failed_count)

    tracks = db.query(models.Track).all()
    audiobooks = db.query(models.Audiobook).all()

    album_keys = {(normalize_text(track.album_artist or track.artist), normalize_text(track.album), str(track.year or "")) for track in tracks if track.album}

    strong_candidate_groups: dict[str, list[models.Track]] = defaultdict(list)
    possible_candidate_groups: dict[str, list[models.Track]] = defaultdict(list)
    recording_groups: dict[str, list[models.Track]] = defaultdict(list)
    album_cover_groups: dict[tuple[str, str], list[models.Track]] = defaultdict(list)
    unknown_genre_tracks: list[models.Track] = []
    suspicious_titles: list[dict] = []

    for track in tracks:
        candidate_key = music_duplicate_candidate_key(track.album_artist or track.artist, track.album, track.title, track.year, track.duration_seconds)
        possible_key = music_possible_duplicate_key(track.album_artist or track.artist, track.album, track.title, track.year)
        recording_key = music_recording_key(track.artist, track.title, track.duration_seconds)
        strong_candidate_groups[candidate_key].append(track)
        possible_candidate_groups[possible_key].append(track)
        recording_groups[recording_key].append(track)
        if track.album:
            album_cover_groups[(track.album_artist or track.artist or "", track.album or "")].append(track)
        if not track.genre or normalize_text(track.genre) in {"", "unknown", "none", "n a", "misc"}:
            unknown_genre_tracks.append(track)
        title_reason = suspicious_title_reason(track)
        if title_reason:
            suspicious_titles.append({**short_track(track), "reason": title_reason})

    strong_duplicate_candidates = []
    strong_paths: set[str] = set()
    for group in strong_candidate_groups.values():
        paths = {track.path for track in group}
        buckets = {duration_bucket(track.duration_seconds, tolerance=5) for track in group if duration_bucket(track.duration_seconds, tolerance=5)}
        if len(group) > 1 and len(paths) > 1 and len(buckets) == 1:
            items = [short_track(track) for track in group]
            strong_duplicate_candidates.extend(items)
            strong_paths.update(str(track.path) for track in group)

    possible_duplicate_candidates = []
    for group in possible_candidate_groups.values():
        paths = {track.path for track in group}
        if len(group) <= 1 or len(paths) <= 1:
            continue
        if all(str(track.path) in strong_paths for track in group):
            continue
        buckets = {duration_bucket(track.duration_seconds, tolerance=5) for track in group if duration_bucket(track.duration_seconds, tolerance=5)}
        has_missing_duration = any(not track.duration_seconds for track in group)
        if has_missing_duration or len(buckets) != 1:
            possible_duplicate_candidates.extend(short_track(track) for track in group)

    variant_release_candidates = []
    for group in recording_groups.values():
        albums = {normalize_text(track.album) for track in group if track.album}
        paths = {track.path for track in group}
        if len(group) > 1 and len(albums) > 1 and len(paths) > 1:
            variant_release_candidates.extend(short_track(track) for track in group)

    missing_cover_albums = []
    for (artist, album), group in album_cover_groups.items():
        if not any(track.cover_path for track in group):
            missing_cover_albums.append({"artist": artist, "album": album, "track_count": len(group), "message": "No indexed cover_path found for this album group."})

    audiobook_edition_groups: dict[str, list[models.Audiobook]] = defaultdict(list)
    audiobook_work_groups: dict[str, list[models.Audiobook]] = defaultdict(list)
    for book in audiobooks:
        chapter_count = chapter_counts.get(book.id, {}).get("total", 0)
        audiobook_edition_groups[audiobook_edition_key(book.title, book.author, book.narrator, book.duration_seconds, chapter_count)].append(book)
        audiobook_work_groups[audiobook_work_key(book.title, book.author)].append(book)

    duplicate_audiobook_editions = []
    for group in audiobook_edition_groups.values():
        if len(group) > 1:
            duplicate_audiobook_editions.extend(short_audiobook(book) for book in group)

    audiobook_variants = []
    for group in audiobook_work_groups.values():
        edition_keys = {audiobook_edition_key(book.title, book.author, book.narrator, book.duration_seconds, 0) for book in group}
        if len(group) > 1 and len(edition_keys) > 1:
            audiobook_variants.extend(short_audiobook(book) for book in group)

    if strong_duplicate_candidates:
        add_issue(issues, "strong_duplicate_candidate", "warning", "strong", "Strong duplicate candidate", "Same artist, release, title, and duration bucket appear more than once in the app index. Read-only diagnostics; no files were changed.", strong_duplicate_candidates, "music_duplicate_candidate")
    if possible_duplicate_candidates:
        add_issue(issues, "possible_duplicate_candidate", "notice", "possible", "Possible duplicate candidate", "Same artist, release, and title appear more than once, but duration evidence is incomplete or inconsistent. Read-only diagnostics; no files were changed.", possible_duplicate_candidates, "music_duplicate_candidate")
    if duplicate_audiobook_editions:
        add_issue(issues, "duplicate_audiobook_edition_candidate", "warning", "strong", "Duplicate audiobook edition candidate", "Same normalized audiobook edition appears more than once in the BM Radio app index. No files were changed.", duplicate_audiobook_editions, "audiobook_duplicate_candidate")
    if variant_release_candidates:
        add_issue(issues, "variant_release_candidate", "notice", "notice", "Variant release candidate", "Same recording title appears across different releases. This may be legitimate and is not counted as a duplicate warning.", variant_release_candidates, "music_variant_candidate")
    if audiobook_variants:
        add_issue(issues, "audiobook_variant_candidate", "notice", "notice", "Audiobook variant candidate", "Same audiobook work appears with different edition details. This is allowed and review-only.", audiobook_variants, "audiobook_variant_candidate")
    if missing_cover_albums:
        add_issue(issues, "missing_covers", "notice", "notice", "Albums with no indexed cover", "Album groups where BM Radio has no cover_path in the app index.", missing_cover_albums)
    if unknown_genre_tracks:
        add_issue(issues, "unknown_genres", "info", "notice", "Tracks with unknown genre", "Tracks with blank or generic embedded/app-index genre metadata. BM Radio may still use app-owned radio profile fallbacks for playback; Archive Assistant should fix archive metadata later.", [short_track(track) for track in unknown_genre_tracks])
    if suspicious_titles:
        add_issue(issues, "weak_title_candidates", "notice", "notice", "Possible weak titles", "Titles that still look like parser leftovers. Numeric song titles like 100 Grandkids are not flagged by this check.", suspicious_titles)

    if not issues:
        title = "No indexed media yet" if total_tracks == 0 and total_audiobooks == 0 else "No integrity issues found"
        message = "BM Radio has no indexed media rows yet. This is a clean empty state, not a verification of a populated library." if total_tracks == 0 and total_audiobooks == 0 else "The BM Radio app index does not currently show duplicate candidates, availability warnings, scan warnings, or obvious metadata issues."
        add_issue(issues, "clean_state", "info", "notice", title, message, [], issue_id="clean-state")

    duplicate_candidate_count = len(strong_duplicate_candidates) + len(possible_duplicate_candidates)
    issues.sort(key=lambda issue: (severity_rank(issue["severity"]), issue["type"]))

    summary = {
        "total_tracks": total_tracks,
        "available_tracks": available_tracks,
        "unavailable_tracks": unavailable_tracks,
        "total_albums": total_albums or len(album_keys),
        "available_albums": available_albums,
        "unavailable_only_albums": unavailable_only_albums,
        "total_audiobooks": total_audiobooks,
        "available_audiobooks": available_audiobooks,
        "unavailable_audiobooks": unavailable_audiobooks,
        "total_audiobook_chapters": total_chapters,
        "available_audiobook_chapters": available_chapters,
        "unavailable_audiobook_chapters": unavailable_chapters,
        "partial_audiobooks": partial_audiobooks,
        "audiobooks_with_unavailable_progress_chapter": len({book.id for _progress, book, _chapter in unavailable_progress_rows}),
        "successful_scan_runs": int(status_counts.get("succeeded", 0)),
        "failed_scan_runs": int(status_counts.get("failed", 0)),
        "running_scan_runs": int(status_counts.get("running", 0)),
        "stale_running_scan_runs": stale_count,
        "latest_music_scan_status": latest["music"]["status"] if latest.get("music") else None,
        "latest_audiobook_scan_status": latest["audiobook"]["status"] if latest.get("audiobook") else None,
        "unavailable_track_playlist_memberships": historical_playlist_count,
        "unavailable_track_favorites": historical_favorite_count,
        "unavailable_track_thumbs": historical_thumb_count,
        "unavailable_track_playback_events": historical_playback_count,
        "duplicate_music_track_release_rows": duplicate_candidate_count,
        "duplicate_music_release_candidates": duplicate_candidate_count,
        "strong_duplicate_candidates": len(strong_duplicate_candidates),
        "possible_duplicate_candidates": len(possible_duplicate_candidates),
        "suspected_duplicate_recordings": len(variant_release_candidates),
        "variant_release_candidates": len(variant_release_candidates),
        "duplicate_audiobook_editions": len(duplicate_audiobook_editions),
        "audiobook_variants": len(audiobook_variants),
        "missing_covers": len(missing_cover_albums),
        "unknown_genres": len(unknown_genre_tracks),
        "weak_titles_corrected": 0,
        "weak_title_candidates": len(suspicious_titles),
        "scanner_warnings": failed_count + stale_count,
        "books_indexed": total_audiobooks > 0,
    }
    return {"generated_at": iso(generated_at), "read_only": True, "availability_policy": LIBRARY_AVAILABLE, "summary": summary, "latest_scans": latest, "issues": issues}


@router.get("/integrity")
def library_integrity(db: Session = Depends(get_db)):
    return library_integrity_response(db)