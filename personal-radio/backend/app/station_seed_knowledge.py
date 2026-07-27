from __future__ import annotations

from .radio_profiles import normalize_token

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


def lookup_by_normalized(mapping: dict, key: str | None, default=None):
    target = normalize_token(key)
    if not target:
        return default
    for name, value in mapping.items():
        if normalize_token(name) == target:
            return value
    return default
