from fastapi import HTTPException
import random
import re

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import models, radio_genres
from .availability import TRACK_UNAVAILABLE_MESSAGE, active_tracks, is_track_available
from .perf import perf_segment
from .queue_contracts import StationQueueRequest
from .queue_payloads import payload
from .radio_profiles import load_radio_profile_cache, normalize_token, profile_for_track, profile_for_track_cached, row_profile
from .station_candidates import (
    current_feedback_by_station_track,
    favorite_ids_by_station_track,
    load_station_candidate_tracks,
    logical_station_count,
    play_counts_by_station_track,
    recent_ids_by_station_track,
    station_identity_key_for_track,
    station_identity_keys_for_track_ids,
    validate_song_seed_track,
)
from .station_version_affinity import (
    VersionAffinityIntent,
    affinity_summary,
    affinity_warnings,
    apply_affinity_to_tiers,
    apply_version_affinity,
    derive_version_affinity_intent,
)
from .station_intelligence import (
    StationCandidateTier,
    assemble_station_window,
    ranked_entries_from_tracks,
    station_distribution_summary,
    station_distribution_warnings,
)


ARTIST_GENRE_FALLBACKS = {
    'Kanye West': 'Hip-Hop',
    'Kendrick Lamar': 'Hip-Hop',
    'Lil Wayne': 'Hip-Hop',
    'The Weeknd': 'R&B',
    'Bastille': 'Alternative',
    'Death Cab for Cutie': 'Alternative Rock',
    'Daft Punk': 'Electronic',
    'Mac Miller': 'Hip-Hop',
    'deadmau5': 'Electronic',
    'Aphex Twin': 'Electronic',
}

RELATED_ARTISTS: dict[str, list[str]] = {
    'Kanye West': ['Kid Cudi', 'Pusha T', 'Jay-Z', 'The Weeknd', 'Kendrick Lamar', 'Lil Wayne'],
    'Kendrick Lamar': ['Kanye West', 'Lil Wayne', 'J. Cole', 'Drake'],
    'Lil Wayne': ['Kanye West', 'Kendrick Lamar', 'Drake', 'Nicki Minaj'],
    'The Weeknd': ['Kanye West', 'Drake', 'Frank Ocean', 'SZA'],
    'Drake': ['The Weeknd', 'Lil Wayne', 'Kanye West', 'Future'],
    'Daft Punk': ['deadmau5', 'Aphex Twin', 'Chemical Brothers', 'Boards of Canada'],
    'deadmau5': ['Daft Punk', 'Aphex Twin', 'Chemical Brothers', 'Skrillex'],
    'Aphex Twin': ['Daft Punk', 'deadmau5', 'Boards of Canada', 'Autechre'],
}

MAX_STATION_LIMIT = 100
MAX_EXCLUDE_IDS = 200



def preferred_scored_entries(entries: list[tuple[float, models.Track]]) -> list[tuple[float, models.Track]]:
    return [(score, track) for score, track in entries if track]


def song_radio_tiers(seed_track: models.Track, seed_profile: dict, ranked: list[models.Track], profile_cache: dict | None = None) -> dict[str, list[tuple[float, models.Track]]]:
    seed_artist = normalize_token(seed_track.artist)
    seed_album_artist = normalize_token(seed_track.album_artist)
    seed_genre = profile_genre(seed_profile) or track_genre(seed_track)
    related_names = set(seed_profile.get('related_artists', [])) | set(lookup_by_normalized(RELATED_ARTISTS, seed_track.artist, []) or [])
    related_tokens = {token for token in (normalize_token(name) for name in related_names) if token}
    tiers: dict[str, list[tuple[float, models.Track]]] = {
        StationCandidateTier.SEED_ARTIST: [],
        StationCandidateTier.STRONG_RELATED: [],
        StationCandidateTier.SAME_GENRE: [],
        StationCandidateTier.SOFT_SIMILAR: [],
        StationCandidateTier.EXPLORATION: [],
    }
    total = len(ranked)
    for index, track in enumerate(ranked):
        score = float(total - index)
        profile = radio_profile(None, track, profile_cache)
        candidate_artist = normalize_token(track.artist)
        candidate_album_artist = normalize_token(track.album_artist)
        candidate_genre = profile_genre(profile) or track_genre(track)
        sub_overlap = bool(set(seed_profile.get('subgenres', [])) & set(profile.get('subgenres', [])))
        mood_overlap = bool(set(seed_profile.get('moods', [])) & set(profile.get('moods', [])))
        energy_match = bool(seed_profile.get('energy') and seed_profile.get('energy') == profile.get('energy'))
        same_artist = candidate_artist in {seed_artist, seed_album_artist} or candidate_album_artist in {seed_artist, seed_album_artist}
        related = candidate_artist in related_tokens or candidate_album_artist in related_tokens
        same_genre = bool(seed_genre and candidate_genre == seed_genre)
        family_match = track_is_genre_compatible(track, seed_genre, profile)
        if same_artist and family_match:
            tier = StationCandidateTier.SEED_ARTIST
        elif related and family_match and (same_genre or sub_overlap or mood_overlap or energy_match):
            tier = StationCandidateTier.STRONG_RELATED
        elif family_match:
            tier = StationCandidateTier.SAME_GENRE
        else:
            tier = StationCandidateTier.EXPLORATION
        tiers[tier].append((score, track))
    return {tier: preferred_scored_entries(entries) for tier, entries in tiers.items()}


def genre_radio_tiers(target: str, ranked: list[models.Track], profile_cache: dict | None = None) -> dict[str, list[tuple[float, models.Track]]]:
    tiers: dict[str, list[tuple[float, models.Track]]] = {
        StationCandidateTier.SAME_GENRE: [],
        StationCandidateTier.FAMILY: [],
        StationCandidateTier.EXPLORATION: [],
    }
    total = len(ranked)
    for index, track in enumerate(ranked):
        score = float(total - index)
        profile = radio_profile(None, track, profile_cache)
        tokens = set(radio_genres.radio_genre_tokens(track, profile))
        raw = norm_genre(track.genre)
        if target and (target in tokens or raw == target or profile_genre(profile) == target):
            tier = StationCandidateTier.SAME_GENRE
        elif target and track_is_genre_compatible(track, target, profile):
            tier = StationCandidateTier.FAMILY
        else:
            tier = StationCandidateTier.EXPLORATION
        tiers[tier].append((score, track))
    return {tier: preferred_scored_entries(entries) for tier, entries in tiers.items()}
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


def candidate_genre(track: models.Track, profile: dict | None = None) -> str:
    return profile_genre(profile or {}) or track_genre(track)


def track_is_genre_compatible(track: models.Track, target: str | None, profile: dict | None = None) -> bool:
    if not target:
        return True
    primary = candidate_genre(track, profile)
    return bool(primary and radio_genres.same_genre_family(target, primary))


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
def latest_feedback(db: Session, tracks: list[models.Track] | None = None) -> dict[int, str]:
    if tracks is not None:
        return current_feedback_by_station_track(db, tracks)
    rows = db.query(models.TrackThumb).order_by(models.TrackThumb.created_at.asc()).all()
    return {r.track_id: r.value.value for r in rows}


def play_counts(db: Session, tracks: list[models.Track] | None = None) -> dict[int, int]:
    if tracks is not None:
        return play_counts_by_station_track(db, tracks)
    rows = (
        db.query(models.PlaybackEvent.track_id, func.count(models.PlaybackEvent.id))
        .filter(models.PlaybackEvent.track_id.isnot(None), models.PlaybackEvent.event_type == "qualified_play")
        .group_by(models.PlaybackEvent.track_id)
        .all()
    )
    return {tid: c for tid, c in rows}


def recent_ids(db: Session, limit: int = 80, tracks: list[models.Track] | None = None) -> set[int]:
    if tracks is not None:
        return recent_ids_by_station_track(db, tracks, limit=limit)
    rows = (
        db.query(models.PlaybackEvent.track_id)
        .filter(models.PlaybackEvent.track_id.isnot(None), models.PlaybackEvent.event_type == "qualified_play")
        .order_by(models.PlaybackEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return {r[0] for r in rows if r[0]}


def favorite_ids(db: Session, tracks: list[models.Track] | None = None) -> set[int]:
    if tracks is not None:
        return favorite_ids_by_station_track(db, tracks)
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
    fb = latest_feedback(db, tracks)
    counts = play_counts(db, tracks)
    recent = recent_ids(db, tracks=tracks)
    favs = favorite_ids(db, tracks)
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


def score_song_radio(db: Session, seed: models.Track, candidates: list[models.Track], profile_cache: dict | None = None, version_intent: VersionAffinityIntent | None = None) -> list[models.Track]:
    seed_profile = radio_profile(db, seed, profile_cache)
    version_intent = version_intent or derive_version_affinity_intent(db, seed)
    seed_genre = profile_genre(seed_profile) or track_genre(seed)
    seed_year = seed.year or 0
    seed_artist = (seed.artist or '').strip().lower()
    seed_album = (seed.album or '').strip().lower()

    fb = latest_feedback(db, candidates)
    recent = recent_ids(db, tracks=candidates)
    favs = favorite_ids(db, candidates)

    scored: list[tuple[float, models.Track]] = []
    for t in candidates:
        if t.id == seed.id:
            continue

        candidate_profile = radio_profile(db, t, profile_cache)
        candidate_genre = profile_genre(candidate_profile) or track_genre(t)
        if seed_genre and not track_is_genre_compatible(t, seed_genre, candidate_profile):
            continue
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

        score += float(apply_version_affinity(t, version_intent)['value'])
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

        identity_key = station_identity_key_for_track(t)
        t_key = f'{identity_key[0]}:{identity_key[1]}' if identity_key and identity_key[0] == 'recording' else normalized_title_key(t)
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



def explain_score_part(label: str, value: float, detail: str | None = None) -> dict:
    item = {'label': label, 'value': round(value, 3)}
    if detail:
        item['detail'] = detail
    return item


def profile_debug(profile: dict) -> dict:
    debug_dict = {
        'primary_genre': profile.get('primary_genre'),
        'subgenres': profile.get('subgenres', []),
        'moods': profile.get('moods', []),
        'energy': profile.get('energy'),
        'related_artists': profile.get('related_artists', []),
        'source': profile.get('source'),
    }
    if profile.get('enrichment_source'):
        debug_dict['enrichment_source'] = profile.get('enrichment_source')
        debug_dict['enrichment_applied'] = profile.get('enrichment_applied')
    return debug_dict


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
    if hasattr(track, '_station_candidate'):
        row.update({
            'recording_id': getattr(track, '_station_recording_id', None),
            'recording_type': getattr(track, '_station_recording_type', None),
            'version_hint': getattr(track, '_station_version_hint', None),
            'effective_track_id': getattr(track, '_station_effective_track_id', track.id),
            'profile_track_id': getattr(track, '_station_profile_track_id', track.id),
            'participation_state': getattr(track, '_station_participation_state', None),
            'source_resolution': getattr(track, '_station_source_resolution', None),
            'source_confidence': getattr(track, '_station_source_confidence', None),
            'source_reason_code': getattr(track, '_station_source_reason_code', None),
            'version_affinity_mode': getattr(track, '_station_version_affinity_mode', None),
            'version_affinity_tier': getattr(track, '_station_version_affinity_tier', None),
        })
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
    version_intent: VersionAffinityIntent | None = None,
) -> dict:
    candidate_profile = radio_profile(db, candidate, profile_cache)
    version_intent = version_intent or derive_version_affinity_intent(db, seed)
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

    parts.append(apply_version_affinity(candidate, version_intent))
    if candidate_album and candidate_album == seed_album:
        parts.append(explain_score_part('same_album_penalty', -2.0, candidate.album))

    score = sum(part['value'] for part in parts)
    return debug_track_row(candidate, score, parts, candidate_profile)


def artist_radio_score_parts(seed_profile: dict, candidate_profile: dict, seed_artist: str, track: models.Track, related_tokens: set[str], fb: dict[int, str], recent: set[int], favs: set[int], allow_exploration: bool = False) -> tuple[float, list[dict], str]:
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
    compatible_genre = track_is_genre_compatible(track, seed_genre, candidate_profile) if seed_genre else True

    tier = 'excluded'
    if is_seed and compatible_genre:
        tier = 'seed_artist'
        parts.append(explain_score_part('seed_artist_track', 10.0, track.artist))
    elif is_related and compatible_genre and (primary_genre_match or subgenre_overlap or mood_overlap or energy_match):
        tier = 'strong_related'
        parts.append(explain_score_part('related_artist_match', 4.0, track.artist or track.album_artist))
    elif compatible_genre and (primary_genre_match or subgenre_overlap or mood_overlap):
        tier = 'soft_similar'
    elif allow_exploration and is_related and compatible_genre:
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



def debug_distribution_from_rows(selected: list[dict], seed_artist: str | None = None) -> dict:
    total = max(len(selected), 1)
    artists: dict[str, int] = {}
    releases: dict[str, int] = {}
    tiers: dict[str, int] = {}
    seed_token = normalize_token(seed_artist)
    seed_count = 0
    profile_count = 0
    for row in selected:
        artist = normalize_token(row.get('artist')) or 'unknown'
        album = str(row.get('album') or '').strip().lower()
        tier = row.get('tier') or 'unknown'
        artists[artist] = artists.get(artist, 0) + 1
        releases[f'{artist}|{album}'] = releases.get(f'{artist}|{album}', 0) + 1
        tiers[tier] = tiers.get(tier, 0) + 1
        if seed_token and artist == seed_token:
            seed_count += 1
        profile = row.get('profile') or {}
        if profile.get('subgenres') or profile.get('moods'):
            profile_count += 1
    exploration = tiers.get(StationCandidateTier.EXPLORATION, 0) + tiers.get('weak_related', 0)
    return {
        'tier_counts': tiers,
        'artist_distribution': dict(sorted(artists.items(), key=lambda item: item[1], reverse=True)[:12]),
        'release_distribution': dict(sorted(releases.items(), key=lambda item: item[1], reverse=True)[:12]),
        'seed_artist_percent': round(seed_count / total * 100, 1) if seed_token else 0,
        'exploration_percent': round(exploration / total * 100, 1),
        'profile_coverage_percent': round(profile_count / total * 100, 1),
    }


def debug_distribution_warnings(summary: dict) -> list[str]:
    warnings: list[str] = []
    if summary.get('seed_artist_percent', 0) > 60:
        warnings.append('too_seed_artist_heavy')
    if summary.get('exploration_percent', 0) > 25:
        warnings.append('fallback_genre_used_heavily')
    if summary.get('profile_coverage_percent', 100) < 30:
        warnings.append('low_profile_coverage')
    if len(summary.get('artist_distribution', {})) <= 2:
        warnings.append('low_related_artist_coverage')
    # Release concentration is expected in tiny libraries; strict album-order detection lives in M5 regression checks.
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
    validate_song_seed_track(db, seed_track)
    version_intent = derive_version_affinity_intent(db, seed_track)

    all_tracks = load_station_candidate_tracks(db, limit=5000, exclude_track_ids=req.exclude_track_ids, seed_track_id=seed_track.id)
    profile_cache = load_radio_profile_cache(db)
    seed_profile = radio_profile(db, seed_track, profile_cache)
    seed_genre = profile_genre(seed_profile) or track_genre(seed_track)
    fb = latest_feedback(db, all_tracks)
    recent = recent_ids(db, tracks=all_tracks)
    favs = favorite_ids(db, all_tracks)
    down = {tid for tid, value in fb.items() if value == 'down'}

    excluded_seed = [seed_track]
    excluded_down = [t for t in all_tracks if t.id in down and t.id != seed_track.id]
    excluded_current = []
    candidates = [t for t in all_tracks if t.id not in down and t.id != seed_track.id]
    if exclude_set and len([t for t in candidates if t.id not in exclude_set]) >= 10:
        candidates = [t for t in candidates if t.id not in exclude_set]

    blocked_unrelated: list[models.Track] = []
    if not req.allow_exploration and seed_genre:
        coherent: list[models.Track] = []
        for track in candidates:
            profile = radio_profile(db, track, profile_cache)
            if track_is_genre_compatible(track, seed_genre, profile):
                coherent.append(track)
            else:
                blocked_unrelated.append(track)
        candidates = coherent

    rows = sort_debug_rows([score_song_candidate_debug(db, seed_track, t, seed_profile, seed_genre, fb, recent, favs, profile_cache, version_intent) for t in candidates])
    track_by_id = {track.id: track for track in candidates}
    ranked_tracks = [track_by_id[row['track_id']] for row in rows if row.get('track_id') in track_by_id]
    tiers = song_radio_tiers(seed_track, seed_profile, ranked_tracks, profile_cache)
    tiers = apply_affinity_to_tiers(tiers, version_intent)
    selected_tracks = assemble_station_window(tiers, limit, profile='song', max_artist_window=3, max_release_window=2)
    selected_ids = {t.id for t in selected_tracks if t}
    tier_by_id = {track.id: tier for tier, entries in tiers.items() for _, track in entries}
    row_by_id = {row['track_id']: row for row in rows}
    selected = [row_by_id[t.id] | {'tier': tier_by_id.get(t.id, 'unknown')} for t in selected_tracks if t.id in row_by_id][:limit]
    top_rejected = [row | {'reason': 'not_selected_after_ranking'} for row in rows if row['track_id'] not in selected_ids][:20]
    top_rejected = [debug_track_row(t, 0, [], radio_profile(db, t, profile_cache), 'seed_track') for t in excluded_seed[:1]] + [debug_track_row(t, 0, [], radio_profile(db, t, profile_cache), 'thumbs_down') for t in excluded_down[:10]] + [debug_track_row(t, 0, [], radio_profile(db, t, profile_cache), 'current_queue_excluded') for t in excluded_current[:10]] + [debug_track_row(t, 0, [explain_score_part('blocked_unrelated_genre', 0, display_genre(seed_genre))], radio_profile(db, t, profile_cache), 'unrelated_genre_blocked') for t in blocked_unrelated[:10]] + top_rejected

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
    distribution = debug_distribution_from_rows(selected, seed_track.artist)
    version_summary = affinity_summary(version_intent, candidates, selected_tracks)
    response = station_debug_response(req, seed, {
        'candidate_count': len(candidates),
        'selected_count': len(selected),
        'excluded_seed_track': len(excluded_seed),
        'excluded_thumbs_down': len(excluded_down),
        'excluded_current_queue': len(excluded_current),
        'unrelated_genre_blocked_count': len(blocked_unrelated),
        'excluded_recent': sum(1 for t in candidates if t.id in recent),
        'profile_matched_count': profile_matched,
        'same_artist_count': same_artist,
        'other_artist_count': len(selected) - same_artist,
        **distribution,
        'version_affinity': version_summary,
    }, selected, top_rejected)
    extra_warnings = []
    if blocked_unrelated:
        extra_warnings.append('unrelated_genre_blocked')
    if len(selected) < limit and blocked_unrelated:
        extra_warnings.append('returned_less_than_limit_to_preserve_coherence')
    response['version_affinity'] = version_summary
    response['warnings'] = list(set(response['warnings'] + debug_distribution_warnings(distribution) + affinity_warnings(version_summary) + extra_warnings))
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
    all_tracks = load_station_candidate_tracks(db, limit=5000, exclude_track_ids=req.exclude_track_ids)
    profile_cache = load_radio_profile_cache(db)
    fb = latest_feedback(db, all_tracks)
    recent = recent_ids(db, tracks=all_tracks)
    favs = favorite_ids(db, all_tracks)
    down = {tid for tid, value in fb.items() if value == 'down'}
    primary = [t for t in all_tracks if normalize_token(t.artist) == seed_token or normalize_token(t.album_artist) == seed_token]
    primary = [t for t in primary if t.id not in down and t.id not in exclude_set]
    seed_profile = radio_profile(db, primary[0], profile_cache) if primary else {'primary_genre': lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_artist, ''), 'subgenres': [], 'moods': [], 'energy': None, 'related_artists': lookup_by_normalized(RELATED_ARTISTS, seed_artist, []), 'source': None}

    related_names = set(lookup_by_normalized(RELATED_ARTISTS, seed_artist, [])) | set(seed_profile.get('related_artists', []))
    related_tokens = {token for token in (normalize_token(name) for name in related_names) if token}

    seed_rows = []
    strong_related = []
    soft_similar = []
    weak_related = []

    for t in all_tracks:
        if t.id in down or t.id in exclude_set:
            continue
        candidate_profile = radio_profile(db, t, profile_cache)
        score, parts, tier = artist_radio_score_parts(seed_profile, candidate_profile, seed_artist, t, related_tokens, fb, recent, favs, req.allow_exploration)

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

    def rows_to_entries(rows: list[dict]) -> list[tuple[float, models.Track]]:
        tracks = [db.get(models.Track, r['track_id']) for r in rows if r.get('track_id')]
        score_by_id = {r['track_id']: r.get('score', 0.0) for r in rows if r.get('track_id')}
        return [(float(score_by_id.get(t.id, 0.0)), t) for t in tracks if t]

    tiers = {
        StationCandidateTier.SEED_ARTIST: preferred_scored_entries(rows_to_entries(seed_rows)),
        StationCandidateTier.STRONG_RELATED: preferred_scored_entries(rows_to_entries(strong_related)),
        StationCandidateTier.SAME_GENRE: preferred_scored_entries(rows_to_entries(soft_similar)),
        StationCandidateTier.EXPLORATION: preferred_scored_entries(rows_to_entries(weak_related)),
    }
    selected_tracks = assemble_station_window(tiers, limit, profile='artist', max_artist_window=3, max_release_window=2)
    selected_ids = {t.id for t in selected_tracks if t}

    all_rows = seed_rows + strong_related + soft_similar + weak_related
    tier_by_id = {track.id: tier for tier, entries in tiers.items() for _, track in entries}
    row_by_id = {row['track_id']: row for row in all_rows}
    selected = [row_by_id[t.id] | {'tier': tier_by_id.get(t.id, row_by_id[t.id].get('tier', 'unknown'))} for t in selected_tracks if t.id in row_by_id][:limit]

    top_rejected = [r | {'reason': 'not_selected_after_ranking'} for r in all_rows if r['track_id'] not in selected_ids][:20]
    pool_tracks = [track for entries in tiers.values() for _, track in entries]
    weak_cap = max(1, int(limit * 0.10))

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
    if len(selected) - seed_artist_count > int(limit * 0.60):
        warnings.append('too_many_other_artist_tracks')
    if duplicate_title_skipped > 0:
        warnings.append('duplicate_titles_detected')

    seed = {'artist': seed_artist, 'profile': profile_debug(seed_profile), 'profile_raw': seed_profile}

    distribution = debug_distribution_from_rows(selected, seed_artist)
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
        **distribution,
    }, selected, top_rejected)

    response['warnings'] = list(set(response['warnings'] + warnings + debug_distribution_warnings(distribution)))
    response['seed'] = strip_internal_seed(seed)
    return response


def genre_station_debug(req: StationQueueRequest, db: Session, down: set[int], exclude_set: set[int]) -> dict:
    limit = station_limit(req.limit)
    target = norm_genre(req.seed_value)
    all_tracks = load_station_candidate_tracks(db, limit=5000, exclude_track_ids=req.exclude_track_ids)
    profile_cache = load_radio_profile_cache(db)
    fb = latest_feedback(db, all_tracks)
    recent = recent_ids(db, tracks=all_tracks)
    down = {tid for tid, value in fb.items() if value == 'down'}
    rows: list[dict] = []
    artist_seen: set[str] = set()
    for t in all_tracks:
        if t.id in down or t.id in exclude_set:
            continue
        profile = radio_profile(db, t, profile_cache)
        profile_match = target in radio_genres.radio_genre_tokens(t, profile)
        raw_match = bool(radio_genres.genre_family_tokens(target) & radio_genres.genre_family_tokens(t.genre))
        fallback_match = track_is_genre_compatible(t, target, profile)
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
    ranked_tracks = [db.get(models.Track, row['track_id']) for row in rows if row.get('track_id')]
    ranked_tracks = [t for t in ranked_tracks if t]
    tiers = genre_radio_tiers(target, ranked_tracks, profile_cache)
    selected_tracks = assemble_station_window(tiers, limit, profile='genre', max_artist_window=3, max_release_window=2)
    selected_ids = {t.id for t in selected_tracks if t}
    tier_by_id = {track.id: tier for tier, entries in tiers.items() for _, track in entries}
    row_by_id = {row['track_id']: row for row in rows}
    selected = [row_by_id[t.id] | {'tier': tier_by_id.get(t.id, 'unknown')} for t in selected_tracks if t.id in row_by_id][:limit]
    distribution = debug_distribution_from_rows(selected)
    response = station_debug_response(req, {'genre': display_genre(target), 'profile': {'primary_genre': display_genre(target)}, 'profile_raw': {'primary_genre': display_genre(target)}}, {
        'candidate_count': len(rows),
        'selected_count': len(selected),
        'excluded_thumbs_down': len([t for t in all_tracks if t.id in down]),
        'excluded_current_queue': len([t for t in all_tracks if t.id in exclude_set]),
        'profile_matched_count': sum(1 for row in selected if any(part['label'] in {'profile_genre_match', 'radio_profile_genre_fallback'} for part in row['score_parts'])),
        'same_artist_count': 0,
        'other_artist_count': len(selected),
        **distribution,
    }, selected, [row | {'reason': 'not_selected_after_ranking'} for row in rows if row['track_id'] not in selected_ids][:20])
    response['warnings'] = list(set(response['warnings'] + debug_distribution_warnings(distribution)))
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
        active_tracks(db)
        .filter(or_(models.Track.artist.in_(clean), models.Track.album_artist.in_(clean)))
        .limit(limit)
        .all()
    )



def build_station_debug(req: StationQueueRequest, db: Session) -> dict:
    segment_name = f"queue.debug.{req.type}.total" if req.type in {'artist', 'song', 'genre'} else 'queue.debug.total'
    with perf_segment(segment_name):
        return _station_queue_debug_impl(req, db)


def _station_queue_debug_impl(req: StationQueueRequest, db: Session) -> dict:
    down: set[int] = set()
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

def build_station_queue(req: StationQueueRequest, db: Session) -> dict:
    with perf_segment('queue.station.total'):
        return _station_queue_impl(req, db)


def _station_queue_impl(req: StationQueueRequest, db: Session) -> dict:
    limit = station_limit(req.limit)
    exclude_set = station_exclude_set(req)
    profile_cache = load_radio_profile_cache(db)

    seed_track = None
    if req.type == 'song':
        if req.seed_track_id:
            seed_track = db.get(models.Track, req.seed_track_id)
        if seed_track is None and req.seed_value:
            try:
                seed_track = db.get(models.Track, int(req.seed_value))
            except (ValueError, TypeError):
                seed_track = None
        if seed_track is None:
            return payload([], source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=0, exclude_count=len(exclude_set), exhausted=True, remaining_estimate=0)
        validate_song_seed_track(db, seed_track)
        version_intent = derive_version_affinity_intent(db, seed_track)

    station_pool = load_station_candidate_tracks(db, limit=5000, exclude_track_ids=exclude_set, seed_track_id=seed_track.id if seed_track is not None else None)
    fb = latest_feedback(db, station_pool)
    down = {tid for tid, value in fb.items() if value == 'down'}
    favs = favorite_ids(db, station_pool)

    if req.type == 'favorites':
        tracks = [track for track in station_pool if track.id not in down and (track.id in favs or fb.get(track.id) == 'up')]
    elif req.type == 'recently_added':
        def first_seen_key(track: models.Track):
            candidate = getattr(track, '_station_candidate', None)
            proxy = candidate.profile_track if candidate is not None else track
            return (proxy.created_at or proxy.last_indexed_at, proxy.id)
        selected = sorted([track for track in station_pool if track.id not in down], key=first_seen_key, reverse=True)[:limit]
        return payload(selected, source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=len(selected), exclude_count=len(exclude_set), exhausted=not selected, remaining_estimate=max(0, len(station_pool) - len(selected)))
    elif req.type == 'deep_cuts':
        counts = play_counts(db, station_pool)
        tracks = sorted([track for track in station_pool if track.id not in down], key=lambda t: (counts.get(t.id, 0), random.random()))[:limit * 10]
    elif req.type == 'genre':
        target = norm_genre(req.seed_value)
        tracks = [track for track in station_pool if track.id not in down and track_is_genre_compatible(track, target, radio_profile(db, track, profile_cache))]
        random.shuffle(tracks)
    elif req.type == 'song':
        seed_profile = radio_profile(db, seed_track, profile_cache)
        seed_genre = profile_genre(seed_profile) or track_genre(seed_track)
        candidates = [track for track in station_pool if track.id not in down]
        if not req.allow_exploration and seed_genre:
            candidates = [track for track in candidates if track_is_genre_compatible(track, seed_genre, radio_profile(db, track, profile_cache))]
        ranked = score_song_radio(db, seed_track, candidates, profile_cache, version_intent)
        tiers = song_radio_tiers(seed_track, seed_profile, ranked, profile_cache)
        tiers = apply_affinity_to_tiers(tiers, version_intent)
        selected_tracks = assemble_station_window(tiers, limit, profile='song', max_artist_window=3, max_release_window=2)
        if len(selected_tracks) < limit and req.allow_exploration:
            selected_tracks = no_repeats(selected_tracks + [track for track in ranked if track not in selected_tracks], limit, artist_loose=False, avoid_title_dups=True)
        return payload(selected_tracks, source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=len(selected_tracks), exclude_count=len(exclude_set), exhausted=not selected_tracks, remaining_estimate=max(0, len(candidates) - len(selected_tracks)))
    elif req.type == 'artist':
        seed_artist = req.seed_value or ''
        seed_token = normalize_token(seed_artist)
        primary = [track for track in station_pool if normalize_token(track.artist) == seed_token or normalize_token(track.album_artist) == seed_token]
        seed_profile = radio_profile(db, primary[0], profile_cache) if primary else {'primary_genre': lookup_by_normalized(ARTIST_GENRE_FALLBACKS, seed_artist, ''), 'subgenres': [], 'moods': [], 'energy': None, 'related_artists': lookup_by_normalized(RELATED_ARTISTS, seed_artist, []), 'source': None}
        related_names = set(lookup_by_normalized(RELATED_ARTISTS, seed_artist, [])) | set(seed_profile.get('related_artists', []))
        related_tokens = {token for token in (normalize_token(name) for name in related_names) if token}
        seed_tracks: list[tuple[float, models.Track]] = []
        strong_related: list[tuple[float, models.Track]] = []
        soft_similar: list[tuple[float, models.Track]] = []
        weak_related: list[tuple[float, models.Track]] = []
        recent = recent_ids(db, tracks=station_pool)
        for track in station_pool:
            if track.id in down:
                continue
            candidate_profile = radio_profile(db, track, profile_cache)
            score, _, tier = artist_radio_score_parts(seed_profile, candidate_profile, seed_artist, track, related_tokens, fb, recent, favs, req.allow_exploration)
            if tier == 'excluded':
                continue
            entry = (score, track)
            if tier == 'seed_artist':
                seed_tracks.append(entry)
            elif tier == 'strong_related':
                strong_related.append(entry)
            elif tier == 'soft_similar':
                soft_similar.append(entry)
            elif tier == 'weak_related':
                weak_related.append(entry)
        tiers = {
            StationCandidateTier.SEED_ARTIST: preferred_scored_entries(seed_tracks),
            StationCandidateTier.STRONG_RELATED: preferred_scored_entries(strong_related),
            StationCandidateTier.SAME_GENRE: preferred_scored_entries(soft_similar),
            StationCandidateTier.EXPLORATION: preferred_scored_entries(weak_related),
        }
        selected_tracks = assemble_station_window(tiers, limit, profile='artist', max_artist_window=3, max_release_window=2)
        pool_tracks = [track for entries in tiers.values() for _, track in entries]
        if len(selected_tracks) < limit:
            selected_tracks = no_repeats(selected_tracks + [track for track in pool_tracks if track not in selected_tracks], limit, artist_loose=True, avoid_title_dups=True)
        return payload(selected_tracks, source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=len(selected_tracks), exclude_count=len(exclude_set), exhausted=not selected_tracks, remaining_estimate=max(0, len(pool_tracks) - len(selected_tracks)))
    else:
        return payload([], source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=0, exclude_count=len(exclude_set), exhausted=True, remaining_estimate=0)

    tracks = score_tracks(db, tracks, req.type)
    if req.type == 'genre':
        tiers = genre_radio_tiers(norm_genre(req.seed_value), tracks, profile_cache)
        selected = assemble_station_window(tiers, limit, profile='genre', max_artist_window=3, max_release_window=2)
        if len(selected) < limit:
            selected = no_repeats(selected + [track for track in tracks if track not in selected], limit, artist_loose=False, avoid_title_dups=True)
    else:
        selected = no_repeats(tracks, limit, artist_loose=req.type == 'artist', avoid_title_dups=True)
    return payload(selected, source_type=req.type, seed_value=req.seed_value, requested_limit=limit, returned=len(selected), exclude_count=len(exclude_set), exhausted=not selected, remaining_estimate=max(0, len(tracks) - len(selected)))