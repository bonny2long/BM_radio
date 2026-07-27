from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import shutil
import subprocess
import sys
from typing import Any

from sqlalchemy import event, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models, station_candidates
from app.perf import collect_perf_segments
from app.perf_benchmark import stable_checksum
from app.perf_fixtures import SyntheticLibrarySpec, build_synthetic_library, create_temp_engine
from app.queue_contracts import StationQueueRequest
from app.routes.stations import get_stations
from app.station_candidates import (
    MAX_STATION_CANDIDATE_POOL,
    load_station_candidate_tracks,
    load_station_recording_candidates,
    select_station_recording_ids,
    station_identity_key_for_track,
)
from app.station_context import build_station_request_context
from app.station_engine import build_station_debug, build_station_queue
from app.station_perf_benchmark import PROD4_FIXTURE_SEED, select_station_seeds, table_counts, track_ids_from_queue

UTC = timezone.utc


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
    build_synthetic_library(db, SyntheticLibrarySpec(physical_tracks=size, seed=PROD4_FIXTURE_SEED))
    return engine, db


def run_script(script: str) -> None:
    result = subprocess.run([sys.executable, script], cwd=Path(__file__).resolve().parents[1], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, f'{script} failed\n{result.stdout}\n{result.stderr}'


def queue_identity(result: dict[str, Any]) -> str:
    return stable_checksum([(row.get('recording_id'), row.get('track_id'), row.get('effective_track_id') or row.get('track_id')) for row in result.get('queue') or []])


def debug_identity(result: dict[str, Any]) -> str:
    return stable_checksum([(row.get('recording_id'), row.get('track_id'), row.get('effective_track_id') or row.get('track_id'), row.get('tier')) for row in result.get('selected') or []])


def conceptual_old_policy_ids(db, *, limit: int, excluded_recording_ids: set[int] | None = None) -> list[int]:
    excluded = excluded_recording_ids or set()
    rows = (
        db.query(
            models.MusicTrackIdentity.recording_id,
            models.MusicRecordingParticipation.participation_state,
            models.Track.created_at.label('first_seen'),
            models.Track.id.label('stable_id'),
        )
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .outerjoin(models.MusicRecordingParticipation, models.MusicRecordingParticipation.recording_id == models.MusicTrackIdentity.recording_id)
        .filter(models.Track.library_availability == 'available')
        .group_by(models.MusicTrackIdentity.recording_id)
        .order_by(models.Track.created_at.desc(), models.Track.id.asc())
        .limit(limit * 3)
        .all()
    )
    out: list[int] = []
    for row in rows:
        rid = int(row.recording_id)
        if rid in excluded:
            continue
        if (row.participation_state or 'included') != 'included':
            continue
        out.append(rid)
        if len(out) >= limit:
            break
    return out


def top_recording_ids(db, count: int) -> list[int]:
    rows = (
        db.query(models.MusicTrackIdentity.recording_id)
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .filter(models.Track.library_availability == 'available')
        .group_by(models.MusicTrackIdentity.recording_id)
        .order_by(models.Track.created_at.desc(), models.Track.id.asc())
        .limit(count)
        .all()
    )
    return [int(row[0]) for row in rows]


def set_participation(db, recording_id: int, state: str | None) -> None:
    row = db.query(models.MusicRecordingParticipation).filter_by(recording_id=recording_id).one_or_none()
    if state is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        row = models.MusicRecordingParticipation(recording_id=recording_id, participation_state=state, state_source='system')
        db.add(row)
    else:
        row.participation_state = state


def add_legacy_track(db, track_id: int, *, available: bool = True) -> models.Track:
    now = datetime(2027, 1, 1, tzinfo=UTC) + timedelta(seconds=track_id)
    track = models.Track(
        id=track_id,
        path=f'legacy/{track_id}.mp3',
        relative_path=f'legacy/{track_id}.mp3',
        title=f'Legacy {track_id}',
        artist='Legacy Artist',
        album='Legacy Album',
        album_artist='Legacy Artist',
        genre='Soul',
        primary_genre='Soul',
        library_availability='available' if available else 'missing',
        created_at=now,
        last_indexed_at=now,
    )
    db.add(track)
    return track


def assert_projection_count(operation) -> dict[str, list[float]]:
    with collect_perf_segments() as segments:
        operation()
    assert len(segments.get('station.candidate_projection', [])) == 1, segments
    return segments


def main() -> int:
    base = Path('tmp_tests') / 'prod4_2b_scope'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    source = Path('app/station_candidates.py').read_text(encoding='utf-8')
    assert 'bounded * 3' not in source
    assert '.limit(bounded * 3)' not in source

    engine, db = build_ctx(base, 'primary', 10000)
    try:
        top = top_recording_ids(db, 8)
        set_participation(db, top[0], 'included')
        set_participation(db, top[1], None)
        set_participation(db, top[2], 'library_only')
        set_participation(db, top[3], 'archived')
        set_participation(db, top[4], 'blocked')
        db.commit()
        selected = select_station_recording_ids(db, limit=10, excluded_recording_ids={top[5]})
        assert top[0] in selected and top[1] in selected
        assert top[2] not in selected and top[3] not in selected and top[4] not in selected and top[5] not in selected

        expected_order = conceptual_old_policy_ids(db, limit=100, excluded_recording_ids={top[5]})[:10]
        assert selected[:10] == expected_order[:10]
        selected_5k = select_station_recording_ids(db, limit=MAX_STATION_CANDIDATE_POOL)
        assert len(selected_5k) <= MAX_STATION_CANDIDATE_POOL

        captured: list[list[int]] = []
        original_resolver = station_candidates.resolve_effective_music_sources_read_only

        def wrapped_resolver(db_arg, *, recording_ids):
            captured.append(list(recording_ids))
            return original_resolver(db_arg, recording_ids=recording_ids)

        station_candidates.resolve_effective_music_sources_read_only = wrapped_resolver
        try:
            candidates = load_station_recording_candidates(db, limit=MAX_STATION_CANDIDATE_POOL)
        finally:
            station_candidates.resolve_effective_music_sources_read_only = original_resolver
        metrics = db.info.get('station_candidate_projection_metrics') or {}
        assert captured and len(captured[-1]) == metrics['recording_ids_selected'] <= MAX_STATION_CANDIDATE_POOL
        assert metrics['recording_ids_source_resolved'] <= MAX_STATION_CANDIDATE_POOL
        assert metrics['recording_rows_loaded'] <= metrics['recording_ids_selected']
        assert metrics['profile_track_ids_selected'] <= metrics['recording_ids_selected']
        assert metrics['track_rows_hydrated'] <= metrics['effective_track_ids_selected'] + metrics['profile_track_ids_selected']
        assert len({candidate.candidate_key for candidate in candidates}) == len(candidates)

        by_recording: dict[int, list[int]] = {}
        for row in db.query(models.MusicTrackIdentity.recording_id, models.MusicTrackIdentity.track_id).all():
            by_recording.setdefault(int(row.recording_id), []).append(int(row.track_id))
        multi = next((rid for rid, ids in by_recording.items() if len(ids) >= 2 and any(candidate.recording_id == rid for candidate in candidates)), None)
        assert multi is not None
        tracks = load_station_candidate_tracks(db, limit=MAX_STATION_CANDIDATE_POOL, exclude_track_ids=[by_recording[multi][0]])
        assert all(getattr(track, '_station_recording_id', None) != multi for track in tracks)

        pref_context = build_station_request_context(db, limit=MAX_STATION_CANDIDATE_POOL)
        preferred = None
        pref_track = None
        for track in pref_context.tracks:
            pref = db.query(models.MusicRecordingPreference).filter_by(recording_id=getattr(track, '_station_recording_id', None)).one_or_none()
            if pref is not None and pref.user_preferred_track_id is not None:
                preferred = pref
                pref_track = track
                break
        assert preferred is not None and pref_track is not None
        assert pref_track.id == preferred.user_preferred_track_id
        ids = sorted(by_recording[int(preferred.recording_id)])
        preferred.user_preferred_track_id = ids[0] if ids[0] != preferred.user_preferred_track_id else ids[-1]
        db.commit()
        fresh_context = build_station_request_context(db, limit=MAX_STATION_CANDIDATE_POOL)
        fresh_track = next(track for track in fresh_context.tracks if getattr(track, '_station_recording_id', None) == preferred.recording_id)
        assert fresh_track.id == preferred.user_preferred_track_id

        auto_context = build_station_request_context(db, limit=MAX_STATION_CANDIDATE_POOL)
        auto_pref = None
        auto_track = None
        for track in auto_context.tracks:
            pref = db.query(models.MusicRecordingPreference).filter_by(recording_id=getattr(track, '_station_recording_id', None)).one_or_none()
            if pref is not None and pref.user_preferred_track_id is None and pref.auto_preferred_track_id is not None:
                auto_pref = pref
                auto_track = track
                break
        assert auto_pref is not None and auto_track is not None
        assert auto_track.id == auto_pref.auto_preferred_track_id

        before_counts = table_counts(db)
        seeds = select_station_seeds(db)
        build_station_queue(StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), db)
        build_station_debug(StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False), db)
        asyncio.run(get_stations(db))
        db.rollback()
        after_counts = table_counts(db)
        assert before_counts == after_counts

        random.seed(1001)
        requests = [
            StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False),
            StationQueueRequest(type='song', seed_track_id=seeds.live_song_track_id, limit=50, shuffle=False),
            StationQueueRequest(type='artist', seed_value=seeds.artist_name, limit=50, shuffle=False),
            StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False),
            StationQueueRequest(type='favorites', limit=50, shuffle=False),
            StationQueueRequest(type='recently_added', limit=50, shuffle=False),
            StationQueueRequest(type='deep_cuts', limit=50, shuffle=False),
        ]
        first = [queue_identity(build_station_queue(req, db)) for req in requests]
        db.rollback()
        random.seed(1001)
        second = [queue_identity(build_station_queue(req, db)) for req in requests]
        db.rollback()
        assert first == second

        history_req = StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False)
        initial = build_station_queue(history_req, db)
        history = track_ids_from_queue(initial)
        db.rollback()
        refill = build_station_queue(StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False, exclude_track_ids=history[-200:]), db)
        db.rollback()
        initial_recordings = {row.get('recording_id') for row in initial.get('queue') or [] if row.get('recording_id')}
        refill_recordings = {row.get('recording_id') for row in refill.get('queue') or [] if row.get('recording_id')}
        assert not (initial_recordings & refill_recordings)

        random.seed(2002)
        debug_first = debug_identity(build_station_debug(StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), db))
        db.rollback()
        assert debug_first

        assert_projection_count(lambda: build_station_queue(StationQueueRequest(type='genre', seed_value=seeds.genre_name, limit=50, shuffle=False), db))
        db.rollback()
        assert_projection_count(lambda: build_station_debug(StationQueueRequest(type='song', seed_track_id=seeds.song_track_id, limit=50, shuffle=False), db))
        db.rollback()
        listing_segments = assert_projection_count(lambda: asyncio.run(get_stations(db)))
        assert len(listing_segments.get('station.profile_cache', [])) == 1
        db.rollback()

        with sql_statements(engine) as statements:
            load_station_candidate_tracks(db, limit=MAX_STATION_CANDIDATE_POOL)
        lowered = '\n'.join(statements).lower()
        assert lowered.count('from music_track_identities') < 20
    finally:
        db.close()
        engine.dispose()

    legacy_engine, legacy_db = build_ctx(base, 'legacy', 20)
    try:
        legacy_db.query(models.MusicRecordingParticipation).update({models.MusicRecordingParticipation.participation_state: 'blocked'})
        add_legacy_track(legacy_db, 100001, available=True)
        add_legacy_track(legacy_db, 100002, available=True)
        add_legacy_track(legacy_db, 100003, available=False)
        legacy_db.commit()
        tracks = load_station_candidate_tracks(legacy_db, limit=2, exclude_track_ids=[100001])
        ids = [track.id for track in tracks]
        assert 100001 not in ids and 100002 in ids and 100003 not in ids
    finally:
        legacy_db.close()
        legacy_engine.dispose()

    eq_engine, eq_db = build_ctx(base, 'equivalence', 10000)
    try:
        assert select_station_recording_ids(eq_db, limit=MAX_STATION_CANDIDATE_POOL) == conceptual_old_policy_ids(eq_db, limit=MAX_STATION_CANDIDATE_POOL)
    finally:
        eq_db.close()
        eq_engine.dispose()

    gate_source = Path('../scripts/check_prod0_baseline.py').read_text(encoding='utf-8')
    assert 'check_prod4_2b_station_candidate_projection_scope.py' in gate_source
    run_script('scripts/check_prod4_2a_scoped_station_profiles.py')
    run_script('scripts/check_prod4_1_station_scale_benchmark.py')
    run_script('scripts/check_prod1_5a_recording_first_station_candidates.py')
    run_script('scripts/check_prod1_5b_station_version_affinity.py')
    print('PASS: BM-PROD4.2B station candidate projection and source-resolution scope')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
