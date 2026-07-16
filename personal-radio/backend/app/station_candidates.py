from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from . import models
from .availability import LIBRARY_AVAILABLE, TRACK_UNAVAILABLE_MESSAGE, is_track_available
from .music_recording_participation import PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY
from .music_source_preference import resolve_effective_music_sources_read_only
from .perf import perf_segment
from .station_candidate_intent import INTENT_GLOBAL, StationCandidateIntent, global_intent

AUTOMATIC_PARTICIPATION_STATES = {PARTICIPATION_INCLUDED}
SEED_PARTICIPATION_STATES = {PARTICIPATION_INCLUDED, PARTICIPATION_LIBRARY_ONLY}
MAX_STATION_CANDIDATE_POOL = 5000


def _has_table(db: Session, table_name: str) -> bool:
    return sqlalchemy_inspect(db.get_bind()).has_table(table_name)


def _has_column(db: Session, table_name: str, column_name: str) -> bool:
    if not _has_table(db, table_name):
        return False
    return any(column["name"] == column_name for column in sqlalchemy_inspect(db.get_bind()).get_columns(table_name))


@dataclass(frozen=True)
class StationRecordingCandidate:
    recording_id: int | None
    candidate_key: tuple[str, int]
    profile_track: models.Track
    effective_track: models.Track
    participation_state: str
    recording_type: str | None
    version_hint: str | None
    source_resolution: str | None
    source_confidence: str | None
    source_reason_code: str | None


def unique_ints(values: Iterable[int | None]) -> list[int]:
    return list(dict.fromkeys(int(value) for value in values if value is not None))


def _track_rows_by_id(db: Session, track_ids: Iterable[int | None]) -> dict[int, models.Track]:
    ids = unique_ints(track_ids)
    if not ids:
        return {}
    return {row.id: row for row in db.query(models.Track).filter(models.Track.id.in_(ids)).all()}



def _attach_candidate_metadata(track: models.Track, candidate: StationRecordingCandidate) -> models.Track:
    for attr in ("_station_version_affinity_mode", "_station_version_affinity_tier", "_station_version_affinity_score"):
        if hasattr(track, attr):
            delattr(track, attr)
    setattr(track, "_station_candidate", candidate)
    setattr(track, "_station_recording_id", candidate.recording_id)
    setattr(track, "_station_effective_track_id", candidate.effective_track.id)
    setattr(track, "_station_profile_track_id", candidate.profile_track.id)
    setattr(track, "_station_participation_state", candidate.participation_state)
    setattr(track, "_station_recording_type", candidate.recording_type)
    setattr(track, "_station_version_hint", candidate.version_hint)
    setattr(track, "_station_source_resolution", candidate.source_resolution)
    setattr(track, "_station_source_confidence", candidate.source_confidence)
    setattr(track, "_station_source_reason_code", candidate.source_reason_code)
    return track


def station_candidate_for_track(track: models.Track) -> StationRecordingCandidate | None:
    return getattr(track, "_station_candidate", None)


def station_identity_key_for_track(track: models.Track | None) -> tuple[str, int] | None:
    if track is None:
        return None
    candidate = station_candidate_for_track(track)
    if candidate is not None:
        return candidate.candidate_key
    return ("track", int(track.id))


def station_identity_keys_for_track_ids(db: Session, track_ids: Iterable[int | None]) -> set[tuple[str, int]]:
    ids = unique_ints(track_ids)
    if not ids:
        return set()
    if not _has_table(db, "music_track_identities"):
        return {("track", track_id) for track_id in ids}
    rows = db.query(models.MusicTrackIdentity.track_id, models.MusicTrackIdentity.recording_id).filter(models.MusicTrackIdentity.track_id.in_(ids)).all()
    by_track = {int(track_id): int(recording_id) for track_id, recording_id in rows}
    out: set[tuple[str, int]] = set()
    for track_id in ids:
        recording_id = by_track.get(track_id)
        out.add(("recording", recording_id) if recording_id is not None else ("track", track_id))
    return out


def seed_recording_id_for_track(db: Session, track_id: int | None) -> int | None:
    if track_id is None:
        return None
    if not _has_table(db, "music_track_identities"):
        return None
    return db.query(models.MusicTrackIdentity.recording_id).filter_by(track_id=track_id).scalar()


def validate_song_seed_track(db: Session, track: models.Track) -> tuple[int | None, str | None]:
    if not is_track_available(track):
        raise HTTPException(409, TRACK_UNAVAILABLE_MESSAGE)
    if not _has_table(db, "music_track_identities") or not _has_table(db, "music_recording_participation"):
        return None, None
    row = (
        db.query(models.MusicTrackIdentity.recording_id, models.MusicRecordingParticipation.participation_state)
        .outerjoin(models.MusicRecordingParticipation, models.MusicRecordingParticipation.recording_id == models.MusicTrackIdentity.recording_id)
        .filter(models.MusicTrackIdentity.track_id == track.id)
        .one_or_none()
    )
    if row is None:
        return None, None
    state = row.participation_state or PARTICIPATION_INCLUDED
    if state not in SEED_PARTICIPATION_STATES:
        raise HTTPException(409, "Recording is not eligible as a station seed")
    return int(row.recording_id), state

def _recording_rows_by_id(db: Session, recording_ids: list[int]) -> dict[int, models.MusicRecording]:
    if not recording_ids:
        return {}
    return {row.id: row for row in db.query(models.MusicRecording).filter(models.MusicRecording.id.in_(recording_ids)).all()}


def select_station_recording_ids(
    db: Session,
    *,
    limit: int,
    excluded_recording_ids: set[int] | None = None,
) -> list[int]:
    bounded = max(1, min(int(limit), MAX_STATION_CANDIDATE_POOL))
    excluded = {int(value) for value in (excluded_recording_ids or set()) if value is not None}
    with perf_segment("station.candidate_identity_query"):
        with perf_segment("station.candidate_sql_eligibility"):
            query = (
                db.query(
                    models.MusicTrackIdentity.recording_id.label("recording_id"),
                    func.min(models.Track.created_at).label("first_seen"),
                    func.min(models.Track.id).label("stable_id"),
                )
                .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
                .outerjoin(models.MusicRecordingParticipation, models.MusicRecordingParticipation.recording_id == models.MusicTrackIdentity.recording_id)
                .filter(models.Track.library_availability == LIBRARY_AVAILABLE)
                .filter(or_(models.MusicRecordingParticipation.id.is_(None), models.MusicRecordingParticipation.participation_state == PARTICIPATION_INCLUDED))
            )
            if excluded:
                query = query.filter(~models.MusicTrackIdentity.recording_id.in_(excluded))
            rows = (
                query
                .group_by(models.MusicTrackIdentity.recording_id)
                .order_by(func.min(models.Track.created_at).desc(), func.min(models.Track.id).asc())
                .limit(bounded)
                .all()
            )
    return unique_ints([row.recording_id for row in rows])


def _sql_text_token(column):
    return func.lower(func.replace(func.replace(func.trim(func.coalesce(column, '')), '_', ' '), '-', ' '))


def _sql_token_variants(values: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value or '').strip().lower().replace('_', ' ')
        for variant in (token, token.replace('-', ' '), token.replace(' ', '-')):
            variant = variant.strip()
            if variant and variant not in seen:
                seen.add(variant)
                out.append(variant)
    return tuple(out)


def _eligible_recording_query(db: Session, *, excluded_recording_ids: set[int] | None = None):
    excluded = {int(value) for value in (excluded_recording_ids or set()) if value is not None}
    query = (
        db.query(
            models.MusicTrackIdentity.recording_id.label('recording_id'),
            func.min(models.Track.created_at).label('first_seen'),
            func.min(models.Track.id).label('stable_id'),
        )
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .outerjoin(models.MusicRecordingParticipation, models.MusicRecordingParticipation.recording_id == models.MusicTrackIdentity.recording_id)
        .filter(models.Track.library_availability == LIBRARY_AVAILABLE)
        .filter(or_(models.MusicRecordingParticipation.id.is_(None), models.MusicRecordingParticipation.participation_state == PARTICIPATION_INCLUDED))
    )
    if excluded:
        query = query.filter(~models.MusicTrackIdentity.recording_id.in_(excluded))
    return query


def eligible_station_recording_count(db: Session, *, excluded_recording_ids: set[int] | None = None) -> int:
    query = _eligible_recording_query(db, excluded_recording_ids=excluded_recording_ids)
    subq = query.group_by(models.MusicTrackIdentity.recording_id).subquery()
    return int(db.query(func.count()).select_from(subq).scalar() or 0)


def _select_station_recording_ids_by_intent_filters(
    db: Session,
    *,
    limit: int,
    excluded_recording_ids: set[int] | None = None,
    artist_tokens: Iterable[str] = (),
    exact_genre_tokens: Iterable[str] = (),
    family_genre_tokens: Iterable[str] = (),
) -> list[int]:
    bounded = max(0, min(int(limit), MAX_STATION_CANDIDATE_POOL))
    if bounded <= 0:
        return []
    artist_values = _sql_token_variants(artist_tokens)
    exact_values = _sql_token_variants(exact_genre_tokens)
    family_values = _sql_token_variants(family_genre_tokens)
    if not artist_values and not exact_values and not family_values:
        return select_station_recording_ids(db, limit=bounded, excluded_recording_ids=excluded_recording_ids)

    query = _eligible_recording_query(db, excluded_recording_ids=excluded_recording_ids)
    genre_columns = [_sql_text_token(models.Track.genre), _sql_text_token(models.Track.primary_genre)]
    if _has_table(db, 'track_radio_profiles'):
        query = query.outerjoin(models.TrackRadioProfile, models.TrackRadioProfile.track_id == models.Track.id)
        genre_columns.append(_sql_text_token(models.TrackRadioProfile.primary_genre))
    if _has_table(db, 'artist_radio_profiles'):
        artist_match = or_(
            _sql_text_token(models.ArtistRadioProfile.artist) == _sql_text_token(models.Track.artist),
            _sql_text_token(models.ArtistRadioProfile.artist) == _sql_text_token(models.Track.album_artist),
        )
        query = query.outerjoin(models.ArtistRadioProfile, artist_match)
        genre_columns.append(_sql_text_token(models.ArtistRadioProfile.primary_genre))
    if _has_table(db, 'album_radio_profiles'):
        album_match = and_(
            _sql_text_token(models.AlbumRadioProfile.album) == _sql_text_token(models.Track.album),
            or_(
                _sql_text_token(models.AlbumRadioProfile.artist) == _sql_text_token(models.Track.artist),
                _sql_text_token(models.AlbumRadioProfile.artist) == _sql_text_token(models.Track.album_artist),
            ),
        )
        query = query.outerjoin(models.AlbumRadioProfile, album_match)
        genre_columns.append(_sql_text_token(models.AlbumRadioProfile.primary_genre))

    filters = []
    if artist_values:
        filters.append(or_(_sql_text_token(models.Track.artist).in_(artist_values), _sql_text_token(models.Track.album_artist).in_(artist_values)))
    if exact_values:
        filters.append(or_(*[column.in_(exact_values) for column in genre_columns]))
    if family_values:
        filters.append(or_(*[column.in_(family_values) for column in genre_columns]))
    rows = (
        query
        .filter(or_(*filters))
        .group_by(models.MusicTrackIdentity.recording_id)
        .order_by(func.min(models.Track.created_at).desc(), func.min(models.Track.id).asc())
        .limit(bounded)
        .all()
    )
    return unique_ints([row.recording_id for row in rows])


def select_intent_station_recording_ids(
    db: Session,
    *,
    limit: int,
    excluded_recording_ids: set[int] | None,
    intent: StationCandidateIntent,
) -> tuple[list[int], dict[str, Any]]:
    bounded = max(1, min(int(limit), MAX_STATION_CANDIDATE_POOL))
    excluded = {int(value) for value in (excluded_recording_ids or set()) if value is not None}
    selected: list[int] = []
    selected_set: set[int] = set()
    bucket_counts: dict[str, int] = {}
    duplicates_removed = 0
    query_count = 0

    def add_bucket(name: str, ids: list[int]) -> None:
        nonlocal duplicates_removed
        added = 0
        for recording_id in ids:
            if recording_id in selected_set:
                duplicates_removed += 1
                continue
            selected_set.add(recording_id)
            selected.append(recording_id)
            added += 1
            if len(selected) >= bounded:
                break
        bucket_counts[name] = bucket_counts.get(name, 0) + added

    def run_bucket(name: str, *, artist_tokens=(), exact_genre_tokens=(), family_genre_tokens=()) -> None:
        nonlocal query_count
        if len(selected) >= bounded:
            return
        bucket_limit = int(intent.bucket_limits.get(name, bounded) or bounded)
        bucket_limit = max(0, min(bucket_limit, bounded - len(selected)))
        if bucket_limit <= 0:
            bucket_counts.setdefault(name, 0)
            return
        combined_excluded = excluded | selected_set
        query_count += 1
        ids = _select_station_recording_ids_by_intent_filters(
            db,
            limit=bucket_limit,
            excluded_recording_ids=combined_excluded,
            artist_tokens=artist_tokens,
            exact_genre_tokens=exact_genre_tokens,
            family_genre_tokens=family_genre_tokens,
        )
        add_bucket(name, ids)

    if intent.mode in {'song', 'artist'}:
        run_bucket('seed_artist', artist_tokens=intent.seed_artist_tokens)
        run_bucket('related_artists', artist_tokens=intent.related_artist_tokens)
        run_bucket('exact_genre', exact_genre_tokens=intent.exact_genre_tokens)
        run_bucket('genre_family', family_genre_tokens=intent.family_genre_tokens)
    elif intent.mode == 'genre':
        run_bucket('exact_genre', exact_genre_tokens=intent.exact_genre_tokens)
        run_bucket('genre_family', family_genre_tokens=intent.family_genre_tokens)

    if len(selected) < bounded:
        run_bucket('global_fallback')

    metrics = intent.debug_summary(bucket_counts=bucket_counts, duplicates_removed=duplicates_removed, total=len(selected))
    metrics['bucket_query_count'] = query_count
    return selected[:bounded], metrics


def _deterministic_profile_track_ids(db: Session, recording_ids: list[int]) -> dict[int, int]:
    if not recording_ids:
        return {}
    row_number = func.row_number().over(
        partition_by=models.MusicTrackIdentity.recording_id,
        order_by=(models.Track.created_at.asc(), models.Track.relative_path.asc(), models.Track.id.asc()),
    ).label("rn")
    subq = (
        db.query(
            models.MusicTrackIdentity.recording_id.label("recording_id"),
            models.Track.id.label("track_id"),
            row_number,
        )
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .filter(models.MusicTrackIdentity.recording_id.in_(recording_ids), models.Track.library_availability == LIBRARY_AVAILABLE)
        .subquery()
    )
    return {int(row.recording_id): int(row.track_id) for row in db.query(subq).filter(subq.c.rn == 1).all()}


def _projection_metrics(
    *,
    bounded: int,
    excluded_recording_ids: set[int],
    excluded_legacy_track_ids: set[int],
    recording_ids: list[int],
    resolutions: dict[int, object],
    profile_ids: dict[int, int],
    tracks_by_id: dict[int, models.Track],
    recordings: dict[int, models.MusicRecording],
    legacy_candidates: list[StationRecordingCandidate],
    final_candidates: list[StationRecordingCandidate],
    intent_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_track_ids = unique_ints([getattr(resolution, "track_id", None) for resolution in resolutions.values()])
    metrics: dict[str, Any] = {
        "candidate_limit": bounded,
        "excluded_recording_ids": len(excluded_recording_ids),
        "excluded_legacy_track_ids": len(excluded_legacy_track_ids),
        "recording_ids_selected": len(recording_ids),
        "recording_ids_source_resolved": len(recording_ids),
        "recording_ids_with_effective_source": len(effective_track_ids),
        "recording_rows_loaded": len(recordings),
        "profile_track_ids_selected": len(set(profile_ids.values())),
        "effective_track_ids_selected": len(effective_track_ids),
        "track_rows_hydrated": len(tracks_by_id),
        "legacy_track_rows_selected": len(legacy_candidates),
        "final_candidate_pool_size": len(final_candidates),
        "candidate_cap_reached": len(final_candidates) >= bounded,
        "recording_ids_loaded": len([candidate for candidate in final_candidates if candidate.recording_id is not None]),
        "candidates_after_participation": len(recording_ids) + len(legacy_candidates),
        "candidates_after_exclusion": len(recording_ids) + len(legacy_candidates),
        "effective_sources_resolved": len(effective_track_ids),
        "profile_tracks_loaded": len(set(profile_ids.values()) | {candidate.profile_track.id for candidate in legacy_candidates}),
        "legacy_candidates_loaded": len(legacy_candidates),
        "fixed_3x_overfetch_removed": True,
    }
    if intent_metrics:
        metrics.update({f"candidate_intent_{key}": value for key, value in intent_metrics.items()})
    return metrics


def load_station_recording_candidates(
    db: Session,
    *,
    limit: int = MAX_STATION_CANDIDATE_POOL,
    exclude_keys: set[tuple[str, int]] | None = None,
    candidate_intent: StationCandidateIntent | None = None,
) -> list[StationRecordingCandidate]:
    bounded = max(1, min(int(limit), MAX_STATION_CANDIDATE_POOL))
    exclude = exclude_keys or set()
    excluded_recording_ids = {int(value) for kind, value in exclude if kind == "recording" and value is not None}
    excluded_legacy_track_ids = {int(value) for kind, value in exclude if kind == "track" and value is not None}
    if not _has_table(db, "music_track_identities"):
        legacy = _legacy_track_candidates(db, limit=bounded, exclude=exclude)
        db.info["station_candidate_projection_metrics"] = _projection_metrics(
            bounded=bounded,
            excluded_recording_ids=excluded_recording_ids,
            excluded_legacy_track_ids=excluded_legacy_track_ids,
            recording_ids=[],
            resolutions={},
            profile_ids={},
            tracks_by_id={candidate.effective_track.id: candidate.effective_track for candidate in legacy},
            recordings={},
            legacy_candidates=legacy,
            final_candidates=legacy,
        )
        return legacy

    selection_intent = candidate_intent or global_intent(requested_queue_limit=bounded, candidate_limit=bounded)
    intent_metrics: dict[str, Any] | None = None
    if selection_intent.mode == INTENT_GLOBAL:
        recording_ids = select_station_recording_ids(db, limit=bounded, excluded_recording_ids=excluded_recording_ids)
        intent_metrics = selection_intent.debug_summary(bucket_counts={'global': len(recording_ids)}, total=len(recording_ids))
    else:
        with perf_segment('station.candidate_intent_count'):
            eligible_count = eligible_station_recording_count(db, excluded_recording_ids=excluded_recording_ids)
        if eligible_count <= bounded:
            recording_ids = select_station_recording_ids(db, limit=bounded, excluded_recording_ids=excluded_recording_ids)
            intent_metrics = selection_intent.debug_summary(bucket_counts={'global_below_cap': len(recording_ids)}, total=len(recording_ids))
            intent_metrics['below_cap_global_equivalent'] = True
        else:
            with perf_segment('station.candidate_intent_buckets'):
                recording_ids, intent_metrics = select_intent_station_recording_ids(
                    db,
                    limit=bounded,
                    excluded_recording_ids=excluded_recording_ids,
                    intent=selection_intent,
                )
            intent_metrics['below_cap_global_equivalent'] = False
    with perf_segment('station.candidate_participation'):
        participation: dict[int, str] = {recording_id: PARTICIPATION_INCLUDED for recording_id in recording_ids}
    with perf_segment('station.source_resolution'):
        resolutions = resolve_effective_music_sources_read_only(db, recording_ids=recording_ids)
    with perf_segment('station.profile_track_resolution'):
        profile_ids = _deterministic_profile_track_ids(db, recording_ids)
    with perf_segment('station.track_hydration'):
        effective_ids = [resolution.track_id for resolution in resolutions.values()]
        tracks_by_id = _track_rows_by_id(db, effective_ids + list(profile_ids.values()))
        with perf_segment('station.candidate_recording_hydration'):
            recordings = _recording_rows_by_id(db, recording_ids)

    candidates: list[StationRecordingCandidate] = []
    for recording_id in recording_ids:
        resolution = resolutions.get(recording_id)
        if resolution is None or resolution.track_id is None:
            continue
        effective_track = tracks_by_id.get(int(resolution.track_id))
        profile_track = tracks_by_id.get(profile_ids.get(recording_id) or int(resolution.track_id))
        recording = recordings.get(recording_id)
        if effective_track is None or profile_track is None:
            continue
        candidate = StationRecordingCandidate(
            recording_id=recording_id,
            candidate_key=("recording", recording_id),
            profile_track=profile_track,
            effective_track=effective_track,
            participation_state=participation.get(recording_id, PARTICIPATION_INCLUDED),
            recording_type=recording.recording_type if recording is not None else None,
            version_hint=recording.version_hint if recording is not None else None,
            source_resolution=resolution.source,
            source_confidence=resolution.confidence,
            source_reason_code=resolution.reason_code,
        )
        candidates.append(candidate)
        if len(candidates) >= bounded:
            break

    with perf_segment('station.candidate_legacy_fill'):
        legacy_candidates = _legacy_track_candidates(db, limit=max(0, bounded - len(candidates)), exclude=exclude)
    candidates.extend(legacy_candidates)
    final_candidates = candidates[:bounded]
    db.info["station_candidate_projection_metrics"] = _projection_metrics(
        bounded=bounded,
        excluded_recording_ids=excluded_recording_ids,
        excluded_legacy_track_ids=excluded_legacy_track_ids,
        recording_ids=recording_ids,
        resolutions=resolutions,
        profile_ids=profile_ids,
        tracks_by_id=tracks_by_id,
        recordings=recordings,
        legacy_candidates=legacy_candidates,
        final_candidates=final_candidates,
        intent_metrics=intent_metrics,
    )
    return final_candidates


def _legacy_track_candidates(db: Session, *, limit: int, exclude: set[tuple[str, int]]) -> list[StationRecordingCandidate]:
    if limit <= 0:
        return []
    excluded_track_ids = {int(value) for kind, value in exclude if kind == "track" and value is not None}
    query = db.query(models.Track)
    if _has_table(db, "music_track_identities"):
        query = query.outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.Track.id).filter(models.MusicTrackIdentity.id.is_(None))
    query = query.filter(models.Track.library_availability == LIBRARY_AVAILABLE)
    if excluded_track_ids:
        query = query.filter(~models.Track.id.in_(excluded_track_ids))
    legacy_tracks = (
        query
        .order_by(models.Track.created_at.desc(), models.Track.id.asc())
        .limit(limit)
        .all()
    )
    candidates: list[StationRecordingCandidate] = []
    for track in legacy_tracks:
        key = ("track", int(track.id))
        candidates.append(StationRecordingCandidate(
            recording_id=None,
            candidate_key=key,
            profile_track=track,
            effective_track=track,
            participation_state=PARTICIPATION_INCLUDED,
            recording_type=None,
            version_hint=None,
            source_resolution="legacy_track",
            source_confidence=None,
            source_reason_code=None,
        ))
        if len(candidates) >= limit:
            break
    return candidates

def station_tracks_from_candidates(candidates: list[StationRecordingCandidate]) -> list[models.Track]:
    return [_attach_candidate_metadata(candidate.effective_track, candidate) for candidate in candidates]


def load_station_candidate_tracks(
    db: Session,
    *,
    limit: int = MAX_STATION_CANDIDATE_POOL,
    exclude_track_ids: Iterable[int | None] | None = None,
    seed_track_id: int | None = None,
    candidate_intent: StationCandidateIntent | None = None,
) -> list[models.Track]:
    exclude_keys = station_identity_keys_for_track_ids(db, exclude_track_ids or [])
    if seed_track_id is not None:
        seed_recording_id = seed_recording_id_for_track(db, seed_track_id)
        exclude_keys.add(("recording", seed_recording_id) if seed_recording_id is not None else ("track", int(seed_track_id)))
    return station_tracks_from_candidates(load_station_recording_candidates(db, limit=limit, exclude_keys=exclude_keys, candidate_intent=candidate_intent))


def current_feedback_by_station_track(db: Session, tracks: list[models.Track]) -> dict[int, str]:
    recording_ids = unique_ints([getattr(track, "_station_recording_id", None) for track in tracks])
    result: dict[int, str] = {}
    can_join_identity = _has_table(db, "music_track_identities")
    has_thumb_recording_id = _has_column(db, "track_thumbs", "recording_id")
    if recording_ids and can_join_identity and has_thumb_recording_id:
        rec_id = func.coalesce(models.TrackThumb.recording_id, models.MusicTrackIdentity.recording_id).label("recording_id")
        row_number = func.row_number().over(partition_by=rec_id, order_by=(models.TrackThumb.created_at.desc(), models.TrackThumb.id.desc())).label("rn")
        subq = (
            db.query(rec_id, models.TrackThumb.value.label("value"), row_number)
            .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.TrackThumb.track_id)
            .filter(rec_id.in_(recording_ids))
            .subquery()
        )
        value_by_recording = {int(row.recording_id): (row.value.value if hasattr(row.value, "value") else str(row.value)) for row in db.query(subq).filter(subq.c.rn == 1).all()}
        for track in tracks:
            recording_id = getattr(track, "_station_recording_id", None)
            if recording_id in value_by_recording:
                result[track.id] = value_by_recording[recording_id]
    legacy_ids = [track.id for track in tracks if getattr(track, "_station_recording_id", None) is None]
    if legacy_ids:
        query = db.query(models.TrackThumb).filter(models.TrackThumb.track_id.in_(legacy_ids))
        if has_thumb_recording_id:
            query = query.filter(models.TrackThumb.recording_id.is_(None))
        rows = query.order_by(models.TrackThumb.created_at.asc(), models.TrackThumb.id.asc()).all()
        for row in rows:
            result[row.track_id] = row.value.value if hasattr(row.value, "value") else str(row.value)
    return result


def favorite_ids_by_station_track(db: Session, tracks: list[models.Track]) -> set[int]:
    recording_ids = unique_ints([getattr(track, "_station_recording_id", None) for track in tracks])
    favorite_recordings: set[int] = set()
    can_join_identity = _has_table(db, "music_track_identities")
    has_favorite_recording_id = _has_column(db, "track_favorites", "recording_id")
    if recording_ids and can_join_identity and has_favorite_recording_id:
        rec_id = func.coalesce(models.TrackFavorite.recording_id, models.MusicTrackIdentity.recording_id)
        rows = (
            db.query(rec_id.label("recording_id"))
            .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.TrackFavorite.track_id)
            .filter(rec_id.in_(recording_ids))
            .group_by(rec_id)
            .all()
        )
        favorite_recordings = {int(row.recording_id) for row in rows}
    legacy_ids = [track.id for track in tracks if getattr(track, "_station_recording_id", None) is None]
    favorite_legacy = set()
    if legacy_ids:
        query = db.query(models.TrackFavorite.track_id).filter(models.TrackFavorite.track_id.in_(legacy_ids))
        if has_favorite_recording_id:
            query = query.filter(models.TrackFavorite.recording_id.is_(None))
        favorite_legacy = {int(row[0]) for row in query.all()}
    return {track.id for track in tracks if getattr(track, "_station_recording_id", None) in favorite_recordings or track.id in favorite_legacy}


def play_counts_by_station_track(db: Session, tracks: list[models.Track]) -> dict[int, int]:
    recording_ids = unique_ints([getattr(track, "_station_recording_id", None) for track in tracks])
    result: dict[int, int] = {}
    can_join_identity = _has_table(db, "music_track_identities")
    has_event_recording_id = _has_column(db, "playback_events", "recording_id")
    if recording_ids and can_join_identity and has_event_recording_id:
        rec_id = func.coalesce(models.PlaybackEvent.recording_id, models.MusicTrackIdentity.recording_id)
        rows = (
            db.query(rec_id.label("recording_id"), func.count(models.PlaybackEvent.id).label("plays"))
            .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.PlaybackEvent.track_id)
            .filter(models.PlaybackEvent.event_type == "qualified_play", rec_id.in_(recording_ids))
            .group_by(rec_id)
            .all()
        )
        plays_by_recording = {int(row.recording_id): int(row.plays or 0) for row in rows}
        for track in tracks:
            recording_id = getattr(track, "_station_recording_id", None)
            if recording_id in plays_by_recording:
                result[track.id] = plays_by_recording[recording_id]
    legacy_ids = [track.id for track in tracks if getattr(track, "_station_recording_id", None) is None]
    if legacy_ids:
        rows = db.query(models.PlaybackEvent.track_id, func.count(models.PlaybackEvent.id)).filter(models.PlaybackEvent.event_type == "qualified_play", models.PlaybackEvent.track_id.in_(legacy_ids)).group_by(models.PlaybackEvent.track_id).all()
        result.update({int(track_id): int(count or 0) for track_id, count in rows})
    return result


def recent_ids_by_station_track(db: Session, tracks: list[models.Track], limit: int = 80) -> set[int]:
    recording_ids = unique_ints([getattr(track, "_station_recording_id", None) for track in tracks])
    recent_recordings: set[int] = set()
    can_join_identity = _has_table(db, "music_track_identities")
    has_event_recording_id = _has_column(db, "playback_events", "recording_id")
    if recording_ids and can_join_identity and has_event_recording_id:
        rec_id = func.coalesce(models.PlaybackEvent.recording_id, models.MusicTrackIdentity.recording_id)
        rows = (
            db.query(rec_id.label("recording_id"))
            .outerjoin(models.MusicTrackIdentity, models.MusicTrackIdentity.track_id == models.PlaybackEvent.track_id)
            .filter(models.PlaybackEvent.event_type == "qualified_play", rec_id.in_(recording_ids))
            .order_by(models.PlaybackEvent.created_at.desc())
            .limit(limit)
            .all()
        )
        recent_recordings = {int(row.recording_id) for row in rows if row.recording_id is not None}
    legacy_ids = [track.id for track in tracks if getattr(track, "_station_recording_id", None) is None]
    recent_legacy: set[int] = set()
    if legacy_ids:
        rows = db.query(models.PlaybackEvent.track_id).filter(models.PlaybackEvent.event_type == "qualified_play", models.PlaybackEvent.track_id.in_(legacy_ids)).order_by(models.PlaybackEvent.created_at.desc()).limit(limit).all()
        recent_legacy = {int(row[0]) for row in rows if row[0] is not None}
    return {track.id for track in tracks if getattr(track, "_station_recording_id", None) in recent_recordings or track.id in recent_legacy}


def logical_station_count(db: Session, *, station_type: str, seed_value: str | None = None) -> int:
    tracks = load_station_candidate_tracks(db, limit=MAX_STATION_CANDIDATE_POOL)
    if station_type == "favorites":
        fb = current_feedback_by_station_track(db, tracks)
        favs = favorite_ids_by_station_track(db, tracks)
        return len([track for track in tracks if track.id in favs or fb.get(track.id) == "up"])
    if station_type == "recently_added":
        return len(tracks)
    if station_type == "deep_cuts":
        counts = play_counts_by_station_track(db, tracks)
        return len([track for track in tracks if counts.get(track.id, 0) <= 1])
    if station_type == "artist" and seed_value:
        token = str(seed_value).strip().lower()
        return len([track for track in tracks if (track.artist or "").strip().lower() == token or (track.album_artist or "").strip().lower() == token])
    if station_type == "genre" and seed_value:
        target = str(seed_value or "").strip().lower()
        return len([track for track in tracks if target and target in (track.genre or "").strip().lower()])
    return 0
