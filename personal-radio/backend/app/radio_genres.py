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
    'rap hip hop': 'hip-hop',
    'rap hip-hop': 'hip-hop',
    'hip hop rap': 'hip-hop',
    'hip-hop rap': 'hip-hop',
    'trap': 'trap',
    'southern hip hop': 'southern hip-hop',
    'southern hip-hop': 'southern hip-hop',
    'alternative hip hop': 'alternative hip-hop',
    'alternative hip-hop': 'alternative hip-hop',
    'east coast hip hop': 'east coast hip-hop',
    'east coast hip-hop': 'east coast hip-hop',
    'west coast hip hop': 'west coast hip-hop',
    'west coast hip-hop': 'west coast hip-hop',
    'jazz rap': 'jazz rap',
    'mixtape': 'mixtape',
    'rnb': 'r&b',
    'r&b': 'r&b',
    'rhythm and blues': 'r&b',
    'alt r&b': 'alternative r&b',
    'alternative r&b': 'alternative r&b',
    'soul': 'soul',
    'funk': 'funk',
    'neo soul': 'neo soul',
    'neosoul': 'neo soul',
    'indiepop': 'indie pop',
    'indie pop': 'indie pop',
    'alternative pop': 'indie pop',
    'alt pop': 'indie pop',
    'alternative': 'alternative',
    'alt rock': 'alternative rock',
    'alternative rock': 'alternative rock',
    'indie rock': 'indie rock',
    'hard rock': 'hard rock',
    'electronic': 'electronic',
    'electronica': 'electronica',
    'edm': 'edm',
    'dance': 'dance',
    'house': 'house',
    'progressive house': 'progressive house',
    'electro house': 'electro house',
    'tech house': 'tech house',
    'techno': 'techno',
    'idm': 'idm',
    'intelligent dance music': 'idm',
    'ambient': 'ambient',
    'ambient electronic': 'ambient electronic',
    'ambient techno': 'ambient techno',
    'downtempo': 'downtempo',
    'trip hop': 'trip hop',
    'trip-hop': 'trip hop',
    'synth pop': 'synthpop',
    'synth-pop': 'synthpop',
    'synthpop': 'synthpop',
    'nu disco': 'nu-disco',
    'nu-disco': 'nu-disco',
    'disco house': 'disco house',
    'experimental electronic': 'experimental electronic',
    'electropop': 'electropop',
    'electro pop': 'electropop',
    'electro-pop': 'electropop',
    'pop': 'pop',
    'dance pop': 'dance pop',
    'rock': 'rock',
    'progressive rock': 'progressive rock',
    'classic rock': 'classic rock',
    'psychedelic rock': 'psychedelic rock',
    'jazz': 'jazz',
    'bebop': 'bebop',
    'hard bop': 'hard bop',
    'post-bop': 'post-bop',
    'modal jazz': 'modal jazz',
    'cool jazz': 'cool jazz',
}

DISPLAY_GENRES = {
    'hip-hop': 'Hip-Hop',
    'rap': 'Rap',
    'trap': 'Trap',
    'southern hip-hop': 'Southern Hip-Hop',
    'alternative hip-hop': 'Alternative Hip-Hop',
    'east coast hip-hop': 'East Coast Hip-Hop',
    'west coast hip-hop': 'West Coast Hip-Hop',
    'jazz rap': 'Jazz Rap',
    'mixtape': 'Mixtape',
    'r&b': 'R&B',
    'alternative r&b': 'Alternative R&B',
    'soul': 'Soul',
    'funk': 'Funk',
    'neo soul': 'Neo Soul',
    'indie pop': 'Indie Pop',
    'alternative': 'Alternative',
    'alternative rock': 'Alternative Rock',
    'indie rock': 'Indie Rock',
    'hard rock': 'Hard Rock',
    'electronic': 'Electronic',
    'electronica': 'Electronica',
    'edm': 'EDM',
    'dance': 'Dance',
    'house': 'House',
    'progressive house': 'Progressive House',
    'electro house': 'Electro House',
    'tech house': 'Tech House',
    'techno': 'Techno',
    'idm': 'IDM',
    'ambient': 'Ambient',
    'ambient electronic': 'Ambient Electronic',
    'ambient techno': 'Ambient Techno',
    'downtempo': 'Downtempo',
    'trip hop': 'Trip Hop',
    'synthpop': 'Synthpop',
    'nu-disco': 'Nu-Disco',
    'disco house': 'Disco House',
    'experimental electronic': 'Experimental Electronic',
    'electropop': 'Electropop',
    'pop': 'Pop',
    'dance pop': 'Dance Pop',
    'rock': 'Rock',
    'progressive rock': 'Progressive Rock',
    'classic rock': 'Classic Rock',
    'psychedelic rock': 'Psychedelic Rock',
    'jazz': 'Jazz',
    'bebop': 'Bebop',
    'hard bop': 'Hard Bop',
    'post-bop': 'Post-Bop',
    'modal jazz': 'Modal Jazz',
    'cool jazz': 'Cool Jazz',
}

HIP_HOP_FAMILY = {'hip-hop', 'rap', 'mixtape', 'southern hip-hop', 'jazz rap', 'alternative hip-hop', 'trap', 'east coast hip-hop', 'west coast hip-hop'}
ELECTRONIC_FAMILY = {'electronic', 'electronica', 'edm', 'dance', 'house', 'progressive house', 'electro house', 'tech house', 'techno', 'idm', 'ambient electronic', 'ambient techno', 'downtempo', 'trip hop', 'synthpop', 'nu-disco', 'disco house', 'experimental electronic', 'ambient'}
ROCK_FAMILY = {'rock', 'classic rock', 'progressive rock', 'alternative rock', 'indie rock', 'hard rock', 'psychedelic rock'}
POP_FAMILY = {'pop', 'dance pop', 'electropop', 'synthpop'}
JAZZ_FAMILY = {'jazz', 'bebop', 'hard bop', 'post-bop', 'modal jazz', 'cool jazz'}
RNB_FAMILY = {'r&b', 'alternative r&b', 'soul', 'funk', 'neo soul'}
ALTERNATIVE_FAMILY = {'alternative', 'indie pop', 'alternative rock', 'indie rock'}

FAMILY_ROOTS = {
    'hip-hop': HIP_HOP_FAMILY,
    'electronic': ELECTRONIC_FAMILY,
    'rock': ROCK_FAMILY,
    'pop': POP_FAMILY,
    'jazz': JAZZ_FAMILY,
    'r&b': RNB_FAMILY,
    'alternative': ALTERNATIVE_FAMILY,
}

FAMILY_BY_TOKEN = {token: family for family, tokens in FAMILY_ROOTS.items() for token in tokens}
FAMILY_TOKENS = {token: set(FAMILY_ROOTS.get(FAMILY_BY_TOKEN.get(token, token), {token})) for token in FAMILY_BY_TOKEN}
FAMILY_DISPLAY = {'r&b': 'R&B / Soul / Funk'}


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


def genre_family(value: str | None) -> str | None:
    token = normalize_genre(value)
    if not token:
        return None
    return FAMILY_BY_TOKEN.get(token, token)


def display_family(value: str | None) -> str:
    family = genre_family(value)
    if not family:
        return ''
    return FAMILY_DISPLAY.get(family, display_genre(family))


def is_family_genre(value: str | None) -> bool:
    token = normalize_genre(value)
    return bool(token and token in FAMILY_ROOTS)


def genre_family_tokens(value: str | None) -> set[str]:
    token = normalize_genre(value)
    if not token:
        return set()
    family = genre_family(token)
    return set(FAMILY_ROOTS.get(family or token, {token}))


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
        tokens.add(raw)

    for value in _profile_values(profile):
        token = normalize_genre(value)
        if token:
            tokens.add(token)

    return {token for token in tokens if token}


def same_genre_family(seed_genre: str | None, candidate_genre: str | None) -> bool:
    seed_family = genre_family(seed_genre)
    candidate_family = genre_family(candidate_genre)
    return bool(seed_family and candidate_family and seed_family == candidate_family)


def genre_matches(target: str | None, track: Any, profile: dict[str, Any] | None = None) -> bool:
    target_token = normalize_genre(target)
    if not target_token:
        return False
    exact_tokens = radio_genre_tokens(track, profile)
    if target_token in exact_tokens:
        return True
    return any(same_genre_family(target_token, token) for token in exact_tokens)
