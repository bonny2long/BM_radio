from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from . import models

GENRE_ALIASES = {
    'hip hop': 'hip-hop',
    'hip-hop': 'hip-hop',
    'hiphop': 'hip-hop',
    'rap': 'hip-hop',
    'r&b': 'r&b',
    'rnb': 'r&b',
    'rhythm and blues': 'r&b',
}

DEFAULT_ARTIST_RADIO_PROFILES: dict[str, dict[str, Any]] = {
    'Kanye West': {'primary_genre': 'Hip-Hop', 'subgenres': ['soulful rap', 'experimental rap', 'pop rap', 'gospel rap'], 'moods': ['cinematic', 'reflective', 'hype', 'melodic'], 'energy': 'mixed', 'era': 'mixed', 'related_artists': ['Kendrick Lamar', 'Lil Wayne', 'The Weeknd', 'Kid Cudi', 'Pusha T', 'Jay-Z']},
    'Kendrick Lamar': {'primary_genre': 'Hip-Hop', 'subgenres': ['conscious rap', 'west coast rap', 'jazz rap', 'cinematic rap'], 'moods': ['lyrical', 'reflective', 'intense', 'cinematic'], 'energy': 'mixed', 'era': '2010s', 'related_artists': ['Kanye West', 'Lil Wayne', 'J. Cole', 'Drake']},
    'Lil Wayne': {'primary_genre': 'Hip-Hop', 'subgenres': ['mixtape rap', 'southern rap', 'punchline rap'], 'moods': ['hype', 'raw', 'confident', 'street'], 'energy': 'high', 'era': '2000s', 'related_artists': ['Kanye West', 'Kendrick Lamar', 'Drake', 'Nicki Minaj']},
    'The Weeknd': {'primary_genre': 'R&B', 'subgenres': ['dark r&b', 'alternative r&b', 'synthpop', 'pop r&b'], 'moods': ['late night', 'moody', 'atmospheric', 'melancholic'], 'energy': 'medium', 'era': '2010s', 'related_artists': ['Kanye West', 'Drake', 'Frank Ocean', 'SZA']},
}

DEFAULT_ALBUM_RADIO_PROFILES = [
    {'artist': 'The Weeknd', 'album': 'Trilogy', 'primary_genre': 'R&B', 'subgenres': ['dark r&b', 'alternative r&b'], 'moods': ['late night', 'moody', 'atmospheric'], 'energy': 'medium', 'era': '2010s'},
    {'artist': 'Kanye West', 'album': '808s & Heartbreak', 'primary_genre': 'Hip-Hop', 'subgenres': ['melodic rap', 'art pop', 'emo rap'], 'moods': ['melancholic', 'reflective', 'minimal'], 'energy': 'low-medium', 'era': '2000s'},
    {'artist': 'Kanye West', 'album': 'My Beautiful Dark Twisted Fantasy', 'primary_genre': 'Hip-Hop', 'subgenres': ['luxury rap', 'baroque rap', 'experimental rap'], 'moods': ['cinematic', 'grand', 'dark', 'hype'], 'energy': 'high', 'era': '2010s'},
]


def normalize_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = ' '.join(str(value).strip().replace('_', ' ').split()).lower()
    return GENRE_ALIASES.get(token, token) or None


def display_genre(value: str | None) -> str | None:
    token = normalize_token(value)
    if not token:
        return None
    return {'hip-hop': 'Hip-Hop', 'r&b': 'R&B'}.get(token, str(value).strip() or token.title())


def normalize_list(values: list[str] | None) -> list[str]:
    out: list[str] = []
    seen = set()
    for value in values or []:
        token = normalize_token(value)
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return normalize_list([str(item) for item in parsed if item is not None])


def dump_list(values: list[str] | None) -> str:
    return json.dumps(normalize_list(values), ensure_ascii=False)


def row_profile(row: Any) -> dict[str, Any]:
    return {'primary_genre': display_genre(getattr(row, 'primary_genre', None)), 'subgenres': parse_json_list(getattr(row, 'subgenres_json', None)), 'moods': parse_json_list(getattr(row, 'moods_json', None)), 'energy': normalize_token(getattr(row, 'energy', None)), 'tempo_bucket': normalize_token(getattr(row, 'tempo_bucket', None)), 'era': normalize_token(getattr(row, 'era', None)), 'related_artists': parse_json_list(getattr(row, 'related_artists_json', None)), 'radio_tags': parse_json_list(getattr(row, 'radio_tags_json', None)), 'source': getattr(row, 'source', None)}


def merge_profile(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if value not in (None, '', []):
            merged[key] = value
    return merged


def fallback_genre(track: models.Track) -> str | None:
    genre = track.genre or None
    if not genre:
        if track.artist in DEFAULT_ARTIST_RADIO_PROFILES:
            genre = DEFAULT_ARTIST_RADIO_PROFILES[track.artist].get('primary_genre')
        elif track.album_artist in DEFAULT_ARTIST_RADIO_PROFILES:
            genre = DEFAULT_ARTIST_RADIO_PROFILES[track.album_artist].get('primary_genre')
    return display_genre(genre)


def empty_profile(track: models.Track | None = None) -> dict[str, Any]:
    return {'primary_genre': fallback_genre(track) if track else None, 'subgenres': [], 'moods': [], 'energy': None, 'tempo_bucket': None, 'era': None, 'related_artists': [], 'radio_tags': [], 'source': None}


def get_artist_profile_row(db: Session, artist: str | None) -> models.ArtistRadioProfile | None:
    if not artist:
        return None
    exact = db.query(models.ArtistRadioProfile).filter_by(artist=artist).one_or_none()
    if exact:
        return exact

    target = normalize_token(artist)
    if not target:
        return None

    rows = db.query(models.ArtistRadioProfile).all()
    for row in rows:
        if normalize_token(row.artist) == target:
            return row
    return None


def profile_for_track(db: Session, track: models.Track) -> dict[str, Any]:
    profile = empty_profile(track)
    artist_row = get_artist_profile_row(db, track.artist)
    if not artist_row:
        artist_row = get_artist_profile_row(db, track.album_artist)
    if artist_row:
        profile = merge_profile(profile, row_profile(artist_row))
    if track.artist and track.album:
        album_row = db.query(models.AlbumRadioProfile).filter_by(artist=track.artist, album=track.album).one_or_none()
        if not album_row and track.album_artist:
            album_row = db.query(models.AlbumRadioProfile).filter_by(artist=track.album_artist, album=track.album).one_or_none()
        if album_row:
            profile = merge_profile(profile, row_profile(album_row))
    track_row = db.query(models.TrackRadioProfile).filter_by(track_id=track.id).one_or_none()
    if track_row:
        profile = merge_profile(profile, row_profile(track_row))
    if not profile.get('primary_genre'):
        profile['primary_genre'] = fallback_genre(track)
    return profile


def artist_profile_payload(row: models.ArtistRadioProfile) -> dict[str, Any]:
    data = row_profile(row)
    return {'artist': row.artist, 'primary_genre': data['primary_genre'], 'subgenres': data['subgenres'], 'moods': data['moods'], 'energy': data['energy'], 'era': data['era'], 'related_artists': data['related_artists'], 'source': row.source}


def track_profile_payload(db: Session, track: models.Track) -> dict[str, Any]:
    data = profile_for_track(db, track)
    return {'track_id': track.id, 'title': track.title, 'artist': track.artist, 'album': track.album, **data}


def apply_artist_profile(row: models.ArtistRadioProfile, payload: dict[str, Any]) -> None:
    if 'primary_genre' in payload: row.primary_genre = payload.get('primary_genre')
    if 'subgenres' in payload: row.subgenres_json = dump_list(payload.get('subgenres'))
    if 'moods' in payload: row.moods_json = dump_list(payload.get('moods'))
    if 'energy' in payload: row.energy = normalize_token(payload.get('energy'))
    if 'era' in payload: row.era = normalize_token(payload.get('era'))
    if 'related_artists' in payload: row.related_artists_json = dump_list(payload.get('related_artists'))
    row.source = payload.get('source') or 'manual'


def apply_track_profile(row: models.TrackRadioProfile, payload: dict[str, Any]) -> None:
    if 'primary_genre' in payload: row.primary_genre = payload.get('primary_genre')
    if 'subgenres' in payload: row.subgenres_json = dump_list(payload.get('subgenres'))
    if 'moods' in payload: row.moods_json = dump_list(payload.get('moods'))
    if 'energy' in payload: row.energy = normalize_token(payload.get('energy'))
    if 'tempo_bucket' in payload: row.tempo_bucket = normalize_token(payload.get('tempo_bucket'))
    if 'radio_tags' in payload: row.radio_tags_json = dump_list(payload.get('radio_tags'))
    row.source = payload.get('source') or 'manual'


def seed_default_radio_profiles(db: Session) -> None:
    changed = False
    for artist, profile in DEFAULT_ARTIST_RADIO_PROFILES.items():
        if db.query(models.ArtistRadioProfile).filter_by(artist=artist).one_or_none():
            continue
        row = models.ArtistRadioProfile(artist=artist, source='seed')
        apply_artist_profile(row, profile)
        row.source = 'seed'
        db.add(row)
        changed = True
    for profile in DEFAULT_ALBUM_RADIO_PROFILES:
        if db.query(models.AlbumRadioProfile).filter_by(artist=profile['artist'], album=profile['album']).one_or_none():
            continue
        db.add(models.AlbumRadioProfile(artist=profile['artist'], album=profile['album'], primary_genre=profile.get('primary_genre'), subgenres_json=dump_list(profile.get('subgenres')), moods_json=dump_list(profile.get('moods')), energy=normalize_token(profile.get('energy')), era=normalize_token(profile.get('era')), source='seed'))
        changed = True
    if changed:
        db.commit()