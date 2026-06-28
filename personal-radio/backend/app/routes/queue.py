import random
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models, radio_genres
from ..db import get_db
from ..perf import perf_segment
from ..release_preferences import choose_preferred_tracks
from .serializers import track_item
from ..radio_profiles import load_radio_profile_cache, normalize_token, profile_for_track, profile_for_track_cached, row_profile

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
    limit: int = 1000


ARTIST_GENRE_FALLBACKS = {
    'Kanye West': 'Hip-Hop',
    'Kendrick Lamar': 'Hip-Hop',
    'Lil Wayne': 'Hip-Hop',
    'The Weeknd': 'R&B',
    'Bastille': 'Alternative',
    'Death Cab for Cutie': 'Alternative Rock',
    'Daft Punk': 'Electronic',
    'Mac Miller': 'Hip-Hop',
}

RELATED_ARTISTS: dict[str, list[str]] = {
    'Kanye West': ['Kid Cudi', 'Pusha T', 'Jay-Z', 'The Weeknd', 'Kendrick Lamar', 'Lil Wayne'],
    'Kendrick Lamar': ['Kanye West', 'Lil Wayne', 'J. Cole', 'Drake'],
    'Lil Wayne': ['Kanye West', 'Kendrick Lamar', 'Drake', 'Nicki Minaj'],
    'The Weeknd': ['Kanye West', 'Drake', 'Frank Ocean', 'SZA'],
    'Drake': ['The Weeknd', 'Lil Wayne', 'Kanye West', 'Future'],
}

MAX_STATION_LIMIT = 100
MAX_EXCLUDE_IDS = 200


def station_limit(value: int) -> int:
    return min(max(value, 1), MAX_STATION_LIMIT)


def station_exclude_set(req: StationQueueRequest) -> set[int]:
    return set((req.exclude_track_ids or [])[:MAX_EXCLUDE_IDS])


def lookup_by_normalized(mapping: dict, key: str | None, default=None):
    target = normalize_token(key)
    if not target:
        return default
    for name, value in mapping.items():
        if normalize_token(name) == target:
            return value
    return default


def norm_genre(value: str | None) -> str:
    return radio_genres.normalize_genre(value) or ''


def display_genre(value: str | None) -> str:
    return radio_genres.display_genre(value)


def track_genre(track: models.Track) -> str:
    return norm_genre(
        track.genre
        or lookup_by_normalized(ARTIST_GENRE_FALLBACKS, track.artist)
        or lookup_by_normalized(ARTIST_GENRE_FALLBACKS, track.album_artist)
    )


def track_matches_genre(track: models.Track, target: str | None, profile: dict | None = None) -> bool:
    return radio_genres.genre_matches(target, track, profile) or bool(radio_genres.genre_family_tokens(target) & radio_genres.genre_family_tokens(track_genre(track)))


def overlap_score(a: list[str], b: list[str], weight: float) -> float:
    if not a or not b:
        return 0.0
    overlap = set(a) & set(b)
    return min(len(overlap), 3) * weight


def profile_genre(profile: dict) -> str:
    return norm_genre(profile.get('primary_genre'))


def radio_profile(db: Session, track: models.Track, cache: dict | None = None) -> dict:
    return profile_for_track_cached(track, cache) if cache is not None else profile_for_track(db, track)


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


def score_song_radio(db: Session, seed: models.Track, candidates: list[models.Track], profile_cache: dict | None = None) -> list[models.Track]:
    seed_profile = radio_profile(db, seed, profile_cache)
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

        candidate_profile = radio_profile(db, t, profile_cache)
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

def normalized_title_key(track: models.Track | None) -> str:
    if not track or not track.title:
        return ''
    title = track.title.lower()
    title = re.sub(r'\(.*?\)', '', title)
    title = re.sub(r'\[.*?\]', '', title)
    title = re.sub(r'[^a-z0-9]', '', title)
    return title


def no_repeats(tracks: list[models.Track], limit: int, artist_loose: bool = False, avoid_title_dups: bool = False) -> list[models.Track]:
    out = []
    used = set()
    used_titles = set()
    last_album = None
    artist_run = {}

    for t in tracks:
        if t.id in used:
            continue
        if last_album and t.album == last_album and len(out) + 1 < limit:
            continue
        if not artist_loose and artist_run.get(t.artist, 0) >= 2 and len(out) + 1 < limit:
            continue

        t_key = normalized_title_key(t)
        if avoid_title_dups and t_key and t_key in used_titles and len(out) + 1 < limit:
            continue

        out.append(t)
        used.add(t.id)
        if avoid_title_dups and t_key:
            used_titles.add(t_key)
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


def smart_track_ids(db: Session, key: str, limit: int = 1000) -> list[int]:
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
            .filter(models.PlaybackEvent.track_id.isnot(None), models.PlaybackEvent.event_type == 'qualified_play')
            .group_by(models.PlaybackEvent.track_id)
            .order_by(func.count(models.PlaybackEvent.id).desc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]
    if key == 'recently_played':
        rows = (
            db.query(models.PlaybackEvent.track_id)
            .filter(models.PlaybackEvent.track_id.isnot(None), models.PlaybackEvent.event_type == 'qualified_play')
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
            .outerjoin(models.PlaybackEvent, (models.PlaybackEvent.track_id == models.Track.id) & (models.PlaybackEvent.event_type == 'qualified_play'))
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
    profile_cache: dict | None = None,
) -> dict:
    candidate_profile = radio_profile(db, candidate, profile_cache)
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


def artist_radio_score_parts(seed_profile: dict, candidate_profile: dict, seed_artist: str, track: models.Track, related_tokens: set[str], fb: dict[int, str], recent: set[int], favs: set[int]) -> tuple[float, list[dict], str]:
    parts = []

    seed_artist_token = normalize_token(seed_artist)
    track_artist_token = normalize_token(track.artist)
    track_album_artist_token = normalize_token(track.album_artist)

    is_seed = (track_artist_token == seed_artist_token or track_album_artist_token == seed_artist_token)
    is_related = bool(related_tokens) and (track_artist_token in related_tokens or track_album_artist_token in related_tokens)

    candidate_genre = profile_genre(candidate_profile) or track_genre(track)
    seed_genre = profile_genre(seed_profile) or norm_genre(lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_artist, ''))
    primary_genre_match = bool(seed_genre and candidate_genre == seed_genre)

    sub_ov = overlap_score(seed_profile.get('subgenres', []), candidate_profile.get('subgenres', []), 1.0)
    mood_ov = overlap_score(seed_profile.get('moods', []), candidate_profile.get('moods', []), 1.0)
    subgenre_overlap = bool(sub_ov > 0)
    mood_overlap = bool(mood_ov > 0)
    energy_match = bool(seed_profile.get('energy') and seed_profile.get('energy') == candidate_profile.get('energy'))

    tier = 'excluded'
    if is_seed:
        tier = 'seed_artist'
        parts.append(explain_score_part('seed_artist_track', 10.0, track.artist))
    elif is_related and (primary_genre_match or subgenre_overlap or mood_overlap or energy_match) or (primary_genre_match and subgenre_overlap):
        tier = 'strong_related'
        if is_related:
            parts.append(explain_score_part('related_artist_match', 4.0, track.artist or track.album_artist))
    elif primary_genre_match or subgenre_overlap or mood_overlap:
        tier = 'soft_similar'
    elif is_related:
        tier = 'weak_related'
        parts.append(explain_score_part('related_artist_match', 1.0, track.artist or track.album_artist))
    else:
        return -999.0, parts, 'excluded'

    if tier in ('seed_artist', 'strong_related', 'soft_similar'):
        if primary_genre_match:
            parts.append(explain_score_part('primary_genre_match', 2.0, display_genre(seed_genre)))
        if subgenre_overlap:
            matches = sorted(set(seed_profile.get('subgenres', [])) & set(candidate_profile.get('subgenres', [])))
            parts.append(explain_score_part('subgenre_overlap', 2.0, ', '.join(matches[:4])))
        if mood_overlap:
            matches = sorted(set(seed_profile.get('moods', [])) & set(candidate_profile.get('moods', [])))
            parts.append(explain_score_part('mood_overlap', 3.0, ', '.join(matches[:4])))
        if energy_match:
            parts.append(explain_score_part('energy_match', 1.0, str(seed_profile.get('energy'))))

    rating = fb.get(track.id)
    if rating == 'up':
        parts.append(explain_score_part('thumbs_up', 0.75))
    elif rating == 'down':
        return -999.0, parts, 'excluded'

    if track.id in favs:
        parts.append(explain_score_part('favorite', 0.40))

    if track.id in recent:
        parts.append(explain_score_part('recent', -1.00))

    score = sum(p['value'] for p in parts)
    return score, parts, tier


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
    limit = station_limit(req.limit)
    seed_track = db.get(models.Track, req.seed_track_id) if req.seed_track_id else None
    if seed_track is None and req.seed_value:
        try:
            seed_track = db.get(models.Track, int(req.seed_value))
        except (ValueError, TypeError):
            seed_track = None
    if seed_track is None:
        return station_debug_response(req, None, {'candidate_count': 0, 'selected_count': 0}, [], [])

    all_tracks = db.query(models.Track).limit(5000).all()
    profile_cache = load_radio_profile_cache(db)
    seed_profile = radio_profile(db, seed_track, profile_cache)
    seed_genre = profile_genre(seed_profile) or track_genre(seed_track)
    fb = latest_feedback(db)
    recent = recent_ids(db)
    favs = favorite_ids(db)

    excluded_seed = [t for t in all_tracks if t.id == seed_track.id]
    excluded_down = [t for t in all_tracks if t.id in down and t.id != seed_track.id]
    excluded_current = [t for t in all_tracks if t.id in exclude_set and t.id not in down and t.id != seed_track.id]
    candidates = [t for t in all_tracks if t.id not in down and t.id != seed_track.id]
    if exclude_set and len([t for t in candidates if t.id not in exclude_set]) >= 10:
        candidates = [t for t in candidates if t.id not in exclude_set]

    rows = sort_debug_rows([score_song_candidate_debug(db, seed_track, t, seed_profile, seed_genre, fb, recent, favs, profile_cache) for t in candidates])
    selected_tracks = no_repeats([db.get(models.Track, row['track_id']) for row in rows if row.get('track_id')], limit, artist_loose=False)
    selected_ids = {t.id for t in selected_tracks if t}
    selected = [row for row in rows if row['track_id'] in selected_ids][:limit]
    top_rejected = [row | {'reason': 'not_selected_after_ranking'} for row in rows if row['track_id'] not in selected_ids][:20]
    top_rejected = [debug_track_row(t, 0, [], radio_profile(db, t, profile_cache), 'seed_track') for t in excluded_seed[:1]] + [debug_track_row(t, 0, [], radio_profile(db, t, profile_cache), 'thumbs_down') for t in excluded_down[:10]] + [debug_track_row(t, 0, [], radio_profile(db, t, profile_cache), 'current_queue_excluded') for t in excluded_current[:10]] + top_rejected

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


def generic_station_candidate_row(db: Session, track: models.Track, parts: list[dict], fb: dict[int, str] | None = None, recent: set[int] | None = None, profile_cache: dict | None = None) -> dict:
    profile = radio_profile(db, track, profile_cache)
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
    limit = station_limit(req.limit)
    seed_artist = req.seed_value or ''
    seed_token = normalize_token(seed_artist)
    all_tracks = db.query(models.Track).limit(5000).all()
    profile_cache = load_radio_profile_cache(db)
    primary = [t for t in all_tracks if normalize_token(t.artist) == seed_token or normalize_token(t.album_artist) == seed_token]
    primary = [t for t in primary if t.id not in down and t.id not in exclude_set]
    seed_profile = radio_profile(db, primary[0], profile_cache) if primary else {'primary_genre': lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_artist, ''), 'subgenres': [], 'moods': [], 'energy': None, 'related_artists': lookup_by_normalized(RELATED_ARTISTS, seed_artist, []), 'source': None}

    related_names = set(lookup_by_normalized(RELATED_ARTISTS, seed_artist, [])) | set(seed_profile.get('related_artists', []))
    related_tokens = {token for token in (normalize_token(name) for name in related_names) if token}

    fb = latest_feedback(db)
    recent = recent_ids(db)
    favs = favorite_ids(db)

    seed_rows = []
    strong_related = []
    soft_similar = []
    weak_related = []

    for t in all_tracks:
        if t.id in down or t.id in exclude_set:
            continue
        candidate_profile = radio_profile(db, t, profile_cache)
        score, parts, tier = artist_radio_score_parts(seed_profile, candidate_profile, seed_artist, t, related_tokens, fb, recent, favs)

        if tier == 'excluded':
            continue

        row = debug_track_row(t, score, parts, candidate_profile)
        row['tier'] = tier

        if tier == 'seed_artist':
            seed_rows.append(row)
        elif tier == 'strong_related':
            strong_related.append(row)
        elif tier == 'soft_similar':
            soft_similar.append(row)
        elif tier == 'weak_related':
            weak_related.append(row)

    seed_rows = sort_debug_rows(seed_rows)
    strong_related = sort_debug_rows(strong_related)
    soft_similar = sort_debug_rows(soft_similar)
    weak_related = sort_debug_rows(weak_related)

    selected_rows = []
    seed_target = min(len(seed_rows), max(int(limit * 0.80), limit - int(limit * 0.20)))
    selected_rows += seed_rows[:seed_target]

    remaining = limit - len(selected_rows)
    selected_rows += strong_related[:remaining]

    remaining = limit - len(selected_rows)
    selected_rows += soft_similar[:remaining]

    remaining = limit - len(selected_rows)
    weak_cap = max(1, int(limit * 0.10))
    selected_rows += weak_related[:min(remaining, weak_cap)]

    remaining = limit - len(selected_rows)
    if remaining > 0:
        selected_rows += seed_rows[seed_target:seed_target + remaining]

    pool_tracks = [db.get(models.Track, r['track_id']) for r in selected_rows if r.get('track_id')]
    pool_tracks = [t for t in pool_tracks if t]

    selected_tracks = no_repeats(choose_preferred_tracks(pool_tracks, mode="radio"), limit, artist_loose=True, avoid_title_dups=True)
    selected_ids = {t.id for t in selected_tracks if t}

    all_rows = seed_rows + strong_related + soft_similar + weak_related
    selected = [r for r in all_rows if r['track_id'] in selected_ids][:limit]

    top_rejected = [r | {'reason': 'not_selected_after_ranking'} for r in all_rows if r['track_id'] not in selected_ids][:20]

    seed_artist_count = sum(1 for r in selected if r.get('tier') == 'seed_artist')
    strong_count = sum(1 for r in selected if r.get('tier') == 'strong_related')
    soft_count = sum(1 for r in selected if r.get('tier') == 'soft_similar')
    weak_count = sum(1 for r in selected if r.get('tier') == 'weak_related')

    pool_titles = [normalized_title_key(t) for t in pool_tracks[:len(selected)]]
    duplicate_title_skipped = len(pool_titles) - len(set(pool_titles))

    warnings = []
    if weak_count > 0:
        warnings.append('weak_related_fill_used')
    if strong_count + soft_count == 0 and len(selected) - seed_artist_count > 0:
        warnings.append('low_compatible_related_coverage')
    if weak_count > weak_cap:
        warnings.append('too_many_weak_related_tracks')
    if len(selected) - seed_artist_count > int(limit * 0.30):
        warnings.append('too_many_other_artist_tracks')
    if duplicate_title_skipped > 0:
        warnings.append('duplicate_titles_detected')

    seed = {'artist': seed_artist, 'profile': profile_debug(seed_profile), 'profile_raw': seed_profile}

    response = station_debug_response(req, seed, {
        'candidate_count': len(all_rows),
        'selected_count': len(selected),
        'excluded_thumbs_down': len([t for t in all_tracks if t.id in down]),
        'excluded_current_queue': len([t for t in all_tracks if t.id in exclude_set]),
        'profile_matched_count': sum(1 for row in selected if row['profile'].get('subgenres') or row['profile'].get('moods')),
        'same_artist_count': seed_artist_count,
        'other_artist_count': len(selected) - seed_artist_count,
        'seed_artist_count': seed_artist_count,
        'strong_related_count': strong_count,
        'soft_similar_count': soft_count,
        'weak_related_count': weak_count,
        'duplicate_title_skipped': duplicate_title_skipped,
    }, selected, top_rejected)

    response['warnings'] = list(set(response['warnings'] + warnings))
    response['seed'] = strip_internal_seed(seed)
    return response


def genre_station_debug(req: StationQueueRequest, db: Session, down: set[int], exclude_set: set[int]) -> dict:
    limit = station_limit(req.limit)
    target = norm_genre(req.seed_value)
    all_tracks = db.query(models.Track).limit(5000).all()
    profile_cache = load_radio_profile_cache(db)
    fb = latest_feedback(db)
    recent = recent_ids(db)
    rows: list[dict] = []
    artist_seen: set[str] = set()
    for t in all_tracks:
        if t.id in down or t.id in exclude_set:
            continue
        profile = radio_profile(db, t, profile_cache)
        profile_match = target in radio_genres.radio_genre_tokens(t, profile)
        raw_match = bool(radio_genres.genre_family_tokens(target) & radio_genres.genre_family_tokens(t.genre))
        fallback_match = track_matches_genre(t, target, profile)
        if not fallback_match:
            continue
        parts: list[dict] = []
        if profile_match and not raw_match:
            parts.append(explain_score_part('radio_profile_genre_fallback', 3.0, display_genre(target)))
        elif profile_match:
            parts.append(explain_score_part('profile_genre_match', 3.0, display_genre(target)))
        elif raw_match:
            parts.append(explain_score_part('raw_genre_match', 2.0, display_genre(target)))
        else:
            parts.append(explain_score_part('artist_genre_fallback', 1.5, display_genre(target)))
        artist_token = normalize_token(t.artist) or ''
        if artist_token and artist_token not in artist_seen:
            parts.append(explain_score_part('artist_diversity', 0.4, t.artist))
            artist_seen.add(artist_token)
        rows.append(generic_station_candidate_row(db, t, parts, fb, recent, profile_cache))

    rows = sort_debug_rows(rows)
    selected_tracks = no_repeats([db.get(models.Track, row['track_id']) for row in rows if row.get('track_id')], limit, artist_loose=False)
    selected_ids = {t.id for t in selected_tracks if t}
    selected = [row for row in rows if row['track_id'] in selected_ids][:limit]
    response = station_debug_response(req, {'genre': display_genre(target), 'profile': {'primary_genre': display_genre(target)}, 'profile_raw': {'primary_genre': display_genre(target)}}, {
        'candidate_count': len(rows),
        'selected_count': len(selected),
        'excluded_thumbs_down': len([t for t in all_tracks if t.id in down]),
        'excluded_current_queue': len([t for t in all_tracks if t.id in exclude_set]),
        'profile_matched_count': sum(1 for row in selected if any(part['label'] in {'profile_genre_match', 'radio_profile_genre_fallback'} for part in row['score_parts'])),
        'same_artist_count': 0,
        'other_artist_count': len(selected),
    }, selected, [row | {'reason': 'not_selected_after_ranking'} for row in rows if row['track_id'] not in selected_ids][:20])
    response['seed'] = strip_internal_seed(response['seed'])
    return response

def unique_tracks(tracks: list[models.Track]) -> list[models.Track]:
    out: list[models.Track] = []
    seen: set[int] = set()
    for track in tracks:
        if track and track.id not in seen:
            seen.add(track.id)
            out.append(track)
    return out


def unique_tracks_cap(tracks: list[models.Track], cap: int) -> list[models.Track]:
    out: list[models.Track] = []
    seen: set[int] = set()
    for track in tracks:
        if track and track.id not in seen:
            seen.add(track.id)
            out.append(track)
            if len(out) >= cap:
                break
    return out


def tracks_by_artist_names(db: Session, names: set[str], limit: int = 2000) -> list[models.Track]:
    clean = [name for name in names if name]
    if not clean:
        return []
    return (
        db.query(models.Track)
        .filter(or_(models.Track.artist.in_(clean), models.Track.album_artist.in_(clean)))
        .limit(limit)
        .all()
    )


def payload(tracks, **meta):
    data = {'queue': [track_item(t) for t in tracks]}
    data.update(meta)
    return data


@router.post('/station/debug')
def station_queue_debug(req: StationQueueRequest, db: Session = Depends(get_db)):
    segment_name = f"queue.debug.{req.type}.total" if req.type in {'artist', 'song', 'genre'} else 'queue.debug.total'
    with perf_segment(segment_name):
        return station_queue_debug_impl(req, db)


def station_queue_debug_impl(req: StationQueueRequest, db: Session = Depends(get_db)):
    fb = latest_feedback(db)
    down = {tid for tid, value in fb.items() if value == 'down'}
    exclude_set = station_exclude_set(req)

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
    with perf_segment('queue.station.total'):
        return station_queue_impl(req, db)


def station_queue_impl(req: StationQueueRequest, db: Session = Depends(get_db)):
    limit = station_limit(req.limit)
    q = db.query(models.Track)
    with perf_segment('queue.station.feedback'):
        fb = latest_feedback(db)
        down = {tid for tid, value in fb.items() if value == 'down'}
    with perf_segment('queue.station.exclude_set'):
        exclude_set = station_exclude_set(req)
    profile_cache = load_radio_profile_cache(db)

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
        genre_candidate_cap = min(max(limit * 40, 500), 2500)
        raw_genre_terms = {req.seed_value or '', display_genre(target), target}
        candidate_pool: list[models.Track] = []
        with perf_segment('queue.station.genre.load_candidates'):
            for term in raw_genre_terms:
                if term:
                    candidate_pool.extend(q.filter(models.Track.genre.ilike(term)).limit(genre_candidate_cap).all())
            profile_artist_names = [
                row.artist
                for row in db.query(models.ArtistRadioProfile).all()
                if radio_genres.genre_matches(target, None, row_profile(row))
            ]
            if profile_artist_names:
                candidate_pool.extend(tracks_by_artist_names(db, set(profile_artist_names), genre_candidate_cap))
            if len(candidate_pool) < limit:
                candidate_pool.extend(q.order_by(models.Track.created_at.desc(), models.Track.last_indexed_at.desc()).limit(genre_candidate_cap).all())
        with perf_segment('queue.station.genre.score_or_shuffle'):
            tracks = [t for t in unique_tracks_cap(candidate_pool, genre_candidate_cap) if t.id not in down and track_matches_genre(t, target, radio_profile(db, t, profile_cache))]
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
            return payload([], source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=0, exclude_count=len(exclude_set), exhausted=True, remaining_estimate=0)

        with perf_segment('queue.station.song.load_seed'):
            seed_profile = radio_profile(db, seed_track, profile_cache)
            seed_genre = profile_genre(seed_profile) or track_genre(seed_track)
        song_candidate_cap = min(max(limit * 40, 500), 2500)
        candidate_pool: list[models.Track] = []
        with perf_segment('queue.station.song.load_candidates'):
            if seed_track.artist:
                candidate_pool.extend(tracks_by_artist_names(db, {seed_track.artist, seed_track.album_artist or ''}, min(limit * 12, song_candidate_cap)))
            related_names = {name for name in seed_profile.get('related_artists', []) if name}
            related_names |= set(lookup_by_normalized(RELATED_ARTISTS, seed_track.artist, []) or [])
            candidate_pool.extend(tracks_by_artist_names(db, related_names, min(limit * 20, song_candidate_cap)))
            if seed_genre:
                candidate_pool.extend(q.filter(models.Track.genre.ilike(display_genre(seed_genre))).limit(min(limit * 20, song_candidate_cap)).all())
                candidate_pool.extend(q.filter(models.Track.genre.ilike(seed_genre)).limit(min(limit * 20, song_candidate_cap)).all())
            fav_ids = list(favorite_ids(db))[:min(limit * 5, 500)]
            if fav_ids:
                fav_tracks = q.filter(models.Track.id.in_(fav_ids)).all()
                if seed_genre:
                    fav_tracks = [t for t in fav_tracks if track_matches_genre(t, seed_genre, radio_profile(db, t, profile_cache))]
                candidate_pool.extend(fav_tracks)
            if len(candidate_pool) < limit:
                recent_pool = q.order_by(models.Track.created_at.desc(), models.Track.last_indexed_at.desc()).limit(min(limit * 20, song_candidate_cap)).all()
                adjacent_recent = [t for t in recent_pool if seed_genre and track_matches_genre(t, seed_genre, radio_profile(db, t, profile_cache))]
                candidate_pool.extend(adjacent_recent)
                if len(candidate_pool) < max(10, int(limit * 0.35)):
                    candidate_pool.extend(recent_pool)
        candidates = [t for t in unique_tracks_cap(candidate_pool, song_candidate_cap) if t.id not in down and t.id != seed_track.id]
        if exclude_set:
            fresh_candidates = [t for t in candidates if t.id not in exclude_set]
            if fresh_candidates:
                candidates = fresh_candidates
            else:
                return payload([], source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=0, exclude_count=len(exclude_set), exhausted=True, remaining_estimate=0)

        with perf_segment('queue.station.song.score'):
            ranked = score_song_radio(db, seed_track, candidates, profile_cache)
        with perf_segment('queue.station.song.select'):
            selected_tracks = no_repeats(choose_preferred_tracks(ranked, mode="radio"), limit, artist_loose=False, avoid_title_dups=True)
        with perf_segment('queue.station.song.serialize'):
            return payload(selected_tracks, source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=len(selected_tracks), exclude_count=len(exclude_set), exhausted=not selected_tracks, remaining_estimate=max(0, len(candidates) - len(selected_tracks)))
    elif req.type == 'artist':
        seed_artist = req.seed_value or ''
        artist_seed_limit = min(max(limit * 10, 200), 1500)
        artist_related_limit = min(max(limit * 10, 200), 1500)
        artist_soft_limit = min(max(limit * 10, 200), 1000)
        with perf_segment('queue.station.artist.load_candidates'):
            primary = (
                q.filter(or_(models.Track.artist == seed_artist, models.Track.album_artist == seed_artist))
                .limit(artist_seed_limit)
                .all()
            )
            primary = [t for t in primary if t.id not in down and t.id not in exclude_set]
            seed_profile = radio_profile(db, primary[0], profile_cache) if primary else {'primary_genre': lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_artist, ''), 'subgenres': [], 'moods': [], 'energy': None, 'related_artists': lookup_by_normalized(RELATED_ARTISTS, seed_artist, []), 'source': None}

            related_names = set(lookup_by_normalized(RELATED_ARTISTS, seed_artist, [])) | set(seed_profile.get('related_artists', []))
            related_tokens = {token for token in (normalize_token(name) for name in related_names) if token}
            related_tracks = tracks_by_artist_names(db, related_names, artist_related_limit)
            broad_tracks = []
            if len(primary) + len(related_tracks) < limit:
                broad_tracks = q.order_by(models.Track.created_at.desc(), models.Track.last_indexed_at.desc()).limit(artist_soft_limit).all()
            all_tracks = unique_tracks_cap(primary + related_tracks + broad_tracks, artist_seed_limit + artist_related_limit + artist_soft_limit)

        recent = recent_ids(db)
        favs = favorite_ids(db)

        seed_tracks = []
        strong_related = []
        soft_similar = []
        weak_related = []

        with perf_segment('queue.station.artist.score'):
            for t in all_tracks:
                if t.id in down or t.id in exclude_set:
                    continue

                candidate_profile = radio_profile(db, t, profile_cache)
                score, _, tier = artist_radio_score_parts(seed_profile, candidate_profile, seed_artist, t, related_tokens, fb, recent, favs)

                if tier == 'excluded':
                    continue

                entry = (score, t)
                if tier == 'seed_artist':
                    seed_tracks.append(entry)
                elif tier == 'strong_related':
                    strong_related.append(entry)
                elif tier == 'soft_similar':
                    soft_similar.append(entry)
                elif tier == 'weak_related':
                    weak_related.append(entry)
        with perf_segment('queue.station.artist.select'):
            seed_tracks.sort(key=lambda x: x[0], reverse=True)
            strong_related.sort(key=lambda x: x[0], reverse=True)
            soft_similar.sort(key=lambda x: x[0], reverse=True)
            weak_related.sort(key=lambda x: x[0], reverse=True)

            selected_entries = []
            seed_target = min(len(seed_tracks), max(int(limit * 0.80), limit - int(limit * 0.20)))
            selected_entries += seed_tracks[:seed_target]

            remaining = limit - len(selected_entries)
            selected_entries += strong_related[:remaining]

            remaining = limit - len(selected_entries)
            selected_entries += soft_similar[:remaining]

            remaining = limit - len(selected_entries)
            weak_cap = max(1, int(limit * 0.10))
            selected_entries += weak_related[:min(remaining, weak_cap)]

            remaining = limit - len(selected_entries)
            if remaining > 0:
                selected_entries += seed_tracks[seed_target:seed_target + remaining]

            pool_tracks = [t for _, t in selected_entries]
            selected_tracks = no_repeats(choose_preferred_tracks(pool_tracks, mode="radio"), limit, artist_loose=True, avoid_title_dups=True)
        with perf_segment('queue.station.artist.serialize'):
            return payload(selected_tracks, source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=len(selected_tracks), exclude_count=len(exclude_set), exhausted=not selected_tracks, remaining_estimate=max(0, len(pool_tracks) - len(selected_tracks)))
    else:
        return payload([], source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=0, exclude_count=len(exclude_set), exhausted=True, remaining_estimate=0)

    if exclude_set:
        fresh_tracks = [t for t in tracks if t.id not in exclude_set]
        if fresh_tracks:
            tracks = fresh_tracks
        else:
            return payload([], source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=0, exclude_count=len(exclude_set), exhausted=True, remaining_estimate=0)

    tracks = score_tracks(db, tracks, req.type)
    with perf_segment('queue.station.serialize'):
        selected = no_repeats(choose_preferred_tracks(tracks, mode="radio"), limit, artist_loose=req.type == 'artist', avoid_title_dups=True)
        return payload(selected, source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=len(selected), exclude_count=len(exclude_set), exhausted=not selected, remaining_estimate=max(0, len(tracks) - len(selected)))


@router.post('/album')
def album_queue(req: AlbumQueueRequest, db: Session = Depends(get_db)):
    tracks = (
        db.query(models.Track)
        .filter_by(artist=req.artist, album=req.album)
        .order_by(models.Track.relative_path, models.Track.title)
        .limit(min(max(req.limit, 1), 2000))
        .all()
    )
    if req.shuffle:
        random.shuffle(tracks)
    return payload(tracks)


@router.post('/artist')
def artist_queue(req: ArtistQueueRequest, db: Session = Depends(get_db)):
    max_tracks = min(max(req.limit, 1), 5000)
    tracks = (
        db.query(models.Track)
        .filter(or_(models.Track.artist == req.artist, models.Track.album_artist == req.artist))
        .order_by(models.Track.album, models.Track.relative_path, models.Track.title)
        .limit(max_tracks)
        .all()
    )
    if req.shuffle:
        random.shuffle(tracks)
    return payload(tracks)


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
    return payload(choose_preferred_tracks(tracks, mode="smart_playlist"))


@router.get('/current')
def get_current_queue():
    return {'queue': []}
