from collections import defaultdict
from pathlib import Path
from typing import Any

from .media_identity import music_recording_key, normalize_text, normalize_year

QUALITY_ORDER = {
    '.flac': 5,
    '.alac': 5,
    '.wav': 4,
    '.aiff': 4,
    '.m4a': 3,
    '.aac': 3,
    '.ogg': 2,
    '.opus': 2,
    '.mp3': 1,
}

KIND_RANK = {
    'album': 0,
    'mixtape': 1,
    'ep': 2,
    'unknown': 3,
    'single': 4,
    'compilation': 5,
    'greatest_hits': 6,
}

COMPILATION_TERMS = ('compilation', 'collection', 'anthology', 'soundtrack')
GREATEST_HITS_TERMS = ('greatest hits', 'best of', 'highlights', 'essentials')
SINGLE_TERMS = (' single', '- single', 'single')
EP_TERMS = (' ep', '- ep', ' ep ')


def _text(track: Any, attr: str) -> str:
    return str(getattr(track, attr, '') or '')


def _path(track: Any) -> str:
    return (_text(track, 'relative_path') or _text(track, 'path')).replace('\\', '/')


def release_kind(track: Any) -> str:
    album = normalize_text(_text(track, 'album'))
    path = normalize_text(_path(track))
    raw = f'{album} {path}'

    if any(term in raw for term in GREATEST_HITS_TERMS):
        return 'greatest_hits'
    if any(term in raw for term in COMPILATION_TERMS):
        return 'compilation'
    if '/singles/' in _path(track).lower().replace('\\', '/') or any(term in raw for term in SINGLE_TERMS):
        return 'single'
    if '/eps/' in _path(track).lower().replace('\\', '/') or any(term in raw for term in EP_TERMS):
        return 'ep'
    if 'mixtape' in raw:
        return 'mixtape'
    if '/albums/' in _path(track).lower().replace('\\', '/'):
        return 'album'
    if album:
        return 'album'
    return 'unknown'


def quality_rank(track: Any) -> int:
    ext = (_text(track, 'file_ext') or Path(_path(track)).suffix).lower()
    if ext and not ext.startswith('.'):
        ext = f'.{ext}'
    return QUALITY_ORDER.get(ext, 0)


def recording_variant_key(track: Any) -> str:
    return music_recording_key(_text(track, 'artist'), _text(track, 'title'), getattr(track, 'duration_seconds', None))


def _library_area_rank(track: Any) -> int:
    area = normalize_text(_text(track, 'library_area'))
    if area == 'library':
        return 0
    if area == 'discographies':
        return 1
    return 2


def _album_context_rank(track: Any) -> int:
    album = normalize_text(_text(track, 'album'))
    return 0 if album else 1


def rank_recording_variant(track: Any) -> tuple:
    kind = release_kind(track)
    year = normalize_year(getattr(track, 'year', None))
    year_value = int(year) if year else 9999
    return (
        KIND_RANK.get(kind, KIND_RANK['unknown']),
        -quality_rank(track),
        year_value,
        _album_context_rank(track),
        _library_area_rank(track),
        _path(track).lower(),
        int(getattr(track, 'id', 0) or 0),
    )


def choose_preferred_tracks(tracks: list[Any], mode: str = 'radio') -> list[Any]:
    if mode not in {'radio', 'smart_playlist', 'broad_display'}:
        return tracks

    groups: dict[str, list[Any]] = defaultdict(list)
    key_order: list[str] = []
    for track in tracks:
        key = recording_variant_key(track)
        if not key or key.endswith('||'):
            key = f'unique:{getattr(track, "id", id(track))}'
        if key not in groups:
            key_order.append(key)
        groups[key].append(track)

    preferred: list[Any] = []
    fallback_variants: list[Any] = []
    for key in key_order:
        group = groups[key]
        if len(group) == 1:
            preferred.append(group[0])
            continue
        ranked = sorted(group, key=rank_recording_variant)
        preferred.append(ranked[0])
        fallback_variants.extend(ranked[1:])

    return preferred + fallback_variants


def annotate_preference(tracks: list[Any]) -> list[dict]:
    preferred_by_key: dict[str, int] = {}
    for track in choose_preferred_tracks(tracks, mode='radio'):
        key = recording_variant_key(track)
        if key not in preferred_by_key:
            preferred_by_key[key] = int(getattr(track, 'id', 0) or 0)

    rows: list[dict] = []
    for track in tracks:
        key = recording_variant_key(track)
        track_id = int(getattr(track, 'id', 0) or 0)
        rows.append({
            'track_id': track_id,
            'recording_key': key,
            'release_kind': release_kind(track),
            'quality_rank': quality_rank(track),
            'rank': rank_recording_variant(track),
            'preferred': preferred_by_key.get(key) == track_id,
        })
    return rows
