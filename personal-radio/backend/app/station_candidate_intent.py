from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import models, radio_genres
from .radio_profiles import load_radio_profile_cache_for_tracks, normalize_token, profile_for_track_cached, row_profile
from .station_seed_knowledge import ARTIST_GENRE_FALLBACKS, RELATED_ARTISTS, lookup_by_normalized

INTENT_GLOBAL = 'global'
INTENT_SONG = 'song'
INTENT_ARTIST = 'artist'
INTENT_GENRE = 'genre'


@dataclass(frozen=True)
class StationCandidateIntent:
    mode: str = INTENT_GLOBAL
    source: str = 'global'
    seed_recording_id: int | None = None
    seed_track_id: int | None = None
    seed_artist_tokens: tuple[str, ...] = ()
    related_artist_tokens: tuple[str, ...] = ()
    exact_genre_tokens: tuple[str, ...] = ()
    family_genre_tokens: tuple[str, ...] = ()
    requested_queue_limit: int = 50
    bucket_limits: dict[str, int] = field(default_factory=dict)

    def debug_summary(self, bucket_counts: dict[str, int] | None = None, duplicates_removed: int = 0, total: int = 0) -> dict[str, Any]:
        return {
            'mode': self.mode,
            'source': self.source,
            'seed_recording_id': self.seed_recording_id,
            'seed_track_id': self.seed_track_id,
            'seed_artist_tokens': list(self.seed_artist_tokens[:8]),
            'related_artist_token_count': len(self.related_artist_tokens),
            'exact_genre_tokens': list(self.exact_genre_tokens),
            'family_genre_token_count': len(self.family_genre_tokens),
            'bucket_limits': dict(self.bucket_limits),
            'bucket_selected_counts': dict(bucket_counts or {}),
            'bucket_duplicates_removed': int(duplicates_removed),
            'deduplicated_total': int(total),
        }


def _tokens(values) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = normalize_token(value)
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return tuple(out)


def _genre_token(value: str | None) -> str | None:
    return radio_genres.normalize_genre(value)


def _genre_family_tokens(values) -> tuple[str, ...]:
    tokens: set[str] = set()
    for value in values:
        token = _genre_token(value)
        if token:
            tokens.update(radio_genres.genre_family_tokens(token) or {token})
    return tuple(sorted(tokens))


def intent_bucket_limits(*, mode: str, candidate_limit: int, requested_queue_limit: int) -> dict[str, int]:
    limit = max(1, int(candidate_limit))
    q = max(1, int(requested_queue_limit or 50))
    if mode == INTENT_ARTIST:
        seed = min(max(q * 10, 500), max(500, limit // 3))
        related = min(max(q * 10, 750), max(500, limit // 4))
        exact = min(max(q * 10, 750), max(500, limit // 3))
        family = max(0, limit - seed - related - exact)
        return {'seed_artist': seed, 'related_artists': related, 'exact_genre': exact, 'genre_family': family, 'global_fallback': limit}
    if mode == INTENT_GENRE:
        exact = min(limit, max(q * 30, int(limit * 0.70)))
        family = limit
        return {'exact_genre': exact, 'genre_family': family, 'global_fallback': limit}
    if mode == INTENT_SONG:
        seed = min(max(q * 8, 400), max(400, limit // 5))
        related = min(max(q * 12, 750), max(500, limit // 4))
        exact = min(max(q * 20, 1000), max(1000, limit // 3))
        family = max(0, limit - seed - related - exact)
        return {'seed_artist': seed, 'related_artists': related, 'exact_genre': exact, 'genre_family': family, 'global_fallback': limit}
    return {'global': limit}


def global_intent(*, requested_queue_limit: int = 50, candidate_limit: int = 5000) -> StationCandidateIntent:
    return StationCandidateIntent(mode=INTENT_GLOBAL, source='global', requested_queue_limit=requested_queue_limit, bucket_limits=intent_bucket_limits(mode=INTENT_GLOBAL, candidate_limit=candidate_limit, requested_queue_limit=requested_queue_limit))


def _recording_id_for_track(db: Session, track_id: int | None) -> int | None:
    if track_id is None:
        return None
    row = db.query(models.MusicTrackIdentity.recording_id).filter_by(track_id=track_id).one_or_none()
    return int(row[0]) if row is not None and row[0] is not None else None


def _scoped_track_profile(db: Session, track: models.Track) -> dict[str, Any]:
    cache = load_radio_profile_cache_for_tracks(db, [track])
    return profile_for_track_cached(track, cache)


def _artist_profile(db: Session, artist: str | None) -> dict[str, Any] | None:
    token = normalize_token(artist)
    if not token:
        return None
    row = (
        db.query(models.ArtistRadioProfile)
        .filter(func.lower(func.replace(func.trim(models.ArtistRadioProfile.artist), '_', ' ')) == token)
        .one_or_none()
    )
    return row_profile(row) if row is not None else None


def song_intent(db: Session, *, seed_track: models.Track, requested_queue_limit: int = 50, candidate_limit: int = 5000) -> StationCandidateIntent:
    profile = _scoped_track_profile(db, seed_track)
    seed_artists = _tokens([seed_track.artist, seed_track.album_artist])
    related = set(profile.get('related_artists') or []) | set(lookup_by_normalized(RELATED_ARTISTS, seed_track.artist, []) or [])
    primary = profile.get('primary_genre') or seed_track.primary_genre or seed_track.genre or lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_track.artist)
    exact = tuple(token for token in [_genre_token(primary)] if token)
    family = _genre_family_tokens(exact)
    return StationCandidateIntent(
        mode=INTENT_SONG,
        source='song_seed',
        seed_recording_id=_recording_id_for_track(db, seed_track.id),
        seed_track_id=int(seed_track.id),
        seed_artist_tokens=seed_artists,
        related_artist_tokens=_tokens(related),
        exact_genre_tokens=exact,
        family_genre_tokens=family,
        requested_queue_limit=requested_queue_limit,
        bucket_limits=intent_bucket_limits(mode=INTENT_SONG, candidate_limit=candidate_limit, requested_queue_limit=requested_queue_limit),
    )


def artist_intent(db: Session, *, seed_artist: str | None, requested_queue_limit: int = 50, candidate_limit: int = 5000) -> StationCandidateIntent:
    profile = _artist_profile(db, seed_artist) or {}
    seed_tokens = _tokens([seed_artist])
    related = set(profile.get('related_artists') or []) | set(lookup_by_normalized(RELATED_ARTISTS, seed_artist, []) or [])
    primary = profile.get('primary_genre') or lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_artist)
    exact = tuple(token for token in [_genre_token(primary)] if token)
    family = _genre_family_tokens(exact)
    return StationCandidateIntent(
        mode=INTENT_ARTIST,
        source='artist_seed',
        seed_artist_tokens=seed_tokens,
        related_artist_tokens=_tokens(related),
        exact_genre_tokens=exact,
        family_genre_tokens=family,
        requested_queue_limit=requested_queue_limit,
        bucket_limits=intent_bucket_limits(mode=INTENT_ARTIST, candidate_limit=candidate_limit, requested_queue_limit=requested_queue_limit),
    )


def genre_intent(*, target_genre: str | None, requested_queue_limit: int = 50, candidate_limit: int = 5000) -> StationCandidateIntent:
    exact = tuple(token for token in [_genre_token(target_genre)] if token)
    family = _genre_family_tokens(exact)
    return StationCandidateIntent(
        mode=INTENT_GENRE,
        source='genre_seed',
        exact_genre_tokens=exact,
        family_genre_tokens=family,
        requested_queue_limit=requested_queue_limit,
        bucket_limits=intent_bucket_limits(mode=INTENT_GENRE, candidate_limit=candidate_limit, requested_queue_limit=requested_queue_limit),
    )
