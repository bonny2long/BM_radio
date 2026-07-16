from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models, radio_genres

GENRE_ALIASES = {
    'hip hop': 'hip-hop',
    'hip-hop': 'hip-hop',
    'hiphop': 'hip-hop',
    'rap': 'hip-hop',
    'r&b': 'r&b',
    'rnb': 'r&b',
    'rhythm and blues': 'r&b',
}

GENRE_FAMILY_PROFILE_DEFAULTS = {
    'electronic': {
        'subgenres': ['electronic', 'electronica', 'idm', 'house', 'edm', 'techno', 'ambient electronic'],
        'moods': ['futuristic', 'atmospheric', 'hypnotic'],
        'energy': 'medium',
    },
    'hip-hop': {
        'subgenres': ['hip-hop', 'rap', 'southern hip-hop', 'jazz rap', 'alternative hip-hop', 'mixtape'],
        'moods': ['rhythmic', 'confident'],
        'energy': 'medium',
    },
    'rock': {
        'subgenres': ['rock', 'classic rock', 'progressive rock', 'alternative rock'],
        'moods': ['driving'],
        'energy': 'medium',
    },
    'jazz': {
        'subgenres': ['jazz', 'bebop', 'hard bop', 'modal jazz', 'cool jazz'],
        'moods': ['improvisational', 'warm'],
        'energy': 'medium',
    },
    'pop': {
        'subgenres': ['pop', 'dance pop', 'electropop'],
        'moods': ['bright', 'melodic'],
        'energy': 'medium',
    },
    'r&b': {
        'subgenres': ['r&b', 'soul', 'funk', 'neo soul'],
        'moods': ['groovy', 'smooth'],
        'energy': 'medium',
    },
}

ARTIST_PROFILE_ENRICHMENT = {
    'aphex twin': {
        'primary_genre': 'IDM',
        'subgenres': ['idm', 'experimental electronic', 'ambient electronic', 'electronica'],
        'moods': ['atmospheric', 'experimental', 'hypnotic'],
        'energy': 'medium',
        'related_artists': ['daft punk', 'deadmau5'],
    }
}

DEFAULT_ARTIST_RADIO_PROFILES: dict[str, dict[str, Any]] = {
    'Kanye West': {'primary_genre': 'Hip-Hop', 'subgenres': ['soulful rap', 'experimental rap', 'pop rap', 'gospel rap'], 'moods': ['cinematic', 'reflective', 'hype', 'melodic'], 'energy': 'mixed', 'era': 'mixed', 'related_artists': ['Kendrick Lamar', 'Lil Wayne', 'The Weeknd', 'Kid Cudi', 'Pusha T', 'Jay-Z']},
    'Kendrick Lamar': {'primary_genre': 'Hip-Hop', 'subgenres': ['conscious rap', 'west coast rap', 'jazz rap', 'cinematic rap'], 'moods': ['lyrical', 'reflective', 'intense', 'cinematic'], 'energy': 'mixed', 'era': '2010s', 'related_artists': ['Kanye West', 'Lil Wayne', 'J. Cole', 'Drake']},
    'Lil Wayne': {'primary_genre': 'Hip-Hop', 'subgenres': ['mixtape rap', 'southern rap', 'punchline rap', 'rap'], 'moods': ['hype', 'raw', 'confident', 'street'], 'energy': 'high', 'era': '2000s', 'related_artists': ['Kanye West', 'Kendrick Lamar', 'Drake', 'Nicki Minaj']},
    'The Weeknd': {'primary_genre': 'R&B', 'subgenres': ['dark r&b', 'alternative r&b', 'synthpop', 'pop r&b'], 'moods': ['late night', 'moody', 'atmospheric', 'melancholic'], 'energy': 'medium', 'era': '2010s', 'related_artists': ['Kanye West', 'Drake', 'Frank Ocean', 'SZA']},
    'Bastille': {'primary_genre': 'Alternative', 'subgenres': ['indie pop', 'alternative pop', 'synthpop'], 'moods': ['anthemic', 'melodic', 'cinematic'], 'energy': 'medium', 'era': '2010s', 'related_artists': ['The Head And The Heart', 'Death Cab for Cutie']},
    'Death Cab for Cutie': {'primary_genre': 'Alternative Rock', 'subgenres': ['indie rock', 'emo indie', 'alternative'], 'moods': ['melancholic', 'reflective', 'melodic'], 'energy': 'medium', 'era': '2000s', 'related_artists': ['Bastille', 'The Head And The Heart']},
    'Daft Punk': {'primary_genre': 'Electronic', 'subgenres': ['dance', 'house', 'disco house', 'french house', 'electropop', 'nu-disco'], 'moods': ['groovy', 'euphoric', 'futuristic', 'danceable', 'cinematic'], 'energy': 'high', 'era': 'mixed', 'related_artists': ['deadmau5', 'Aphex Twin', 'Chemical Brothers', 'Boards of Canada']},
    'deadmau5': {'primary_genre': 'Electronic', 'subgenres': ['progressive house', 'electro house', 'tech house', 'edm'], 'moods': ['atmospheric', 'driving', 'hypnotic', 'futuristic'], 'energy': 'high', 'era': '2000s', 'related_artists': ['Daft Punk', 'Aphex Twin', 'Chemical Brothers', 'Skrillex']},
    'Aphex Twin': {'primary_genre': 'Electronic', 'subgenres': ['idm', 'ambient electronic', 'experimental electronic', 'acid techno', 'drill and bass'], 'moods': ['cerebral', 'hypnotic', 'dark', 'introspective', 'experimental'], 'energy': 'mixed', 'era': '1990s', 'related_artists': ['Daft Punk', 'deadmau5', 'Boards of Canada', 'Autechre']},
    'Mac Miller': {'primary_genre': 'Hip-Hop', 'subgenres': ['rap', 'alternative hip-hop', 'jazz rap'], 'moods': ['laid back', 'reflective', 'melodic'], 'energy': 'medium', 'era': '2010s', 'related_artists': ['Kendrick Lamar', 'Kanye West']},
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


def is_thin_radio_profile(profile: dict[str, Any]) -> bool:
    if not profile:
        return True
    if profile.get('subgenres') or profile.get('moods') or profile.get('energy') or profile.get('related_artists'):
        return False
    return True


def enrich_profile(profile: dict[str, Any], artist: str | None) -> dict[str, Any]:
    if not profile or not is_thin_radio_profile(profile):
        return profile
    
    enriched = dict(profile)
    artist_key = normalize_token(artist)
    override = ARTIST_PROFILE_ENRICHMENT.get(artist_key) if artist_key else None
    
    if override:
        for k, v in override.items():
            if not enriched.get(k):
                enriched[k] = v
        enriched['enrichment_source'] = 'bm_radio_artist_enrichment'
        enriched['enrichment_applied'] = True
        return enriched
        
    primary = profile.get('primary_genre')
    if primary:
        family = radio_genres.genre_family(primary)
        defaults = GENRE_FAMILY_PROFILE_DEFAULTS.get(family) if family else None
        if defaults:
            for k, v in defaults.items():
                if not enriched.get(k):
                    enriched[k] = v
            enriched['enrichment_source'] = 'bm_radio_genre_family'
            enriched['enrichment_applied'] = True
            
    return enriched


def fallback_genre(track: models.Track) -> str | None:
    genre = getattr(track, 'primary_genre', None) or track.genre or None
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
    return enrich_profile(profile, track.artist)


def load_radio_profile_cache(db: Session) -> dict[str, Any]:
    return {
        'artists': {
            normalize_token(row.artist): row_profile(row)
            for row in db.query(models.ArtistRadioProfile).all()
            if normalize_token(row.artist)
        },
        'albums': {
            (normalize_token(row.artist), normalize_token(row.album)): row_profile(row)
            for row in db.query(models.AlbumRadioProfile).all()
            if normalize_token(row.artist) and normalize_token(row.album)
        },
        'tracks': {
            row.track_id: row_profile(row)
            for row in db.query(models.TrackRadioProfile).all()
        },
    }


def profile_for_track_cached(track: models.Track, cache: dict[str, Any]) -> dict[str, Any]:
    profile = empty_profile(track)
    artist_key = normalize_token(track.artist)
    album_artist_key = normalize_token(track.album_artist)
    album_key = normalize_token(track.album)

    artist_profile = None
    if artist_key:
        artist_profile = cache.get('artists', {}).get(artist_key)
    if not artist_profile and album_artist_key:
        artist_profile = cache.get('artists', {}).get(album_artist_key)
    if artist_profile:
        profile = merge_profile(profile, artist_profile)

    album_profile = None
    if artist_key and album_key:
        album_profile = cache.get('albums', {}).get((artist_key, album_key))
    if not album_profile and album_artist_key and album_key:
        album_profile = cache.get('albums', {}).get((album_artist_key, album_key))
    if album_profile:
        profile = merge_profile(profile, album_profile)

    track_profile = cache.get('tracks', {}).get(track.id)
    if track_profile:
        profile = merge_profile(profile, track_profile)
    if not profile.get('primary_genre'):
        profile['primary_genre'] = fallback_genre(track)
    return enrich_profile(profile, track.artist)
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

PROFILE_SCOPE_CHUNK_SIZE = 500


def _chunked(values: list[Any], size: int = PROFILE_SCOPE_CHUNK_SIZE):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _track_profile_ids(tracks: Iterable[models.Track]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for track in tracks:
        for value in (getattr(track, 'id', None), getattr(track, '_station_effective_track_id', None), getattr(track, '_station_profile_track_id', None)):
            if value is None:
                continue
            track_id = int(value)
            if track_id not in seen:
                seen.add(track_id)
                ids.append(track_id)
    return ids


def _artist_keys_for_tracks(tracks: Iterable[models.Track]) -> set[str]:
    keys: set[str] = set()
    for track in tracks:
        for value in (getattr(track, 'artist', None), getattr(track, 'album_artist', None)):
            key = normalize_token(value)
            if key:
                keys.add(key)
    return keys


def _album_keys_for_tracks(tracks: Iterable[models.Track]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for track in tracks:
        album_key = normalize_token(getattr(track, 'album', None))
        if not album_key:
            continue
        for value in (getattr(track, 'artist', None), getattr(track, 'album_artist', None)):
            artist_key = normalize_token(value)
            if artist_key:
                keys.add((artist_key, album_key))
    return keys


def _sql_normalized(column):
    return func.lower(func.replace(func.trim(column), '_', ' '))


def load_radio_profile_cache_for_tracks(
    db: Session,
    tracks: Iterable[models.Track],
    *,
    extra_tracks: Iterable[models.Track] | None = None,
) -> dict[str, Any]:
    requested_tracks = list(tracks or [])
    if extra_tracks is not None:
        requested_tracks.extend(list(extra_tracks))

    track_ids = _track_profile_ids(requested_tracks)
    artist_keys = _artist_keys_for_tracks(requested_tracks)
    album_keys = _album_keys_for_tracks(requested_tracks)
    metrics: dict[str, int] = {
        'requested_candidate_tracks': len(requested_tracks),
        'requested_profile_track_ids': len(track_ids),
        'requested_artist_keys': len(artist_keys),
        'requested_album_keys': len(album_keys),
        'artist_profile_rows_loaded': 0,
        'album_profile_rows_loaded': 0,
        'track_profile_rows_loaded': 0,
        'artist_profile_queries': 0,
        'album_profile_queries': 0,
        'track_profile_queries': 0,
    }

    artists: dict[str, dict[str, Any]] = {}
    artist_key_list = sorted(artist_keys)
    for chunk in _chunked(artist_key_list):
        if not chunk:
            continue
        metrics['artist_profile_queries'] += 1
        rows = db.query(models.ArtistRadioProfile).filter(_sql_normalized(models.ArtistRadioProfile.artist).in_(chunk)).all()
        for row in rows:
            key = normalize_token(row.artist)
            if key and key in artist_keys:
                artists[key] = row_profile(row)
    metrics['artist_profile_rows_loaded'] = len(artists)

    albums: dict[tuple[str, str], dict[str, Any]] = {}
    album_key_list = sorted(album_keys)
    for chunk in _chunked(album_key_list):
        if not chunk:
            continue
        metrics['album_profile_queries'] += 1
        artist_chunk = sorted({artist for artist, _album in chunk})
        album_chunk = sorted({album for _artist, album in chunk})
        rows = (
            db.query(models.AlbumRadioProfile)
            .filter(_sql_normalized(models.AlbumRadioProfile.artist).in_(artist_chunk))
            .filter(_sql_normalized(models.AlbumRadioProfile.album).in_(album_chunk))
            .all()
        )
        requested = set(chunk)
        for row in rows:
            key = (normalize_token(row.artist), normalize_token(row.album))
            if key[0] and key[1] and key in requested:
                albums[key] = row_profile(row)
    metrics['album_profile_rows_loaded'] = len(albums)

    track_profiles: dict[int, dict[str, Any]] = {}
    for chunk in _chunked(track_ids):
        if not chunk:
            continue
        metrics['track_profile_queries'] += 1
        rows = db.query(models.TrackRadioProfile).filter(models.TrackRadioProfile.track_id.in_(chunk)).all()
        for row in rows:
            track_profiles[int(row.track_id)] = row_profile(row)
    metrics['track_profile_rows_loaded'] = len(track_profiles)

    return {
        'artists': artists,
        'albums': albums,
        'tracks': track_profiles,
        '_station_profile_metrics': metrics,
    }