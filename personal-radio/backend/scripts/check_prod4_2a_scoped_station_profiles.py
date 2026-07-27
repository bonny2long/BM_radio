from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
import random
import shutil
import subprocess
import sys
from typing import Any

from sqlalchemy import event, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.perf import collect_perf_segments
from app.perf_benchmark import stable_checksum
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine
from app.queue_contracts import StationQueueRequest
from app.radio_profiles import load_radio_profile_cache, load_radio_profile_cache_for_tracks, profile_for_track_cached
from app.routes.stations import get_stations
from app.station_candidates import MAX_STATION_CANDIDATE_POOL, load_station_candidate_tracks, station_identity_key_for_track
from app.station_context import build_station_request_context
from app.station_engine import build_station_debug, build_station_queue
from app.station_perf_benchmark import PROD4_FIXTURE_SEED, queue_checksum, select_station_seeds, table_counts


@contextmanager
def sql_statements(engine):
    statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(str(statement or ''))

    event.listen(engine, 'before_cursor_execute', before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, 'before_cursor_execute', before_cursor_execute)


def build_ctx(base: Path, name: str, size: int = 1000):
    engine, Session = create_temp_engine(base / f'{name}.db')
    db = Session()
    summary = build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=size, seed=PROD4_FIXTURE_SEED))
    return engine, db, summary


def table_row_count(db, table: str) -> int:
    return int(db.execute(text(f'select count(*) from "{table}"')).scalar_one() or 0)


def assert_no_unfiltered_profile_load(statements: list[str]) -> None:
    for statement in statements:
        lowered = ' '.join(statement.lower().split())
        if 'from track_radio_profiles' in lowered:
            assert ' where ' in lowered and 'track_id' in lowered, statement
        if 'from artist_radio_profiles' in lowered:
            assert ' where ' in lowered and 'artist' in lowered, statement
        if 'from album_radio_profiles' in lowered:
            assert ' where ' in lowered and 'album' in lowered and 'artist' in lowered, statement


def queue_result_identity(result: dict[str, Any]) -> str:
    return stable_checksum([
        (row.get('recording_id'), row.get('track_id'), row.get('effective_track_id') or row.get('track_id'))
        for row in result.get('queue') or []
    ])


def debug_identity(result: dict[str, Any]) -> str:
    return stable_checksum([
        (row.get('recording_id'), row.get('track_id'), row.get('effective_track_id') or row.get('track_id'), row.get('tier'))
        for row in result.get('selected') or []
    ])


def prepare_profile_equivalence_rows(db) -> list[models.Track]:
    tracks = db.query(models.Track).order_by(models.Track.id.asc()).limit(8).all()
    for index, track in enumerate(tracks, start=1):
        track.artist = f'Profile Artist {index}'
        track.album_artist = f'Profile Album Artist {index}'
        track.album = f'Profile Album {index}'
        track.genre = None
        track.primary_genre = None
    tracks[4].artist = 'Guest Artist'
    tracks[5].artist = 'Case Artist'
    tracks[5].album_artist = 'Case Artist'
    tracks[5].album = 'Case Album'
    tracks[7].artist = 'Aphex Twin'
    tracks[7].album_artist = 'Aphex Twin'
    tracks[7].album = 'Thin Album'
    db.query(models.TrackRadioProfile).filter(models.TrackRadioProfile.track_id.in_([track.id for track in tracks])).delete(synchronize_session=False)
    db.add(models.ArtistRadioProfile(artist='Profile Artist 1', primary_genre='Soul', subgenres_json='["neo soul"]', moods_json='["warm"]', energy='medium', related_artists_json='["Friend A"]', source='test'))
    db.add(models.AlbumRadioProfile(artist='Profile Artist 2', album='Profile Album 2', primary_genre='Jazz', subgenres_json='["hard bop"]', moods_json='["cool"]', energy='low', source='test'))
    db.add(models.TrackRadioProfile(track_id=tracks[2].id, primary_genre='Rock', subgenres_json='["alt rock"]', moods_json='["driving"]', energy='high', source='test'))
    db.add(models.ArtistRadioProfile(artist='Profile Artist 4', primary_genre='Pop', subgenres_json='["dance pop"]', moods_json='["bright"]', energy='medium', source='test'))
    db.add(models.AlbumRadioProfile(artist='Profile Artist 4', album='Profile Album 4', primary_genre='Electronic', subgenres_json='["house"]', moods_json='["club"]', energy='high', source='test'))
    db.add(models.TrackRadioProfile(track_id=tracks[3].id, primary_genre='Hip-Hop', subgenres_json='["rap"]', moods_json='["confident"]', energy='high', source='test'))
    db.add(models.AlbumRadioProfile(artist='Profile Album Artist 5', album='Profile Album 5', primary_genre='R&B', subgenres_json='["slow jam"]', moods_json='["smooth"]', energy='low', source='test'))
    db.add(models.ArtistRadioProfile(artist='case artist', primary_genre='Funk', subgenres_json='["funk"]', moods_json='["groovy"]', energy='medium', source='test'))
    db.add(models.AlbumRadioProfile(artist='case artist', album='case album', primary_genre='Disco', subgenres_json='["nu disco"]', moods_json='["danceable"]', energy='high', source='test'))
    db.add(models.AlbumRadioProfile(artist='Profile Artist 1', album='Profile Album 2', primary_genre='Classical', subgenres_json='["cross product"]', moods_json='[]', energy='low', source='cross_product_guard'))
    db.add(models.TrackRadioProfile(track_id=tracks[7].id, primary_genre='Electronic', subgenres_json='[]', moods_json='[]', energy=None, source='thin'))
    db.commit()
    return tracks


def assert_profile_equivalence(db) -> None:
    tracks = prepare_profile_equivalence_rows(db)
    full = load_radio_profile_cache(db)
    scoped = load_radio_profile_cache_for_tracks(db, tracks)
    for track in tracks:
        assert profile_for_track_cached(track, scoped) == profile_for_track_cached(track, full), track.id
    assert ('profile artist 1', 'profile album 2') not in scoped['albums']
    assert profile_for_track_cached(tracks[7], scoped).get('enrichment_source') == 'bm_radio_artist_enrichment'


def assert_chunking(db) -> None:
    tracks = db.query(models.Track).order_by(models.Track.id.asc()).limit(1200).all()
    scoped = load_radio_profile_cache_for_tracks(db, tracks)
    metrics = scoped['_station_profile_metrics']
    assert metrics['requested_profile_track_ids'] >= 1200
    assert metrics['track_profile_queries'] >= 3
    assert metrics['track_profile_rows_loaded'] <= metrics['requested_profile_track_ids']


def assert_projection_count(operation, expected_name: str = 'station.candidate_projection') -> dict[str, list[float]]:
    with collect_perf_segments() as segments:
        operation()
    assert len(segments.get(expected_name, [])) == 1, segments
    return segments


def assert_source_preference_freshness(db) -> None:
    row = db.execute(text('select recording_id from music_track_identities group by recording_id having count(*) >= 2 order by recording_id limit 1')).first()
    assert row is not None
    track_ids = [int(item[0]) for item in db.execute(text('select track_id from music_track_identities where recording_id=:rid order by track_id'), {'rid': row[0]}).all()]
    context1 = build_station_request_context(db, limit=MAX_STATION_CANDIDATE_POOL)
    before = next(track for track in context1.tracks if getattr(track, '_station_recording_id', None) == row[0])
    pref = db.query(models.MusicRecordingPreference).filter_by(recording_id=row[0]).one_or_none()
    if pref is None:
        pref = models.MusicRecordingPreference(recording_id=row[0], decision_state='selected', confidence='high', reason_code='test', policy_version=1, candidate_count=2, eligible_candidate_count=2)
        db.add(pref)
    pref.user_preferred_track_id = track_ids[-1]
    db.commit()
    context2 = build_station_request_context(db, limit=MAX_STATION_CANDIDATE_POOL)
    after = next(track for track in context2.tracks if getattr(track, '_station_recording_id', None) == row[0])
    assert before.id != after.id or after.id == track_ids[-1]
    assert after.id == track_ids[-1]


def run_script(script: str) -> None:
    result = subprocess.run([sys.executable, script], cwd=Path(__file__).resolve().parents[1], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, f'{script} failed\n{result.stdout}\n{result.stderr}'


def main() -> int:
    base = Path('tmp_tests') / 'prod4_2a_smoke'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        engine, db, summary = build_ctx(base, 'primary', 5000)
        try:
            seeds = select_station_seeds(db)
            with sql_statements(engine) as statements:
                build_station_queue(StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), db)
                db.rollback()
            assert_no_unfiltered_profile_load(statements)

            context50 = build_station_request_context(db, limit=50)
            assert context50.profile_metrics['track_profile_rows_loaded'] <= context50.profile_metrics['requested_profile_track_ids'] <= 100
            profile_ids = {getattr(track, '_station_profile_track_id', track.id) for track in context50.tracks}
            assert profile_ids <= set(context50.profile_cache['tracks'])
            seed_track = db.get(models.Track, seeds.song_track_id)
            seed_context = build_station_request_context(db, limit=50, seed_track=seed_track, exclude_track_ids=[seed_track.id])
            assert seed_track.id in seed_context.profile_cache['tracks']

            assert_profile_equivalence(db)
            assert_chunking(db)

            scoped_a = load_radio_profile_cache_for_tracks(db, [seed_track])
            track_row = db.query(models.TrackRadioProfile).filter_by(track_id=seed_track.id).one_or_none()
            if track_row is None:
                track_row = models.TrackRadioProfile(track_id=seed_track.id, source='freshness')
                db.add(track_row)
            track_row.primary_genre = 'Polka'
            track_row.subgenres_json = '["fresh"]'
            track_row.moods_json = '["fresh"]'
            track_row.energy = 'low'
            db.commit()
            scoped_b = load_radio_profile_cache_for_tracks(db, [seed_track])
            assert profile_for_track_cached(seed_track, scoped_a) != profile_for_track_cached(seed_track, scoped_b)

            source = Path('app/station_context.py').read_text(encoding='utf-8') + Path('app/radio_profiles.py').read_text(encoding='utf-8')
            assert 'lru_cache' not in source and 'global ' not in source and 'SessionLocal' not in source

            assert_projection_count(lambda: build_station_queue(StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), db))
            db.rollback()
            assert_projection_count(lambda: build_station_queue(StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False), db))
            db.rollback()
            assert_projection_count(lambda: build_station_queue(StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False), db))
            db.rollback()
            assert_projection_count(lambda: build_station_debug(StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), db))
            db.rollback()
            listing_segments = assert_projection_count(lambda: asyncio.run(get_stations(db)))
            assert len(listing_segments.get('station.profile_cache', [])) == 1
            db.rollback()

            random_seed_requests = [
                StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False),
                StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False),
                StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False),
                StationQueueRequest(type='favorites', limit=50, shuffle=False),
            ]
            random.seed(4242)
            first = [queue_result_identity(build_station_queue(req, db)) for req in random_seed_requests]
            db.rollback()
            random.seed(4242)
            second = [queue_result_identity(build_station_queue(req, db)) for req in random_seed_requests]
            db.rollback()
            assert first == second
            random.seed(4343)
            debug_first = debug_identity(build_station_debug(StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), db))
            db.rollback()
            random.seed(4343)
            debug_second = debug_identity(build_station_debug(StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), db))
            db.rollback()
            assert debug_first == debug_second

            before_pool = [station_identity_key_for_track(track) for track in load_station_candidate_tracks(db, limit=MAX_STATION_CANDIDATE_POOL)]
            context_pool = [station_identity_key_for_track(track) for track in build_station_request_context(db, limit=MAX_STATION_CANDIDATE_POOL).tracks]
            assert before_pool == context_pool

            assert_source_preference_freshness(db)
            before_counts = table_counts(db)
            build_station_queue(StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False), db)
            build_station_debug(StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False), db)
            asyncio.run(get_stations(db))
            db.rollback()
            after_counts = table_counts(db)
            assert before_counts == after_counts

            with sql_statements(engine) as profile_statements:
                build_station_request_context(db, limit=500)
            track_profile_queries = [stmt for stmt in profile_statements if 'track_radio_profiles' in stmt.lower()]
            assert len(track_profile_queries) <= 2, track_profile_queries
            assert table_row_count(db, 'track_radio_profiles') >= 4990
        finally:
            db.close()
            engine.dispose()

        gate_source = Path('../scripts/check_prod0_baseline.py').read_text(encoding='utf-8')
        assert 'check_prod4_2a_scoped_station_profiles.py' in gate_source
        run_script('scripts/check_prod4_1_station_scale_benchmark.py')
        run_script('scripts/check_prod1_5a_recording_first_station_candidates.py')
        run_script('scripts/check_prod1_5b_station_version_affinity.py')
        print('PASS: BM-PROD4.2A scoped station profiles and request context')
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())