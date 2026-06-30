from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app import radio_genres
from app.db import SessionLocal
from app.main import app
from app.models import Track
from app.queue_contracts import StationQueueRequest
from app.station_engine import build_station_debug

NON_ELECTRONIC_FAMILIES = {'hip-hop', 'jazz', 'rock', 'pop', 'r&b'}
ELECTRONIC_ARTISTS = {'daft punk', 'deadmau5', 'aphex twin'}


def norm(value: str | None) -> str:
    return ' '.join(str(value or '').strip().lower().split())


def selected_families(debug: dict) -> set[str]:
    families: set[str] = set()
    for row in debug.get('selected', []):
        genre = (row.get('profile') or {}).get('primary_genre')
        family = radio_genres.genre_family(genre)
        if family:
            families.add(family)
    return families


def selected_artists(debug: dict) -> set[str]:
    return {norm(row.get('artist')) for row in debug.get('selected', [])}


def assert_no_unrelated_electronic(debug: dict, label: str) -> None:
    offenders = selected_families(debug) & NON_ELECTRONIC_FAMILIES
    assert not offenders, f'{label}: unrelated families selected: {sorted(offenders)}'


def first_track_for_artist(db, artist: str) -> Track | None:
    return db.query(Track).filter(Track.artist == artist).order_by(Track.id).first()


def main() -> None:
    assert radio_genres.normalize_genre('IDM') == 'idm'
    assert radio_genres.normalize_genre('Progressive House') == 'progressive house'
    assert radio_genres.genre_family('IDM') == 'electronic'
    assert radio_genres.genre_family('Progressive House') == 'electronic'
    assert radio_genres.same_genre_family('Electronic', 'IDM')
    assert radio_genres.same_genre_family('Electronic', 'Progressive House')
    assert radio_genres.same_genre_family('Hip-Hop', 'Mixtape')
    assert radio_genres.same_genre_family('Hip-Hop', 'Jazz Rap')
    assert not radio_genres.same_genre_family('Electronic', 'Hip-Hop')
    assert not radio_genres.same_genre_family('Electronic', 'Jazz')
    assert not radio_genres.same_genre_family('Hip-Hop', 'Pop')
    assert radio_genres.display_genre('idm') == 'IDM'
    assert radio_genres.display_genre('edm') == 'EDM'
    assert radio_genres.display_genre('r&b') == 'R&B'
    assert radio_genres.display_genre('hip-hop') == 'Hip-Hop'
    assert radio_genres.display_genre('progressive house') == 'Progressive House'

    client = TestClient(app)
    stations = client.get('/api/stations/').json()
    genre_stations = [station for station in stations if station.get('type') == 'genre' and station.get('source') == 'system']
    assert len(genre_stations) > 5, f'expected more than 5 genre stations, got {len(genre_stations)}'
    assert any(station.get('seed_value') == 'Electronic' for station in genre_stations), 'Electronic Radio not exposed'
    assert all('family' in station and 'display_family' in station and 'featured' in station and 'is_family_station' in station for station in genre_stations), 'genre metadata missing'

    db = SessionLocal()
    try:
        electronic = build_station_debug(StationQueueRequest(type='genre', seed_value='Electronic', limit=25), db)
        assert_no_unrelated_electronic(electronic, 'Electronic Radio')
        present_electronic_artists = ELECTRONIC_ARTISTS & {norm(row[0]) for row in db.query(Track.artist).distinct().all()}
        if len(present_electronic_artists) >= 2:
            selected = selected_artists(electronic)
            assert len(selected & present_electronic_artists) >= 2, f'Electronic Radio did not mix electronic artists: {selected}'

        for artist in ('Daft Punk', 'Deadmau5', 'Aphex Twin'):
            seed = first_track_for_artist(db, artist)
            if not seed:
                continue
            debug = build_station_debug(StationQueueRequest(type='song', seed_track_id=seed.id, limit=25), db)
            assert_no_unrelated_electronic(debug, f'{artist} song radio')
            assert float(debug.get('summary', {}).get('exploration_percent', 0)) <= 15, debug.get('summary')

        hiphop = build_station_debug(StationQueueRequest(type='genre', seed_value='Hip-Hop', limit=25), db)
        assert 'electronic' not in selected_families(hiphop), 'Hip-Hop Radio pulled Electronic after M5.1'
    finally:
        db.close()

    print('ok: station genre families M5.1')


if __name__ == '__main__':
    main()
