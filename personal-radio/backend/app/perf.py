from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import event, text
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .db import engine

query_count_var: ContextVar[dict[str, int] | None] = ContextVar('query_count', default=None)
_installed = False


def install_query_counter() -> None:
    global _installed
    if _installed:
        return

    @event.listens_for(engine, 'before_cursor_execute')
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter = query_count_var.get()
        if counter is not None:
            counter['count'] = counter.get('count', 0) + 1

    _installed = True


class RequestTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        counter = {'count': 0}
        token = query_count_var.set(counter)
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        query_count = counter.get('count', 0)
        query_count_var.reset(token)
        if elapsed_ms > 250 or query_count > 100:
            print(f'[PERF] {request.method} {request.url.path} {elapsed_ms:.1f}ms {query_count} queries')
        response.headers['X-BM-Radio-Time-Ms'] = f'{elapsed_ms:.1f}'
        response.headers['X-BM-Radio-Query-Count'] = str(query_count)
        return response


@contextmanager
def perf_segment(name: str, threshold_ms: float = 25.0):
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms >= threshold_ms:
            print(f'[PERF:SEGMENT] {name} {elapsed_ms:.1f}ms')


INDEX_STATEMENTS = [
    'CREATE INDEX IF NOT EXISTS ix_tracks_album_artist ON tracks (album_artist)',
    'CREATE INDEX IF NOT EXISTS ix_tracks_library_area ON tracks (library_area)',
    'CREATE INDEX IF NOT EXISTS ix_tracks_created_at ON tracks (created_at)',
    'CREATE INDEX IF NOT EXISTS ix_tracks_last_indexed_at ON tracks (last_indexed_at)',
    'CREATE INDEX IF NOT EXISTS ix_track_thumbs_track_id ON track_thumbs (track_id)',
    'CREATE INDEX IF NOT EXISTS ix_track_thumbs_station_id ON track_thumbs (station_id)',
    'CREATE INDEX IF NOT EXISTS ix_track_thumbs_created_at ON track_thumbs (created_at)',
    'CREATE INDEX IF NOT EXISTS ix_track_favorites_track_id ON track_favorites (track_id)',
    'CREATE INDEX IF NOT EXISTS ix_track_favorites_created_at ON track_favorites (created_at)',
    'CREATE INDEX IF NOT EXISTS ix_playback_events_track_id ON playback_events (track_id)',
    'CREATE INDEX IF NOT EXISTS ix_playback_events_audiobook_id ON playback_events (audiobook_id)',
    'CREATE INDEX IF NOT EXISTS ix_playback_events_station_id ON playback_events (station_id)',
    'CREATE INDEX IF NOT EXISTS ix_playback_events_event_type ON playback_events (event_type)',
    'CREATE INDEX IF NOT EXISTS ix_playback_events_created_at ON playback_events (created_at)',
    'CREATE INDEX IF NOT EXISTS ix_audiobooks_status ON audiobooks (status)',
    'CREATE INDEX IF NOT EXISTS ix_audiobooks_updated_at ON audiobooks (updated_at)',
    'CREATE INDEX IF NOT EXISTS ix_audiobook_progress_audiobook_id ON audiobook_progress (audiobook_id)',
    'CREATE INDEX IF NOT EXISTS ix_audiobook_progress_chapter_id ON audiobook_progress (chapter_id)',
    'CREATE INDEX IF NOT EXISTS ix_audiobook_progress_updated_at ON audiobook_progress (updated_at)',
]


def ensure_performance_indexes() -> None:
    with engine.begin() as conn:
        for statement in INDEX_STATEMENTS:
            conn.execute(text(statement))


def install_performance_tools(app) -> None:
    if settings.APP_ENV.lower() != 'development':
        return
    install_query_counter()
    app.add_middleware(RequestTimingMiddleware)