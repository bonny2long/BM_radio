from __future__ import annotations

from typing import Any

GENERIC_GENRES = {
    '',
    'unknown',
    'none',
    'n/a',
    'na',
    'other',
    'misc',
    'various',
    'genre',
    'music',
    'audio',
}

GENRE_ALIASES = {
    'hip hop': 'hip-hop',
    'hip-hop': 'hip-hop',
    'hiphop': 'hip-hop',
    'rap': 'rap',
    'southern hip hop': 'southern hip-hop',
    'southern hip-hop': 'southern hip-hop',
    'alternative hip hop': 'alternative hip-hop',
    'alternative hip-hop': 'alternative hip-hop',
    'jazz rap': 'jazz rap',
    'mixtape': 'mixtape',
    'rnb': 'r&b',
    'r&b': 'r&b',
    'rhythm and blues': 'r&b',
    'alt r&b': 'alternative r&b',
    'alternative r&b': 'alternative r&b',
    'indiepop': 'indie pop',
    'indie pop': 'indie pop',
    'alternative': 'alternative',
    'alt rock': 'alternative rock',
    'alternative rock': 'alternative rock',
    'indie rock': 'indie rock',
    'electronic': 'electronic',
    'electronica': 'electronic',
    'edm': 'electronic',
    'dance': 'dance',
    'pop': 'pop',
    'dance pop': 'dance pop',
    'synth pop': 'synth-pop',
    'synth-pop': 'synth-pop',
    'synthpop': 'synth-pop',
    'electropop': 'electropop',
    'idm': 'idm',
    'house': 'house',
    'techno': 'techno',
    'ambient': 'ambient',
    'rock': 'rock',
    'progressive rock': 'progressive rock',
    'classic rock': 'classic rock',
    'psychedelic rock': 'psychedelic rock',
    'jazz': 'jazz',
    'bebop': 'bebop',
    'hard bop': 'hard bop',
    'post-bop': 'post-bop',
}

DISPLAY_GENRES = {
    'hip-hop': 'Hip-Hop',
    'rap': 'Rap',
    'southern hip-hop': 'Southern Hip-Hop',
    'alternative hip-hop': 'Alternative Hip-Hop',
    'jazz rap': 'Jazz Rap',
    'mixtape': 'Mixtape',
    'r&b': 'R&B',
    'alternative r&b': 'Alternative R&B',
    'indie pop': 'Indie Pop',
    'alternative': 'Alternative',
    'alternative rock': 'Alternative Rock',
    'indie rock': 'Indie Rock',
    'electronic': 'Electronic',
    'dance': 'Dance',
    'pop': 'Pop',
    'dance pop': 'Dance Pop',
    'synth-pop': 'Synth-Pop',
    'electropop': 'Electropop',
    'idm': 'IDM',
    'house': 'House',
    'techno': 'Techno',
    'ambient': 'Ambient',
    'rock': 'Rock',
    'progressive rock': 'Progressive Rock',
    'classic rock': 'Classic Rock',
    'psychedelic rock': 'Psychedelic Rock',
    'jazz': 'Jazz',
    'bebop': 'Bebop',
    'hard bop': 'Hard Bop',
    'post-bop': 'Post-Bop',
}

HIP_HOP_FAMILY = {'hip-hop', 'rap', 'southern hip-hop', 'alternative hip-hop', 'jazz rap', 'mixtape'}
POP_FAMILY = {'pop', 'dance pop', 'synth-pop', 'electropop'}
ELECTRONIC_FAMILY = {'electronic', 'idm', 'house', 'dance', 'techno', 'ambient'}
ROCK_FAMILY = {'rock', 'progressive rock', 'classic rock', 'psychedelic rock', 'alternative rock', 'indie rock'}
JAZZ_FAMILY = {'jazz', 'bebop', 'hard bop', 'post-bop'}
RNB_FAMILY = {'r&b', 'alternative r&b'}
ALTERNATIVE_FAMILY = {'alternative', 'indie pop', 'alternative rock', 'indie rock'}

FAMILY_TOKENS = {
    **{token: HIP_HOP_FAMILY for token in HIP_HOP_FAMILY},
    **{token: POP_FAMILY for token in POP_FAMILY},
    **{token: ELECTRONIC_FAMILY for token in ELECTRONIC_FAMILY},
    **{token: ROCK_FAMILY for token in ROCK_FAMILY},
    **{token: JAZZ_FAMILY for token in JAZZ_FAMILY},
    **{token: RNB_FAMILY for token in RNB_FAMILY},
    **{token: ALTERNATIVE_FAMILY for token in ALTERNATIVE_FAMILY},
}


def _clean(value: str | None) -> str:
    return ' '.join(str(value or '').strip().replace('_', ' ').replace('/', ' ').split()).lower()


def normalize_genre(value: str | None) -> str | None:
    token = _clean(value)
    if token in GENERIC_GENRES:
        return None
    return GENRE_ALIASES.get(token, token) or None


def is_generic_genre(value: str | None) -> bool:
    return normalize_genre(value) is None


def display_genre(value: str | None) -> str:
    token = normalize_genre(value)
    if not token:
        return ''
    return DISPLAY_GENRES.get(token, token.title())


def genre_family_tokens(value: str | None) -> set[str]:
    token = normalize_genre(value)
    if not token:
        return set()
    return set(FAMILY_TOKENS.get(token, {token}))


def _profile_values(profile: dict[str, Any] | None) -> list[str]:
    if not profile:
        return []
    values: list[str] = []
    primary = profile.get('primary_genre')
    if primary:
        values.append(str(primary))
    for key in ('subgenres', 'radio_tags'):
        raw = profile.get(key) or []
        if isinstance(raw, (list, tuple, set)):
            values.extend(str(item) for item in raw if item)
    return values


def resolve_track_radio_profile(track: Any, artist_profile: dict[str, Any] | None = None, album_profile: dict[str, Any] | None = None, track_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = normalize_genre(getattr(track, 'genre', None))
    source = 'track_genre' if raw else None
    primary = raw
    subgenres: list[str] = []

    for candidate_source, profile in (('track_profile', track_profile), ('artist_profile', artist_profile), ('album_profile', album_profile)):
        values = _profile_values(profile)
        if not primary:
            for value in values:
                token = normalize_genre(value)
                if token:
                    primary = token
                    source = candidate_source
                    break
        for value in values:
            token = normalize_genre(value)
            if token and token != primary and token not in subgenres:
                subgenres.append(token)

    if not primary:
        primary = 'unknown'
        source = 'unknown'

    return {
        'radio_primary_genre': display_genre(primary),
        'radio_subgenres': [display_genre(item) for item in subgenres],
        'radio_source': source,
    }


def radio_genre_tokens(track: Any, profile: dict[str, Any] | None = None) -> set[str]:
    tokens: set[str] = set()
    raw = normalize_genre(getattr(track, 'genre', None))
    if raw:
        tokens |= genre_family_tokens(raw)

    for value in _profile_values(profile):
        tokens |= genre_family_tokens(value)

    return {token for token in tokens if token}


def same_genre_family(seed_genre: str | None, candidate_genre: str | None) -> bool:
    seed_tokens = genre_family_tokens(seed_genre)
    candidate_tokens = genre_family_tokens(candidate_genre)
    return bool(seed_tokens and candidate_tokens and seed_tokens & candidate_tokens)


def genre_matches(target: str | None, track: Any, profile: dict[str, Any] | None = None) -> bool:
    target_tokens = genre_family_tokens(target)
    if not target_tokens:
        return False
    return bool(target_tokens & radio_genre_tokens(track, profile))
