import random
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from .serializers import track_item
from ..radio_profiles import normalize_token, profile_for_track

router = APIRouter()


class StationQueueRequest(BaseModel):
    type: str
    seed_value: str | None = None
    seed_track_id: int | None = None
    limit: int = 50
    shuffle: bool = True
    exclude_track_ids: list[int] = []


class AlbumQueueRequest(BaseModel):
    artist: str
    album: str
    limit: int = 500
    shuffle: bool = False


class ArtistQueueRequest(BaseModel):
    artist: str
    limit: int = 50
    shuffle: bool = False


class PlaylistQueueRequest(BaseModel):
    playlist_id: int
    shuffle: bool = False


class SmartPlaylistQueueRequest(BaseModel):
    key: str
    shuffle: bool = False
    limit: int = 100


ARTIST_GENRE_FALLBACKS = {
    'Kanye West': 'Hip-Hop',
    'Kendrick Lamar': 'Hip-Hop',
    'Lil Wayne': 'Hip-Hop',
    'The Weeknd': 'R&B',
}

RELATED_ARTISTS: dict[str, list[str]] = {
    'Kanye West': ['Kid Cudi', 'Pusha T', 'Jay-Z', 'The Weeknd', 'Kendrick Lamar', 'Lil Wayne'],
    'Kendrick Lamar': ['Kanye West', 'Lil Wayne', 'J. Cole', 'Drake'],
    'Lil Wayne': ['Kanye West', 'Kendrick Lamar', 'Drake', 'Nicki Minaj'],
    'The Weeknd': ['Kanye West', 'Drake', 'Frank Ocean', 'SZA'],
    'Drake': ['The Weeknd', 'Lil Wayne', 'Kanye West', 'Future'],
}


def lookup_by_normalized(mapping: dict, key: str | None, default=None):
    target = normalize_token(key)
    if not target:
        return default
    for name, value in mapping.items():
        if normalize_token(name) == target:
            return value
    return default


GENRE_ALIASES = {
    'hip hop': 'hip-hop',
    'hip-hop': 'hip-hop',
    'hiphop': 'hip-hop',
    'rap': 'hip-hop',
    'r&b': 'r&b',
    'rnb': 'r&b',
    'rhythm and blues': 'r&b',
}


def norm_genre(value: str | None) -> str:
    v = (value or '').strip().lower().replace('/', ' ').replace('_', ' ')
    v = ' '.join(v.split())
    return GENRE_ALIASES.get(v, v)


def display_genre(value: str | None) -> str:
    v = norm_genre(value)
    return {'hip-hop': 'Hip-Hop', 'r&b': 'R&B'}.get(v, (value or '').strip())


def track_genre(track: models.Track) -> str:
    return norm_genre(
        track.genre
        or lookup_by_normalized(ARTIST_GENRE_FALLBACKS, track.artist)
        or lookup_by_normalized(ARTIST_GENRE_FALLBACKS, track.album_artist)
    )



def overlap_score(a: list[str], b: list[str], weight: float) -> float:
    if not a or not b:
        return 0.0
    overlap = set(a) & set(b)
    return min(len(overlap), 3) * weight


def profile_genre(profile: dict) -> str:
    return normalize_token(profile.get('primary_genre')) or ''


def is_related_artist(profile: dict, track: models.Track) -> bool:
    related = {normalize_token(name) for name in profile.get('related_artists', [])}
    return normalize_token(track.artist) in related or normalize_token(track.album_artist) in related
def latest_feedback(db: Session) -> dict[int, str]:
    rows = db.query(models.TrackThumb).order_by(models.TrackThumb.created_at.asc()).all()
    return {r.track_id: r.value.value for r in rows}


def play_counts(db: Session) -> dict[int, int]:
    rows = (
        db.query(models.PlaybackEvent.track_id, func.count(models.PlaybackEvent.id))
        .filter(models.PlaybackEvent.track_id.isnot(None))
        .group_by(models.PlaybackEvent.track_id)
        .all()
    )
    return {tid: c for tid, c in rows}


def recent_ids(db: Session, limit: int = 80) -> set[int]:
    rows = (
        db.query(models.PlaybackEvent.track_id)
        .filter(models.PlaybackEvent.track_id.isnot(None))
        .order_by(models.PlaybackEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return {r[0] for r in rows if r[0]}


def favorite_ids(db: Session) -> set[int]:
    return {r[0] for r in db.query(models.TrackFavorite.track_id).all()}


def album_counts(tracks: list[models.Track]) -> dict[tuple[str, str], int]:
    counts = {}
    for t in tracks:
        key = (t.artist or '', t.album or '')
        counts[key] = counts.get(key, 0) + 1
    return counts


def track_number_guess(track: models.Track) -> int | None:
    text = ' '.join([track.relative_path or '', track.title or ''])
    m = re.search(r'(?:^|[\\/\s._-])(?:disc\s*\d+[\\/\s._-]*)?(\d{1,2})(?:[\s._-]+|$)', text, re.I)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 40:
            return n
    return None


def score_tracks(db: Session, tracks: list[models.Track], station_type: str) -> list[models.Track]:
    fb = latest_feedback(db)
    counts = play_counts(db)
    recent = recent_ids(db)
    favs = favorite_ids(db)
    albums = album_counts(tracks)
    scored = []

    for t in tracks:
        rating = fb.get(t.id)
        plays = counts.get(t.id, 0)
        num = track_number_guess(t)
        album_total = albums.get((t.artist or '', t.album or ''), 0)
        score = random.random()
        score -= min(plays, 20) * 0.08
        if rating == 'up':
            score += 0.35
        if rating == 'down':
            score -= 5.0
        if t.id in recent:
            score -= 0.45
        if station_type == 'deep_cuts':
            if plays == 0:
                score += 1.0
            else:
                score += max(0, .5 - (plays * .12))
            if num and num >= 4:
                score += 0.45
            if album_total >= 6:
                score += 0.25
            if num in (1, 2):
                score -= 0.45
            if t.id in favs:
                score -= 0.35
        if station_type == 'favorites' and rating == 'up':
            score += 0.25
        scored.append((score, t))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored]


def score_song_radio(db: Session, seed: models.Track, candidates: list[models.Track]) -> list[models.Track]:
    seed_profile = profile_for_track(db, seed)
    seed_genre = profile_genre(seed_profile) or track_genre(seed)
    seed_year = seed.year or 0
    seed_artist = (seed.artist or '').strip().lower()
    seed_album = (seed.album or '').strip().lower()

    fb = latest_feedback(db)
    recent = recent_ids(db)
    favs = favorite_ids(db)

    scored: list[tuple[float, models.Track]] = []
    for t in candidates:
        if t.id == seed.id:
            continue

        candidate_profile = profile_for_track(db, t)
        candidate_genre = profile_genre(candidate_profile) or track_genre(t)
        score = random.random() * 0.5

        score += overlap_score(seed_profile.get('subgenres', []), candidate_profile.get('subgenres', []), 5.0)
        score += overlap_score(seed_profile.get('moods', []), candidate_profile.get('moods', []), 3.0)

        if seed_profile.get('energy') and seed_profile.get('energy') == candidate_profile.get('energy'):
            score += 1.5
        if seed_genre and candidate_genre == seed_genre:
            score += 3.0
        if is_related_artist(seed_profile, t):
            score += 1.0

        t_artist = (t.artist or '').strip().lower()
        t_album = (t.album or '').strip().lower()

        if t_artist == seed_artist:
            score += 1.5
        if (t.album_artist or '').strip().lower() == seed_artist:
            score += 0.8

        t_year = t.year or 0
        if seed_year and t_year:
            year_diff = abs(t_year - seed_year)
            if year_diff <= 1:
                score += 0.8
            elif year_diff <= 3:
                score += 0.5
            elif year_diff <= 5:
                score += 0.2

        if t.library_area and seed.library_area and t.library_area == seed.library_area:
            score += 0.4

        rating = fb.get(t.id)
        if rating == 'up':
            score += 0.5
        elif rating == 'down':
            score -= 5.0

        if t.id in favs:
            score += 0.3
        if t.id in recent:
            score -= 1.0
        if t_album and t_album == seed_album:
            score -= 2.0

        scored.append((score, t))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [t for _, t in scored]

    seed_artist_tracks = [t for t in ranked if (t.artist or '').strip().lower() == seed_artist]
    other_tracks = [t for t in ranked if (t.artist or '').strip().lower() != seed_artist]

    if len(other_tracks) >= 10:
        result: list[models.Track] = []
        si, oi = 0, 0
        while len(result) < len(ranked):
            for _ in range(2):
                if si < len(seed_artist_tracks):
                    result.append(seed_artist_tracks[si])
                    si += 1
            for _ in range(4):
                if oi < len(other_tracks):
                    result.append(other_tracks[oi])
                    oi += 1
            if si >= len(seed_artist_tracks) and oi >= len(other_tracks):
                break
        return result

    return ranked

def no_repeats(tracks: list[models.Track], limit: int, artist_loose: bool = False) -> list[models.Track]:
    out = []
    used = set()
    last_album = None
    artist_run = {}

    for t in tracks:
        if t.id in used:
            continue
        if last_album and t.album == last_album and len(out) + 1 < limit:
            continue
        if not artist_loose and artist_run.get(t.artist, 0) >= 2 and len(out) + 1 < limit:
            continue
        out.append(t)
        used.add(t.id)
        last_album = t.album
        artist_run = {t.artist: artist_run.get(t.artist, 0) + 1}
        if len(out) >= limit:
            break

    if len(out) < limit:
        for t in tracks:
            if t.id not in used:
                out.append(t)
                used.add(t.id)
                if len(out) >= limit:
                    break
    return out


def smart_track_ids(db: Session, key: str, limit: int = 100) -> list[int]:
    limit = max(1, min(limit, 1000))
    if key == 'favorites':
        return [
            r[0]
            for r in db.query(models.TrackFavorite.track_id)
            .order_by(models.TrackFavorite.created_at.desc())
            .limit(limit)
            .all()
        ]
    if key == 'thumbs_up':
        latest = latest_feedback(db)
        return [tid for tid, value in latest.items() if value == 'up'][:limit]
    if key == 'most_played':
        rows = (
            db.query(models.PlaybackEvent.track_id, func.count(models.PlaybackEvent.id))
            .filter(models.PlaybackEvent.track_id.isnot(None))
            .group_by(models.PlaybackEvent.track_id)
            .order_by(func.count(models.PlaybackEvent.id).desc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]
    if key == 'recently_played':
        rows = (
            db.query(models.PlaybackEvent.track_id)
            .filter(models.PlaybackEvent.track_id.isnot(None))
            .order_by(models.PlaybackEvent.created_at.desc())
            .limit(limit * 4)
            .all()
        )
        out = []
        seen = set()
        for (tid,) in rows:
            if tid and tid not in seen:
                seen.add(tid)
                out.append(tid)
            if len(out) >= limit:
                break
        return out
    if key == 'recently_added':
        return [
            r[0]
            for r in db.query(models.Track.id)
            .order_by(models.Track.created_at.desc(), models.Track.last_indexed_at.desc())
            .limit(limit)
            .all()
        ]
    if key == 'never_played':
        rows = (
            db.query(models.Track.id)
            .outerjoin(models.PlaybackEvent, models.PlaybackEvent.track_id == models.Track.id)
            .group_by(models.Track.id)
            .having(func.count(models.PlaybackEvent.id) == 0)
            .order_by(models.Track.created_at.desc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]
    return []


def explain_score_part(label: str, value: float, detail: str | None = None) -> dict:
    item = {'label': label, 'value': round(value, 3)}
    if detail:
        item['detail'] = detail
    return item


def profile_debug(profile: dict) -> dict:
    return {
        'primary_genre': profile.get('primary_genre'),
        'subgenres': profile.get('subgenres', []),
        'moods': profile.get('moods', []),
        'energy': profile.get('energy'),
        'related_artists': profile.get('related_artists', []),
        'source': profile.get('source'),
    }


def debug_track_row(track: models.Track, score: float, score_parts: list[dict], profile: dict, reason: str | None = None) -> dict:
    row = {
        'track_id': track.id,
        'title': track.title,
        'artist': track.artist,
        'album': track.album,
        'score': round(score, 3),
        'profile': profile_debug(profile),
        'score_parts': score_parts,
    }
    if reason:
        row['reason'] = reason
    return row


def overlap_part(label: str, seed_values: list[str], candidate_values: list[str], weight: float) -> dict | None:
    if not seed_values or not candidate_values:
        return None
    matches = sorted(set(seed_values) & set(candidate_values))
    if not matches:
        return None
    return explain_score_part(label, min(len(matches), 3) * weight, ', '.join(matches[:4]))


def score_song_candidate_debug(
    db: Session,
    seed: models.Track,
    candidate: models.Track,
    seed_profile: dict,
    seed_genre: str,
    fb: dict[int, str],
    recent: set[int],
    favs: set[int],
) -> dict:
    candidate_profile = profile_for_track(db, candidate)
    candidate_genre = profile_genre(candidate_profile) or track_genre(candidate)
    seed_artist = (seed.artist or '').strip().lower()
    seed_album = (seed.album or '').strip().lower()
    parts: list[dict] = []

    random_value = random.random() * 0.5
    parts.append(explain_score_part('random_base', random_value))

    part = overlap_part('subgenre_overlap', seed_profile.get('subgenres', []), candidate_profile.get('subgenres', []), 5.0)
    if part:
        parts.append(part)
    part = overlap_part('mood_overlap', seed_profile.get('moods', []), candidate_profile.get('moods', []), 3.0)
    if part:
        parts.append(part)

    if seed_profile.get('energy') and seed_profile.get('energy') == candidate_profile.get('energy'):
        parts.append(explain_score_part('energy_match', 1.5, str(seed_profile.get('energy'))))
    if seed_genre and candidate_genre == seed_genre:
        parts.append(explain_score_part('primary_genre_match', 3.0, display_genre(seed_genre)))
    if is_related_artist(seed_profile, candidate):
        parts.append(explain_score_part('related_artist_match', 1.0, candidate.artist or candidate.album_artist))

    candidate_artist = (candidate.artist or '').strip().lower()
    candidate_album = (candidate.album or '').strip().lower()
    if candidate_artist == seed_artist:
        parts.append(explain_score_part('same_artist', 1.5, candidate.artist))
    if (candidate.album_artist or '').strip().lower() == seed_artist:
        parts.append(explain_score_part('same_album_artist', 0.8, candidate.album_artist))

    seed_year = seed.year or 0
    candidate_year = candidate.year or 0
    if seed_year and candidate_year:
        year_diff = abs(candidate_year - seed_year)
        if year_diff <= 1:
            parts.append(explain_score_part('year_proximity', 0.8, str(candidate_year)))
        elif year_diff <= 3:
            parts.append(explain_score_part('year_proximity', 0.5, str(candidate_year)))
        elif year_diff <= 5:
            parts.append(explain_score_part('year_proximity', 0.2, str(candidate_year)))

    if candidate.library_area and seed.library_area and candidate.library_area == seed.library_area:
        parts.append(explain_score_part('same_library_area', 0.4, candidate.library_area))

    rating = fb.get(candidate.id)
    if rating == 'up':
        parts.append(explain_score_part('thumbs_up_boost', 0.5))
    elif rating == 'down':
        parts.append(explain_score_part('thumbs_down_penalty', -5.0))

    if candidate.id in favs:
        parts.append(explain_score_part('favorite_boost', 0.3))
    if candidate.id in recent:
        parts.append(explain_score_part('recent_penalty', -1.0))
    if candidate_album and candidate_album == seed_album:
        parts.append(explain_score_part('same_album_penalty', -2.0, candidate.album))

    score = sum(part['value'] for part in parts)
    return debug_track_row(candidate, score, parts, candidate_profile)


def sort_debug_rows(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: row.get('score', 0), reverse=True)


def debug_warnings(req_type: str, seed_track: models.Track | None, seed_profile: dict, selected: list[dict]) -> list[str]:
    warnings: list[str] = []
    if seed_track and not seed_profile.get('subgenres') and not seed_profile.get('moods'):
        warnings.append('seed_track_uses_artist_profile_only' if seed_profile.get('source') else 'seed_track_has_no_track_profile')
    if selected:
        coverage = sum(1 for row in selected if row['profile'].get('subgenres') or row['profile'].get('moods')) / len(selected)
        if coverage < 0.30:
            warnings.append('low_profile_coverage')
        if req_type == 'song' and seed_track:
            same_artist = sum(1 for row in selected if normalize_token(row.get('artist')) == normalize_token(seed_track.artist)) / len(selected)
            if same_artist > 0.75:
                warnings.append('too_many_same_artist_tracks')
        broad_only = 0
        for row in selected:
            labels = {part['label'] for part in row.get('score_parts', [])}
            has_broad = bool(labels & {'primary_genre_match', 'profile_primary_genre_match', 'fallback_genre_match'})
            has_specific = bool(labels & {'subgenre_overlap', 'mood_overlap', 'related_artist_match', 'same_artist', 'seed_artist_track'})
            if has_broad and not has_specific:
                broad_only += 1
        if broad_only / len(selected) > 0.60:
            warnings.append('fallback_genre_used_heavily')
    return warnings


def station_debug_base(req: StationQueueRequest) -> dict:
    return {
        'type': req.type,
        'seed_value': req.seed_value,
        'seed_track_id': req.seed_track_id,
        'limit': min(max(req.limit, 1), 100),
    }


def station_debug_response(req: StationQueueRequest, seed: dict | None, summary: dict, selected: list[dict], top_rejected: list[dict]) -> dict:
    return {
        'station': station_debug_base(req),
        'seed': seed,
        'summary': summary,
        'selected': selected,
        'top_rejected': top_rejected[:20],
        'warnings': debug_warnings(req.type, seed.get('track') if seed else None, seed.get('profile_raw', {}) if seed else {}, selected),
    }


def strip_internal_seed(seed: dict | None) -> dict | None:
    if not seed:
        return None
    return {k: v for k, v in seed.items() if k not in {'track', 'profile_raw'}}


def song_station_debug(req: StationQueueRequest, db: Session, down: set[int], exclude_set: set[int]) -> dict:
    limit = min(max(req.limit, 1), 100)
    seed_track = db.get(models.Track, req.seed_track_id) if req.seed_track_id else None
    if seed_track is None and req.seed_value:
        try:
            seed_track = db.get(models.Track, int(req.seed_value))
        except (ValueError, TypeError):
            seed_track = None
    if seed_track is None:
        return station_debug_response(req, None, {'candidate_count': 0, 'selected_count': 0}, [], [])

    seed_profile = profile_for_track(db, seed_track)
    seed_genre = profile_genre(seed_profile) or track_genre(seed_track)
    all_tracks = db.query(models.Track).limit(5000).all()
    fb = latest_feedback(db)
    recent = recent_ids(db)
    favs = favorite_ids(db)

    excluded_seed = [t for t in all_tracks if t.id == seed_track.id]
    excluded_down = [t for t in all_tracks if t.id in down and t.id != seed_track.id]
    excluded_current = [t for t in all_tracks if t.id in exclude_set and t.id not in down and t.id != seed_track.id]
    candidates = [t for t in all_tracks if t.id not in down and t.id != seed_track.id]
    if exclude_set and len([t for t in candidates if t.id not in exclude_set]) >= 10:
        candidates = [t for t in candidates if t.id not in exclude_set]

    rows = sort_debug_rows([score_song_candidate_debug(db, seed_track, t, seed_profile, seed_genre, fb, recent, favs) for t in candidates])
    selected_tracks = no_repeats([db.get(models.Track, row['track_id']) for row in rows if row.get('track_id')], limit, artist_loose=False)
    selected_ids = {t.id for t in selected_tracks if t}
    selected = [row for row in rows if row['track_id'] in selected_ids][:limit]
    top_rejected = [row | {'reason': 'not_selected_after_ranking'} for row in rows if row['track_id'] not in selected_ids][:20]
    top_rejected = [debug_track_row(t, 0, [], profile_for_track(db, t), 'seed_track') for t in excluded_seed[:1]] + [debug_track_row(t, 0, [], profile_for_track(db, t), 'thumbs_down') for t in excluded_down[:10]] + [debug_track_row(t, 0, [], profile_for_track(db, t), 'current_queue_excluded') for t in excluded_current[:10]] + top_rejected

    profile_matched = sum(1 for row in selected if any(part['label'] in {'subgenre_overlap', 'mood_overlap', 'energy_match', 'primary_genre_match', 'related_artist_match'} for part in row['score_parts']))
    same_artist = sum(1 for row in selected if normalize_token(row.get('artist')) == normalize_token(seed_track.artist))
    seed = {
        'track_id': seed_track.id,
        'title': seed_track.title,
        'artist': seed_track.artist,
        'album': seed_track.album,
        'profile': profile_debug(seed_profile),
        'profile_raw': seed_profile,
        'track': seed_track,
    }
    response = station_debug_response(req, seed, {
        'candidate_count': len(candidates),
        'selected_count': len(selected),
        'excluded_seed_track': len(excluded_seed),
        'excluded_thumbs_down': len(excluded_down),
        'excluded_current_queue': len(excluded_current),
        'excluded_recent': sum(1 for t in candidates if t.id in recent),
        'profile_matched_count': profile_matched,
        'same_artist_count': same_artist,
        'other_artist_count': len(selected) - same_artist,
    }, selected, top_rejected)
    response['seed'] = strip_internal_seed(seed)
    return response


def generic_station_candidate_row(db: Session, track: models.Track, parts: list[dict], fb: dict[int, str] | None = None, recent: set[int] | None = None) -> dict:
    profile = profile_for_track(db, track)
    fb = fb if fb is not None else latest_feedback(db)
    recent = recent if recent is not None else recent_ids(db)
    rating = fb.get(track.id)
    if rating == 'up':
        parts.append(explain_score_part('thumbs_up_boost', 0.5))
    elif rating == 'down':
        parts.append(explain_score_part('thumbs_down_penalty', -5.0))
    if track.id in recent:
        parts.append(explain_score_part('recent_penalty', -1.0))
    return debug_track_row(track, sum(part['value'] for part in parts), parts, profile)


def artist_station_debug(req: StationQueueRequest, db: Session, down: set[int], exclude_set: set[int]) -> dict:
    limit = min(max(req.limit, 1), 100)
    seed_artist = req.seed_value or ''
    seed_token = normalize_token(seed_artist)
    all_tracks = db.query(models.Track).limit(5000).all()
    primary = [t for t in all_tracks if normalize_token(t.artist) == seed_token or normalize_token(t.album_artist) == seed_token]
    primary = [t for t in primary if t.id not in down and t.id not in exclude_set]
    seed_profile = profile_for_track(db, primary[0]) if primary else {'primary_genre': lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_artist, ''), 'subgenres': [], 'moods': [], 'energy': None, 'related_artists': lookup_by_normalized(RELATED_ARTISTS, seed_artist, []), 'source': None}
    related_names = set(lookup_by_normalized(RELATED_ARTISTS, seed_artist, [])) | set(seed_profile.get('related_artists', []))
    related_tokens = {token for token in (normalize_token(name) for name in related_names) if token}
    target_genre = profile_genre(seed_profile) or norm_genre(lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_artist, ''))
    fb = latest_feedback(db)
    recent = recent_ids(db)

    rows: list[dict] = []
    for t in all_tracks:
        if t.id in down or t.id in exclude_set:
            continue
        profile = profile_for_track(db, t)
        parts: list[dict] = []
        if normalize_token(t.artist) == seed_token or normalize_token(t.album_artist) == seed_token:
            parts.append(explain_score_part('seed_artist_track', 8.0, seed_artist))
        if related_tokens and (normalize_token(t.artist) in related_tokens or normalize_token(t.album_artist) in related_tokens):
            parts.append(explain_score_part('related_artist_match', 3.0, t.artist or t.album_artist))
        if target_genre and (profile_genre(profile) or track_genre(t)) == target_genre:
            parts.append(explain_score_part('primary_genre_match', 2.0, display_genre(target_genre)))
        part = overlap_part('subgenre_overlap', seed_profile.get('subgenres', []), profile.get('subgenres', []), 1.0)
        if part:
            parts.append(part)
        part = overlap_part('mood_overlap', seed_profile.get('moods', []), profile.get('moods', []), 1.0)
        if part:
            parts.append(part)
        if parts:
            rows.append(generic_station_candidate_row(db, t, parts, fb, recent))

    rows = sort_debug_rows(rows)
    selected_tracks = no_repeats([db.get(models.Track, row['track_id']) for row in rows if row.get('track_id')], limit, artist_loose=True)
    selected_ids = {t.id for t in selected_tracks if t}
    selected = [row for row in rows if row['track_id'] in selected_ids][:limit]
    seed = {'artist': seed_artist, 'profile': profile_debug(seed_profile), 'profile_raw': seed_profile}
    response = station_debug_response(req, seed, {
        'candidate_count': len(rows),
        'selected_count': len(selected),
        'excluded_thumbs_down': len([t for t in all_tracks if t.id in down]),
        'excluded_current_queue': len([t for t in all_tracks if t.id in exclude_set]),
        'profile_matched_count': sum(1 for row in selected if row['profile'].get('subgenres') or row['profile'].get('moods')),
        'same_artist_count': sum(1 for row in selected if normalize_token(row.get('artist')) == seed_token),
        'other_artist_count': sum(1 for row in selected if normalize_token(row.get('artist')) != seed_token),
    }, selected, [row | {'reason': 'not_selected_after_ranking'} for row in rows if row['track_id'] not in selected_ids][:20])
    response['seed'] = strip_internal_seed(seed)
    return response


def genre_station_debug(req: StationQueueRequest, db: Session, down: set[int], exclude_set: set[int]) -> dict:
    limit = min(max(req.limit, 1), 100)
    target = norm_genre(req.seed_value)
    all_tracks = db.query(models.Track).limit(5000).all()
    fb = latest_feedback(db)
    recent = recent_ids(db)
    rows: list[dict] = []
    artist_seen: set[str] = set()
    for t in all_tracks:
        if t.id in down or t.id in exclude_set:
            continue
        profile = profile_for_track(db, t)
        profile_match = profile_genre(profile) == target
        fallback_match = track_genre(t) == target
        if not profile_match and not fallback_match:
            continue
        parts: list[dict] = []
        if profile_match:
            parts.append(explain_score_part('profile_primary_genre_match', 3.0, display_genre(target)))
        elif fallback_match:
            parts.append(explain_score_part('fallback_genre_match', 1.5, display_genre(target)))
        artist_token = normalize_token(t.artist) or ''
        if artist_token and artist_token not in artist_seen:
            parts.append(explain_score_part('artist_diversity', 0.4, t.artist))
            artist_seen.add(artist_token)
        rows.append(generic_station_candidate_row(db, t, parts, fb, recent))

    rows = sort_debug_rows(rows)
    selected_tracks = no_repeats([db.get(models.Track, row['track_id']) for row in rows if row.get('track_id')], limit, artist_loose=False)
    selected_ids = {t.id for t in selected_tracks if t}
    selected = [row for row in rows if row['track_id'] in selected_ids][:limit]
    response = station_debug_response(req, {'genre': display_genre(target), 'profile': {'primary_genre': display_genre(target)}, 'profile_raw': {'primary_genre': display_genre(target)}}, {
        'candidate_count': len(rows),
        'selected_count': len(selected),
        'excluded_thumbs_down': len([t for t in all_tracks if t.id in down]),
        'excluded_current_queue': len([t for t in all_tracks if t.id in exclude_set]),
        'profile_matched_count': sum(1 for row in selected if any(part['label'] == 'profile_primary_genre_match' for part in row['score_parts'])),
        'same_artist_count': 0,
        'other_artist_count': len(selected),
    }, selected, [row | {'reason': 'not_selected_after_ranking'} for row in rows if row['track_id'] not in selected_ids][:20])
    response['seed'] = strip_internal_seed(response['seed'])
    return response

def payload(tracks):
    return {'queue': [track_item(t) for t in tracks]}


@router.post('/station/debug')
def station_queue_debug(req: StationQueueRequest, db: Session = Depends(get_db)):
    fb = latest_feedback(db)
    down = {tid for tid, value in fb.items() if value == 'down'}
    exclude_set = set(req.exclude_track_ids) if req.exclude_track_ids else set()

    if req.type == 'song':
        return song_station_debug(req, db, down, exclude_set)
    if req.type == 'artist':
        return artist_station_debug(req, db, down, exclude_set)
    if req.type == 'genre':
        return genre_station_debug(req, db, down, exclude_set)
    return {
        'station': station_debug_base(req),
        'seed': None,
        'summary': {'candidate_count': 0, 'selected_count': 0},
        'selected': [],
        'top_rejected': [],
        'warnings': ['debug_not_available_for_station_type'],
    }

@router.post('/station')
def station_queue(req: StationQueueRequest, db: Session = Depends(get_db)):
    limit = min(max(req.limit, 1), 100)
    q = db.query(models.Track)
    fb = latest_feedback(db)
    down = {tid for tid, value in fb.items() if value == 'down'}
    exclude_set = set(req.exclude_track_ids) if req.exclude_track_ids else set()

    if req.type == 'favorites':
        fav_tracks = [
            f.track
            for f in db.query(models.TrackFavorite)
            .order_by(models.TrackFavorite.created_at.desc())
            .limit(limit * 6)
            .all()
            if f.track
        ]
        up_ids = [tid for tid, value in fb.items() if value == 'up']
        up_tracks = db.query(models.Track).filter(models.Track.id.in_(up_ids)).all() if up_ids else []
        tracks = [t for t in fav_tracks + up_tracks if t.id not in down]
    elif req.type == 'recently_added':
        tracks = (
            q.order_by(models.Track.created_at.desc(), models.Track.last_indexed_at.desc())
            .limit(limit * 5)
            .all()
        )
        random.shuffle(tracks)
        tracks = [t for t in tracks if t.id not in down]
    elif req.type == 'deep_cuts':
        tracks = (
            q.outerjoin(models.PlaybackEvent, models.PlaybackEvent.track_id == models.Track.id)
            .group_by(models.Track.id)
            .order_by(func.count(models.PlaybackEvent.id), func.random())
            .limit(limit * 10)
            .all()
        )
        tracks = [t for t in tracks if t.id not in down]
    elif req.type == 'genre':
        target = norm_genre(req.seed_value)
        tracks = [t for t in q.limit(5000).all() if t.id not in down and ((profile_genre(profile_for_track(db, t)) or track_genre(t)) == target)]
        random.shuffle(tracks)
    elif req.type == 'song':
        seed_track = None
        if req.seed_track_id:
            seed_track = db.get(models.Track, req.seed_track_id)
        if seed_track is None and req.seed_value:
            try:
                seed_track = db.get(models.Track, int(req.seed_value))
            except (ValueError, TypeError):
                pass
        if seed_track is None:
            return {'queue': []}

        candidates = [t for t in q.limit(5000).all() if t.id not in down and t.id != seed_track.id]
        if exclude_set and len([t for t in candidates if t.id not in exclude_set]) >= 10:
            candidates = [t for t in candidates if t.id not in exclude_set]

        ranked = score_song_radio(db, seed_track, candidates)
        return payload(no_repeats(ranked, limit, artist_loose=False))
    elif req.type == 'artist':
        seed_artist = req.seed_value or ''

        primary_tracks = q.filter(
            or_(models.Track.artist == seed_artist, models.Track.album_artist == seed_artist)
        ).limit(limit * 8).all()
        primary_tracks = [t for t in primary_tracks if t.id not in down]

        seed_profile = profile_for_track(db, primary_tracks[0]) if primary_tracks else {
            'primary_genre': lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_artist, ''),
            'subgenres': [],
            'moods': [],
            'energy': None,
            'related_artists': lookup_by_normalized(RELATED_ARTISTS, seed_artist, []),
        }
        related_names = set(lookup_by_normalized(RELATED_ARTISTS, seed_artist, [])) | set(seed_profile.get('related_artists', []))
        related_tokens = {token for token in (normalize_token(name) for name in related_names) if token}
        target_genre = profile_genre(seed_profile) or norm_genre(lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_artist, ''))

        related_tracks: list[models.Track] = []
        if related_tokens or target_genre or seed_profile.get('subgenres') or seed_profile.get('moods'):
            all_tracks = q.limit(5000).all()
            primary_ids = {t.id for t in primary_tracks}
            related_tracks = []
            for t in all_tracks:
                if t.id in primary_ids or t.id in down:
                    continue
                candidate_profile = profile_for_track(db, t)
                candidate_genre = profile_genre(candidate_profile) or track_genre(t)
                artist_token = normalize_token(t.artist)
                album_artist_token = normalize_token(t.album_artist)
                related_match = bool(related_tokens) and (artist_token in related_tokens or album_artist_token in related_tokens)
                if (
                    related_match
                    or (target_genre and candidate_genre == target_genre)
                    or overlap_score(seed_profile.get('subgenres', []), candidate_profile.get('subgenres', []), 1.0) > 0
                    or overlap_score(seed_profile.get('moods', []), candidate_profile.get('moods', []), 1.0) > 0
                ):
                    related_tracks.append(t)

        if exclude_set:
            filtered_primary = [t for t in primary_tracks if t.id not in exclude_set]
            filtered_related = [t for t in related_tracks if t.id not in exclude_set]
            primary_tracks = filtered_primary or primary_tracks
            related_tracks = filtered_related

        filler_limit = int(limit * 0.35)
        seed_target = max(int(limit * 0.65), limit - len(related_tracks[:filler_limit]))
        filler_target = limit - min(seed_target, len(primary_tracks))

        random.shuffle(primary_tracks)
        random.shuffle(related_tracks)
        tracks = primary_tracks[:seed_target] + related_tracks[:filler_target]
        random.shuffle(tracks)
    else:
        return {'queue': []}

    if exclude_set and len([t for t in tracks if t.id not in exclude_set]) >= 10:
        tracks = [t for t in tracks if t.id not in exclude_set]

    tracks = score_tracks(db, tracks, req.type)
    return payload(no_repeats(tracks, limit, artist_loose=req.type == 'artist'))


@router.post('/album')
def album_queue(req: AlbumQueueRequest, db: Session = Depends(get_db)):
    tracks = (
        db.query(models.Track)
        .filter_by(artist=req.artist, album=req.album)
        .order_by(models.Track.relative_path, models.Track.title)
        .limit(min(req.limit, 500))
        .all()
    )
    if req.shuffle:
        random.shuffle(tracks)
    return payload(tracks)


@router.post('/artist')
def artist_queue(req: ArtistQueueRequest, db: Session = Depends(get_db)):
    tracks = (
        db.query(models.Track)
        .filter(or_(models.Track.artist == req.artist, models.Track.album_artist == req.artist))
        .limit(min(req.limit * 8, 500))
        .all()
    )
    random.shuffle(tracks)
    if not req.shuffle:
        tracks = score_tracks(db, tracks, 'artist')
    return payload(no_repeats(tracks, min(req.limit, 100), artist_loose=True))


@router.post('/playlist')
def playlist_queue(req: PlaylistQueueRequest, db: Session = Depends(get_db)):
    rows = (
        db.query(models.PlaylistTrack)
        .filter_by(playlist_id=req.playlist_id)
        .order_by(models.PlaylistTrack.position, models.PlaylistTrack.id)
        .all()
    )
    tracks = [r.track for r in rows if r.track]
    if req.shuffle:
        random.shuffle(tracks)
    return payload(tracks)


@router.post('/smart-playlist')
def smart_playlist_queue(req: SmartPlaylistQueueRequest, db: Session = Depends(get_db)):
    ids = smart_track_ids(db, req.key, req.limit)
    if not ids:
        return {'queue': []}
    tracks = [db.get(models.Track, tid) for tid in ids]
    tracks = [t for t in tracks if t]
    if req.shuffle:
        random.shuffle(tracks)
    return payload(tracks)


@router.get('/current')
def get_current_queue():
    return {'queue': []}