from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..media_identity import (
    audiobook_edition_key,
    audiobook_work_key,
    duration_bucket,
    music_recording_key,
    music_track_release_key,
    normalize_text,
)

router = APIRouter()


MAX_ITEMS_PER_ISSUE = 8


def severity_rank(severity: str) -> int:
    return {"error": 0, "warning": 1, "notice": 2, "info": 3}.get(severity, 4)


def add_issue(issues: list[dict], issue_type: str, severity: str, title: str, message: str, items: list[dict]):
    issues.append(
        {
            "type": issue_type,
            "severity": severity,
            "title": title,
            "message": message,
            "count": len(items),
            "items": items[:MAX_ITEMS_PER_ISSUE],
        }
    )


def short_track(track: models.Track) -> dict:
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "year": track.year,
        "path": track.relative_path or track.path,
    }


def short_audiobook(book: models.Audiobook) -> dict:
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "narrator": book.narrator,
        "year": book.year,
        "path": book.relative_path or book.path,
    }


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


@router.get("/integrity")
def library_integrity(db: Session = Depends(get_db)):
    tracks = db.query(models.Track).all()
    audiobooks = db.query(models.Audiobook).all()
    issues: list[dict] = []

    album_keys = {
        (
            normalize_text(track.album_artist or track.artist),
            normalize_text(track.album),
            str(track.year or ""),
        )
        for track in tracks
        if track.album
    }

    release_groups: dict[str, list[models.Track]] = defaultdict(list)
    recording_groups: dict[str, list[models.Track]] = defaultdict(list)
    album_cover_groups: dict[tuple[str, str], list[models.Track]] = defaultdict(list)
    unknown_genre_tracks: list[models.Track] = []
    suspicious_titles: list[dict] = []

    for track in tracks:
        track_number = ""
        parts = (track.relative_path or track.path or "").replace("\\", "/").split("/")
        if parts:
            filename = parts[-1]
            prefix = filename.split(" ", 1)[0].split("-", 1)[0].strip()
            if prefix.isdigit():
                track_number = prefix
        release_key = "|".join(
            [
                music_track_release_key(track.album_artist or track.artist, track.album, track.title, track.year, track_number),
                duration_bucket(track.duration_seconds, tolerance=5),
            ]
        )
        recording_key = music_recording_key(track.artist, track.title, track.duration_seconds)
        release_groups[release_key].append(track)
        recording_groups[recording_key].append(track)
        if track.album:
            album_cover_groups[(track.album_artist or track.artist or "", track.album or "")].append(track)
        if not track.genre or normalize_text(track.genre) in {"", "unknown", "none", "n a", "misc"}:
            unknown_genre_tracks.append(track)
        title_reason = suspicious_title_reason(track)
        if title_reason:
            suspicious_titles.append({**short_track(track), "reason": title_reason})

    duplicate_release_rows = []
    for group in release_groups.values():
        paths = {track.path for track in group}
        if len(group) > 1 and len(paths) > 1:
            duplicate_release_rows.extend(short_track(track) for track in group)

    suspected_recordings = []
    for group in recording_groups.values():
        albums = {normalize_text(track.album) for track in group if track.album}
        paths = {track.path for track in group}
        if len(group) > 1 and len(albums) > 1 and len(paths) > 1:
            suspected_recordings.extend(short_track(track) for track in group)

    missing_cover_albums = []
    for (artist, album), group in album_cover_groups.items():
        if not any(track.cover_path for track in group):
            missing_cover_albums.append(
                {
                    "artist": artist,
                    "album": album,
                    "track_count": len(group),
                    "message": "No indexed cover_path found for this album group.",
                }
            )

    audiobook_edition_groups: dict[str, list[models.Audiobook]] = defaultdict(list)
    audiobook_work_groups: dict[str, list[models.Audiobook]] = defaultdict(list)
    for book in audiobooks:
        chapter_count = db.query(func.count(models.AudiobookChapter.id)).filter_by(audiobook_id=book.id).scalar() or 0
        audiobook_edition_groups[
            audiobook_edition_key(book.title, book.author, book.narrator, book.duration_seconds, chapter_count)
        ].append(book)
        audiobook_work_groups[audiobook_work_key(book.title, book.author)].append(book)

    duplicate_audiobook_editions = []
    for group in audiobook_edition_groups.values():
        if len(group) > 1:
            duplicate_audiobook_editions.extend(short_audiobook(book) for book in group)

    audiobook_variants = []
    for group in audiobook_work_groups.values():
        edition_keys = {
            audiobook_edition_key(book.title, book.author, book.narrator, book.duration_seconds, 0)
            for book in group
        }
        if len(group) > 1 and len(edition_keys) > 1:
            audiobook_variants.extend(short_audiobook(book) for book in group)

    if duplicate_release_rows:
        add_issue(
            issues,
            "duplicate_music_track_release_rows",
            "warning",
            "Duplicate music release rows",
            "Same normalized track/release identity appears more than once in the BM Radio app index.",
            duplicate_release_rows,
        )
    if suspected_recordings:
        add_issue(
            issues,
            "suspected_duplicate_recording",
            "notice",
            "Possible duplicate recordings",
            "Same normalized artist/title/duration appears across multiple releases. This is review-only; singles and album tracks are preserved.",
            suspected_recordings,
        )
    if duplicate_audiobook_editions:
        add_issue(
            issues,
            "duplicate_audiobook_editions",
            "warning",
            "Duplicate audiobook editions",
            "Same normalized audiobook edition appears more than once in the BM Radio app index.",
            duplicate_audiobook_editions,
        )
    if audiobook_variants:
        add_issue(
            issues,
            "audiobook_variants",
            "notice",
            "Audiobook variants",
            "Same audiobook work appears with different edition details. This is allowed and review-only.",
            audiobook_variants,
        )
    if missing_cover_albums:
        add_issue(
            issues,
            "missing_covers",
            "notice",
            "Albums with no indexed cover",
            "Album groups where BM Radio has no cover_path in the app index.",
            missing_cover_albums,
        )
    if unknown_genre_tracks:
        add_issue(
            issues,
            "unknown_genres",
            "info",
            "Tracks with unknown genre",
            "Tracks with blank or generic genre metadata.",
            [short_track(track) for track in unknown_genre_tracks],
        )
    if suspicious_titles:
        add_issue(
            issues,
            "weak_title_candidates",
            "notice",
            "Possible weak titles",
            "Titles that still look like parser leftovers. Numeric song titles like 100 Grandkids are not flagged by this check.",
            suspicious_titles,
        )

    if not issues:
        add_issue(
            issues,
            "clean_state",
            "info",
            "No integrity issues found",
            "The BM Radio app index does not currently show duplicate rows or obvious metadata issues.",
            [],
        )

    issues.sort(key=lambda issue: (severity_rank(issue["severity"]), issue["type"]))
    return {
        "summary": {
            "total_tracks": len(tracks),
            "total_albums": len(album_keys),
            "total_audiobooks": len(audiobooks),
            "duplicate_music_track_release_rows": len(duplicate_release_rows),
            "suspected_duplicate_recordings": len(suspected_recordings),
            "duplicate_audiobook_editions": len(duplicate_audiobook_editions),
            "audiobook_variants": len(audiobook_variants),
            "missing_covers": len(missing_cover_albums),
            "unknown_genres": len(unknown_genre_tracks),
            "weak_titles_corrected": 0,
            "weak_title_candidates": len(suspicious_titles),
            "scanner_warnings": 0,
            "books_indexed": False,
        },
        "issues": issues,
    }
