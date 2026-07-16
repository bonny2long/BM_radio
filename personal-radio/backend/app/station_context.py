from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy.orm import Session

from . import models
from .perf import perf_segment
from .radio_profiles import load_radio_profile_cache_for_tracks
from .station_candidates import (
    MAX_STATION_CANDIDATE_POOL,
    current_feedback_by_station_track,
    favorite_ids_by_station_track,
    load_station_candidate_tracks,
    play_counts_by_station_track,
    recent_ids_by_station_track,
)


@dataclass(frozen=True)
class StationRequestContext:
    tracks: list[models.Track]
    profile_cache: dict[str, Any]
    feedback: dict[int, str]
    favorites: set[int]
    play_counts: dict[int, int]
    recent: set[int]
    candidate_metrics: dict[str, Any]
    profile_metrics: dict[str, Any]


def _candidate_metrics(tracks: list[models.Track]) -> dict[str, Any]:
    recording_ids = {getattr(track, '_station_recording_id', None) for track in tracks if getattr(track, '_station_recording_id', None) is not None}
    profile_ids = {getattr(track, '_station_profile_track_id', track.id) for track in tracks}
    return {
        'recording_ids_loaded': len(recording_ids),
        'candidates_after_participation': len(tracks),
        'candidates_after_exclusion': len(tracks),
        'effective_sources_resolved': len([track for track in tracks if getattr(track, '_station_effective_track_id', None) is not None]),
        'profile_tracks_loaded': len(profile_ids),
        'legacy_candidates_loaded': len([track for track in tracks if getattr(track, '_station_recording_id', None) is None]),
        'final_candidate_pool_size': len(tracks),
        'candidate_cap_reached': len(tracks) >= MAX_STATION_CANDIDATE_POOL,
    }


def build_station_request_context(
    db: Session,
    *,
    limit: int = MAX_STATION_CANDIDATE_POOL,
    exclude_track_ids: Iterable[int | None] | None = None,
    seed_track: models.Track | None = None,
    include_feedback: bool = True,
    include_favorites: bool = True,
    include_play_counts: bool = True,
    include_recent: bool = True,
) -> StationRequestContext:
    with perf_segment('station.context_total'):
        with perf_segment('station.context_candidates'):
            with perf_segment('station.candidate_projection'):
                tracks = load_station_candidate_tracks(
                    db,
                    limit=limit,
                    exclude_track_ids=exclude_track_ids or [],
                    seed_track_id=seed_track.id if seed_track is not None else None,
                )
        candidate_metrics = _candidate_metrics(tracks)
        extra_tracks = [seed_track] if seed_track is not None else []
        with perf_segment('station.profile_cache'):
            with perf_segment('station.profile_scope_keys'):
                scoped_tracks = list(tracks)
            profile_cache = load_radio_profile_cache_for_tracks(db, scoped_tracks, extra_tracks=extra_tracks)
        profile_metrics = dict(profile_cache.get('_station_profile_metrics') or {})

        feedback: dict[int, str] = {}
        favorites: set[int] = set()
        play_counts: dict[int, int] = {}
        recent: set[int] = set()
        with perf_segment('station.context_signals'):
            if include_feedback:
                with perf_segment('station.listener_signals.feedback'):
                    feedback = current_feedback_by_station_track(db, tracks)
            if include_favorites:
                with perf_segment('station.listener_signals.favorites'):
                    favorites = favorite_ids_by_station_track(db, tracks)
            if include_play_counts:
                with perf_segment('station.listener_signals.play_counts'):
                    play_counts = play_counts_by_station_track(db, tracks)
            if include_recent:
                with perf_segment('station.listener_signals.recent'):
                    recent = recent_ids_by_station_track(db, tracks)

        context = StationRequestContext(
            tracks=tracks,
            profile_cache=profile_cache,
            feedback=feedback,
            favorites=favorites,
            play_counts=play_counts,
            recent=recent,
            candidate_metrics=candidate_metrics,
            profile_metrics=profile_metrics,
        )
        db.info['station_request_context_metrics'] = {
            'candidate_metrics': candidate_metrics,
            'profile_metrics': profile_metrics,
        }
        return context