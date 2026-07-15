from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from . import models

SCAN_PATH_BATCH_SIZE = 500
EXACT_PATH_LOOKUP_CHUNK_SIZE = 500
MAX_DUPLICATE_WARNING_SAMPLES = 200


def chunked(values: Iterable, size: int):
    chunk = []
    for value in values:
        chunk.append(value)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def unique_strings(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def tracks_by_exact_paths(
    db: Session,
    *,
    paths: list[str],
    chunk_size: int = EXACT_PATH_LOOKUP_CHUNK_SIZE,
) -> dict[str, models.Track]:
    """Load existing Tracks for exact candidate paths only.

    Track.path is the authoritative physical-source identity. This helper
    intentionally includes unavailable rows so returning files keep user state.
    """
    found: dict[str, models.Track] = {}
    for chunk in chunked(unique_strings(paths), chunk_size):
        for track in db.query(models.Track).filter(models.Track.path.in_(chunk)).all():
            if track.path:
                found[track.path] = track
    return found


@dataclass(frozen=True)
class DiagnosticRow:
    track_id: int
    path: str | None
    title: str | None
    recording_id: int
    release_id: int


def _diagnostic_rows_for_track_ids(db: Session, track_ids: list[int]) -> list[DiagnosticRow]:
    rows: list[DiagnosticRow] = []
    for chunk in chunked(track_ids, EXACT_PATH_LOOKUP_CHUNK_SIZE):
        query_rows = (
            db.query(
                models.Track.id,
                models.Track.path,
                models.Track.title,
                models.MusicTrackIdentity.recording_id,
                models.MusicEdition.release_id,
            )
            .join(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.Track.id)
            .join(models.MusicEdition, models.MusicEdition.id == models.MusicTrackIdentity.edition_id)
            .filter(models.Track.id.in_(chunk))
            .all()
        )
        rows.extend(
            DiagnosticRow(
                track_id=int(track_id),
                path=path,
                title=title,
                recording_id=int(recording_id),
                release_id=int(release_id),
            )
            for track_id, path, title, recording_id, release_id in query_rows
        )
    return rows


def _canonical_pair_payload_rows(first: DiagnosticRow, second: DiagnosticRow) -> tuple[DiagnosticRow, DiagnosticRow, int, int]:
    low_track_id, high_track_id = sorted([first.track_id, second.track_id])
    low_row = first if first.track_id == low_track_id else second
    high_row = second if second.track_id == high_track_id else first
    return low_row, high_row, low_track_id, high_track_id


def collect_music_scan_identity_diagnostics(
    db: Session,
    *,
    track_ids: list[int],
    warning_sample_limit: int = MAX_DUPLICATE_WARNING_SAMPLES,
) -> dict[str, object]:
    """Collect duplicate/variant scan diagnostics from first-class identity rows.

    Scope starts from tracks affected by the current scan, expands to their
    recording IDs, then reads only sibling links for those recordings.
    Public counters are affected-Track counts; warning rows are a bounded sample
    of unique canonical diagnostic relationships.
    """
    affected_ids = sorted({int(value) for value in track_ids if value is not None})
    result: dict[str, object] = {
        "physical_sources_preserved": 0,
        "duplicates_suspected": 0,
        "duplicate_warnings": [],
        "duplicate_warnings_truncated": False,
        "duplicate_warning_relationships": 0,
        "identity_diagnostic_recordings": 0,
        "identity_diagnostic_tracks": 0,
    }
    if not affected_ids:
        return result

    affected_rows = _diagnostic_rows_for_track_ids(db, affected_ids)
    affected_by_id = {row.track_id: row for row in affected_rows}
    recording_ids = sorted({row.recording_id for row in affected_rows})
    result["identity_diagnostic_recordings"] = len(recording_ids)
    if not recording_ids:
        return result

    sibling_rows: list[DiagnosticRow] = []
    for chunk in chunked(recording_ids, EXACT_PATH_LOOKUP_CHUNK_SIZE):
        query_rows = (
            db.query(
                models.Track.id,
                models.Track.path,
                models.Track.title,
                models.MusicTrackIdentity.recording_id,
                models.MusicEdition.release_id,
            )
            .join(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.Track.id)
            .join(models.MusicEdition, models.MusicEdition.id == models.MusicTrackIdentity.edition_id)
            .filter(models.MusicTrackIdentity.recording_id.in_(chunk))
            .order_by(models.MusicTrackIdentity.recording_id.asc(), models.MusicEdition.release_id.asc(), models.Track.id.asc())
            .all()
        )
        sibling_rows.extend(
            DiagnosticRow(
                track_id=int(track_id),
                path=path,
                title=title,
                recording_id=int(recording_id),
                release_id=int(release_id),
            )
            for track_id, path, title, recording_id, release_id in query_rows
        )
    result["identity_diagnostic_tracks"] = len(sibling_rows)

    siblings_by_recording: dict[int, list[DiagnosticRow]] = {}
    for row in sibling_rows:
        siblings_by_recording.setdefault(row.recording_id, []).append(row)

    warnings_by_key: dict[tuple[object, ...], dict[str, object]] = {}
    physical_count = 0
    duplicate_count = 0

    for track_id in affected_ids:
        current = affected_by_id.get(track_id)
        if current is None:
            continue
        siblings = sorted(
            [row for row in siblings_by_recording.get(current.recording_id, []) if row.track_id != current.track_id],
            key=lambda row: (row.release_id, row.track_id),
        )
        same_release = next((row for row in siblings if row.release_id == current.release_id), None)
        cross_release = next((row for row in siblings if row.release_id != current.release_id), None)
        if same_release is not None:
            physical_count += 1
            low_row, high_row, low_track_id, high_track_id = _canonical_pair_payload_rows(current, same_release)
            key = ("physical_source_preserved", low_track_id, high_track_id, current.recording_id, current.release_id)
            warnings_by_key.setdefault(key, {
                "type": "physical_source_preserved",
                "media_kind": "music",
                "title": low_row.title,
                "existing_id": high_row.track_id,
                "candidate_path": low_row.path,
                "reason": "same first-class recording and release; distinct physical path retained for identity/preference resolution",
                "recording_id": current.recording_id,
                "release_id": current.release_id,
                "track_ids": [low_track_id, high_track_id],
                "release_ids": [current.release_id],
            })
        if cross_release is not None:
            duplicate_count += 1
            low_row, high_row, low_track_id, high_track_id = _canonical_pair_payload_rows(current, cross_release)
            low_release_id, high_release_id = sorted([current.release_id, cross_release.release_id])
            key = ("recording_duplicate_detected", low_track_id, high_track_id, current.recording_id, low_release_id, high_release_id)
            warnings_by_key.setdefault(key, {
                "type": "recording_duplicate_detected",
                "media_kind": "music",
                "title": low_row.title,
                "existing_id": high_row.track_id,
                "candidate_path": low_row.path,
                "reason": "same first-class recording across different releases; kept as possible variant",
                "recording_id": current.recording_id,
                "release_id": high_release_id,
                "track_ids": [low_track_id, high_track_id],
                "release_ids": [low_release_id, high_release_id],
            })

    warning_keys = sorted(warnings_by_key)
    warnings = [warnings_by_key[key] for key in warning_keys[:warning_sample_limit]]
    result["physical_sources_preserved"] = physical_count
    result["duplicates_suspected"] = duplicate_count
    result["duplicate_warnings"] = warnings
    result["duplicate_warning_relationships"] = len(warning_keys)
    result["duplicate_warnings_truncated"] = len(warning_keys) > len(warnings)
    return result
