from __future__ import annotations

import random
import re
from collections import Counter, deque
from typing import Any


class StationCandidateTier:
    SEED_ARTIST = 'seed_artist'
    STRONG_RELATED = 'strong_related'
    SAME_GENRE = 'same_genre'
    SOFT_SIMILAR = 'soft_similar'
    EXPLORATION = 'exploration'
    FAMILY = 'family'


ARTIST_RADIO_QUOTAS = {
    StationCandidateTier.SEED_ARTIST: 0.38,
    StationCandidateTier.STRONG_RELATED: 0.34,
    StationCandidateTier.SAME_GENRE: 0.18,
    StationCandidateTier.SOFT_SIMILAR: 0.08,
    StationCandidateTier.EXPLORATION: 0.02,
}

SONG_RADIO_QUOTAS = {
    StationCandidateTier.SEED_ARTIST: 0.26,
    StationCandidateTier.STRONG_RELATED: 0.42,
    StationCandidateTier.SAME_GENRE: 0.24,
    StationCandidateTier.SOFT_SIMILAR: 0.06,
    StationCandidateTier.EXPLORATION: 0.02,
}

GENRE_RADIO_QUOTAS = {
    StationCandidateTier.SAME_GENRE: 0.74,
    StationCandidateTier.FAMILY: 0.22,
    StationCandidateTier.EXPLORATION: 0.04,
}

TIER_ORDER = [
    StationCandidateTier.SEED_ARTIST,
    StationCandidateTier.STRONG_RELATED,
    StationCandidateTier.SAME_GENRE,
    StationCandidateTier.SOFT_SIMILAR,
    StationCandidateTier.FAMILY,
    StationCandidateTier.EXPLORATION,
]


def artist_key(track: Any) -> str:
    return ' '.join(str(getattr(track, 'artist', '') or getattr(track, 'album_artist', '') or '').strip().lower().split())


def release_key(track: Any) -> tuple[str, str]:
    return (artist_key(track), ' '.join(str(getattr(track, 'album', '') or '').strip().lower().split()))


def normalized_title_key(track: Any) -> str:
    recording_id = getattr(track, '_station_recording_id', None)
    if recording_id is not None:
        return f'recording:{recording_id}'
    title = str(getattr(track, 'title', '') or '').lower()
    title = re.sub(r'\(.*?\)', '', title)
    title = re.sub(r'\[.*?\]', '', title)
    title = re.sub(r'[^a-z0-9]', '', title)
    return title


def _entry_score(entry: tuple[float, Any]) -> float:
    try:
        return float(entry[0])
    except Exception:
        return 0.0


def _entry_track(entry: tuple[float, Any]) -> Any:
    return entry[1]


def ranked_entries_from_tracks(tracks: list[Any]) -> list[tuple[float, Any]]:
    total = len(tracks)
    return [(float(total - index), track) for index, track in enumerate(tracks)]


def diversify_tier(entries: list[tuple[float, Any]], chunk_size: int = 7) -> list[tuple[float, Any]]:
    """Sort by score, then shuffle small score bands so radio does not preserve album-order feel."""
    ranked = sorted(entries, key=_entry_score, reverse=True)
    out: list[tuple[float, Any]] = []
    for index in range(0, len(ranked), chunk_size):
        chunk = ranked[index:index + chunk_size]
        random.shuffle(chunk)
        out.extend(chunk)
    return out


def _quota_counts(profile: str, limit: int) -> dict[str, int]:
    if profile == 'song':
        quotas = SONG_RADIO_QUOTAS
    elif profile == 'genre':
        quotas = GENRE_RADIO_QUOTAS
    else:
        quotas = ARTIST_RADIO_QUOTAS

    counts = {tier: int(limit * pct) for tier, pct in quotas.items()}
    assigned = sum(counts.values())
    remainder_order = sorted(quotas, key=quotas.get, reverse=True)
    while assigned < limit:
        for tier in remainder_order:
            counts[tier] = counts.get(tier, 0) + 1
            assigned += 1
            if assigned >= limit:
                break
    return counts


def _tier_schedule(profile: str, limit: int) -> list[str]:
    counts = _quota_counts(profile, limit)
    active = {tier: count for tier, count in counts.items() if count > 0}
    schedule: list[str] = []
    preference = [tier for tier in TIER_ORDER if tier in active]
    while len(schedule) < limit and active:
        for tier in preference:
            if active.get(tier, 0) <= 0:
                continue
            schedule.append(tier)
            active[tier] -= 1
            if active[tier] <= 0:
                active.pop(tier, None)
            if len(schedule) >= limit:
                break
    return schedule


def _eligible(track: Any, selected: list[Any], used_ids: set[int], used_titles: set[str], strictness: int, max_artist_window: int, max_release_window: int) -> bool:
    track_id = getattr(track, 'id', None)
    if track_id in used_ids:
        return False

    title = normalized_title_key(track)
    if strictness <= 1 and title and title in used_titles:
        return False

    artist = artist_key(track)
    release = release_key(track)

    if strictness <= 2 and len(selected) >= 2:
        last_two = selected[-2:]
        if artist and all(artist_key(item) == artist for item in last_two):
            return False
        if release[1] and all(release_key(item) == release for item in last_two):
            return False

    if strictness <= 1:
        window = selected[-9:]
        if artist and sum(1 for item in window if artist_key(item) == artist) >= max_artist_window:
            return False
        if release[1] and sum(1 for item in window if release_key(item) == release) >= max_release_window:
            return False

    return True


def assemble_station_window(tiers: dict[str, list[tuple[float, Any]]], limit: int, profile: str = 'artist', max_artist_window: int = 3, max_release_window: int = 2) -> list[Any]:
    """Assemble a radio window from scored tiers with diversity caps.

    The function is deliberately DB-free so station_engine owns loading/scoring while this
    module owns station-window planning.
    """
    if limit <= 0:
        return []

    pools: dict[str, deque[tuple[float, Any]]] = {tier: deque(diversify_tier(entries)) for tier, entries in tiers.items() if entries}
    if not pools:
        return []

    selected: list[Any] = []
    used_ids: set[int] = set()
    used_titles: set[str] = set()
    schedule = _tier_schedule(profile, limit)
    fallback_order = [tier for tier in TIER_ORDER if tier in pools]

    def take_from(tier: str, strictness: int) -> bool:
        pool = pools.get(tier)
        if not pool:
            return False
        skipped: list[tuple[float, Any]] = []
        picked: tuple[float, Any] | None = None
        while pool:
            entry = pool.popleft()
            track = _entry_track(entry)
            if _eligible(track, selected, used_ids, used_titles, strictness, max_artist_window, max_release_window):
                picked = entry
                break
            skipped.append(entry)
        for item in reversed(skipped):
            pool.appendleft(item)
        if picked is None:
            return False
        track = _entry_track(picked)
        selected.append(track)
        if getattr(track, 'id', None) is not None:
            used_ids.add(track.id)
        title = normalized_title_key(track)
        if title:
            used_titles.add(title)
        return True

    for wanted_tier in schedule:
        if len(selected) >= limit:
            break
        picked = False
        for strictness in (1, 2, 3):
            candidate_tiers = [wanted_tier] + [tier for tier in fallback_order if tier != wanted_tier]
            for tier in candidate_tiers:
                if take_from(tier, strictness):
                    picked = True
                    break
            if picked:
                break
        if not picked:
            break

    if len(selected) < limit:
        for tier in fallback_order:
            pool = pools.get(tier)
            while pool and len(selected) < limit:
                track = _entry_track(pool.popleft())
                track_id = getattr(track, 'id', None)
                if track_id in used_ids:
                    continue
                selected.append(track)
                if track_id is not None:
                    used_ids.add(track_id)

    return selected[:limit]


def station_distribution_summary(selected: list[Any], tier_by_id: dict[int, str] | None = None, seed_artist: str | None = None) -> dict:
    tier_by_id = tier_by_id or {}
    total = max(len(selected), 1)
    artists = Counter(artist_key(track) or 'unknown' for track in selected)
    releases = Counter('|'.join(release_key(track)) for track in selected)
    tiers = Counter(tier_by_id.get(getattr(track, 'id', -1), 'unknown') for track in selected)
    seed_key = ' '.join(str(seed_artist or '').strip().lower().split())
    seed_count = sum(1 for track in selected if seed_key and artist_key(track) == seed_key)
    exploration_count = tiers.get(StationCandidateTier.EXPLORATION, 0) + tiers.get('weak_related', 0)
    return {
        'tier_counts': dict(tiers),
        'artist_distribution': dict(artists.most_common(12)),
        'release_distribution': dict(releases.most_common(12)),
        'seed_artist_percent': round((seed_count / total) * 100, 1) if seed_key else 0,
        'exploration_percent': round((exploration_count / total) * 100, 1),
    }


def station_distribution_warnings(selected: list[Any], tier_by_id: dict[int, str] | None = None, seed_artist: str | None = None) -> list[str]:
    if not selected:
        return ['small_candidate_pool']
    summary = station_distribution_summary(selected, tier_by_id, seed_artist)
    warnings: list[str] = []
    if seed_artist and summary['seed_artist_percent'] > 55:
        warnings.append('too_seed_artist_heavy')
    if summary['exploration_percent'] > 25:
        warnings.append('fallback_genre_used_heavily')
    if len(summary['artist_distribution']) <= 2 and len(selected) >= 10:
        warnings.append('low_related_artist_coverage')
    if any(count >= 4 for count in summary['release_distribution'].values()) and len(selected) >= 10:
        warnings.append('album_order_risk')
    if len(selected) < 10:
        warnings.append('small_candidate_pool')
    return warnings